"""Helpers that build fake / tiny real colcon workspaces for launcher tests."""

import os
import stat
import subprocess
import textwrap
from pathlib import Path
from typing import Iterable

INDEX = Path('share/ament_index/resource_index/packages')


def fake_prefix(prefix: Path, package: str, executables: Iterable[str] = (),
                launch_files: Iterable[str] = ()) -> Path:
    """An install prefix with an ament index entry, executables and launch files."""
    (prefix / INDEX).mkdir(parents=True, exist_ok=True)
    (prefix / INDEX / package).write_text('')
    lib = prefix / 'lib' / package
    lib.mkdir(parents=True, exist_ok=True)
    for name in executables:
        path = lib / name
        path.write_text('#!/bin/sh\necho hi\n')
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    launch = prefix / 'share' / package / 'launch'
    launch.mkdir(parents=True, exist_ok=True)
    for name in launch_files:
        (launch / name).write_text('')
    return prefix


def fake_source(src: Path, package: str) -> Path:
    pkg = src / package
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / 'package.xml').write_text(
        f'<?xml version="1.0"?>\n<package format="3"><name>{package}</name>'
        '<version>0.0.0</version><description>x</description>'
        '<maintainer email="a@b.c">a</maintainer><license>MIT</license></package>\n')
    return pkg


FIXTURE_PKG = 'rn_fixture'
FIXTURE_LAUNCH = textwrap.dedent('''\
    from launch import LaunchDescription
    from launch_ros.actions import Node


    def generate_launch_description():
        return LaunchDescription([
            Node(package='demo_nodes_cpp', executable='talker', name='rn_named_talker',
                 namespace='rn_ns', output='screen'),
        ])
''')


def ament_python_package(src: Path, name: str = FIXTURE_PKG, broken: bool = False) -> Path:
    """A minimal real ament_python package with one console script and one launch file."""
    pkg = src / name
    (pkg / name).mkdir(parents=True, exist_ok=True)
    (pkg / 'resource').mkdir(exist_ok=True)
    (pkg / 'launch').mkdir(exist_ok=True)
    (pkg / 'resource' / name).write_text('')
    (pkg / name / '__init__.py').write_text('')
    (pkg / name / 'hello.py').write_text(
        'def main():\n    print("hello from fixture", flush=True)\n')
    (pkg / 'launch' / 'named.launch.py').write_text(FIXTURE_LAUNCH)
    (pkg / 'package.xml').write_text(textwrap.dedent(f'''\
        <?xml version="1.0"?>
        <package format="3">
          <name>{name}</name><version>0.0.1</version><description>fixture</description>
          <maintainer email="a@b.c">a</maintainer><license>MIT</license>
          <export><build_type>ament_python</build_type></export>
        </package>
    '''))
    (pkg / 'setup.cfg').write_text(f'[develop]\nscript_dir=$base/lib/{name}\n'
                                   f'[install]\ninstall_scripts=$base/lib/{name}\n')
    syntax_error = 'this is not python (\n' if broken else ''
    (pkg / 'setup.py').write_text(syntax_error + textwrap.dedent(f'''\
        from setuptools import setup
        setup(
            name='{name}', version='0.0.1', packages=['{name}'],
            data_files=[
                ('share/ament_index/resource_index/packages', ['resource/{name}']),
                ('share/{name}', ['package.xml']),
                ('share/{name}/launch', ['launch/named.launch.py']),
            ],
            install_requires=['setuptools'], zip_safe=True,
            entry_points={{'console_scripts': ['hello = {name}.hello:main']}},
        )
    '''))
    return pkg


def colcon_build(root: Path, package: str) -> subprocess.CompletedProcess:
    return subprocess.run(['colcon', 'build', '--packages-select', package, '--symlink-install'],
                          cwd=root, capture_output=True, text=True, timeout=300,
                          env={**os.environ})
