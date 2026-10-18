"""The node side of user code: importing from scope B / C, relative imports, sibling reload,
notices (slow import, rclpy, extension modules), missing dependencies and requirements.txt.

docs/design/user-code.md §5–§6. The loader runs inside the pytest process here (as it does inside
the node process); ``test_user_code_ros.py`` runs real node processes.
"""

import os
import sys
import time

import pytest

from roshanavi.function import code_imports, node_env
from roshanavi.function.class_loader import ClassLoader
from roshanavi.function.loader import FunctionLoader, LoadError, missing_module_of
from roshanavi.function.scopes import CodeLocations
from user_code_fixtures import (SHOUT_EXTENSION, ament_python, build_extension, flat_project,
                                install_dist, src_layout_project, write)

SHOUT = 'def shout(text: str) -> str:\n    return text.upper()\n'


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / 'ws'
    (root / 'src').mkdir(parents=True)
    return root


@pytest.fixture
def clean_modules():
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.split('.')[0].startswith(('lu_', 'ext_', 'inst_')) or name == 'fastlib':
            del sys.modules[name]
    code_imports.uninstall()


def test_b_src_layout_relative_imports_and_sibling_reload(ws, tmp_path, clean_modules):
    proj = src_layout_project(tmp_path / 'proj', 'lu_lib', {
        'utils.py': "SUFFIX = '!'\n",
        'deep/__init__.py': '', 'deep/more.py': 'def twice(x):\n    return x * 2\n',
        'filters.py': '''\
            from .utils import SUFFIX
            from .deep.more import twice


            def shout(text: str) -> str:
                return twice(text.upper()) + SUFFIX
        '''})
    loc = CodeLocations(str(ws), code_paths=(str(proj),))
    loader = FunctionLoader(loc, 'lu_lib.filters', 'shout')
    assert loader.load()('ab') == 'ABAB!'
    watched = {os.path.basename(p) for p in loader.watched_files}
    assert {'filters.py', 'utils.py', 'more.py', '__init__.py'} <= watched
    write(proj / 'src' / 'lu_lib' / 'utils.py', "SUFFIX = '?'\n")   # only the sibling changes
    assert loader.changed()
    assert loader.load()('ab') == 'ABAB?'
    assert loader.environment['scope'] == 'code_path'
    assert loader.environment['python']['executable'] == sys.executable


def test_b_class_node_loads_from_a_flat_project(ws, tmp_path, clean_modules):
    proj = flat_project(tmp_path / 'p', 'lu_cls', {'state.py': '''\
        class Acc:
            def __init__(self, start: int = 0):
                self.total = start

            def process(self, x: int) -> int:
                self.total += x
                return self.total
    '''})
    loader = ClassLoader(CodeLocations(str(ws), code_paths=(str(proj),)), 'lu_cls.state', 'Acc')
    acc = loader.load()(start=5)
    assert acc.process(2) == 7
    assert loader.location_of_function().endswith('lu_cls/state.py:1')


def test_c_installed_module_is_imported_normally_and_never_reloaded(ws, tmp_path, monkeypatch,
                                                                    clean_modules):
    site = tmp_path / 'site'
    install_dist(site, 'inst-lib', '2.0', {'filters.py': SHOUT}, top='inst_lib')
    monkeypatch.syspath_prepend(str(site))
    loc = CodeLocations(str(ws), installed_modules=('inst_lib',))   # the node: its own sys.path
    loader = FunctionLoader(loc, 'inst_lib.filters', 'shout')
    assert loader.load()('x') == 'X'
    assert loader.watched_files == [] and not loader.changed()
    assert {'code': 'no_hot_reload_installed'} in loader.notices
    assert loader.environment['scope'] == 'installed'
    assert loader.environment['loaded_from'] == str((site / 'inst_lib' / 'filters.py').resolve())
    assert loader.load() is loader.function     # a second load keeps the same function


def test_c_extension_module_function(ws, tmp_path, monkeypatch, clean_modules):
    site = tmp_path / 'site'
    if build_extension(site, 'fastlib', SHOUT_EXTENSION) is None:
        pytest.skip('no C compiler / Python.h in this image')
    monkeypatch.syspath_prepend(str(site))
    loader = FunctionLoader(CodeLocations(str(ws), installed_modules=('fastlib',)), 'fastlib',
                            'shout')
    assert loader.load()('abc') == 'ABC!!'
    codes = [n['code'] for n in loader.notices]
    assert 'extension_module' in codes and 'no_hot_reload_installed' in codes
    assert loader.location_of_function().startswith('fastlib')


def test_extension_inside_a_source_package_has_a_no_reload_notice(ws, clean_modules):
    pkg = ament_python(ws / 'src', 'ext_pkg', {'logic.py': 'from .fastlib import shout as s\n\n'
                                               'def shout(text: str) -> str:\n    return s(text)\n'})
    if build_extension(pkg / 'ext_pkg', 'fastlib', SHOUT_EXTENSION) is None:
        pytest.skip('no C compiler / Python.h in this image')
    loader = FunctionLoader(str(ws), 'ext_pkg.logic', 'shout')
    assert loader.load()('a') == 'A!!'
    notice = next(n for n in loader.notices if n['code'] == 'extension_no_reload')
    assert notice['files'][0].startswith('fastlib')


def test_notices_slow_import_and_rclpy(ws, clean_modules):
    ament_python(ws / 'src', 'lu_slow', {'logic.py': 'import time\ntime.sleep(1.1)\n' + SHOUT,
                                         'rosy.py': 'import rclpy  # noqa\n' + SHOUT})
    slow = FunctionLoader(str(ws), 'lu_slow.logic', 'shout')
    slow.load()
    notice = next(n for n in slow.notices if n['code'] == 'slow_import')
    assert notice['seconds'] >= 1.0 and slow.import_seconds >= 1.0
    rosy = FunctionLoader(str(ws), 'lu_slow.rosy', 'shout')
    rosy.load()
    assert {'code': 'imports_rclpy'} in rosy.notices
    assert not [n for n in rosy.notices if n['code'] == 'slow_import']


def test_missing_dependency_is_named_and_own_modules_are_not(ws, clean_modules):
    ament_python(ws / 'src', 'lu_dep', {
        'needs.py': 'import numpy_absent_for_test_xyz\n' + SHOUT,
        'typo.py': 'from .not_there import x\n' + SHOUT,
        'later.py': 'def shout(text: str) -> str:\n    import cv2_absent_xyz\n    return text\n',
        'wrapped.py': 'try:\n    import yaml_absent_xyz\nexcept ImportError as e:\n'
                      '    raise ImportError("install yaml_absent_xyz first") from e\n' + SHOUT})
    for module, missing in (('lu_dep.needs', 'numpy_absent_for_test_xyz'),
                            ('lu_dep.typo', None), ('lu_dep.wrapped', 'yaml_absent_xyz')):
        loader = FunctionLoader(str(ws), module, 'shout')
        with pytest.raises(LoadError) as err:
            loader.load()
        assert err.value.problem.missing_module == missing, module
        assert (err.value.problem.to_dict().get('missing_module')) == missing
    later = FunctionLoader(str(ws), 'lu_dep.later', 'shout')
    function = later.load()
    with pytest.raises(ModuleNotFoundError) as exc:
        function('x')
    assert missing_module_of(exc.value, 'lu_dep') == 'cv2_absent_xyz'


def test_a_package_named_like_a_library_the_node_imported_is_refused(ws, tmp_path, clean_modules):
    import pluggy  # noqa: F401 - loaded by pytest, like rclpy / numpy in the node
    proj = flat_project(tmp_path / 'p', 'pluggy', {'m.py': SHOUT})
    loader = FunctionLoader(CodeLocations(str(ws), code_paths=(str(proj),)), 'pluggy.m', 'shout')
    with pytest.raises(LoadError, match='already used inside the node'):
        loader.load()
    assert sys.modules['pluggy'].__file__ != str(proj / 'pluggy' / '__init__.py')


def test_requirements_txt_next_to_the_code_is_compared(ws, tmp_path, monkeypatch, clean_modules):
    site = tmp_path / 'site'
    install_dist(site, 'Inst_Lib', '2.0', {}, top='inst_lib')
    monkeypatch.syspath_prepend(str(site))
    pkg = ament_python(ws / 'src', 'lu_req', {'logic.py': SHOUT})
    write(pkg / 'requirements.txt', '''\
        # comment
        inst-lib>=1.5   # installed (name normalized)
        definitely-not-installed-xyz>=1
        inst_lib<1.0
        -r other.txt
        legacy-only; python_version < "3"
        https://example.com/x.whl
    ''')
    loader = FunctionLoader(str(ws), 'lu_req.logic', 'shout')
    loader.load()
    (req,) = loader.environment['requirements']
    assert req['file'] == 'src/lu_req/requirements.txt'
    assert [m['name'] for m in req['missing']] == ['definitely-not-installed-xyz']
    assert [(m['name'], m['installed']) for m in req['mismatched']] == [('inst_lib', '2.0')]
    assert req['ok'] == 1
    assert {s['reason'] for s in req['skipped']} == {'option', 'not_for_this_environment'}

    # Without packaging: presence only, markers are not guessed.
    monkeypatch.setattr(node_env, 'Requirement', None)
    plain = node_env.check_file(str(pkg / 'requirements.txt'), 'r.txt')
    assert [m['name'] for m in plain['missing']] == ['definitely-not-installed-xyz']
    assert plain['mismatched'] == [] and plain['ok'] == 2 and plain['exact'] is False
    assert {s['reason'] for s in plain['skipped']} == {'option', 'marker_unchecked'}


def test_requirements_of_a_failing_import_are_still_checked(ws, tmp_path, clean_modules):
    proj = flat_project(tmp_path / 'p', 'lu_fail', {'m.py': 'import missing_pkg_qq\n' + SHOUT})
    write(proj / 'requirements.txt', 'missing-pkg-qq==1.0\n')
    loader = FunctionLoader(CodeLocations(str(ws), code_paths=(str(proj),)), 'lu_fail.m', 'shout')
    with pytest.raises(LoadError):
        loader.load()
    (req,) = loader.environment['requirements']
    assert req['file'] == str((proj / 'requirements.txt').resolve())
    assert req['missing'][0]['name'] == 'missing-pkg-qq'


def test_python_info_tells_venv_or_not(monkeypatch):
    info = node_env.python_info()
    assert info['executable'] == sys.executable and info['venv'] is (sys.prefix != sys.base_prefix)
    monkeypatch.setattr(sys, 'prefix', '/some/venv')
    assert node_env.python_info()['venv'] is True


def test_parse_line_is_conservative():
    assert node_env.parse_line('numpy>=1.20,<3')[0][0] == 'numpy'
    assert node_env.parse_line('  # only a comment')[0] is None
    assert node_env.parse_line('-e .')[1] == 'option'
    assert node_env.parse_line('git+https://x/y.git')[1] == 'option'
    assert node_env.parse_line('???')[1] == 'unreadable'


def test_reload_keeps_working_after_many_saves(ws, clean_modules):
    pkg = ament_python(ws / 'src', 'lu_many', {'logic.py': SHOUT})
    loader = FunctionLoader(str(ws), 'lu_many.logic', 'shout')
    loader.load()
    for i in range(5):
        write(pkg / 'lu_many' / 'logic.py', f'def shout(text):\n    return "{i}" + text\n')
        time.sleep(0.01)
        assert loader.load()('x') == f'{i}x'
    assert loader.loads == 6


# ---- scope B folders as libraries of the user's code ---------------------------------------------
PID_LIB = {'core.py': "GAIN = 2\n\n\ndef scale(x):\n    return x * GAIN\n",
           '__init__.py': 'from .core import scale\n'}


def a_package_using(ws, lib, extra=''):
    """A scope A class / function whose logic does ``import <lib>`` (the demo's goto.py)."""
    return ament_python(ws / 'src', 'lu_app', {
        'logic.py': f'import {lib}\n{extra}\n\ndef shout(text: str) -> str:\n'
                    f'    return str({lib}.scale(len(text)))\n\n\n'
                    f'class Goto:\n    def process(self, text: str) -> str:\n'
                    f'        return str({lib}.scale(len(text)))\n'})


@pytest.mark.parametrize('layout', ['flat', 'src'])
def test_scope_a_code_imports_a_package_of_a_registered_code_path(ws, tmp_path, clean_modules,
                                                                  layout):
    build = flat_project if layout == 'flat' else src_layout_project
    proj = build(tmp_path / 'third_party' / 'simple-pid', 'lu_pid', PID_LIB)
    a_package_using(ws, 'lu_pid')
    loc = CodeLocations(str(ws), code_paths=(str(proj),))
    assert ClassLoader(loc, 'lu_app.logic', 'Goto').load()().process('abc') == '6'
    assert FunctionLoader(loc, 'lu_app.logic', 'shout').load()('abcd') == '8'


def test_a_code_path_that_is_a_package_itself_serves_only_that_package(ws, tmp_path,
                                                                       clean_modules):
    proj = tmp_path / 'lu_selfpkg'
    write(proj / '__init__.py', 'def scale(x):\n    return x + 1\n')
    write(proj / 'secret.py', 'VALUE = 1\n')
    a_package_using(ws, 'lu_selfpkg')
    loc = CodeLocations(str(ws), code_paths=(str(proj),))
    assert FunctionLoader(loc, 'lu_app.logic', 'shout').load()('abc') == '4'
    assert code_imports.locate('secret', loc) is None   # siblings of the folder are not exposed


def test_without_the_registration_the_library_is_missing(ws, tmp_path, clean_modules):
    flat_project(tmp_path / 'simple-pid', 'lu_pid', PID_LIB)
    a_package_using(ws, 'lu_pid')
    loader = FunctionLoader(CodeLocations(str(ws)), 'lu_app.logic', 'shout')
    with pytest.raises(LoadError) as err:
        loader.load()
    assert err.value.problem.missing_module == 'lu_pid'
    assert not [f for f in sys.meta_path if isinstance(f, code_imports.CodeImportFinder)]


def test_the_standard_library_and_runtime_names_are_never_served_from_a_code_path(
        ws, tmp_path, clean_modules):
    # json would be shadowed by a folder that comes first; here it is appended last AND refused
    proj = tmp_path / 'proj'
    for name in ('json', 'winreg', 'audio_common_msgs', 'rclpy_fake_ok'):
        write(proj / name / '__init__.py', "WHO = 'user'\n")
    write(proj / 'tests' / '__init__.py', '')
    loc = CodeLocations(str(ws), code_paths=(str(proj),))
    roots = code_imports.import_roots(loc)
    assert code_imports.locate_spec('json', roots) is None
    assert code_imports.locate_spec('winreg', roots) is None            # stdlib name, absent here
    assert code_imports.locate_spec('audio_common_msgs', roots) is None  # the node's own runtime
    assert code_imports.locate_spec('tests', roots) is None             # not a library folder
    assert code_imports.locate_spec('rclpy_fake_ok', roots) is not None
    ament_python(ws / 'src', 'lu_app', {'logic.py': 'import winreg\n' + SHOUT})
    loader = FunctionLoader(loc, 'lu_app.logic', 'shout')
    with pytest.raises(LoadError) as err:
        loader.load()
    assert err.value.problem.missing_module == 'winreg'
    import json
    assert json.__file__.startswith(os.path.dirname(os.__file__))   # the standard library


def test_an_outward_symlink_in_a_code_path_is_not_served(ws, tmp_path, clean_modules):
    outside = tmp_path / 'outside'
    write(outside / 'lu_out' / '__init__.py', 'X = 1\n')
    proj = tmp_path / 'proj'
    proj.mkdir()
    os.symlink(outside / 'lu_out', proj / 'lu_out')
    inside = flat_project(tmp_path / 'proj2', 'lu_inside', {})
    os.symlink(inside / 'lu_inside', inside / 'lu_alias')    # inward: fine
    loc = CodeLocations(str(ws), code_paths=(str(proj), str(inside)))
    roots = code_imports.import_roots(loc)
    assert code_imports.locate_spec('lu_out', roots) is None
    assert code_imports.locate_spec('lu_alias', roots) is not None


def test_site_packages_come_first_and_the_library_wins_over_the_code_path(ws, tmp_path,
                                                                           monkeypatch,
                                                                           clean_modules):
    site = tmp_path / 'site'
    install_dist(site, 'lu-twin', '1.0', {'__init__.py': 'def scale(x):\n    return -1\n'},
                 top='lu_twin')
    monkeypatch.syspath_prepend(str(site))
    proj = flat_project(tmp_path / 'proj', 'lu_twin', PID_LIB)
    a_package_using(ws, 'lu_twin')
    loader = FunctionLoader(CodeLocations(str(ws), code_paths=(str(proj),)), 'lu_app.logic',
                            'shout')
    assert loader.load()('abc') == '-1'


def test_a_changed_library_of_a_code_path_is_reloaded_like_a_sibling(ws, tmp_path,
                                                                     clean_modules):
    proj = flat_project(tmp_path / 'simple-pid', 'lu_pid', PID_LIB)
    a_package_using(ws, 'lu_pid')
    loader = FunctionLoader(CodeLocations(str(ws), code_paths=(str(proj),)), 'lu_app.logic',
                            'shout')
    assert loader.load()('abc') == '6'
    assert {'core.py', '__init__.py'} <= {os.path.basename(p) for p in loader.watched_files
                                          if str(proj) in p}
    assert not loader.changed()
    write(proj / 'lu_pid' / 'core.py', 'GAIN = 10\n\n\ndef scale(x):\n    return x * GAIN\n')
    assert loader.changed()
    assert loader.load()('abc') == '30'
    # a broken library keeps the old function running and is reported with its location
    write(proj / 'lu_pid' / 'core.py', 'def scale(x:\n')
    assert loader.changed()
    with pytest.raises(LoadError):
        loader.load()
    assert loader.function('abc') == '30'
    write(proj / 'lu_pid' / 'core.py', 'def scale(x):\n    return 0\n')
    assert loader.load()('abc') == '0'


def test_reload_never_drops_modules_that_merely_live_inside_a_code_path(ws, tmp_path,
                                                                        clean_modules):
    """A venv inside the project folder (common): its libraries are not code-path libraries."""
    proj = flat_project(tmp_path / 'proj', 'lu_pid', PID_LIB)
    write(proj / '.venv' / 'lib' / 'lu_vendor' / '__init__.py', 'V = 1\n')
    sys.path.insert(0, str(proj / '.venv' / 'lib'))
    try:
        import lu_vendor
        a_package_using(ws, 'lu_pid')
        loader = FunctionLoader(CodeLocations(str(ws), code_paths=(str(proj),)), 'lu_app.logic',
                                'shout')
        loader.load()
        loader.load()
        assert sys.modules['lu_vendor'] is lu_vendor
        assert not [p for p in loader.watched_files if '.venv' in p]
    finally:
        sys.path.remove(str(proj / '.venv' / 'lib'))


def test_c_installed_module_imports_other_installed_libraries_and_code_path_ones(
        ws, tmp_path, monkeypatch, clean_modules):
    """Scope C is on the interpreter's own path; code paths (B) are libraries for it too."""
    site = tmp_path / 'site'
    install_dist(site, 'inst-base', '1.0', {'__init__.py': 'K = 3\n'}, top='inst_base')
    install_dist(site, 'inst-top', '1.0', {'filters.py': (
        'import inst_base\nimport lu_pid\n\n\ndef shout(text: str) -> str:\n'
        '    return str(inst_base.K + lu_pid.scale(1))\n')}, top='inst_top')
    monkeypatch.syspath_prepend(str(site))
    proj = flat_project(tmp_path / 'simple-pid', 'lu_pid', PID_LIB)
    loc = CodeLocations(str(ws), code_paths=(str(proj),), installed_modules=('inst_top',))
    assert FunctionLoader(loc, 'inst_top.filters', 'shout').load()('x') == '5'
