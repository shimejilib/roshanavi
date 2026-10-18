"""Relay pipeline generator: topology, expected rates, spec JSON, roshanavi project (pure Python).

No ROS import here: ``scripts/gen_pipeline.py`` (the command line) and the unit tests use it on a
machine without ROS. The ROS side that turns the spec into processes / a composable container
is ``pipeline_launch.py``. The formats are documented in docs/design/nodes.md.

A pipeline is a set of source / relay / sink nodes joined by topics::

    chain   src -> relay_1 -> ... -> relay_n -> sink
    fanout  src -> hub relay -> W lanes of relays -> W sinks      (hub publishes to all lanes)
    fanin   W sources (each with its lane of relays) -> merge relay -> sink
    grid    W sources -> (stages-2) stages of W relays -> W sinks; with links "mesh" every node
            sends to the same column and the next one in turn (round robin) and listens to both
            upstream neighbours, so the picture is a net, not W separate chains

``expected`` tells how many messages per second every sink should see when nothing is overloaded,
so a measurement can compute a drop rate even when the sequence numbers of one path are mixed.
"""

import json
import math
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SPEC_VERSION = 1
SHAPES = ('chain', 'fanout', 'fanin', 'grid')
LINKS = ('straight', 'mesh')
MODES = ('process', 'container')
CONTAINER_TYPES = ('st', 'mt')
PROCESS_MODES = ('busy', 'sleep')

SOURCE, RELAY, SINK = 'source', 'relay', 'sink'
PACKAGE = 'roshanavi_examples'
EXECUTABLES = {SOURCE: 'pipeline_source', RELAY: 'pipeline_relay', SINK: 'pipeline_sink'}
PLUGINS = {SOURCE: 'roshanavi_examples::PipelineSource',
           RELAY: 'roshanavi_examples::PipelineRelay',
           SINK: 'roshanavi_examples::PipelineSink'}

# name: (shape, stages, width) -- sizes of the presets (node counts: 3, 20, 200)
PRESETS: Dict[str, Dict[str, Any]] = {
    'small': {'shape': 'chain', 'stages': 3, 'width': 1},
    'medium': {'shape': 'grid', 'stages': 5, 'width': 4},
    'large': {'shape': 'grid', 'stages': 10, 'width': 20},
}
# Above this many nodes the project is one launch target (a project holds at most 100 targets).
MAX_RUN_TARGETS = 60


@dataclass(frozen=True)
class PipelineParams:
    """Everything that decides what a generated pipeline looks like and does."""
    shape: str = 'chain'
    stages: int = 3
    width: int = 1
    links: str = 'mesh'                # grid only
    rate_hz: float = 10.0              # per source
    payload_bytes: int = 1024          # size the sources create
    process_ms: float = 0.0            # per relay and message
    process_mode: str = 'busy'
    relay_payload_bytes: int = -1      # -1: relays pass the input bytes through
    rate_limit_hz: float = 0.0         # per relay, 0 = off
    drop_ratio: float = 0.0            # per relay
    keep_stamp: bool = True
    topic_prefix: str = '/pipe'
    # defaults of the launch file (can be overridden by its launch arguments)
    mode: str = 'process'
    containers: int = 1
    container_type: str = 'st'
    intra_process: bool = False

    def validate(self) -> None:
        def need(ok: bool, message: str) -> None:
            if not ok:
                raise ValueError(message)
        need(self.shape in SHAPES, f'shape must be one of {SHAPES}')
        need(self.links in LINKS, f'links must be one of {LINKS}')
        need(self.mode in MODES, f'mode must be one of {MODES}')
        need(self.container_type in CONTAINER_TYPES, f'container_type must be {CONTAINER_TYPES}')
        need(self.process_mode in PROCESS_MODES, f'process_mode must be {PROCESS_MODES}')
        need(self.width >= 1, 'width must be at least 1')
        need(self.stages >= (2 if self.shape == 'chain' else 3),
             'stages must be at least 2 for a chain and 3 for the other shapes')
        need(self.rate_hz > 0, 'rate_hz must be positive')
        need(self.payload_bytes >= 0, 'payload_bytes must be 0 or more')
        need(self.process_ms >= 0, 'process_ms must be 0 or more')
        need(0 <= self.drop_ratio <= 1, 'drop_ratio must be between 0 and 1')
        need(self.rate_limit_hz >= 0, 'rate_limit_hz must be 0 or more')
        need(self.containers >= 1, 'containers must be at least 1')
        need(self.topic_prefix.startswith('/') and not self.topic_prefix.endswith('/'),
             'topic_prefix must start with / and not end with /')


def preset_params(name: str, **overrides: Any) -> PipelineParams:
    """Parameters of a size preset (small / medium / large) with some values replaced."""
    if name not in PRESETS:
        raise ValueError(f'unknown preset {name!r}; choose from {tuple(PRESETS)}')
    return replace(PipelineParams(**PRESETS[name]), **overrides)


@dataclass(frozen=True)
class PipelineNode:
    name: str
    kind: str                      # source / relay / sink
    stage: int
    lane: int
    params: Mapping[str, Any]      # only values that differ from the node's own defaults
    inputs: Tuple[str, ...]        # topics, in order: in, in_1, ...
    outputs: Tuple[str, ...]       # topics, in order: out, out_1, ...

    @property
    def remaps(self) -> Dict[str, str]:
        result = {endpoint('in', i): t for i, t in enumerate(self.inputs)}
        result.update({endpoint('out', i): t for i, t in enumerate(self.outputs)})
        return result


@dataclass(frozen=True)
class Pipeline:
    name: str
    params: PipelineParams
    nodes: Tuple[PipelineNode, ...]
    expected_sink_hz: Mapping[str, float]
    topic_hz: Mapping[str, float]

    def by_kind(self, kind: str) -> List[PipelineNode]:
        return [n for n in self.nodes if n.kind == kind]

    @property
    def topics(self) -> List[str]:
        return sorted({t for n in self.nodes for t in n.outputs})


def endpoint(base: str, index: int) -> str:
    """Relative topic name of the index-th input / output (same rule as the C++ nodes)."""
    return base if index == 0 else f'{base}_{index}'


# ---- layouts: which node feeds which --------------------------------------------------------

# (kind, stage, lane) per node, and links (source node index, dst node index). The k-th link out
# of a node is its output topic k; the order of links into a node is its input order.
Layout = Tuple[List[Tuple[str, int, int]], List[Tuple[int, int]]]


def _chain(p: PipelineParams) -> Layout:
    nodes = [(SOURCE, 0, 0)] + [(RELAY, s, 0) for s in range(1, p.stages - 1)] + \
        [(SINK, p.stages - 1, 0)]
    return nodes, [(i, i + 1) for i in range(len(nodes) - 1)]


def _fanout(p: PipelineParams) -> Layout:
    last = p.stages - 1
    nodes = [(SOURCE, 0, 0), (RELAY, 1, 0)]
    links = [(0, 1)]
    for lane in range(p.width):
        previous = 1
        for stage in range(2, last):
            nodes.append((RELAY, stage, lane))
            links.append((previous, len(nodes) - 1))
            previous = len(nodes) - 1
        nodes.append((SINK, last, lane))
        links.append((previous, len(nodes) - 1))
    return nodes, links


def _fanin(p: PipelineParams) -> Layout:
    merge_stage = p.stages - 2
    nodes: List[Tuple[str, int, int]] = []
    lane_ends = []
    links: List[Tuple[int, int]] = []
    for lane in range(p.width):
        nodes.append((SOURCE, 0, lane))
        previous = len(nodes) - 1
        for stage in range(1, merge_stage):
            nodes.append((RELAY, stage, lane))
            links.append((previous, len(nodes) - 1))
            previous = len(nodes) - 1
        lane_ends.append(previous)
    nodes.append((RELAY, merge_stage, 0))
    merge = len(nodes) - 1
    links.extend((end, merge) for end in lane_ends)
    nodes.append((SINK, p.stages - 1, 0))
    links.append((merge, merge + 1))
    return nodes, links


def _grid(p: PipelineParams) -> Layout:
    width, last = p.width, p.stages - 1
    nodes = [(SOURCE if s == 0 else SINK if s == last else RELAY, s, lane)
             for s in range(p.stages) for lane in range(width)]
    links = []
    for s in range(last):
        for lane in range(width):
            here = s * width + lane
            links.append((here, (s + 1) * width + lane))
            if p.links == 'mesh' and width > 1:
                links.append((here, (s + 1) * width + (lane + 1) % width))
    return nodes, links


LAYOUTS = {'chain': _chain, 'fanout': _fanout, 'fanin': _fanin, 'grid': _grid}


def _node_names(nodes: Sequence[Tuple[str, int, int]]) -> List[str]:
    in_stage: Dict[int, int] = {}
    for _, stage, _ in nodes:
        in_stage[stage] = in_stage.get(stage, 0) + 1
    names = []
    for kind, stage, lane in nodes:
        suffix = f'_{lane}' if in_stage[stage] > 1 else ''
        if kind == SOURCE:
            names.append('src' + suffix)
        elif kind == SINK:
            names.append('sink' + suffix)
        else:
            names.append(f'relay_{stage}{suffix}')
    return names


def _node_params(p: PipelineParams, kind: str, n_in: int, n_out: int,
                 round_robin: bool) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if kind == SOURCE:
        params.update(rate_hz=p.rate_hz, payload_bytes=p.payload_bytes)
    elif kind == RELAY:
        for key, value, default in (
                ('process_ms', p.process_ms, 0), ('process_mode', p.process_mode, 'busy'),
                ('payload_bytes', p.relay_payload_bytes, -1),
                ('rate_limit_hz', p.rate_limit_hz, 0), ('keep_stamp', p.keep_stamp, True),
                ('drop_ratio', p.drop_ratio, 0)):
            if value != default:
                params[key] = value
    if kind != SOURCE and n_in > 1:
        params['num_inputs'] = n_in
    if kind != SINK and n_out > 1:
        params['num_outputs'] = n_out
        if round_robin:
            params['fanout'] = 'round_robin'
    return params


def _propagate(nodes: Sequence[PipelineNode], p: PipelineParams) -> Tuple[Dict[str, float],
                                                                          Dict[str, float]]:
    """Messages per second on every topic and at every sink, nothing overloaded."""
    topic_hz: Dict[str, float] = {}
    sink_hz: Dict[str, float] = {}
    for node in sorted(nodes, key=lambda n: n.stage):
        incoming = sum(topic_hz[t] for t in node.inputs)
        if node.kind == SINK:
            sink_hz[node.name] = incoming
            continue
        if node.kind == SOURCE:
            total = p.rate_hz
        else:
            total = incoming * (1.0 - p.drop_ratio)
            if p.rate_limit_hz > 0:
                total = min(total, p.rate_limit_hz)
        each = total / len(node.outputs) if node.params.get('fanout') == 'round_robin' else total
        for topic in node.outputs:
            topic_hz[topic] = each
    return topic_hz, sink_hz


def build_pipeline(p: PipelineParams, name: Optional[str] = None) -> Pipeline:
    """The nodes, their topics and the expected rates of the pipeline ``p`` describes."""
    p.validate()
    layout, links = LAYOUTS[p.shape](p)
    names = _node_names(layout)
    if len(set(names)) != len(names):
        raise ValueError('internal error: duplicate node names')
    outs: List[List[str]] = [[] for _ in layout]
    ins: List[List[str]] = [[] for _ in layout]
    for src, dst in links:
        topic = f'{p.topic_prefix}/{names[src]}' + (f'_o{len(outs[src])}' if outs[src] else '')
        outs[src].append(topic)
        ins[dst].append(topic)
    round_robin = p.shape == 'grid' and p.links == 'mesh'
    nodes = tuple(
        PipelineNode(names[i], kind, stage, lane,
                     _node_params(p, kind, len(ins[i]), len(outs[i]), round_robin),
                     tuple(ins[i]), tuple(outs[i]))
        for i, (kind, stage, lane) in enumerate(layout))
    topic_hz, sink_hz = _propagate(nodes, p)
    return Pipeline(name or f'pipeline_{p.shape}', p, nodes, sink_hz, topic_hz)


# ---- containers -----------------------------------------------------------------------------

def assign_containers(nodes: Sequence[PipelineNode], count: int) -> List[List[PipelineNode]]:
    """Split the nodes (ordered by stage, then lane) into at most ``count`` equal-sized runs."""
    if count < 1:
        raise ValueError('count must be at least 1')
    ordered = sorted(nodes, key=lambda n: (n.stage, n.lane, n.name))
    size = max(1, math.ceil(len(ordered) / count))
    return [ordered[i:i + size] for i in range(0, len(ordered), size)]


def container_name(index: int, total: int) -> str:
    return 'pipeline_container' if total == 1 else f'pipeline_container_{index}'


# ---- spec JSON ------------------------------------------------------------------------------

def to_spec(pipe: Pipeline) -> Dict[str, Any]:
    """The JSON document ``pipeline.launch.py`` reads (documented in docs/design/nodes.md)."""
    p = pipe.params
    subscribers: Dict[str, List[str]] = {}
    for node in pipe.nodes:
        for topic in node.inputs:
            subscribers.setdefault(topic, []).append(node.name)
    publisher = {t: n.name for n in pipe.nodes for t in n.outputs}
    return {
        'version': SPEC_VERSION,
        'name': pipe.name,
        'shape': p.shape, 'stages': p.stages, 'width': p.width, 'links': p.links,
        'launch': {'mode': p.mode, 'containers': p.containers,
                   'container_type': p.container_type, 'intra_process': p.intra_process},
        'nodes': [{'name': n.name, 'kind': n.kind, 'stage': n.stage, 'lane': n.lane,
                   'params': dict(n.params), 'remaps': n.remaps} for n in pipe.nodes],
        'topics': [{'topic': t, 'publisher': publisher[t], 'subscribers': subscribers.get(t, []),
                    'hz': round(pipe.topic_hz[t], 6)} for t in pipe.topics],
        'expected': {'sink_hz': {k: round(v, 6) for k, v in pipe.expected_sink_hz.items()},
                     'total_sink_hz': round(sum(pipe.expected_sink_hz.values()), 6)},
    }


def spec_json(pipe: Pipeline) -> str:
    return json.dumps(to_spec(pipe), indent=1, sort_keys=False) + '\n'


# ---- roshanavi project ----------------------------------------------------------------------

def _scalar(value: Any) -> str:
    """A YAML scalar (JSON strings / numbers / booleans are YAML)."""
    return json.dumps(value)


def _flow(mapping: Mapping[str, Any]) -> str:
    return '{' + ', '.join(f'{k}: {_scalar(v)}' for k, v in mapping.items()) + '}'


def run_targets_possible(pipe: Pipeline) -> bool:
    return len(pipe.nodes) <= MAX_RUN_TARGETS


def project_yaml(pipe: Pipeline, spec_path: str, mode: str,
                 comment: str = '') -> str:
    """A roshanavi project for the pipeline.

    process mode with few nodes: one ``kind: run`` target per node (each can be stopped alone).
    Otherwise (container mode, or too many nodes): one ``kind: launch`` target of the installed
    ``pipeline.launch.py`` reading ``spec_path`` (a path as seen by the roshanavi server).
    """
    if mode not in MODES:
        raise ValueError(f'mode must be one of {MODES}')
    lines = ['version: 1'] if not comment else [f'# {ln}' for ln in comment.splitlines()] + \
        ['version: 1']
    lines.append('targets:')
    if mode == 'process' and run_targets_possible(pipe):
        for node in pipe.nodes:
            lines += [f'- id: {node.name.replace("_", "-")}', '  kind: run',
                      f'  package: {PACKAGE}', f'  executable: {EXECUTABLES[node.kind]}',
                      f'  name: {node.name}']
            if node.params:
                lines.append(f'  params: {_flow(node.params)}')
            lines += [f'  remaps: {_flow(node.remaps)}',
                      f'  role: {"mine" if node.kind == RELAY else "dependency"}',
                      '  autostart: true']
    else:
        p = pipe.params
        args = [f'spec:={spec_path}', f'mode:={mode}']
        if mode == 'container':
            args += [f'containers:={p.containers}', f'container_type:={p.container_type}',
                     f'intra_process:={str(p.intra_process).lower()}']
        lines += [f'- id: {pipe.name.replace("_", "-")}', '  kind: launch', f'  package: {PACKAGE}',
                  '  launch_file: pipeline.launch.py',
                  f'  args: [{", ".join(_scalar(a) for a in args)}]',
                  '  role: mine', '  autostart: true']
    return '\n'.join(lines) + '\n'


LAUNCH_FILE_TEXT = '''"""Generated by scripts/gen_pipeline.py -- do not edit; run the generator again.

Starts the pipeline described by pipeline.json (next to this file):
  ros2 launch {launch_path} mode:=process        one process per node (default of this pipeline: {mode})
  ros2 launch {launch_path} mode:=container      all nodes in ComposableNodeContainer(s)
Other launch arguments: containers (number of containers), container_type (st|mt),
intra_process (true|false). See docs/design/nodes.md.
"""
import os

from roshanavi_examples.pipeline_launch import launch_description


def generate_launch_description():
    return launch_description(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           'pipeline.json'))
'''


def launch_file_text(pipe: Pipeline) -> str:
    return LAUNCH_FILE_TEXT.format(launch_path='pipeline.launch.py', mode=pipe.params.mode)


def describe(pipe: Pipeline) -> str:
    """One line for the command line / README."""
    p = pipe.params
    kinds = {k: len(pipe.by_kind(k)) for k in (SOURCE, RELAY, SINK)}
    return (f'{pipe.name}: {p.shape} {p.stages}x{p.width}, {len(pipe.nodes)} nodes '
            f'({kinds[SOURCE]} source, {kinds[RELAY]} relay, {kinds[SINK]} sink), '
            f'{len(pipe.topics)} topics, {p.rate_hz:g} Hz x {p.payload_bytes} B, '
            f'expected {sum(pipe.expected_sink_hz.values()):g} msg/s into the sinks')
