import os

import pytest

from roshanavi.files import (FileAccessError, list_files, load_stream, parse_csv, parse_jsonl,
                             resolve_in_data_dir)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / 'data'
    (root / 'sub').mkdir(parents=True)
    (root / 'a.jsonl').write_text('{"data": "x"}\n')
    (root / 'sub' / 'b.csv').write_text('data\nhello\n')
    bag = root / 'bag1'
    bag.mkdir()
    (bag / 'metadata.yaml').write_text('x: 1\n')
    (bag / 'bag1_0.mcap').write_bytes(b'\0' * 10)
    (tmp_path / 'secret.txt').write_text('nope')
    return root


def test_resolve_inside(tree):
    assert resolve_in_data_dir(str(tree), 'a.jsonl') == os.path.realpath(tree / 'a.jsonl')
    assert resolve_in_data_dir(str(tree), 'sub/../a.jsonl').endswith('a.jsonl')


@pytest.mark.parametrize('path', ['../secret.txt', '/etc/passwd', 'sub/../../secret.txt', '',
                                  'a\x00b'])
def test_resolve_rejects_escape(tree, path):
    with pytest.raises(FileAccessError) as info:
        resolve_in_data_dir(str(tree), path)
    assert info.value.code == 'forbidden_path'


def test_resolve_rejects_symlink_escape(tree):
    os.symlink(tree.parent / 'secret.txt', tree / 'link.txt')
    with pytest.raises(FileAccessError) as info:
        resolve_in_data_dir(str(tree), 'link.txt')
    assert info.value.code == 'forbidden_path'


def test_resolve_rejects_sibling_prefix_dir(tree):
    sibling = tree.parent / 'data_evil'
    sibling.mkdir()
    (sibling / 'x.jsonl').write_text('{}\n')
    with pytest.raises(FileAccessError):
        resolve_in_data_dir(str(tree), '../data_evil/x.jsonl')


def test_resolve_missing(tree):
    with pytest.raises(FileAccessError) as info:
        resolve_in_data_dir(str(tree), 'missing.jsonl')
    assert info.value.code == 'not_found'


def test_list_files(tree):
    files = {f['path']: f for f in list_files(str(tree))}
    assert files['a.jsonl']['kind'] == 'jsonl'
    assert files[os.path.join('sub', 'b.csv')]['kind'] == 'csv'
    assert files['bag1']['kind'] == 'bag'
    assert not any(p.startswith('bag1' + os.sep) for p in files)


def test_list_files_missing_dir(tmp_path):
    assert list_files(str(tmp_path / 'nope')) == []


def test_parse_jsonl():
    assert parse_jsonl('{"a": 1}\n\n{"a": 2}\n') == [{'a': 1}, {'a': 2}]
    with pytest.raises(FileAccessError, match='line 2'):
        parse_jsonl('{"a": 1}\n{bad\n')
    with pytest.raises(FileAccessError):
        parse_jsonl('[1, 2]\n')


def test_parse_csv_nested_paths_and_types():
    rows = parse_csv('pose.position.x,pose.position.y,frame,flag\n1.5,2,map,true\n')
    assert rows == [{'pose': {'position': {'x': 1.5, 'y': 2}}, 'frame': 'map', 'flag': True}]


def test_parse_csv_errors():
    with pytest.raises(FileAccessError):
        parse_csv('a,a\n1,2\n')
    with pytest.raises(FileAccessError, match='line 2'):
        parse_csv('a,b\n1\n')
    with pytest.raises(FileAccessError, match='conflicting'):
        parse_csv('a,a.b\n1,2\n')


def test_load_stream_by_extension(tree):
    assert load_stream(str(tree / 'a.jsonl')) == [{'data': 'x'}]
    assert load_stream(str(tree / 'sub' / 'b.csv')) == [{'data': 'hello'}]
    with pytest.raises(FileAccessError):
        load_stream(str(tree / 'bag1' / 'metadata.yaml'))
