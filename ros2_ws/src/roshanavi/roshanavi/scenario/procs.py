"""Setup processes and project targets for scenarios (reuses the Launcher's process manager).

* Setup items (``run`` / ``launch`` / ``cmd`` / ``function`` / ``transform`` / ``dummy``) become
  launcher specs in a **private** :class:`ProcessManager`: the same argv validation
  (only discovered packages / executables / launch files), own process group,
  SIGINT -> SIGTERM -> SIGKILL. :meth:`SetupProcesses.close` always stops all of them.
* ``target`` setup items and ``start: {target: id}`` / ``stop`` steps act on project
  targets through :class:`TargetController`; when the scenario ends every target is put
  back the way it was (started by the scenario -> stopped, stopped -> started again).
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..launcher.errors import LauncherError
from ..launcher.manager import ProcessManager
from ..launcher.schema import DummySpec, FunctionSpec, TargetSpec, TransformSpec
from .schema import SetupEntry

LOG = logging.getLogger(__name__)

LOG_TAIL_LINES = 20
DEAD_STATES = ('exited', 'crashed', 'invalid')


class SetupError(Exception):
    def __init__(self, message: str, log_tail: Sequence[str] = ()):
        super().__init__(message)
        self.log_tail = list(log_tail)


def _ros_args(rest: List[str]) -> Dict[str, Any]:
    """``--ros-args -p k:=v -r a:=b -r __node:=n -r __ns:=/x`` -> TargetSpec fields."""
    out: Dict[str, Any] = {'params': {}, 'remaps': {}}
    i = 0
    while i < len(rest):
        flag = rest[i]
        if flag not in ('-p', '-r', '--param', '--remap') or i + 1 >= len(rest):
            raise SetupError(f'cmd の --ros-args で使えるのは -p name:=value と -r from:=to だけです '
                             f'({flag!r})')
        key, sep, value = rest[i + 1].partition(':=')
        if not sep:
            raise SetupError(f'cmd の {flag} {rest[i + 1]!r} は name:=value の形にしてください')
        if flag in ('-p', '--param'):
            out['params'][key] = _param_value(value)
        elif key == '__node':
            out['name'] = value
        elif key == '__ns':
            out['namespace'] = value
        else:
            out['remaps'][key] = value
        i += 2
    return out


def _param_value(text: str) -> Any:
    lowered = text.lower()
    if lowered in ('true', 'false'):
        return lowered == 'true'
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def spec_from_cmd(index: int, cmd: Sequence[str]) -> TargetSpec:
    """``["ros2", "run"|"launch", pkg, exe_or_file, ...]`` -> a validated launcher spec."""
    argv = list(cmd)
    if len(argv) < 4 or argv[0] != 'ros2' or argv[1] not in ('run', 'launch'):
        raise SetupError('cmd は ["ros2", "run", パッケージ, 実行ファイル, ...] か '
                         '["ros2", "launch", パッケージ, launch ファイル, 引数:=値 ...] の形にしてください '
                         '(ほかのコマンドは起動しません)')
    kind, package, name, rest = argv[1], argv[2], argv[3], argv[4:]
    if kind == 'launch':
        return TargetSpec(id=f'scn-cmd-{index}', kind='launch', package=package, launch_file=name,
                          args=rest)
    args, ros = rest, {}
    if '--ros-args' in rest:
        cut = rest.index('--ros-args')
        args, ros = rest[:cut], _ros_args(rest[cut + 1:])
    return TargetSpec(id=f'scn-cmd-{index}', kind='run', package=package, executable=name,
                      args=args, **ros)


def spec_for(index: int, entry: SetupEntry) -> Any:
    item = entry.item
    if item.kind == 'run':
        run = item.run
        return TargetSpec(id=f'scn-run-{index}', kind='run', package=run.package,
                          executable=run.executable, name=run.name, namespace=run.namespace,
                          params=run.params, remaps=run.remaps, args=run.args)
    if item.kind == 'launch':
        launch = item.launch
        args = [f'{k}:={str(v).lower() if isinstance(v, bool) else v}'
                for k, v in launch.args.items()]
        return TargetSpec(id=f'scn-launch-{index}', kind='launch', package=launch.package,
                          launch_file=launch.file, args=args)
    if item.kind == 'cmd':
        return spec_from_cmd(index, item.cmd)
    return entry.node_spec


def node_names(spec: Any) -> List[str]:
    """Nodes a spec will create when its name is known (implicit wait_for_node)."""
    if isinstance(spec, (FunctionSpec, TransformSpec, DummySpec)) or (
            isinstance(spec, TargetSpec) and spec.kind == 'run'):
        if spec.name:
            return [full_node_name(spec.name, spec.namespace)]
    return []


def full_node_name(name: str, namespace: Optional[str] = None) -> str:
    if name.startswith('/'):
        return name
    ns = (namespace or '').strip('/')
    return f'/{ns}/{name}' if ns else f'/{name}'


class TargetController:
    """Starts / stops project targets and restores their state at the end."""

    def __init__(self, manager: ProcessManager, lookup: Optional[Callable[[str], Any]] = None,
                 owned: bool = False):
        self._manager = manager
        self._lookup = lookup  # CLI: project spec by id (registered on first use)
        self._owned = owned
        self._initial: Dict[str, bool] = {}

    def _ensure(self, target_id: str) -> None:
        try:
            self._manager.target(target_id)
            return
        except LauncherError:
            if self._lookup is None:
                raise SetupError(f'起動設定 {target_id!r} がプロジェクトにありません') from None
        spec = self._lookup(target_id)
        if spec is None:
            raise SetupError(f'起動設定 {target_id!r} がプロジェクトにありません')
        try:
            self._manager.add(spec, strict=True)
        except LauncherError as exc:
            raise SetupError(f'起動設定 {target_id!r} を使えません: {exc}') from exc

    def _remember(self, target_id: str) -> bool:
        alive = self._manager.target(target_id).alive()
        self._initial.setdefault(target_id, alive)
        return alive

    def start(self, target_id: str) -> str:
        self._ensure(target_id)
        if self._remember(target_id):
            return f'{target_id} はもう動いています'
        try:
            self._manager.start(target_id)
        except LauncherError as exc:
            raise SetupError(f'{target_id} を起動できません: {exc}') from exc
        return f'{target_id} を起動しました'

    def stop(self, target_id: str) -> str:
        self._ensure(target_id)
        if not self._remember(target_id):
            return f'{target_id} はもう止まっています'
        try:
            self._manager.stop(target_id)
        except LauncherError as exc:
            raise SetupError(f'{target_id} を止められません: {exc}') from exc
        return f'{target_id} を止めました'

    def nodes(self, target_id: str) -> List[str]:
        return node_names(self._manager.target(target_id).spec)

    def status(self, target_id: str) -> str:
        return self._manager.target(target_id).status()

    def log_tail(self, target_id: str) -> List[str]:
        try:
            return self._manager.logs(target_id).tail(LOG_TAIL_LINES)
        except LauncherError:
            return []

    def restore(self) -> None:
        for target_id, was_alive in self._initial.items():
            try:
                alive = self._manager.target(target_id).alive()
                if was_alive and not alive:
                    self._manager.start(target_id)
                elif alive and not was_alive:
                    self._manager.stop(target_id)
            except LauncherError as exc:
                LOG.warning('scenario: cannot restore target %s: %s', target_id, exc)
        self._initial.clear()
        if self._owned:
            self._manager.close()


class SetupProcesses:
    """The scenario's own child processes (private registry, always torn down)."""

    def __init__(self, manager: ProcessManager):
        self._manager = manager
        self._ids: List[str] = []

    def start(self, index: int, entry: SetupEntry) -> List[str]:
        """Start one item; returns the nodes to wait for."""
        try:
            spec = spec_for(index, entry)
            self._manager.add(spec, strict=True)
            self._ids.append(spec.id)
            self._manager.start(spec.id)
        except LauncherError as exc:
            raise SetupError(_launcher_text(exc)) from exc
        except ValueError as exc:  # pydantic validation of a cmd-built spec
            raise SetupError(f'cmd を起動設定にできません: {exc}') from exc
        return [*node_names(spec), *(full_node_name(n) for n in entry.item.wait_for_node)]

    def last_id(self) -> Optional[str]:
        return self._ids[-1] if self._ids else None

    def status(self, target_id: str) -> str:
        return self._manager.target(target_id).status()

    def log_tail(self, target_id: str) -> List[str]:
        try:
            return self._manager.logs(target_id).tail(LOG_TAIL_LINES)
        except LauncherError:
            return []

    def pids(self) -> List[int]:
        pids: List[int] = []
        for target_id in self._ids:
            try:
                pids += self._manager.target(target_id).to_dict()['pids']
            except LauncherError:
                continue
        return pids

    def close(self) -> None:
        self._manager.close()


def _launcher_text(exc: LauncherError) -> str:
    code = getattr(exc, 'code', '')
    hint = {'unknown_package': 'パッケージが見つかりません (ビルド・source 済みか確認してください)',
            'unknown_executable': '実行ファイルが見つかりません',
            'unknown_launch_file': 'launch ファイルが見つかりません'}.get(code)
    return f'{hint}: {exc}' if hint else f'起動できません: {exc}'


def wait_nodes(present: Callable[[], List[str]], names: Sequence[str], timeout: float,
               alive: Callable[[], bool], tick: Callable[[], None] = lambda: None,
               poll_sec: float = 0.1) -> List[str]:
    """Wait until every node in ``names`` is in the graph; returns the missing ones.

    Stops early (returning the missing nodes) when the process is no longer alive.
    """
    deadline = time.monotonic() + timeout
    missing = list(names)
    while missing:
        current = set(present())
        missing = [n for n in names if n not in current]
        if not missing or time.monotonic() >= deadline or not alive():
            break
        tick()
        time.sleep(poll_sec)
    return missing
