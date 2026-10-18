"""Launch builder of the relay pipeline (roshanavi_examples.pipeline_launch): which actions come out.

No node is started: the actions are built from a generated spec and inspected, in process mode
(one Node per pipeline node) and container mode (ComposableNodeContainer(s) holding them).
"""

import json

import pytest
from launch import LaunchContext
from launch_ros.actions import ComposableNodeContainer, Node

from roshanavi.launch_import.extract import container_nodes
from roshanavi_examples import pipeline_gen as gen
from roshanavi_examples import pipeline_launch as launch


@pytest.fixture
def spec():
    return json.loads(gen.spec_json(gen.build_pipeline(gen.preset_params('medium'))))


def test_process_mode_is_one_node_per_pipeline_node(spec):
    actions = launch.build_actions(spec, 'process', 1, 'st', False)
    assert len(actions) == 20 and all(isinstance(a, Node) for a in actions)
    first = actions[0]
    assert first.node_package == 'roshanavi_examples'
    assert first.node_executable == 'pipeline_source'


@pytest.mark.parametrize('count', [1, 2, 3, 5])
def test_container_mode_holds_every_node_exactly_once(spec, count):
    actions = launch.build_actions(spec, 'container', count, 'st', False)
    assert len(actions) == min(count, 20) and all(isinstance(a, ComposableNodeContainer) for a in actions)
    listed = [text for a in actions for text in container_nodes(a, LaunchContext())]
    assert len(listed) == 20
    assert sorted(t.split('(')[1].rstrip(')') for t in listed) == sorted(n['name'] for n in spec['nodes'])
    assert {t.split(' ')[0] for t in listed} == {
        'roshanavi_examples/roshanavi_examples::PipelineSource',
        'roshanavi_examples/roshanavi_examples::PipelineRelay',
        'roshanavi_examples/roshanavi_examples::PipelineSink'}


def test_container_type_and_intra_process_are_applied(spec):
    st = launch.build_actions(spec, 'container', 1, 'st', False)[0]
    mt = launch.build_actions(spec, 'container', 1, 'mt', True)[0]
    assert st.node_executable == 'component_container'
    assert mt.node_executable == 'component_container_mt'
    desc = getattr(mt, '_ComposableNodeContainer__composable_node_descriptions')[0]
    plain = getattr(st, '_ComposableNodeContainer__composable_node_descriptions')[0]
    assert [list(a.values()) for a in desc.extra_arguments] == [[True]]
    assert [list(a.values()) for a in plain.extra_arguments] == [[False]]


def test_unknown_mode_and_container_type_are_rejected(spec):
    with pytest.raises(ValueError, match='mode'):
        launch.build_actions(spec, 'thread', 1, 'st', False)
    with pytest.raises(ValueError, match='container_type'):
        launch.build_actions(spec, 'container', 1, 'xx', False)


def test_spec_file_is_validated(tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps({'version': 2, 'nodes': []}))
    with pytest.raises(ValueError, match='not a pipeline spec'):
        launch.load_spec(str(bad))


def test_launch_description_declares_the_overrides(tmp_path, spec):
    path = tmp_path / 'pipeline.json'
    path.write_text(json.dumps(spec))
    description = launch.launch_description(str(path))
    names = {e.name for e in description.entities if hasattr(e, 'default_value')}
    assert names == {'mode', 'containers', 'container_type', 'intra_process'}
    installed = launch.launch_description()
    assert 'spec' in {e.name for e in installed.entities if hasattr(e, 'default_value')}
