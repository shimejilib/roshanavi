"""The "run separately" list of the takeover remainder (docs/design/integration.md).

In per-node takeover, roshanavi runs each decomposed Node as its own target and the
rest of the launch file (ExecuteProcess, containers, timers, event handlers, nodes it
could not decompose) as one launch target: ``takeover_rest.launch.py`` includes the
original file and skips exactly the Nodes listed here. A key is
``package:executable:name:namespace`` (name / namespace empty when not set); keys are
joined with ``,``. None of these characters can occur in valid ROS names.
"""

from typing import Iterable, Mapping, Optional, Set, Tuple

Key = Tuple[str, str, str, str]
REST_LAUNCH_FILE = 'takeover_rest.launch.py'
REST_PACKAGE = 'roshanavi'
ARG_PACKAGE = 'roshanavi_package'
ARG_LAUNCH_FILE = 'roshanavi_launch_file'
ARG_SKIP = 'roshanavi_skip'


def node_key(identity: Mapping[str, Optional[str]]) -> Key:
    return tuple(str(identity.get(k) or '') for k in  # type: ignore[return-value]
                 ('package', 'executable', 'name', 'namespace'))


def encode(keys: Iterable[Key]) -> str:
    return ','.join(sorted({':'.join(key) for key in keys}))


def decode(text: str) -> Set[Key]:
    keys: Set[Key] = set()
    for item in (text or '').split(','):
        parts = item.split(':')
        if len(parts) == 4 and parts[0] and parts[1]:
            keys.add((parts[0], parts[1], parts[2], parts[3]))
    return keys
