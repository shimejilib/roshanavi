"""Where function / class node code may come from: scopes A / B / C, containment, the project file.

docs/design/user-code.md — real fixture trees for U2 (ament_python), U3 (ament_cmake_python),
U4 (flat / src layout), U5 (installed, namespace, extension, editable) and the safety rules.
Nothing here starts ROS; the server side never imports user code (checked with marker files).
"""

import os

import pytest

from roshanavi.function import class_modules, installed, modules, scopes
from roshanavi.function.scopes import CodeLocations, check_code_path
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.project import dump_project, parse_project
from roshanavi.launcher.schema import CodeSettings, ProjectSpec
from roshanavi.pydantic_compat import ValidationError
from user_code_fixtures import (ament_cmake_python, ament_python, flat_project, install_dist,
                                src_layout_project, write)

SHOUT = 'def shout(text: str) -> str:\n    return text.upper()\n'


def names(locations):
    return [m['module'] for m in modules.list_modules(locations)]


def marker_module(marker):
    return f'open({str(marker)!r}, "w").write("imported")\n' + SHOUT


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / 'ws'
    ament_python(root / 'src', 'u2_pkg', {'logic.py': SHOUT, 'helpers/__init__.py': '',
                                          'helpers/text.py': SHOUT})
    return root


# ---- scope A ------------------------------------------------------------------------------------
def test_a_ament_python_and_cmake_python_layouts(ws):
    ament_cmake_python(ws / 'src', 'u3_cpp_pkg', {'tools.py': SHOUT})
    ament_cmake_python(ws / 'src', 'u3_dir_pkg', {'conv.py': SHOUT}, package_dir='python/u3_py',
                       python_name='u3_py')
    loc = CodeLocations.of(str(ws))
    assert {'u2_pkg.logic', 'u2_pkg.helpers.text', 'u3_cpp_pkg.tools', 'u3_py.conv'} <= set(
        names(loc))
    entry = next(m for m in modules.list_modules(loc) if m['module'] == 'u3_py.conv')
    assert entry == {'module': 'u3_py.conv', 'ros_package': 'u3_dir_pkg',
                     'file': 'src/u3_dir_pkg/python/u3_py/conv.py', 'scope': 'workspace',
                     'source': str((ws / 'src' / 'u3_dir_pkg').resolve()), 'listable': True}
    resolved = modules.resolve_module(loc, 'u3_cpp_pkg.tools')
    assert resolved.scope == 'workspace' and resolved.file.endswith('u3_cpp_pkg/u3_cpp_pkg/tools.py')
    assert [f['name'] for f in modules.describe_module(loc, 'u3_py.conv')['functions']] == ['shout']


def test_a_reserved_names_are_never_user_packages(ws):
    """A package called like the standard library / the node's runtime would replace it."""
    ament_python(ws / 'src', 'json_pkg', {'x.py': SHOUT}, python_name='json')
    ament_python(ws / 'src', 'np_pkg', {'x.py': SHOUT}, python_name='numpy')
    listed = names(str(ws))
    assert not [n for n in listed if n.split('.')[0] in ('json', 'numpy')]
    for module in ('json.x', 'numpy.x'):
        with pytest.raises(LauncherError) as err:
            modules.resolve_module(str(ws), module)
        assert err.value.code == 'unknown_module'


# ---- scope B ------------------------------------------------------------------------------------
def test_b_flat_src_and_package_layouts_are_opt_in(ws, tmp_path):
    flat = flat_project(tmp_path / 'work' / 'flat_proj', 'flat_lib', {'filters.py': SHOUT})
    src = src_layout_project(tmp_path / 'work' / 'src_proj', 'src_lib', {'filters.py': SHOUT})
    pkg = tmp_path / 'work' / 'pkg_itself'
    write(pkg / '__init__.py', '')
    write(pkg / 'core.py', SHOUT)
    assert 'flat_lib.filters' not in names(str(ws))         # not registered: not offered
    loc = CodeLocations(str(ws), code_paths=(str(flat), str(src), str(pkg)))
    listed = {m['module']: m for m in modules.list_modules(loc)}
    assert {'flat_lib.filters', 'src_lib.filters', 'pkg_itself.core'} <= set(listed)
    assert listed['src_lib.filters']['scope'] == 'code_path'
    assert listed['src_lib.filters']['file'] == str(src / 'src' / 'src_lib' / 'filters.py')
    assert listed['src_lib.filters']['source'] == str(src) and listed['src_lib.filters'][
        'ros_package'] is None
    resolved = modules.resolve_module(loc, 'src_lib.filters')
    assert resolved.package.root == str(src.resolve()) and resolved.scope == 'code_path'
    info = modules.describe_module(loc, 'flat_lib.filters')
    assert info['scope'] == 'code_path' and info['functions'][0]['name'] == 'shout'


def test_b_relative_paths_and_home_are_resolved_against_the_workspace(ws):
    proj = flat_project(ws / 'extra' / 'proj', 'rel_lib', {'m.py': SHOUT})
    loc = CodeLocations(str(ws), code_paths=('extra/proj',))
    assert modules.resolve_module(loc, 'rel_lib.m').file == str((proj / 'rel_lib' / 'm.py')
                                                                .resolve())


def test_a_wins_over_b_for_the_same_name(ws, tmp_path):
    flat = flat_project(tmp_path / 'p', 'u2_pkg', {'logic.py': 'def other(x): return x\n'})
    loc = CodeLocations(str(ws), code_paths=(str(flat),))
    assert modules.resolve_module(loc, 'u2_pkg.logic').scope == 'workspace'
    assert [m['scope'] for m in modules.list_modules(loc) if m['module'] == 'u2_pkg.logic'] == [
        'workspace']


# ---- symlinks (inward ok, outward refused) -----------------------------------------------------
def test_symlinks_inward_work_and_outward_are_refused(ws, tmp_path):
    pkg = ws / 'src' / 'u2_pkg' / 'u2_pkg'
    shared = write(ws / 'src' / 'shared' / 'common.py', SHOUT)       # inside src, outside pkg
    os.symlink(shared, pkg / 'inward.py')
    outside = write(tmp_path / 'outside.py', SHOUT)
    os.symlink(outside, pkg / 'outward.py')
    os.symlink(tmp_path, ws / 'src' / 'u2_pkg' / 'escape_pkg')       # a package dir outside
    write(tmp_path / '__init__.py', '')
    loc = CodeLocations.of(str(ws))
    assert modules.resolve_module(loc, 'u2_pkg.inward').file == str(shared.resolve())
    listed = names(loc)
    assert 'u2_pkg.inward' in listed and 'u2_pkg.outward' not in listed
    assert not [n for n in listed if n.startswith('escape_pkg')]
    for bad in ('u2_pkg.outward', 'escape_pkg'):
        with pytest.raises(LauncherError) as err:
            modules.resolve_module(loc, bad)
        assert err.value.code == 'unknown_module'

    # B: the registered directory is the root; links that leave it are refused too.
    proj = flat_project(tmp_path / 'b' / 'proj', 'b_lib', {'ok.py': SHOUT})
    os.symlink(outside, proj / 'b_lib' / 'leak.py')
    write(proj / 'shared.py', SHOUT)
    os.symlink(proj / 'shared.py', proj / 'b_lib' / 'inner.py')
    loc_b = CodeLocations(str(ws), code_paths=(str(proj),))
    assert modules.resolve_module(loc_b, 'b_lib.inner').file == str((proj / 'shared.py').resolve())
    with pytest.raises(LauncherError):
        modules.resolve_module(loc_b, 'b_lib.leak')
    assert 'b_lib.leak' not in names(loc_b)


# ---- scope C ------------------------------------------------------------------------------------
def test_c_installed_package_namespace_and_submodules(ws, tmp_path):
    site = tmp_path / 'site'
    install_dist(site, 'inst-lib', '1.2.0', {'filters.py': SHOUT, 'sub/__init__.py': '',
                                             'sub/deep.py': SHOUT}, top='inst_lib')
    other = tmp_path / 'site2'
    write(site / 'acme' / 'vision' / '__init__.py', '')            # namespace portion 1
    write(site / 'acme' / 'vision' / 'edge.py', SHOUT)
    write(other / 'acme' / 'audio' / '__init__.py', '')            # namespace portion 2
    write(other / 'acme' / 'audio' / 'gain.py', SHOUT)
    search = (str(site), str(other))
    loc = CodeLocations(str(ws), installed_modules=('inst_lib', 'acme'), search_path=search)
    listed = {m['module']: m for m in modules.list_modules(loc)}
    assert {'inst_lib', 'inst_lib.filters', 'inst_lib.sub.deep', 'acme.vision.edge',
            'acme.audio.gain'} <= set(listed)
    assert listed['inst_lib.filters']['scope'] == 'installed'
    assert listed['inst_lib.filters']['file'] == str(site / 'inst_lib' / 'filters.py')
    assert modules.resolve_module(loc, 'acme.audio.gain').file == str(
        (other / 'acme' / 'audio' / 'gain.py').resolve())
    with pytest.raises(LauncherError, match='namespace'):
        modules.resolve_module(loc, 'acme')
    # Not registered -> not offered, even though it is installed.
    assert 'inst_lib.filters' not in names(CodeLocations(str(ws), search_path=search))
    with pytest.raises(LauncherError):
        modules.resolve_module(CodeLocations(str(ws), installed_modules=('acme',),
                                             search_path=search), 'inst_lib.filters')
    with pytest.raises(LauncherError):   # the standard library is never an installed module
        modules.resolve_module(CodeLocations(str(ws), installed_modules=('os',)), 'os')


def test_c_extension_only_module_is_not_listable(ws, tmp_path):
    import importlib.machinery
    site = tmp_path / 'site'
    write(site / f'fastlib{importlib.machinery.EXTENSION_SUFFIXES[0]}', 'not really an ELF')
    loc = CodeLocations(str(ws), installed_modules=('fastlib',), search_path=(str(site),))
    entry = next(m for m in modules.list_modules(loc) if m['module'] == 'fastlib')
    assert entry['listable'] is False
    info = class_modules.describe_module(loc, 'fastlib')
    assert (info['listable'], info['functions'], info['classes']) == (False, [], [])
    assert {n['code'] for n in info['notices']} == {'extension_module', 'no_hot_reload_installed'}


def test_c_editable_install_mapping_is_read_statically(ws, tmp_path):
    proj = src_layout_project(tmp_path / 'editable_proj', 'ed_lib', {'core.py': SHOUT})
    site = tmp_path / 'site'
    write(site / '__editable___ed_lib_0_1_finder.py',
          f'MAPPING = {{"ed_lib": {str(proj / "src" / "ed_lib")!r}}}\nNAMESPACES = {{}}\n')
    loc = CodeLocations(str(ws), installed_modules=('ed_lib',), search_path=(str(site),))
    assert modules.resolve_module(loc, 'ed_lib.core').file == str(
        (proj / 'src' / 'ed_lib' / 'core.py').resolve())


def test_b_and_c_with_the_same_name_the_source_wins(ws, tmp_path):
    proj = flat_project(tmp_path / 'proj', 'vision_lib', {'filters.py': SHOUT})
    site = tmp_path / 'site'
    install_dist(site, 'vision-lib', '0.9', {'filters.py': 'def installed(x): return x\n'},
                 top='vision_lib')
    loc = CodeLocations(str(ws), code_paths=(str(proj),), installed_modules=('vision_lib',),
                        search_path=(str(site),))
    resolved = modules.resolve_module(loc, 'vision_lib.filters')
    assert resolved.scope == 'code_path' and resolved.file.startswith(str(proj.resolve()))
    scoped = [m['scope'] for m in modules.list_modules(loc) if m['module'] == 'vision_lib.filters']
    assert scoped == ['code_path']


def test_c_locate_follows_the_path_finder_order(tmp_path):
    first, second = tmp_path / 'a', tmp_path / 'b'
    write(first / 'dup' / 'x.py', SHOUT)                 # namespace portion (no __init__)
    write(second / 'dup.py', SHOUT)                      # a module wins over a portion
    found = installed.locate('dup', [str(first), str(second)])
    assert (found.kind, found.file) == ('source', str(second / 'dup.py'))
    write(first / 'dup' / '__init__.py', '')             # a regular package wins over all
    assert installed.locate('dup', [str(first), str(second)]).kind == 'package'
    assert installed.locate('nope', [str(first)]) is None
    assert installed.locate('../etc', [str(first)]) is None


# ---- the server never imports user code ---------------------------------------------------------
def test_listing_and_describing_never_import(ws, tmp_path):
    markers = [tmp_path / f'm{i}' for i in range(3)]
    write(ws / 'src' / 'u2_pkg' / 'u2_pkg' / 'side.py', marker_module(markers[0]))
    proj = flat_project(tmp_path / 'proj', 'b_lib', {'side.py': marker_module(markers[1])})
    site = tmp_path / 'site'
    install_dist(site, 'c-lib', '1', {'side.py': marker_module(markers[2])}, top='c_lib')
    write(site / 'c_lib' / '__init__.py', marker_module(markers[2]))
    loc = CodeLocations(str(ws), code_paths=(str(proj),), installed_modules=('c_lib',),
                        search_path=(str(site),))
    modules.list_modules(loc)
    for module in ('u2_pkg.side', 'b_lib.side', 'c_lib.side', 'c_lib'):
        assert class_modules.describe_module(loc, module)['functions'][0]['name'] == 'shout'
    assert not [m for m in markers if m.exists()]


def test_describe_lists_skipped_names_and_rclpy_notice(ws):
    write(ws / 'src' / 'u2_pkg' / 'u2_pkg' / 'mixed.py', '''\
        import rclpy

        def visible(x: int) -> int:
            return x

        def _hidden(x):
            return x

        async def later(x):
            return x

        if __name__ == '__main__':
            def demo():
                pass
    ''')
    info = modules.describe_module(str(ws), 'u2_pkg.mixed')
    assert [f['name'] for f in info['functions']] == ['visible']
    assert {(s['name'], s['reason']) for s in info['skipped']} == {
        ('_hidden', 'private'), ('later', 'async'), ('demo', 'main_guard')}
    assert [n['code'] for n in info['notices']] == ['imports_rclpy']


# ---- registering code paths ---------------------------------------------------------------------
def test_check_code_path_refuses_unsafe_places(ws, tmp_path):
    data = tmp_path / 'data'
    (data / 'uploads').mkdir(parents=True)
    loc = CodeLocations(str(ws), data_dir=str(data))
    good = flat_project(tmp_path / 'good', 'g', {'m.py': SHOUT})
    assert check_code_path(str(good), loc) == str(good.resolve())
    (tmp_path / 'repo' / '.git' / 'objects').mkdir(parents=True)
    bad = ['/', '/usr', os.path.expanduser('~'), str(data), str(data / 'uploads'), str(tmp_path),
           str(tmp_path / 'repo' / '.git' / 'objects'), 'a\x00b', 'x\ny', '', '   ',
           str(tmp_path / 'missing')]
    for path in bad:
        with pytest.raises(LauncherError) as err:
            check_code_path(path, loc)
        assert err.value.code == 'invalid_code_path', path
    # A stale entry (removed later) is skipped by the listing, not an error.
    assert modules.list_modules(CodeLocations(str(ws), code_paths=(str(tmp_path / 'gone'),)))


def test_project_file_keeps_code_paths_and_installed_modules():
    spec = ProjectSpec.model_validate({'code_paths': ['~/work/vision_lib', '/opt/x'],
                                       'installed_modules': ['vision_lib.filters']})
    text = dump_project(spec)
    assert 'code_paths:' in text and 'installed_modules:' in text
    again = parse_project(text)
    assert again.code_paths == ['~/work/vision_lib', '/opt/x']
    assert again.installed_modules == ['vision_lib.filters']
    assert 'code_paths' not in dump_project(ProjectSpec())          # empty: not written
    for bad in [{'code_paths': ['a\x01b']}, {'code_paths': ['x', 'x']},
                {'code_paths': ['']}, {'code_paths': ['  ']},
                {'installed_modules': ['roshanavi.server']},
                {'installed_modules': ['bad-name']}, {'installed_modules': ['a..b']},
                {'installed_modules': ['os']}, {'installed_modules': ['subprocess']},
                {'installed_modules': ['builtins']},
                {'code_paths': ['p'] * 21}, {'code_paths': ['x' * 1025]}]:
        with pytest.raises(ValidationError):
            CodeSettings.model_validate(bad)
        with pytest.raises(ValidationError):
            ProjectSpec.model_validate(bad)
    with pytest.raises(ValidationError):
        CodeSettings.model_validate({'code_paths': [], 'other': 1})
    with pytest.raises(LauncherError):
        parse_project('code_paths: [x, x]\n')


def test_scopes_order_and_package_dataclass(ws, tmp_path):
    proj = src_layout_project(tmp_path / 'p', 'later_lib', {'m.py': SHOUT})
    loc = CodeLocations(str(ws), code_paths=(str(proj),))
    packages = scopes.source_packages(loc)
    assert [(p.top, p.scope) for p in packages] == [('u2_pkg', 'workspace'),
                                                    ('later_lib', 'code_path')]
    assert packages[1].path == str(proj / 'src' / 'later_lib')
