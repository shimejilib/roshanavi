"""Composition root: runtime + graph + traffic + injector + echo + launcher + media + resources.

A single 1 s housekeeping timer (executor thread) collects the ROS graph,
updates the graph snapshot, syncs traffic subscriptions and ticks the hz
history. It also maps graph nodes to launcher processes (roles). Everything
the API serves is read from those cached snapshots.
"""

import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

import psutil

from . import graph, rates, sample_media
from .echo import EchoManager
from .fd_guard import FdGuard
from .gc_janitor import GcJanitor
from .injector import Injector
from .launch_import.importer import LaunchImporter
from .launch_import.takeover import TakeoverService
from .launcher.catalog import ProjectCatalog
from .launcher.service import Launcher
from .launcher.trash import Trash
from .media.diskguard import DiskGuard, DiskThresholds
from .media.recorder import Recorder
from .media.viewer import MediaViewer
from .lifecycle import LifecycleService
from .params import ParamService
from .resources.attribution import SelfPids
from .resources.service import ResourceContext, ResourceService
from .ros_runtime import RosRuntime
from .scenario.service import ScenarioService
from .service_defaults import DEFAULT_SERVICE_TIMEOUT_SEC
from .traffic import DEFAULT_WINDOW_SEC
from .traffic_backend import PROBE_OFF, TrafficService
from .tracing import merge as trace_merge
from .tracing.config import DEFAULT_RT_PER_CPU
from .tracing.service import LTTNG_DAEMONS, TRACING_OFF, TracingService

LOG = logging.getLogger(__name__)

HOUSEKEEPING_PERIOD_SEC = 1.0


def _created_at(pid: int) -> Optional[float]:
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


class Lab:
    def __init__(self, data_dir: str = '/data', show_self: bool = False,
                 node_name: str = 'roshanavi', window_sec: float = DEFAULT_WINDOW_SEC,
                 traffic_exclude: Sequence[str] = (), monitor_heavy: bool = False,
                 period_sec: float = HOUSEKEEPING_PERIOD_SEC,
                 clock: Callable[[], float] = time.monotonic,
                 workspace: Optional[str] = None, project_path: Optional[str] = None,
                 autostart: bool = True, stop_timeouts: Optional[Sequence[float]] = None,
                 disk_thresholds: DiskThresholds = DiskThresholds(), probe: str = PROBE_OFF,
                 tracing: str = TRACING_OFF, trace_buffer_per_cpu: int = DEFAULT_RT_PER_CPU,
                 examples_dir: Optional[str] = None, generate_samples: bool = False,
                 resources: bool = True, reverse_dns: bool = True,
                 use_remembered_project: bool = True, takeover_poll_sec: float = 2.0,
                 service_timeout_sec: float = DEFAULT_SERVICE_TIMEOUT_SEC):
        self.data_dir = data_dir
        self.examples_dir = examples_dir
        self._generate_samples = generate_samples
        self.catalog = ProjectCatalog(data_dir, examples_dir)
        # The last project the user switched to; --launch always works on --project instead.
        remembered = self.catalog.remembered_path() if use_remembered_project else None
        if remembered:
            LOG.info('starting on the remembered project %s', remembered)
        self.launcher = Launcher(workspace or os.getcwd(), data_dir,
                                 project_path=remembered or project_path,
                                 autostart=autostart, timeouts=stop_timeouts)
        self.importer = LaunchImporter(self.launcher, data_dir)
        self.trash = Trash(self.launcher)
        self.takeover = TakeoverService(self.importer, data_dir, poll_sec=takeover_poll_sec,
                                        autostart=autostart)
        self.runtime = RosRuntime(node_name)
        self.graph = graph.GraphMonitor(show_self=show_self)
        self.launcher.manager.topic_types = lambda topic: self.graph.raw().topics.get(topic, [])
        self.traffic = TrafficService(self.runtime, probe=probe, window_sec=window_sec,
                                      exclude=traffic_exclude, clock=clock,
                                      monitor_heavy=monitor_heavy)
        # The saved per-topic monitoring on / off of the project, applied again whenever
        # the project's choices change (a project switch or reload) in housekeeping.
        self._applied_monitor: Dict[str, bool] = self.launcher.traffic_monitor
        self.traffic.selector.replace_overrides(self._applied_monitor)
        self.tracing = TracingService(tracing, rt_per_cpu=trace_buffer_per_cpu)
        self._node_pids: Dict[str, Optional[int]] = {}
        self.injector = Injector(self.runtime, data_dir, clock=clock,
                                 extra_roots=(self.launcher.workspace.root,))
        self.echo = EchoManager(self.runtime)
        self.viewer = MediaViewer(self.runtime)
        self.params = ParamService(self.runtime, service_timeout_sec)
        self.lifecycle = LifecycleService(self.runtime, service_timeout_sec)
        self.recorder = Recorder(data_dir, DiskGuard(data_dir, disk_thresholds))
        # Resource monitoring (docs/design/resources.md): own 1 Hz thread, same disk thresholds.
        self.resources = ResourceService(self._resource_context, data_dir,
                                         DiskGuard(data_dir, disk_thresholds),
                                         reverse_dns=reverse_dns, enabled=resources)
        self._period = period_sec
        self._timer: Any = None
        self.housekeeping_runs = 0
        self._fd_guard = FdGuard()
        self._gc_janitor = GcJanitor()
        # Scenarios (docs/design/scenarios.md): files next to the current project file.
        self.scenarios = ScenarioService(self, lambda: self.launcher.project.path)

    def start(self) -> 'Lab':
        if self._generate_samples:  # perception demo media (ffmpeg; first run only)
            sample_media.ensure_in_background(self.data_dir)
        self.runtime.start()
        self.traffic.start()
        # Before the first housekeeping: the Launcher's autostart must find the init capture on.
        self.tracing.start()
        self._timer = self.runtime.create_timer(self._period, self.housekeeping)
        self.resources.start()
        return self

    def housekeeping(self) -> None:
        """Executor-thread callback; never raises (a crash would kill the timer)."""
        try:
            raw = graph.collect(self.runtime)
            node_info = self.launcher.observe(graph.node_ids(raw))
            self._node_pids = {n: info.get('pid') for n, info in node_info.items()}
            self.graph.update(raw, self.injector.list(), node_info,
                              self.launcher.manager.action_topics())
            self._apply_saved_monitoring()
            self.traffic.sync(raw)
            self.traffic.tick()
            self.tracing.poll()
            self._fd_guard.check()
            self._gc_janitor.tick()
            self.housekeeping_runs += 1
        except Exception:  # keep the loop alive but make failures visible
            LOG.exception('housekeeping failed')

    def _apply_saved_monitoring(self) -> None:
        saved = self.launcher.traffic_monitor
        if saved != self._applied_monitor:
            self._applied_monitor = saved
            self.traffic.selector.replace_overrides(saved)

    def set_topic_monitoring(self, topic: str, enabled: bool) -> None:
        """Turn a topic's measurement on / off now and remember it in the project file."""
        self.launcher.set_traffic_monitor(topic, enabled)  # first: housekeeping reads it back
        self._applied_monitor = self.launcher.traffic_monitor
        self.traffic.set_monitored(topic, enabled)

    def _resource_context(self) -> ResourceContext:
        """Read by the resource sampler thread once per second (all calls are thread-safe)."""
        snapshot, _ = self.graph.snapshot()
        manager = self.launcher.manager
        active = self.recorder.status()['active']
        tracing_on = bool(self.tracing.status().get('active'))
        own = SelfPids(server=os.getpid(), probe=self.traffic.status().get('pid'),
                       tracing=self.tracing.worker_pid(),
                       recorder=active.get('pid') if active else None,
                       lttng_names=LTTNG_DAEMONS if tracing_on else ())
        return ResourceContext(
            nodes=tuple(n['id'] for n in snapshot['nodes'] if not n.get('job_id')),
            launcher=self.launcher.mapper.mapping(), targets=tuple(manager.process_refs()),
            roles=manager.roles(), own=own, traffic=self.traffic.snapshot,
            recording=bool(active))

    def traffic_view(self, window_sec: Optional[float] = None) -> List[Dict[str, Any]]:
        """Traffic entries (rates over ``window_sec``) plus per-publisher rates for the map."""
        snapshot, _ = self.graph.snapshot()
        known = rates.known_rates(self.injector.list(), snapshot['nodes'],
                                  self.launcher.targets())
        entries = rates.annotate_traffic(self.traffic.snapshot(window_sec), snapshot['edges'],
                                         known)
        return trace_merge.apply_trace(entries, self.tracing.snapshot(), window_sec)

    def tracing_status(self, entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """詳細計測モード status, plus unsupported nodes and processing diagnostics."""
        status = self.tracing.status()
        snap = self.tracing.snapshot()
        if snap is None:
            return {**status, 'unsupported': [], 'diagnostics': []}
        snapshot, _ = self.graph.snapshot()
        unsupported = trace_merge.unsupported_nodes(
            snapshot['nodes'], snap, self._node_pids, self.tracing.started_wall, _created_at)
        entries = self.traffic_view() if entries is None else entries
        return {**status, 'unsupported': unsupported,
                'diagnostics': trace_merge.behind_list(entries)}

    def set_tracing(self, enabled: bool) -> Dict[str, Any]:
        """Turn 詳細計測モード on / off; roshanavi's own processes are filtered out."""
        exclude = [os.getpid()]
        probe_pid = self.traffic.status().get('pid')
        if probe_pid:
            exclude.append(int(probe_pid))
        self.tracing.set_enabled(enabled, exclude)
        return self.tracing_status()

    def stop(self) -> None:
        self.resources.close()  # idempotent; only reads, so it can go first
        self.scenarios.close()  # cancel a running scenario first: its teardown uses the rest
        self.takeover.close()  # no re-import while the targets stop
        self.launcher.close()  # idempotent; child processes go first
        self.tracing.close()  # idempotent; the worker destroys its LTTng sessions
        self.recorder.close()  # SIGINT so the bag is finalized
        if not self.runtime.running:
            return
        if self._timer is not None:
            self.runtime.destroy_timer(self._timer)
            self._timer = None
        self.injector.close()
        self.echo.close()
        self.viewer.close()
        self.params.close()
        self.lifecycle.close()
        self.traffic.close()
        self.runtime.stop()

    def __enter__(self) -> 'Lab':
        return self.start()

    def __exit__(self, *exc: Optional[Any]) -> None:
        self.stop()
