"""``bag`` injection mode: ``ros2 bag play`` as a subprocess, stopped with SIGINT."""

import logging
import signal
import subprocess
import threading
from typing import List, Optional

from .jobs import InjectError, InjectSpec, Job, validate_topic

LOG = logging.getLogger(__name__)

BAG_STOP_TIMEOUT_SEC = 5.0
MAX_BAG_RATE = 100.0


class BagJob(Job):
    """Runs ``ros2 bag play`` as a subprocess; stopped with SIGINT."""

    def __init__(self, spec: InjectSpec, bag_path: str):
        super().__init__(spec)
        self._cmd = build_bag_command(bag_path, spec)
        self._proc: Optional[subprocess.Popen] = None

    def begin(self) -> None:
        try:
            self._proc = subprocess.Popen(self._cmd, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            raise InjectError('bag_failed', f'cannot start ros2 bag play: {exc}', 500) from exc
        threading.Thread(target=self._watch, name=f'bag-{self.id}', daemon=True).start()

    def _watch(self) -> None:
        _, stderr = self._proc.communicate()
        code = self._proc.returncode
        if code == 0:
            self.finish('done')
        else:
            tail = (stderr or '').strip().splitlines()[-3:]
            self.finish('error', f'ros2 bag play exited with {code}: {" | ".join(tail)}')

    def _teardown(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=BAG_STOP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            LOG.warning('bag job %s ignored SIGINT, killing', self.id)
            proc.kill()


def build_bag_command(bag_path: str, spec: InjectSpec) -> List[str]:
    if not 0 < spec.bag_rate <= MAX_BAG_RATE:
        raise InjectError('invalid_request', f'bag_rate must be in (0, {MAX_BAG_RATE}]')
    cmd = ['ros2', 'bag', 'play', bag_path, '--rate', str(spec.bag_rate)]
    if spec.loop:
        cmd.append('--loop')
    if spec.bag_topics:
        cmd += ['--topics', *[validate_topic(t) for t in spec.bag_topics]]
    return cmd
