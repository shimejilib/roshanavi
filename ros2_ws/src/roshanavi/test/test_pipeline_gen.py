"""Relay pipeline generator (roshanavi_examples.pipeline_gen): topology, rates, project files.

Pure Python: no ROS node is started here. The committed examples/pipeline_* must be exactly what
the generator writes (so the docs and the samples cannot drift apart).
"""

import json
import os

import pytest
import yaml

from roshanavi_examples import pipeline_gen as gen

EXAMPLES = os.environ.get('ROSHANAVI_TEST_EXAMPLES', '/examples')


def build(**kw):
    return gen.build_pipeline(gen.PipelineParams(**kw))


def by_name(pipe):
    return {n.name: n for n in pipe.nodes}


def check_wiring(pipe):
    """Invariants every pipeline must have."""
    names = [n.name for n in pipe.nodes]
    assert len(set(names)) == len(names)
    publishers = {}
    for node in pipe.nodes:
        assert len(set(node.outputs)) == len(node.outputs)
        for topic in node.outputs:
            assert topic not in publishers, f'{topic} has two publishers'
            publishers[topic] = node.name
    for node in pipe.nodes:
        for topic in node.inputs:
            assert topic in publishers, f'{node.name} listens to {topic} that nobody publishes'
        if node.kind == gen.SOURCE:
            assert not node.inputs and node.outputs
        elif node.kind == gen.SINK:
            assert node.inputs and not node.outputs
        else:
            assert node.inputs and node.outputs
    for topic in publishers:
        assert any(topic in n.inputs for n in pipe.nodes), f'{topic} has no subscriber'
    stage = {n.name: n.stage for n in pipe.nodes}
    for node in pipe.nodes:  # edges only go forward: no cycles
        for topic in node.inputs:
            assert stage[publishers[topic]] < node.stage
    # parameter counts match the wiring the C++ node will create
    for node in pipe.nodes:
        assert node.params.get('num_inputs', 1) == max(1, len(node.inputs))
        assert node.params.get('num_outputs', 1) == max(1, len(node.outputs))
        assert set(node.remaps) == {gen.endpoint('in', i) for i in range(len(node.inputs))} | \
            {gen.endpoint('out', i) for i in range(len(node.outputs))}


def reachable_sinks(pipe, source):
    consumers = {}
    for n in pipe.nodes:
        for t in n.inputs:
            consumers.setdefault(t, []).append(n)
    seen, todo = set(), [by_name(pipe)[source]]
    while todo:
        node = todo.pop()
        for topic in node.outputs:
            for nxt in consumers[topic]:
                if nxt.name not in seen:
                    seen.add(nxt.name)
                    todo.append(nxt)
    return {n for n in seen if by_name(pipe)[n].kind == gen.SINK}


# ---- presets and shapes -----------------------------------------------------------------------

@pytest.mark.parametrize('preset,total,sources,sinks', [
    ('small', 3, 1, 1), ('medium', 20, 4, 4), ('large', 200, 20, 20)])
def test_preset_sizes(preset, total, sources, sinks):
    pipe = gen.build_pipeline(gen.preset_params(preset))
    assert len(pipe.nodes) == total
    assert len(pipe.by_kind(gen.SOURCE)) == sources and len(pipe.by_kind(gen.SINK)) == sinks
    check_wiring(pipe)


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match='unknown preset'):
        gen.preset_params('huge')


def test_chain_is_a_line():
    pipe = build(shape='chain', stages=5)
    assert [n.name for n in pipe.nodes] == ['src', 'relay_1', 'relay_2', 'relay_3', 'sink']
    nodes = by_name(pipe)
    assert nodes['src'].outputs == nodes['relay_1'].inputs == ('/pipe/src',)
    assert nodes['relay_3'].outputs == nodes['sink'].inputs == ('/pipe/relay_3',)
    assert len(pipe.topics) == 4
    assert pipe.expected_sink_hz == {'sink': 10.0}
    check_wiring(pipe)


def test_two_stage_chain_is_source_to_sink():
    pipe = build(shape='chain', stages=2)
    assert [n.kind for n in pipe.nodes] == [gen.SOURCE, gen.SINK]
    check_wiring(pipe)


def test_fanout_hub_feeds_every_lane_and_each_sink_gets_everything():
    pipe = build(shape='fanout', stages=5, width=3, rate_hz=20)
    nodes = by_name(pipe)
    hub = nodes['relay_1']
    assert len(hub.outputs) == 3 and hub.params['num_outputs'] == 3
    assert 'fanout' not in hub.params  # "all" is the default of the node
    assert len(pipe.nodes) == 1 + 1 + 3 * (5 - 3 + 1)
    assert len(pipe.by_kind(gen.SINK)) == 3
    assert reachable_sinks(pipe, 'src') == {'sink_0', 'sink_1', 'sink_2'}
    assert pipe.expected_sink_hz == {'sink_0': 20.0, 'sink_1': 20.0, 'sink_2': 20.0}
    check_wiring(pipe)


def test_fanin_merges_all_sources_into_one_sink():
    pipe = build(shape='fanin', stages=4, width=3, rate_hz=5)
    nodes = by_name(pipe)
    merge = nodes['relay_2']
    assert len(merge.inputs) == 3 and merge.params['num_inputs'] == 3
    assert len(pipe.by_kind(gen.SOURCE)) == 3 and len(pipe.by_kind(gen.SINK)) == 1
    assert pipe.expected_sink_hz == {'sink': 15.0}  # the rates add up
    for source in ('src_0', 'src_1', 'src_2'):
        assert reachable_sinks(pipe, source) == {'sink'}
    check_wiring(pipe)


def test_grid_straight_is_independent_columns():
    pipe = build(shape='grid', stages=4, width=3, links='straight')
    assert len(pipe.nodes) == 12
    for j in range(3):
        assert reachable_sinks(pipe, f'src_{j}') == {f'sink_{j}'}
    assert all(len(n.inputs) <= 1 and len(n.outputs) <= 1 for n in pipe.nodes)
    check_wiring(pipe)


def test_grid_mesh_every_node_talks_to_two_neighbours_and_keeps_the_rate():
    pipe = build(shape='grid', stages=5, width=4, rate_hz=10)
    nodes = by_name(pipe)
    for n in pipe.nodes:
        if n.kind != gen.SINK:
            assert len(n.outputs) == 2 and n.params['fanout'] == 'round_robin'
        if n.kind != gen.SOURCE:
            assert len(n.inputs) == 2
    # src_1 sends one half to its own column and one half to the next column
    assert nodes['src_1'].outputs[0] in nodes['relay_1_1'].inputs
    assert nodes['src_1'].outputs[1] in nodes['relay_1_2'].inputs
    assert nodes['src_3'].outputs[1] in nodes['relay_1_0'].inputs  # wraps around
    # round robin splits each node's rate: nothing multiplies, nothing vanishes
    assert pipe.expected_sink_hz == {f'sink_{j}': 10.0 for j in range(4)}
    for topic, hz in pipe.topic_hz.items():
        assert hz == pytest.approx(5.0), topic
    for source in range(4):
        assert reachable_sinks(pipe, f'src_{source}')
    check_wiring(pipe)


def test_grid_of_width_two_has_distinct_mesh_topics():
    pipe = build(shape='grid', stages=3, width=2)
    check_wiring(pipe)
    relay = by_name(pipe)['relay_1_0']
    assert len(set(relay.inputs)) == 2


def test_grid_of_width_one_degenerates_to_a_chain():
    pipe = build(shape='grid', stages=4, width=1)
    assert [n.name for n in pipe.nodes] == ['src', 'relay_1', 'relay_2', 'sink']
    check_wiring(pipe)


def test_large_grid_is_consistent():
    check_wiring(gen.build_pipeline(gen.preset_params('large')))


# ---- rates ------------------------------------------------------------------------------------

def test_expected_rate_with_drops_and_limits():
    pipe = build(shape='chain', stages=4, rate_hz=100, drop_ratio=0.5)
    assert pipe.expected_sink_hz['sink'] == pytest.approx(100 * 0.5 * 0.5)  # two relays
    capped = build(shape='chain', stages=3, rate_hz=100, rate_limit_hz=30)
    assert capped.expected_sink_hz['sink'] == pytest.approx(30.0)
    loose = build(shape='chain', stages=3, rate_hz=10, rate_limit_hz=30)
    assert loose.expected_sink_hz['sink'] == pytest.approx(10.0)


def test_relay_params_only_list_what_differs_from_the_node_defaults():
    plain = by_name(build(shape='chain'))['relay_1']
    assert dict(plain.params) == {}
    busy = by_name(build(shape='chain', process_ms=5, relay_payload_bytes=2048, keep_stamp=False,
                         rate_limit_hz=20, drop_ratio=0.1, process_mode='sleep'))['relay_1']
    assert dict(busy.params) == {'process_ms': 5, 'process_mode': 'sleep',
                                 'payload_bytes': 2048, 'rate_limit_hz': 20,
                                 'keep_stamp': False, 'drop_ratio': 0.1}
    src = by_name(build(shape='chain', rate_hz=25, payload_bytes=4096))['src']
    assert dict(src.params) == {'rate_hz': 25, 'payload_bytes': 4096}


@pytest.mark.parametrize('kw,message', [
    ({'shape': 'ring'}, 'shape'), ({'shape': 'chain', 'stages': 1}, 'stages'),
    ({'shape': 'grid', 'stages': 2}, 'stages'), ({'width': 0}, 'width'),
    ({'rate_hz': 0}, 'rate_hz'), ({'drop_ratio': 1.5}, 'drop_ratio'),
    ({'process_ms': -1}, 'process_ms'), ({'containers': 0}, 'containers'),
    ({'topic_prefix': 'pipe'}, 'topic_prefix'), ({'topic_prefix': '/pipe/'}, 'topic_prefix'),
    ({'mode': 'thread'}, 'mode'), ({'process_mode': 'nap'}, 'process_mode'),
    ({'payload_bytes': -1}, 'payload_bytes'),
])
def test_invalid_parameters_are_rejected(kw, message):
    with pytest.raises(ValueError, match=message):
        build(**kw)


# ---- containers -------------------------------------------------------------------------------

@pytest.mark.parametrize('count', [1, 2, 3, 7, 50])
def test_assign_containers_partitions_every_node_once(count):
    pipe = gen.build_pipeline(gen.preset_params('medium'))
    groups = gen.assign_containers(pipe.nodes, count)
    assert 1 <= len(groups) <= count
    flat = [n.name for g in groups for n in g]
    assert sorted(flat) == sorted(n.name for n in pipe.nodes)
    sizes = [len(g) for g in groups]
    assert all(sizes[i] >= sizes[i + 1] for i in range(len(sizes) - 1))  # equal runs, last shorter


def test_assign_containers_keeps_stage_order():
    pipe = gen.build_pipeline(gen.preset_params('medium'))
    first, *_ = gen.assign_containers(pipe.nodes, 4)
    assert {n.stage for n in first} == {0, 1}  # 5 nodes per container, 4 per stage


def test_container_names():
    assert gen.container_name(0, 1) == 'pipeline_container'
    assert gen.container_name(2, 3) == 'pipeline_container_2'


# ---- spec JSON and project --------------------------------------------------------------------

def test_spec_describes_every_node_and_topic():
    pipe = gen.build_pipeline(gen.preset_params('medium'))
    spec = json.loads(gen.spec_json(pipe))
    assert spec['version'] == 1 and len(spec['nodes']) == 20 and len(spec['topics']) == 32
    assert spec['expected']['total_sink_hz'] == 40.0
    names = {n['name'] for n in spec['nodes']}
    for topic in spec['topics']:
        assert topic['publisher'] in names and set(topic['subscribers']) <= names
        assert len(topic['subscribers']) == 1  # the mesh: every topic has one consumer
    assert spec['launch'] == {'mode': 'process', 'containers': 1, 'container_type': 'st',
                              'intra_process': False}


def load_project(text):
    from roshanavi.launcher.schema import ProjectSpec
    return ProjectSpec(**yaml.safe_load(text))


@pytest.mark.parametrize('preset,mode,kind,count', [
    ('small', 'process', 'run', 3), ('medium', 'process', 'run', 20),
    ('large', 'process', 'launch', 1), ('small', 'container', 'launch', 1),
    ('medium', 'container', 'launch', 1)])
def test_project_files_pass_the_roshanavi_schema(preset, mode, kind, count):
    pipe = gen.build_pipeline(gen.preset_params(preset), f'pipeline_{preset}')
    project = load_project(gen.project_yaml(pipe, f'/examples/pipeline_{preset}/pipeline.json', mode))
    assert len(project.targets) == count
    assert {t.kind for t in project.targets} == {kind}
    if kind == 'run':
        assert {t.name for t in project.targets} == {n.name for n in pipe.nodes}
        assert {t.remaps[k] for t in project.targets for k in t.remaps} == \
            {t for n in pipe.nodes for t in (*n.inputs, *n.outputs)}
        assert {t.role for t in project.targets if t.executable == 'pipeline_relay'} == {'mine'}
    else:
        target = project.targets[0]
        assert (target.package, target.launch_file) == ('roshanavi_examples', 'pipeline.launch.py')
        assert any(a.startswith('spec:=/examples/pipeline_') for a in target.args)
        assert f'mode:={mode}' in target.args


def test_run_target_params_survive_the_launcher_validation():
    from roshanavi.launcher import validate
    pipe = build(shape='fanout', stages=4, width=2, process_ms=3, keep_stamp=False)
    project = load_project(gen.project_yaml(pipe, '/x/pipeline.json', 'process'))
    for target in project.targets:
        validate.target_id(target.id)
        validate.remaps(target.remaps)
        validate.params({k: str(v) for k, v in target.params.items()})
        validate.node_name(target.name)


def test_project_rejects_an_unknown_mode():
    with pytest.raises(ValueError, match='mode'):
        gen.project_yaml(build(), '/x.json', 'thread')


def test_launch_file_text_names_the_spec_next_to_it():
    text = gen.launch_file_text(build())
    compile(text, 'pipeline.launch.py', 'exec')
    assert "'pipeline.json'" in text and 'launch_description' in text


# ---- the committed samples are what the generator writes -------------------------------------

@pytest.mark.skipif(not os.path.isdir(EXAMPLES), reason='examples/ not mounted')
@pytest.mark.parametrize('preset', list(gen.PRESETS))
def test_committed_examples_are_up_to_date(preset):
    pipe = gen.build_pipeline(gen.preset_params(preset), f'pipeline_{preset}')
    folder = os.path.join(EXAMPLES, f'pipeline_{preset}')
    server = f'/examples/pipeline_{preset}/pipeline.json'
    expected = {'pipeline.json': gen.spec_json(pipe),
                'pipeline.launch.py': gen.launch_file_text(pipe)}
    for name, text in expected.items():
        with open(os.path.join(folder, name), encoding='utf-8') as fh:
            assert fh.read() == text, f'{name} of {folder} is stale: run scripts/gen_pipeline.py --all'
    for name, mode in (('roshanavi.yaml', 'process'), ('roshanavi_container.yaml', 'container')):
        with open(os.path.join(folder, name), encoding='utf-8') as fh:
            text = fh.read()
        assert yaml.safe_load(text) == yaml.safe_load(gen.project_yaml(pipe, server, mode)), name
