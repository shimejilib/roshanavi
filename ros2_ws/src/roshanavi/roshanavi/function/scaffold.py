"""「ひな形を作る」: a minimal ament_python package for a function / class node (docs/design/user-code.md).

``POST /api/functions/scaffold {name}`` writes ``<workspace>/src/<name>/`` with package.xml (the
dependency examples as comments), setup.py / setup.cfg / resource marker, ``<name>/__init__.py``,
``<name>/logic.py`` (a typed function and a class with ``__init__`` / ``process`` / ``reset``),
``test/test_logic.py`` (ROS-free pytest) and README.md. It works as a function node and a class
node right away (no build: scope A loads the source) and ``colcon build`` builds it.

Safety: the name follows the ROS package name rules and must not be taken (an existing
directory, a ROS package of the workspace or the environment, the standard library / the node's
runtime, another Python package of the scopes). The directory is created with ``mkdir`` (never
reused) and every file with ``O_EXCL``; the target must be inside ``<workspace>/src``. Values are
validated before they are put into the files (the name is ``[a-z][a-z0-9_]*``).
"""

import keyword
import os
import re
import xml.etree.ElementTree as ElementTree
from typing import Any, Dict, Iterable, List

from ..launcher.errors import LauncherError
from .scopes import CodeLocations, inside, is_reserved_top, source_packages

NAME_RE = re.compile(r'^[a-z][a-z0-9_]{0,63}\Z')
DEFAULT_NAME = 'my_logic'
FUNCTION_NAME = 'convert'
CLASS_NAME = 'Processor'

PACKAGE_XML = '''\
<?xml version="1.0"?>
<?xml-model href="http://download.ros.org/schema/package_format3.xsd" schematypens="http://www.w3.org/2001/XMLSchema"?>
<package format="3">
  <name>{name}</name>
  <version>0.0.1</version>
  <description>{name}: roshanavi の関数・クラスノードで動かすロジック</description>
  <maintainer email="you@example.com">you</maintainer>
  <license>MIT</license>

  <!--
    ロジックが使うライブラリは、ここに exec_depend で書きます (推奨)。
    書いたあと、ワークスペースで rosdep install を実行すると apt で入ります
    (OS の Python を壊しません。コマンドは README.md にあります)。
    例 (import 名と rosdep キーは違うことがあります):
      <exec_depend>python3-numpy</exec_depend>    import numpy
      <exec_depend>python3-opencv</exec_depend>   import cv2
      <exec_depend>python3-yaml</exec_depend>     import yaml
    apt に無いライブラリは requirements.txt と仮想環境 (venv) で入れます (README.md)。
  -->

  <test_depend>python3-pytest</test_depend>

  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
'''

SETUP_PY = '''\
from setuptools import find_packages, setup

package_name = '{name}'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='you',
    maintainer_email='you@example.com',
    description='{name}: roshanavi の関数・クラスノードで動かすロジック',
    license='MIT',
    tests_require=['pytest'],
    # 普通の ROS ノードとしても動かすときは、ここに console_scripts を足します
    # (roshanavi の「ROS ノードのコードとして書き出す」が手順を書き出します)。
    entry_points={{'console_scripts': []}},
)
'''

SETUP_CFG = '''\
[develop]
script_dir=$base/lib/{name}
[install]
install_scripts=$base/lib/{name}
[tool:pytest]
# `python3 -m pytest test` (ROS なし) で {name} を import できるように
pythonpath = .
'''

INIT_PY = '''\
"""{name}: roshanavi の関数・クラスノードで動かすロジック (ROS を import しません)。"""
'''

LOGIC_PY = '''\
"""{name} のロジック。ROS を import しない、ふつうの Python です。

- 関数 ``{function}``: 「関数ノード」で動かします (受信のたびに呼ばれ、戻り値が送られます)。
- クラス ``{cls}``: 「クラスノード」で動かします (``process`` が受信のたびに呼ばれ、
  ``reset`` はボタンで呼べます。``__init__`` の引数は ROS の設定値 (パラメータ) になります)。

ファイルを保存すると、動いているノードがすぐに読み直します (ビルドは要りません)。
重い準備 (モデルの読み込みなど) はモジュールの直下ではなく、クラスの ``__init__`` に書きます。
"""


def {function}(text: str) -> str:
    """受け取った文字列を大文字にして返します。None を返すと何も送りません。"""
    return text.upper()


class {cls}:
    """受け取った文字列に、通し番号を付けて返します (状態を持つ処理の例)。"""

    def __init__(self, prefix: str = '#'):
        self.prefix = prefix
        self.count = 0

    def process(self, text: str) -> str:
        self.count += 1
        return f'{{self.prefix}}{{self.count}} {{text}}'

    def reset(self) -> None:
        """通し番号を 0 に戻します (「操作メソッド」にするとボタンで呼べます)。"""
        self.count = 0
'''

TEST_PY = '''\
"""ROS なしで動くテスト: `cd src/{name} && python3 -m pytest test`"""

from {name}.logic import {cls}, {function}


def test_{function}_makes_upper_case():
    assert {function}('hello') == 'HELLO'


def test_{cls_lower}_counts_and_resets():
    logic = {cls}(prefix='No.')
    assert logic.process('a') == 'No.1 a'
    assert logic.process('b') == 'No.2 b'
    logic.reset()
    assert logic.process('c') == 'No.1 c'
'''

README = '''\
# {name}

roshanavi の **関数ノード / クラスノード** で動かすロジックのひな形です。ROS のコードは書きません。

| ファイル | 中身 |
|---|---|
| `{name}/logic.py` | 関数 `{function}` (関数ノード用) と、クラス `{cls}` (クラスノード用) |
| `test/test_logic.py` | ROS なしで動く pytest |
| `package.xml` | 依存ライブラリの書き方の例 (コメント) |

## 動かす (ビルドは要りません)

1. roshanavi の「＋ 関数・クラスノードを作る」を開きます。
2. 「関数」を選び、モジュール `{name}.logic`、関数 `{function}`、入力と出力のチャンネル (トピック) を選びます (空のまま作って、地図の上で線を引いてつないでもかまいません)。
   クラスノードにするときは「クラス」を選び、クラス `{cls}`、`process` に入力と出力を、`reset` を「操作メソッド」にします。
3. `{name}/logic.py` を書き換えて保存すると、動いているノードがすぐに読み直します。

## テスト (ROS なし)

```bash
cd src/{name}
python3 -m pytest test
```

## 依存ライブラリ

roshanavi は pip を自動では実行しません。

1. **推奨**: `package.xml` に `<exec_depend>python3-numpy</exec_depend>` のように書き、
   ワークスペースで `rosdep install --from-paths src/{name} --ignore-src -y`。
2. **apt に無いもの**: `requirements.txt` を置き、`python3 -m venv --system-site-packages ~/roshanavi-venv`
   で仮想環境を作って `source ~/roshanavi-venv/bin/activate` → `pip install -r requirements.txt`。
   その端末で roshanavi を起動し直します。

## 普通の ROS パッケージとして

`colcon build --packages-select {name}` でビルドできます。普通の rclpy ノードにしたいときは、
roshanavi の編集画面の「ROS ノードのコードとして書き出す」を使います。
'''


def check_name(name: Any) -> str:
    """The package name, or LauncherError(``invalid_package_name``) with the rule it breaks."""
    code = 'invalid_package_name'
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise LauncherError(code, 'the name must be lowercase letters, digits and _ (starting '
                            'with a letter, at most 64), e.g. my_logic')
    if '__' in name or name.endswith('_'):
        raise LauncherError(code, 'the name must not contain "__" or end with "_" (ROS package '
                            'name rules)')
    if keyword.iskeyword(name) or is_reserved_top(name):
        raise LauncherError(code, f'{name!r} is a Python keyword or the name of a standard / ROS '
                            'library; choose another name')
    return name


def render(name: str) -> Dict[str, str]:
    """``{relative path: content}`` of the package (checked: the Python files compile and
    package.xml parses; an XML comment must not contain ``--``)."""
    values = {'name': name, 'function': FUNCTION_NAME, 'cls': CLASS_NAME,
              'cls_lower': CLASS_NAME.lower()}
    templates = [
        ('package.xml', PACKAGE_XML), ('setup.py', SETUP_PY), ('setup.cfg', SETUP_CFG),
        (os.path.join('resource', name), ''), (os.path.join(name, '__init__.py'), INIT_PY),
        (os.path.join(name, 'logic.py'), LOGIC_PY),
        (os.path.join('test', 'test_logic.py'), TEST_PY), ('README.md', README)]
    out = {rel: text.format(**values) for rel, text in templates}
    for rel, text in out.items():
        if rel.endswith('.py'):
            compile(text, rel, 'exec')
    ElementTree.fromstring(out['package.xml'].split('?>', 2)[-1])
    return out


def scaffold(locations: CodeLocations, name: Any,
             taken_packages: Iterable[str] = ()) -> Dict[str, Any]:
    """Create the package; returns what to preselect in the create dialog."""
    name = check_name(name)
    src = locations.src
    target = os.path.join(src, name)
    if os.path.lexists(target):
        raise LauncherError('file_exists', f'{target} already exists (nothing was overwritten)',
                            409)
    if name in set(taken_packages):
        raise LauncherError('name_taken', f'a ROS package {name!r} already exists (in the '
                            'workspace or the installed ROS environment)', 409)
    if any(p.top == name for p in source_packages(locations)):
        raise LauncherError('name_taken', f'a Python package {name!r} already exists in the '
                            'workspace or a code path', 409)
    if not inside(os.path.realpath(os.path.dirname(target)), src):
        raise LauncherError('forbidden_path', f'{target} is outside {src}')
    files = render(name)
    created: List[str] = []
    try:
        os.makedirs(src, exist_ok=True)
        os.mkdir(target)
        created.append(target)
        for rel, text in files.items():
            path = os.path.join(target, rel)
            parent = os.path.dirname(path)
            if not os.path.isdir(parent):
                os.mkdir(parent)
                created.append(parent)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            created.append(path)
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(text)
    except FileExistsError as exc:
        _rollback(created)
        raise LauncherError('file_exists', f'{target} already exists (nothing was overwritten)',
                            409) from exc
    except OSError as exc:
        _rollback(created)
        raise LauncherError('not_writable', f'cannot create {target}: {exc.strerror or exc} '
                            '(the workspace src is read-only or not yours?)', 403) from exc
    return {'package': name, 'directory': target, 'module': f'{name}.logic',
            'function': FUNCTION_NAME, 'class_name': CLASS_NAME,
            'files': [os.path.join(target, rel) for rel in files]}


def _rollback(created: List[str]) -> None:
    """Remove only what this call created (files first, then its directories)."""
    for path in reversed(created):
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                os.rmdir(path)
            else:
                os.unlink(path)
        except OSError:
            pass
