"""「コードの場所」: why code is not found, with the user's real paths (docs/design/user-code.md §3).

Every reason of the design table is built as a real tree: no ``__init__.py``, no package.xml,
syntax error, no top-level function / class, private names, an unsynced git submodule (made with
real ``git``; roshanavi itself never runs git), an outward symlink — plus collisions, stale code
paths and missing installed modules.
"""

import os
import subprocess

import pytest

from roshanavi.function import code_report, modules
from roshanavi.function.scopes import CodeLocations
from user_code_fixtures import (ament_python, clone, flat_project, install_dist,
                                repo_with_submodule, write)

SHOUT = 'def shout(text: str) -> str:\n    return text.upper()\n'


def codes(report):
    return [p['code'] for p in report['problems']]


def problem(report, code, **match):
    found = [p for p in report['problems'] if p['code'] == code
             and all(p.get(k) == v for k, v in match.items())]
    assert found, (code, match, report['problems'])
    return found[0]


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / 'ws'
    ament_python(root / 'src', 'good_pkg', {'logic.py': SHOUT})
    return root


def test_every_reason_of_the_design_table(ws, tmp_path):
    src = ws / 'src'
    # 1. no __init__.py (a directory with .py files inside a ROS package)
    pkg = ament_python(src, 'noinit_pkg', {})
    os.unlink(pkg / 'noinit_pkg' / '__init__.py')
    write(pkg / 'noinit_pkg' / 'logic.py', SHOUT)
    # 2. no package.xml under src
    write(src / 'plain_scripts' / 'tool.py', SHOUT)
    # 3. syntax error
    write(src / 'good_pkg' / 'good_pkg' / 'broken.py', 'def shout(text:\n    return text\n')
    # 4. no top-level function / class (only inside a class / if __name__)
    write(src / 'good_pkg' / 'good_pkg' / 'consts.py', '''\
        LIMIT = 3
        if __name__ == '__main__':
            def demo():
                pass
    ''')
    # 5. only names starting with _
    write(src / 'good_pkg' / 'good_pkg' / 'internal.py', 'def _helper(x):\n    return x\n')
    # 7. a symlink that leaves the workspace
    outside = tmp_path / 'elsewhere' / 'their_pkg'
    write(outside / 'package.xml', '<package><name>their_pkg</name></package>')
    os.symlink(outside, src / 'their_pkg')
    # extra: .py next to package.xml (a common first mistake)
    write(src / 'good_pkg' / 'logic_here.py', SHOUT)

    report = code_report.report(CodeLocations.of(str(ws)))
    assert problem(report, 'no_init', path=str(pkg / 'noinit_pkg'))['package'] == 'noinit_pkg'
    problem(report, 'not_ros_package', path=str(src / 'plain_scripts'))
    err = problem(report, 'syntax_error', file=str(src / 'good_pkg' / 'good_pkg' / 'broken.py'))
    assert err['line'] == 1 and err['message']
    nm = problem(report, 'no_members', file=str(src / 'good_pkg' / 'good_pkg' / 'consts.py'))
    assert nm['skipped'] == ['demo']
    assert problem(report, 'private_only', file=str(
        src / 'good_pkg' / 'good_pkg' / 'internal.py'))['names'] == ['_helper']
    out = problem(report, 'outside_symlink', path=str(src / 'their_pkg'))
    assert out['target'] == str(outside.resolve())
    assert problem(report, 'loose_files', path=str(src / 'good_pkg'))['files'] == ['logic_here.py']
    # The candidate still works, and nothing else is reported.
    assert 'good_pkg.logic' in [m['module'] for m in modules.list_modules(str(ws))]
    assert set(codes(report)) == {'no_init', 'not_ros_package', 'syntax_error', 'no_members',
                                  'private_only', 'outside_symlink', 'loose_files'}
    assert report['place_here'] == [{'scope': 'workspace', 'root': str(src.resolve())}]
    assert report['scopes']['workspace']['packages'] == [
        {'top': 'good_pkg', 'ros_package': 'good_pkg', 'dir': str(src / 'good_pkg' / 'good_pkg')}]
    assert report['src_exists'] and report['src_writable']


def test_namespace_packages_in_source_scopes_say_what_to_do(ws, tmp_path):
    """PEP 420 namespace packages (no ``__init__.py``) are fine when installed (scope C), but a
    source package needs one: the reason says so, for A and B."""
    pkg = ament_python(ws / 'src', 'ns_ros_pkg', {})
    os.unlink(pkg / 'ns_ros_pkg' / '__init__.py')
    write(pkg / 'ns_ros_pkg' / 'vision' / '__init__.py', '')
    write(pkg / 'ns_ros_pkg' / 'vision' / 'edge.py', SHOUT)
    proj = tmp_path / 'ns_proj'
    write(proj / 'src' / 'acme' / 'vision' / '__init__.py', '')
    write(proj / 'src' / 'acme' / 'vision' / 'edge.py', SHOUT)
    report = code_report.report(CodeLocations(str(ws), code_paths=(str(proj),)))
    problem(report, 'namespace_package', path=str(pkg / 'ns_ros_pkg'))
    problem(report, 'namespace_package', path=str((proj / 'src' / 'acme').resolve()))
    assert 'code_path_empty' not in codes(report)
    assert not [m for m in modules.list_modules(CodeLocations(str(ws), code_paths=(str(proj),)))
                if 'edge' in m['module']]


def test_report_never_imports(ws, tmp_path):
    marker = tmp_path / 'imported'
    write(ws / 'src' / 'good_pkg' / 'good_pkg' / 'side.py',
          f'open({str(marker)!r}, "w").write("x")\n' + SHOUT)
    proj = flat_project(tmp_path / 'proj', 'b_lib', {
        'side.py': f'open({str(marker)!r}, "w").write("x")\n'})
    code_report.report(CodeLocations(str(ws), code_paths=(str(proj),)))
    assert not marker.exists()


def test_missing_src_and_empty_workspace(tmp_path):
    report = code_report.report(CodeLocations.of(str(tmp_path / 'nows')))
    assert codes(report) == ['no_src'] and not report['src_exists']


# ---- git submodules (U7) --------------------------------------------------------------------
def test_unsynced_submodule_says_how_to_sync_and_synced_one_is_a_normal_package(tmp_path):
    sub_files = {'package.xml': '<?xml version="1.0"?><package format="3"><name>vision_lib'
                 '</name><version>0.0.0</version><description>x</description><maintainer '
                 'email="a@b.c">a</maintainer><license>MIT</license></package>\n',
                 'vision_lib/__init__.py': '', 'vision_lib/filters.py': SHOUT}
    repo = repo_with_submodule(tmp_path, sub_files)
    unsynced = clone(repo, tmp_path / 'clone_plain', recursive=False)
    assert (unsynced / 'src' / 'vision_lib').is_dir()
    assert not os.listdir(unsynced / 'src' / 'vision_lib')
    report = code_report.report(CodeLocations.of(str(unsynced)))
    sub = problem(report, 'submodule_empty', path=str((unsynced / 'src' / 'vision_lib').resolve()))
    assert sub['command'] == 'git submodule update --init --recursive'
    assert sub['root'] == str(unsynced.resolve())
    assert 'not_ros_package' not in codes(report)

    synced = clone(repo, tmp_path / 'clone_recursive', recursive=True)
    assert (synced / 'src' / 'vision_lib' / '.git').is_file()      # a gitlink file: not entered
    report = code_report.report(CodeLocations.of(str(synced)))
    assert 'submodule_empty' not in codes(report)
    assert 'vision_lib.filters' in [m['module'] for m in modules.list_modules(str(synced))]


def test_unsynced_submodule_inside_a_code_path(tmp_path, ws):
    repo = repo_with_submodule(tmp_path, {'lib/__init__.py': '', 'lib/m.py': SHOUT},
                               sub_path='third_party/lib_repo')
    plain = clone(repo, tmp_path / 'b_clone', recursive=False)
    report = code_report.report(CodeLocations(str(ws), code_paths=(str(plain),)))
    problem(report, 'submodule_empty', path=str((plain / 'third_party' / 'lib_repo').resolve()))
    # a non-ROS synced submodule under src: "not a ROS package -> register it"
    synced = clone(repo, tmp_path / 'b_synced', recursive=True)
    sub_dir = synced / 'third_party' / 'lib_repo'
    loc = CodeLocations(str(ws), code_paths=(str(sub_dir),))
    assert 'lib.m' in [m['module'] for m in modules.list_modules(loc)]


def test_git_dirs_are_never_entered(ws):
    git_dir = ws / 'src' / 'good_pkg' / '.git'
    write(git_dir / 'objects' / 'evil.py', 'def evil(x): return x\n')
    write(ws / 'src' / 'good_pkg' / 'good_pkg' / '.git' / 'x.py', 'def x(y): return y\n')
    listed = [m['module'] for m in modules.list_modules(str(ws))]
    assert not [m for m in listed if 'evil' in m or m.endswith('.x')]
    report = code_report.report(CodeLocations.of(str(ws)))
    assert not [p for p in report['problems'] if '.git' in str(p.get('path') or p.get('file'))]


# ---- scope B / C status --------------------------------------------------------------------
def test_code_path_and_installed_statuses_and_collisions(ws, tmp_path):
    good = flat_project(tmp_path / 'good', 'b_lib', {'m.py': SHOUT})
    noinit = tmp_path / 'scripts_only'
    write(noinit / 'tool.py', SHOUT)
    empty = tmp_path / 'empty_dir'
    empty.mkdir()
    collide = flat_project(tmp_path / 'collide', 'good_pkg', {'m.py': SHOUT})
    site = tmp_path / 'site'
    install_dist(site, 'b-lib', '1', {'m.py': SHOUT}, top='b_lib')
    install_dist(site, 'c-lib', '1', {'m.py': SHOUT}, top='c_lib')
    import importlib.machinery
    write(site / f'fastlib{importlib.machinery.EXTENSION_SUFFIXES[0]}', 'x')
    loc = CodeLocations(str(ws), code_paths=(str(good), str(noinit), str(empty), str(collide),
                                             str(tmp_path / 'gone')),
                        installed_modules=('b_lib', 'c_lib', 'fastlib', 'not_installed_xyz'),
                        search_path=(str(site),))
    report = code_report.report(loc)
    statuses = {c['path']: c for c in report['scopes']['code_paths']}
    assert statuses[str(good)]['packages'] == [{'top': 'b_lib', 'dir': str(good / 'b_lib'),
                                               'layout': 'flat'}]
    assert statuses[str(tmp_path / 'gone')]['status'] == 'invalid'
    problem(report, 'code_path_invalid', path=str(tmp_path / 'gone'))
    problem(report, 'no_init', path=str(noinit.resolve()))
    problem(report, 'code_path_empty', path=str(empty.resolve()))
    col = problem(report, 'name_collision', top='good_pkg')
    assert (col['kept_scope'], col['ignored_scope']) == ('workspace', 'code_path')
    col = problem(report, 'name_collision', top='b_lib')
    assert (col['kept_scope'], col['ignored_scope'], col['ignored']) == ('code_path', 'installed',
                                                                        'b_lib')
    problem(report, 'installed_not_found', module='not_installed_xyz')
    by_module = {i['module']: i for i in report['scopes']['installed_modules']}
    assert by_module['b_lib']['status'] == 'shadowed'
    assert by_module['c_lib']['status'] == 'found' and by_module['c_lib']['listable']
    assert by_module['fastlib']['status'] == 'extension' and not by_module['fastlib']['listable']
    assert {'scope': 'code_path', 'root': str(good.resolve())} in report['place_here']


def test_gitmodules_paths_cannot_escape(tmp_path):
    root = tmp_path / 'r'
    write(root / '.gitmodules', '[submodule "x"]\n\tpath = ../../etc\n[submodule "y"]\n'
                                '\tpath = lib/y\n\turl = ../y\n')
    assert code_report.gitmodule_paths(str(root)) == [str((root / 'lib' / 'y').resolve())]


def test_git_is_not_needed_to_read_submodules(tmp_path, monkeypatch):
    """The report reads .gitmodules only: it works with git removed from PATH."""
    repo = repo_with_submodule(tmp_path, {'lib/__init__.py': ''}, sub_path='src/lib_repo')
    plain = clone(repo, tmp_path / 'c', recursive=False)
    monkeypatch.setenv('PATH', '/nonexistent')
    calls = []
    real_run = subprocess.run
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: calls.append(a) or real_run(*a, **k))
    report = code_report.report(CodeLocations.of(str(plain)))
    assert 'submodule_empty' in codes(report) and calls == []
