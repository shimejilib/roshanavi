"""UDP counters from ``/proc/net/snmp`` (pure parser + a reader).

The file has header / value line pairs per protocol, e.g.::

    Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors SndbufErrors ...
    Udp: 1234 0 5 999 5 0 ...

``RcvbufErrors`` counts datagrams the kernel dropped because a socket's receive buffer
was full (DDS readers that cannot keep up with large messages). The counters belong to
the network namespace: inside a container they only cover that container.
"""

from typing import Dict, Optional

SNMP_PATH = '/proc/net/snmp'


def parse_snmp(text: str, proto: str = 'Udp') -> Dict[str, int]:
    """``{counter: value}`` of one protocol; {} when missing or malformed."""
    prefix = proto + ':'
    lines = [line.split() for line in text.splitlines() if line.startswith(prefix)]
    if len(lines) < 2:
        return {}
    header, values = lines[0][1:], lines[1][1:]
    if len(header) != len(values):
        return {}
    out: Dict[str, int] = {}
    for key, value in zip(header, values):
        try:
            out[key] = int(value)
        except ValueError:
            continue
    return out


def read_udp(path: str = SNMP_PATH) -> Optional[Dict[str, int]]:
    try:
        with open(path, encoding='ascii', errors='replace') as handle:
            counters = parse_snmp(handle.read())
    except OSError:
        return None
    return counters or None
