"""A missing library → rosdep key + package.xml line, or a venv (docs/design/user-code.md §5).

Uses the real ``rosdep`` of the image with its cache (``rosdep update`` ran in the base image) for
the online case, an empty HOME for "rosdep has no database" (offline / never updated) and a
missing binary. roshanavi never runs pip: the hint only contains commands to show.
"""

import os
import subprocess

import pytest

from roshanavi.function import dependencies, modules
from roshanavi.function.dependencies import RosdepResolver, candidate_keys, hint, lookup
from roshanavi.function.scopes import CodeLocations
from user_code_fixtures import ament_python, flat_project, write

SHOUT = 'def shout(text: str) -> str:\n    return text.upper()\n'
NO_VENV = {'executable': '/usr/bin/python3', 'version': '3.x', 'venv': False}


def rosdep_works():
    try:
        return subprocess.run(['rosdep', 'resolve', 'python3-numpy'], capture_output=True,
                              timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


needs_rosdep = pytest.mark.skipif(not rosdep_works(), reason='rosdep with its cache is needed')


def test_candidate_keys():
    assert candidate_keys('cv2') == ['python3-opencv', 'python3-cv2']
    assert candidate_keys('numpy.linalg') == ['python3-numpy']
    assert candidate_keys('My_Lib') == ['python3-my-lib']
    assert candidate_keys('PIL') == ['python3-pil']


@needs_rosdep
def test_online_lookup_uses_rosdeps_database():
    resolver = RosdepResolver()
    numpy = lookup('numpy', resolver)
    assert (numpy['status'], numpy['key'], numpy['installer']) == ('found', 'python3-numpy', 'apt')
    assert numpy['packages'] == ['python3-numpy']
    assert lookup('cv2', resolver)['key'] == 'python3-opencv'
    none = lookup('surely_not_a_real_library_xyz', resolver)
    assert none['status'] == 'not_found' and none['tried'] == ['python3-surely-not-a-real-library-xyz']


def test_offline_or_never_updated_rosdep_is_unavailable(tmp_path):
    empty = tmp_path / 'home'
    empty.mkdir()
    env = {**os.environ, 'HOME': str(empty), 'ROS_HOME': str(empty / '.ros')}
    result = lookup('numpy', RosdepResolver(env=env))
    if result.get('reason') == 'rosdep_missing':
        pytest.skip('rosdep is not installed')
    assert (result['status'], result['reason'], result['candidate']) == (
        'unavailable', 'no_database', 'python3-numpy')
    assert lookup('numpy', RosdepResolver(binary=str(tmp_path / 'no-rosdep')))['reason'] == \
        'rosdep_missing'


def test_resolver_caches_parses_and_handles_timeouts():
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[:2] == ['rosdep', 'resolve'] and 'shell' not in kwargs
        if argv[2] == 'python3-slow':
            raise subprocess.TimeoutExpired(argv, 10)
        if argv[2] == 'python3-pipish':
            return subprocess.CompletedProcess(argv, 0, '#pip\npipish\n', '')
        if argv[2] == 'python3-x':
            return subprocess.CompletedProcess(argv, 0, '#ROSDEP[python3-x]\n#apt\npython3-x\n', '')
        return subprocess.CompletedProcess(argv, 1, '', "ERROR: no rosdep rule for 'k'\n")

    resolver = RosdepResolver(runner=runner, clock=lambda: 0.0)
    assert resolver.resolve('python3-x') == {'status': 'found', 'key': 'python3-x',
                                             'installer': 'apt', 'packages': ['python3-x']}
    resolver.resolve('python3-x')
    assert len(calls) == 1                                 # cached
    assert lookup('pipish', resolver)['status'] == 'not_found'   # pip keys would run pip
    assert resolver.resolve('python3-slow')['reason'] == 'timeout'
    assert resolver.resolve('Bad Key;rm')['status'] == 'not_found'
    assert all(len(argv) == 3 for argv in calls)


@needs_rosdep
def test_hint_for_a_workspace_package(tmp_path):
    ws = tmp_path / 'ws'
    pkg = ament_python(ws / 'src', 'dep_pkg', {'logic.py': 'import numpy\n' + SHOUT})
    resolved = modules.resolve_module(str(ws), 'dep_pkg.logic')
    out = hint('numpy', resolved, RosdepResolver(), NO_VENV)
    assert out['route'] == 'rosdep' and out['exec_depend'] == '<exec_depend>python3-numpy</exec_depend>'
    assert out['package_xml'] == str((pkg / 'package.xml').resolve())
    assert out['rosdep_command'] == f'rosdep install --from-paths {pkg.resolve()} --ignore-src -y'
    assert out['apt_command'] == 'sudo apt install python3-numpy'
    assert out['already_declared'] is False
    write(pkg / 'package.xml', (pkg / 'package.xml').read_text().replace(
        '<export>', '<exec_depend>python3-numpy</exec_depend>\n  <export>'))
    assert hint('numpy', resolved, RosdepResolver(), NO_VENV)['already_declared'] is True
    # a commented-out line does not count
    write(pkg / 'package.xml', (pkg / 'package.xml').read_text().replace(
        '<exec_depend>python3-numpy</exec_depend>', '<!-- <exec_depend>python3-numpy</exec_depend> -->'))
    assert hint('numpy', resolved, RosdepResolver(), NO_VENV)['already_declared'] is False


def test_hint_without_a_rosdep_key_is_the_venv_route(tmp_path):
    proj = flat_project(tmp_path / 'proj', 'b_lib', {'m.py': SHOUT})
    write(proj / 'requirements.txt', 'superlib==1\n')
    resolved = modules.resolve_module(CodeLocations(str(tmp_path), code_paths=(str(proj),)),
                                      'b_lib.m')
    fake = RosdepResolver(runner=lambda argv, **kw: subprocess.CompletedProcess(
        argv, 1, '', "ERROR: no rosdep rule for 'x'"))
    out = hint('superlib', resolved, fake, NO_VENV)
    assert out['route'] == 'venv' and 'exec_depend' not in out and out['note'] == 'code_path'
    assert out['venv']['commands'] == [
        'python3 -m venv --system-site-packages ~/roshanavi-venv',
        'source ~/roshanavi-venv/bin/activate',
        f'pip install -r {(proj / "requirements.txt").resolve()}']
    assert 'package_xml' not in out
    # pip names that differ from the import name are said so
    cv = hint('cv2', None, fake, NO_VENV)
    assert cv['venv']['pip_name'] == 'opencv-python' and cv['venv']['pip_name_differs']
    # inside a venv already: install into exactly that interpreter
    active = hint('superlib', None, fake, {'executable': '/v/bin/python3', 'venv': True})
    assert active['venv']['commands'] == ['/v/bin/python3 -m pip install superlib']


def test_hint_when_rosdep_is_unavailable_shows_both_routes():
    offline = RosdepResolver(runner=lambda argv, **kw: subprocess.CompletedProcess(
        argv, 1, '', 'ERROR: your rosdep installation has not been initialized yet.  Please '
        'run:\n\n    rosdep update\n'))
    out = hint('numpy', None, offline, NO_VENV)
    assert out['rosdep']['status'] == 'unavailable' and out['rosdep']['reason'] == 'no_database'
    assert out['exec_depend'] == '<exec_depend>python3-numpy</exec_depend>'   # unverified
    assert out['route'] == 'venv' and out['venv']['commands']


def test_never_runs_pip():
    seen = []

    def runner(argv, **kwargs):
        seen.append(argv)
        return subprocess.run(argv, **kwargs)

    out = hint('numpy', None, RosdepResolver(runner=runner), NO_VENV)
    assert seen and all(argv[:2] == ['rosdep', 'resolve'] for argv in seen)
    assert out['venv']['commands'][-1] == 'pip install numpy'   # shown, not run
    assert dependencies.VENV_DIR == '~/roshanavi-venv'


# ---- registered code paths (scope B) in the advice -------------------------------------------------
class FakeRosdep(RosdepResolver):
    """rosdep has no rule for anything."""

    def __init__(self):
        super().__init__(runner=lambda argv, **kw: subprocess.CompletedProcess(
            argv, 1, '', "ERROR: no rosdep rule for 'x'"))


class NoRosdep(RosdepResolver):
    def resolve(self, key):   # asking rosdep at all would be wrong when the answer is local
        raise AssertionError('rosdep must not be asked for a library of a registered place')


def test_a_library_that_is_in_a_registered_place_says_restart_not_rosdep(tmp_path):
    proj = flat_project(tmp_path / 'simple-pid', 'dep_pid', {'m.py': SHOUT})
    loc = CodeLocations(str(tmp_path), code_paths=(str(proj),))
    out = hint('dep_pid', None, NoRosdep(), NO_VENV, loc)
    assert out['route'] == 'code_path_restart' and out['rosdep']['status'] == 'skipped'
    assert out['code_places']['found_in']['path'] == str(proj)
    assert out['code_places']['found_in']['file'] == str((proj / 'dep_pid' / '__init__.py').resolve())


def test_a_registered_place_without_the_library_says_so_instead_of_rosdep(tmp_path):
    proj = tmp_path / 'third_party' / 'simple-pid'
    write(proj / 'README.md', 'nothing importable here')
    loc = CodeLocations(str(tmp_path), code_paths=(str(proj),))
    out = hint('simple_pid', None, NoRosdep(), NO_VENV, loc)
    assert out['route'] == 'code_path_missing'
    assert out['code_places']['looks_like'] == {'path': str(proj), 'real': str(proj.resolve())}
    assert out['code_places']['found_in'] is None and 'exec_depend' not in out


def test_an_unrelated_registered_place_does_not_hide_the_normal_advice(tmp_path):
    proj = flat_project(tmp_path / 'proj', 'dep_other', {'m.py': SHOUT})
    loc = CodeLocations(str(tmp_path), code_paths=(str(proj),))
    out = hint('superlib', None, FakeRosdep(), NO_VENV, loc)
    assert out['route'] == 'venv' and out['venv']['commands']
    assert out['code_places']['registered'] == [{'path': str(proj), 'real': str(proj.resolve())}]
    assert out['code_places']['found_in'] is None and out['code_places']['looks_like'] is None
    plain = hint('superlib', None, FakeRosdep(), NO_VENV)   # nothing registered at all
    assert plain['code_places']['registered'] == [] and plain['route'] == 'venv'


def test_a_standard_library_name_is_never_found_in_a_registered_place(tmp_path):
    proj = tmp_path / 'proj'
    write(proj / 'winreg' / '__init__.py', '')
    loc = CodeLocations(str(tmp_path), code_paths=(str(proj),))
    assert hint('winreg', None, FakeRosdep(), NO_VENV, loc)['code_places']['found_in'] is None
