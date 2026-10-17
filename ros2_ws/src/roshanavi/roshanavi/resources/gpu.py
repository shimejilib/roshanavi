"""GPU via NVML (``pynvml``, optional): utilization, memory, temperature, per-process memory.

Degrades instead of failing: without ``pynvml`` or an NVIDIA driver the reader reports
``available: false`` with a reason the UI explains. Known limits:
- WSL2: NVML usually works for the whole GPU, but the per-process list is often empty
  (``per_process: false``), so per-node GPU memory is unknown there.
- Containers: the GPU is only visible when started with ``--gpus``; NVML reports host
  PIDs, which do not match the container's PIDs (per-process values then stay empty).
"""

import logging
import platform
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)

REASON_NOT_INSTALLED = 'not_installed'
REASON_NO_DRIVER = 'no_driver'
REASON_NO_DEVICE = 'no_device'


def is_wsl() -> bool:
    return 'microsoft' in platform.release().lower()


def _load_nvml() -> Any:
    import pynvml  # type: ignore[import-not-found]  # optional dependency
    return pynvml


def _text(value: Any) -> str:
    return value.decode('utf-8', 'replace') if isinstance(value, bytes) else str(value)


class GpuReader:
    def __init__(self, loader: Any = _load_nvml, wsl: Optional[bool] = None):
        self._nvml: Any = None
        self._handles: List[Any] = []
        self._wsl = is_wsl() if wsl is None else wsl
        self.reason: Optional[str] = None
        try:
            nvml = loader()
        except ImportError:
            self.reason = REASON_NOT_INSTALLED
            return
        try:
            nvml.nvmlInit()
            count = nvml.nvmlDeviceGetCount()
            self._handles = [nvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
        except Exception as exc:  # NVMLError_* (no driver / library), anything from bindings
            LOG.info('GPU monitoring off: %s', exc)
            self.reason = REASON_NO_DRIVER
            return
        if not self._handles:
            self.reason = REASON_NO_DEVICE
            return
        self._nvml = nvml

    @property
    def available(self) -> bool:
        return self._nvml is not None

    def _device(self, index: int, handle: Any, procs: Dict[int, int]) -> Dict[str, Any]:
        nvml = self._nvml
        out: Dict[str, Any] = {'index': index, 'name': None, 'util_pct': None, 'mem_used': None,
                               'mem_total': None, 'temp_c': None}
        calls = (('name', lambda: _text(nvml.nvmlDeviceGetName(handle))),
                 ('util_pct', lambda: nvml.nvmlDeviceGetUtilizationRates(handle).gpu),
                 ('temp_c', lambda: nvml.nvmlDeviceGetTemperature(handle,
                                                                  nvml.NVML_TEMPERATURE_GPU)))
        for key, call in calls:
            try:
                out[key] = call()
            except Exception:  # a field the GPU / driver does not support
                pass
        try:
            mem = nvml.nvmlDeviceGetMemoryInfo(handle)
            out['mem_used'], out['mem_total'] = int(mem.used), int(mem.total)
        except Exception:
            pass
        for getter in ('nvmlDeviceGetComputeRunningProcesses',
                       'nvmlDeviceGetGraphicsRunningProcesses'):
            try:
                for proc in getattr(nvml, getter)(handle) or ():
                    used = getattr(proc, 'usedGpuMemory', None)
                    if used is not None:
                        procs[int(proc.pid)] = procs.get(int(proc.pid), 0) + int(used)
            except Exception:
                continue
        return out

    def read(self) -> Dict[str, Any]:
        """``{available, reason, wsl, devices: [...], procs: {pid: bytes}, per_process}``."""
        if not self.available:
            return {'available': False, 'reason': self.reason, 'wsl': self._wsl, 'devices': [],
                    'procs': {}, 'per_process': False}
        procs: Dict[int, int] = {}
        devices = [self._device(i, h, procs) for i, h in enumerate(self._handles)]
        return {'available': True, 'reason': None, 'wsl': self._wsl, 'devices': devices,
                'procs': procs, 'per_process': bool(procs)}

    def close(self) -> None:
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml = None
