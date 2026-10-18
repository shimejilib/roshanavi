"""A missing library of the user's code → what to do about it (``GET /api/functions/dependency``).

roshanavi **never runs pip** (nor apt). It only shows the commands (docs/design/user-code.md):

1. 推奨: a rosdep key → ``<exec_depend>KEY</exec_depend>`` in the ROS package's ``package.xml``
   and ``rosdep install`` (installs the apt package; does not break the OS Python).
2. 代替: no apt key → a venv with ``--system-site-packages`` (ROS stays visible), ``pip install``
   there, and start roshanavi from that venv.

The module → key mapping uses rosdep's own database: candidate keys (a few well-known names that
differ from the import name, then ``python3-<name>``) are checked with ``rosdep resolve <key>``
(argv list, no shell, 10 s). Only keys that resolve to the **apt** installer count (``*-pip`` keys
would run pip). Without rosdep or its cache (offline, ``rosdep update`` never ran) the answer is
"unavailable" and both routes are shown with the unverified candidate.
"""

import os
import re
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional

from . import node_env
from .modules import ResolvedModule
from .scopes import SCOPE_CODE_PATH, SCOPE_INSTALLED, SCOPE_WORKSPACE

ROSDEP_TIMEOUT_SEC = 10.0
UNAVAILABLE_TTL_SEC = 60.0
MODULE_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,7}\Z')
KEY_RE = re.compile(r'^[a-z0-9][a-z0-9._+-]{0,99}\Z')
VENV_DIR = '~/roshanavi-venv'

# Import name -> rosdep key, where the key is not python3-<name> (verified with rosdep resolve).
ROSDEP_ALIASES = {
    'cv2': 'python3-opencv', 'yaml': 'python3-yaml', 'PIL': 'python3-pil',
    'sklearn': 'python3-sklearn', 'skimage': 'python3-skimage', 'serial': 'python3-serial',
    'usb': 'python3-usb', 'bs4': 'python3-bs4', 'dateutil': 'python3-dateutil',
    'zmq': 'python3-zmq', 'gi': 'python3-gi', 'attr': 'python3-attr', 'jwt': 'python3-jwt',
    'Crypto': 'python3-pycryptodome', 'serial_asyncio': 'python3-serial-asyncio',
    'mpl_toolkits': 'python3-matplotlib', 'pydot': 'python3-pydot', 'shapely': 'python3-shapely',
}
# Import name -> pip distribution name, where they differ (for the venv route).
PIP_NAMES = {
    'cv2': 'opencv-python', 'PIL': 'Pillow', 'sklearn': 'scikit-learn', 'skimage': 'scikit-image',
    'yaml': 'PyYAML', 'bs4': 'beautifulsoup4', 'serial': 'pyserial', 'usb': 'pyusb',
    'dateutil': 'python-dateutil', 'zmq': 'pyzmq', 'Crypto': 'pycryptodome', 'gi': 'PyGObject',
    'attr': 'attrs', 'jwt': 'PyJWT', 'magic': 'python-magic', 'dotenv': 'python-dotenv',
    'google': 'protobuf', 'mpl_toolkits': 'matplotlib',
}


def candidate_keys(module: str) -> List[str]:
    """rosdep keys to try for an import name (``cv2`` → ``python3-opencv``)."""
    top = module.split('.')[0]
    keys = []
    if top in ROSDEP_ALIASES:
        keys.append(ROSDEP_ALIASES[top])
    keys.append('python3-' + top.lower().replace('_', '-'))
    return [k for i, k in enumerate(keys) if KEY_RE.match(k) and k not in keys[:i]]


class RosdepResolver:
    """``rosdep resolve <key>`` with a cache (keys do not change while the server runs)."""

    def __init__(self, binary: str = 'rosdep', env: Optional[Mapping[str, str]] = None,
                 runner: Callable[..., Any] = subprocess.run, clock: Callable[[], float] =
                 time.monotonic):
        self._binary = binary
        self._env = dict(os.environ if env is None else env)
        self._run = runner
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._unavailable_at: Optional[float] = None
        self._unavailable: Optional[Dict[str, Any]] = None

    def resolve(self, key: str) -> Dict[str, Any]:
        """``{status: found|not_found|unavailable, key, installer?, packages?, reason?}``."""
        if not KEY_RE.match(key):
            return {'status': 'not_found', 'key': key}
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            if self._unavailable and self._clock() - (self._unavailable_at or 0) \
                    < UNAVAILABLE_TTL_SEC:
                return {**self._unavailable, 'key': key}
        result = self._ask(key)
        with self._lock:
            if result['status'] == 'unavailable':
                self._unavailable, self._unavailable_at = result, self._clock()
            else:
                self._cache[key] = result
        return result

    def _ask(self, key: str) -> Dict[str, Any]:
        try:
            done = self._run([self._binary, 'resolve', key], env=self._env, capture_output=True,
                             text=True, timeout=ROSDEP_TIMEOUT_SEC, check=False,
                             stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            return {'status': 'unavailable', 'key': key, 'reason': 'rosdep_missing'}
        except subprocess.TimeoutExpired:
            return {'status': 'unavailable', 'key': key, 'reason': 'timeout'}
        except OSError as exc:
            return {'status': 'unavailable', 'key': key, 'reason': 'error', 'detail': str(exc)}
        out, err = done.stdout or '', done.stderr or ''
        if done.returncode == 0:
            installer, packages = '', []
            for line in out.splitlines():
                line = line.strip()
                if line.startswith('#ROSDEP['):
                    continue
                if line.startswith('#'):
                    installer = line[1:].strip()
                elif line:
                    packages += line.split()
            return {'status': 'found', 'key': key, 'installer': installer,
                    'packages': packages[:20]}
        text = (out + err).lower()
        if 'no rosdep rule' in text or 'cannot locate rosdep definition' in text \
                or 'no definition of' in text:
            return {'status': 'not_found', 'key': key}
        if 'rosdep update' in text or 'rosdep init' in text or 'not been initialized' in text:
            return {'status': 'unavailable', 'key': key, 'reason': 'no_database'}
        return {'status': 'unavailable', 'key': key, 'reason': 'error',
                'detail': (err or out).strip()[-300:]}


def lookup(module: str, resolver: RosdepResolver) -> Dict[str, Any]:
    """The first apt key of the candidates, else not_found / unavailable (with the candidate)."""
    tried = []
    for key in candidate_keys(module):
        result = resolver.resolve(key)
        tried.append(key)
        if result['status'] == 'found' and result.get('installer') == 'apt':
            return {**result, 'tried': tried}
        if result['status'] == 'unavailable':
            return {**result, 'candidate': key, 'tried': tried}
    return {'status': 'not_found', 'tried': tried}


def _declared(package_xml: str, key: str) -> bool:
    try:
        with open(package_xml, encoding='utf-8', errors='replace') as fh:
            text = fh.read(256 * 1024)
    except OSError:
        return False
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    return re.search(r'<(exec_depend|depend)>\s*' + re.escape(key) + r'\s*</\1>', text) is not None


def _requirements_file(resolved: Optional[ResolvedModule]) -> Optional[str]:
    if resolved is None or resolved.scope == SCOPE_INSTALLED:
        return None
    package = resolved.package
    for directory in (package.source if package.ros_package else package.root, package.base_dir):
        path = os.path.join(directory or '', node_env.REQUIREMENTS_FILE)
        if directory and os.path.isfile(path):
            return os.path.realpath(path)
    return None


def hint(missing: str, resolved: Optional[ResolvedModule], resolver: RosdepResolver,
         python: Dict[str, Any]) -> Dict[str, Any]:
    """Both routes for one missing import, filled with the user's real paths."""
    top = missing.split('.')[0]
    rosdep = lookup(top, resolver)
    key = rosdep.get('key') if rosdep['status'] == 'found' else rosdep.get('candidate')
    out: Dict[str, Any] = {'missing': missing, 'top': top, 'rosdep': rosdep,
                           'scope': resolved.scope if resolved else None,
                           'route': 'rosdep' if rosdep['status'] == 'found' else 'venv',
                           'python': {k: python.get(k) for k in ('executable', 'version', 'venv')}}
    if key:
        out['exec_depend'] = f'<exec_depend>{key}</exec_depend>'
        apt = ' '.join(rosdep.get('packages') or []) or None
        out['apt_command'] = f'sudo apt install {apt}' if apt else None
    if resolved is not None and resolved.scope == SCOPE_WORKSPACE and resolved.package.source:
        package_xml = os.path.join(resolved.package.source, 'package.xml')
        out['package_xml'] = package_xml
        out['already_declared'] = bool(key) and _declared(package_xml, key)
        out['rosdep_command'] = (f'rosdep install --from-paths {resolved.package.source} '
                                 '--ignore-src -y')
    pip_name = PIP_NAMES.get(top, top)
    requirements = _requirements_file(resolved)
    install = f'pip install -r {requirements}' if requirements else f'pip install {pip_name}'
    if python.get('venv'):
        # Already in a venv: install into exactly that interpreter.
        install = f'{python.get("executable")} -m {install}'
        steps = [install]
    else:
        steps = [f'python3 -m venv --system-site-packages {VENV_DIR}',
                 f'source {VENV_DIR}/bin/activate', install]
    out['venv'] = {'pip_name': pip_name, 'pip_name_differs': pip_name != top,
                   'requirements': requirements, 'commands': steps,
                   'active': bool(python.get('venv'))}
    if resolved is not None and resolved.scope == SCOPE_CODE_PATH:
        out['note'] = 'code_path'   # not a ROS package: no package.xml to add the key to
    return out
