"""Helpers that write a generated relay pipeline (roshanavi_examples.pipeline_gen) for tests."""

import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from roshanavi_examples import pipeline_gen as gen


def write_spec(folder: str, params: gen.PipelineParams, name: str = 'pipeline_test',
               source_rates: Optional[Sequence[float]] = None) -> Tuple[str, Dict[str, Any]]:
    """Write pipeline.json (optionally with a different rate per source) and return its path."""
    pipe = gen.build_pipeline(params, name)
    spec = json.loads(gen.spec_json(pipe))
    if source_rates:
        sources = [n for n in spec['nodes'] if n['kind'] == gen.SOURCE]
        for node, rate in zip(sources, source_rates):
            node['params']['rate_hz'] = rate
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, 'pipeline.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(spec, fh)
    return path, spec


def launch_target(target_id: str, spec_path: str, mode: str, **extra: str) -> Dict[str, Any]:
    """A ``kind: launch`` target of the installed pipeline.launch.py."""
    args: List[str] = [f'spec:={spec_path}', f'mode:={mode}'] + [f'{k}:={v}' for k, v in extra.items()]
    return {'id': target_id, 'kind': 'launch', 'package': 'roshanavi_examples',
            'launch_file': 'pipeline.launch.py', 'args': args, 'role': 'mine'}


def pipeline_node_ids(spec: Dict[str, Any]) -> List[str]:
    return sorted('/' + n['name'] for n in spec['nodes'])
