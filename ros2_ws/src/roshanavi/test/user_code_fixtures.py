"""Real directory trees for the user-code situations U1–U7 (docs/design/user-code.md).

Every builder writes the layout a user would really have on disk (package.xml, setup.py,
CMakeLists.txt, pyproject.toml, dist-info, .gitmodules ...) under a pytest tmp directory.
"""

import os
import subprocess
import sys
import sysconfig
import textwrap
import time
from pathlib import Path
from typing import Dict, Optional

PACKAGE_XML = '''<?xml version="1.0"?>
<package format="3">
  <name>{name}</name>
  <version>0.0.1</version>
  <description>fixture</description>
  <maintainer email="a@b.c">a</maintainer>
  <license>MIT</license>
  {depends}
  <export><build_type>{build_type}</build_type></export>
</package>
'''

_bump = [1]


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))
    stamp = time.time() + _bump[0]   # a distinct mtime on every write (hot reload sees it)
    _bump[0] += 1
    os.utime(path, (stamp, stamp))
    return path


def _modules(base: Path, modules: Dict[str, str]) -> None:
    for rel, text in modules.items():
        write(base / rel, text)


def ament_python(src: Path, name: str, modules: Dict[str, str], depends: str = '',
                 python_name: Optional[str] = None) -> Path:
    """U2: ``src/<name>/<name>/__init__.py`` + modules (the ament_python layout)."""
    pkg = src / name
    write(pkg / 'package.xml', PACKAGE_XML.format(name=name, depends=depends,
                                                  build_type='ament_python'))
    write(pkg / 'setup.py', 'from setuptools import setup\nsetup(name=%r)\n' % name)
    top = pkg / (python_name or name)
    write(top / '__init__.py', '')
    _modules(top, modules)
    return pkg


def ament_cmake_python(src: Path, name: str, modules: Dict[str, str],
                       package_dir: Optional[str] = None, python_name: Optional[str] = None
                       ) -> Path:
    """U3: an ament_cmake package with Python installed by ament_cmake_python."""
    pkg = src / name
    write(pkg / 'package.xml', PACKAGE_XML.format(
        name=name, depends='<buildtool_depend>ament_cmake_python</buildtool_depend>',
        build_type='ament_cmake'))
    install = '${PROJECT_NAME}' if python_name is None else python_name
    extra = f' PACKAGE_DIR {package_dir}' if package_dir else ''
    write(pkg / 'CMakeLists.txt', f'''\
        cmake_minimum_required(VERSION 3.8)
        project({name})
        find_package(ament_cmake REQUIRED)
        find_package(ament_cmake_python REQUIRED)
        # the C++ node lives in src/
        ament_python_install_package({install}{extra})
        ament_package()
    ''')
    write(pkg / 'src' / 'node.cpp', 'int main() { return 0; }\n')
    rel = package_dir or (python_name or name)
    top = pkg / rel
    write(top / '__init__.py', '')
    _modules(top, modules)
    return pkg


def flat_project(root: Path, top: str, modules: Dict[str, str]) -> Path:
    """U4 (flat): ``<root>/pyproject.toml`` and ``<root>/<top>/__init__.py``."""
    write(root / 'pyproject.toml', f'[project]\nname = "{top}"\nversion = "0.1"\n')
    write(root / top / '__init__.py', '')
    _modules(root / top, modules)
    return root


def src_layout_project(root: Path, top: str, modules: Dict[str, str]) -> Path:
    """U4 (src layout): ``<root>/src/<top>/__init__.py``."""
    write(root / 'pyproject.toml', f'[project]\nname = "{top}"\nversion = "0.1"\n')
    write(root / 'src' / top / '__init__.py', '')
    _modules(root / 'src' / top, modules)
    return root


def site_packages(venv_or_root: Path) -> Path:
    """The site-packages directory of a venv (or a plain directory to put on PYTHONPATH)."""
    lib = venv_or_root / 'lib'
    if lib.is_dir():
        found = sorted(lib.glob('python3*/site-packages'))
        if found:
            return found[0]
    site = venv_or_root / 'site'
    site.mkdir(parents=True, exist_ok=True)
    return site


def install_dist(site: Path, dist: str, version: str, modules: Dict[str, str],
                 top: Optional[str] = None) -> Path:
    """U5: what ``pip install`` leaves behind: the package and its ``.dist-info``."""
    if top is not None:
        _modules(site / top, {'__init__.py': '', **modules})
    else:
        _modules(site, modules)
    info = site / f'{dist.replace("-", "_")}-{version}.dist-info'
    write(info / 'METADATA', f'Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n')
    write(info / 'RECORD', '')
    write(info / 'INSTALLER', 'pip\n')
    return site


def make_venv(path: Path) -> Path:
    """``python3 -m venv --system-site-packages`` (without pip: no network, no ensurepip)."""
    subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', '--without-pip',
                    str(path)], check=True, capture_output=True)
    return path


def build_extension(directory: Path, name: str, c_body: str) -> Optional[Path]:
    """Compile a tiny CPython extension module (None when there is no compiler / Python.h)."""
    include = sysconfig.get_paths()['include']
    if not os.path.isfile(os.path.join(include, 'Python.h')):
        return None
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f'{name}.c'
    source.write_text(textwrap.dedent(c_body))
    target = directory / f'{name}{sysconfig.get_config_var("EXT_SUFFIX")}'
    try:
        subprocess.run(['cc', '-shared', '-fPIC', f'-I{include}', str(source), '-o', str(target)],
                       check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    source.unlink()
    return target


SHOUT_EXTENSION = r'''
#define PY_SSIZE_T_CLEAN
#include <Python.h>
static PyObject *shout(PyObject *self, PyObject *arg) {
    PyObject *upper = PyObject_CallMethod(arg, "upper", NULL);
    if (!upper) return NULL;
    PyObject *out = PyUnicode_Concat(upper, PyUnicode_FromString("!!"));
    Py_DECREF(upper);
    return out;
}
static PyMethodDef methods[] = {{"shout", shout, METH_O, "shout"}, {NULL, NULL, 0, NULL}};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "fastlib", NULL, -1, methods};
PyMODINIT_FUNC PyInit_fastlib(void) { return PyModule_Create(&module); }
'''


# ---- git (the test runs git to build the fixture; roshanavi never does) -------------------------
GIT = ['git', '-c', 'user.email=t@example.com', '-c', 'user.name=t', '-c',
       'protocol.file.allow=always', '-c', 'init.defaultBranch=main']


def git(cwd: Path, *args: str) -> None:
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def repo_with_submodule(tmp: Path, sub_files: Dict[str, str], sub_path: str = 'src/vision_lib'
                        ) -> Path:
    """A workspace repository with ``sub_path`` as a git submodule; returns the super repo."""
    sub = tmp / 'sub_repo'
    _modules(sub, sub_files)
    git(sub, 'init', '-q')
    git(sub, 'add', '-A')
    git(sub, 'commit', '-q', '-m', 'sub')
    ws = tmp / 'super_ws'
    (ws / 'src').mkdir(parents=True)
    write(ws / 'src' / 'README.md', 'workspace\n')
    git(ws, 'init', '-q')
    git(ws, 'submodule', 'add', '-q', str(sub), sub_path)
    git(ws, 'add', '-A')
    git(ws, 'commit', '-q', '-m', 'super')
    return ws


def clone(repo: Path, target: Path, recursive: bool) -> Path:
    args = ['clone', '-q', *(['--recurse-submodules'] if recursive else []), str(repo),
            str(target)]
    git(repo.parent, *args)
    return target
