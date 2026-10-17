"""Parameter resolution for imported launch Nodes (pure: rcl YAML rules, split)."""

import pytest

from roshanavi.launch_import.params_merge import (file_values, flatten, matches, merge_sources,
                                                  split_params, unflatten)

FILE = {
    '/**': {'ros__parameters': {'common': 7, 'rate': 1}},
    '/r1/talker': {'ros__parameters': {'rate': 99, 'nested': {'gain': 2.0}}},
    'r1': {'listener': {'ros__parameters': {'nested_ns': True}}},
    '/**/talker': {'ros__parameters': {'any_ns': 'x'}},
    '/r1/*': {'ros__parameters': {'one_level': 1}},
    'other': {'ros__parameters': {'ignored': 1}},
}


@pytest.mark.parametrize('path,name,expected', [
    ('/**', '/talker', True), ('/**', '/a/b/c', True),
    ('/**/talker', '/talker', True), ('/**/talker', '/r1/talker', True),
    ('/**/talker', '/r1/listener', False),
    ('/r1/*', '/r1/talker', True), ('/r1/*', '/r1/x/talker', False),
    ('/r1/talker', '/r1/talker', True), ('r1/talker', '/r1/talker', True),
    ('/talker', '/r1/talker', False),
    ('/**', None, True), ('/r1/talker', None, False)])
def test_matches(path, name, expected):
    assert matches(path, name) is expected


def test_file_values_wildcards_first_then_specific():
    values = file_values(FILE, '/r1/talker')
    assert values == {'common': 7, 'rate': 99, 'any_ns': 'x', 'one_level': 1,
                      'nested.gain': 2.0}
    assert file_values(FILE, '/r1/listener') == {'common': 7, 'rate': 1, 'one_level': 1,
                                                 'nested_ns': True}
    assert file_values(FILE, None) == {'common': 7, 'rate': 1}
    assert file_values('not a mapping', '/x') == {}


def test_merge_sources_in_launch_order():
    sources = [{'kind': 'param', 'name': 'use_sim_time', 'value': False, 'global': True},
               {'kind': 'dict', 'values': {'rate': 5, 'deep': {'a': 1}}},
               {'kind': 'file', 'path': '/p.yaml', 'content': FILE},
               {'kind': 'param', 'name': 'last', 'value': 'x'},
               {'kind': 'file', 'path': '/bad.yaml', 'error': 'OSError: nope'}]
    merged, files, problems = merge_sources(sources, '/r1/talker')
    assert merged['use_sim_time'] is False
    assert merged['rate'] == 99  # the file comes after the dict
    assert merged['deep.a'] == 1 and merged['last'] == 'x'
    assert files == ['/p.yaml', '/bad.yaml']
    assert problems[0]['code'] == 'param_file_unreadable'


def test_split_scalars_from_the_rest():
    scalars, rest = split_params({'rate': 5, 'gain': 1.5, 'on': True, 'label': 'a',
                                  'ids': [1, 2], 'bad name': 1, 'gone': None,
                                  'qos_overrides./chatter.depth': 3, 'big': 'x' * 5000})
    assert scalars == {'rate': 5, 'gain': 1.5, 'on': True, 'label': 'a'}
    assert set(rest) == {'ids', 'bad name', 'qos_overrides./chatter.depth', 'big'}


def test_flatten_unflatten_round_trip():
    nested = {'a': {'b': 1, 'c': {'d': [1, 2]}}, 'e': 'x'}
    assert flatten(nested) == {'a.b': 1, 'a.c.d': [1, 2], 'e': 'x'}
    assert unflatten(flatten(nested)) == nested
