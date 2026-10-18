"""What the node's own Python environment has (runs **inside the node process**).

- :func:`python_info`: which interpreter runs the node and whether it is a virtual environment
  (「venv に入れたのに見つからない」 is almost always a node running another Python).
- :func:`check_requirements`: a ``requirements.txt`` next to the user's code compared with the
  distributions installed in this interpreter (``importlib.metadata``; nothing is installed and
  pip is never run). Lines are parsed with ``packaging`` when it is available, else with a
  conservative parser that only checks presence.
"""

import importlib.metadata
import os
import platform
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

REQUIREMENTS_FILE = 'requirements.txt'
MAX_REQUIREMENTS_BYTES = 256 * 1024
MAX_REQUIREMENT_LINES = 500
_NAME_RE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$')
_SIMPLE_SPEC_RE = re.compile(r'^((~=|==|!=|<=|>=|<|>|===)\s*[A-Za-z0-9.*+!_-]+\s*,?\s*)*$')

try:  # optional: exact version / marker checks
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - packaging is present on Jazzy and Lyrical
    Requirement = None  # type: ignore[assignment,misc]


def python_info() -> Dict[str, Any]:
    base = getattr(sys, 'base_prefix', sys.prefix)
    return {'executable': sys.executable, 'version': platform.python_version(),
            'prefix': sys.prefix, 'venv': sys.prefix != base,
            'virtual_env': os.environ.get('VIRTUAL_ENV') or None}


def normalize(name: str) -> str:
    """PEP 503 name normalization (``Foo_Bar`` == ``foo-bar``)."""
    return re.sub(r'[-_.]+', '-', name).lower()


def _installed_version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        pass
    except Exception:  # noqa: BLE001 - broken metadata must not break the node
        return None
    wanted = normalize(name)
    try:
        for dist in importlib.metadata.distributions():
            if normalize(dist.metadata.get('Name') or '') == wanted:
                return dist.version
    except Exception:  # noqa: BLE001
        return None
    return None


def _strip(line: str) -> str:
    return re.split(r'\s+#', line.strip(), maxsplit=1)[0].strip() if not line.lstrip().startswith(
        '#') else ''


def parse_line(line: str) -> Tuple[Optional[Tuple[str, str, Any]], Optional[str]]:
    """``((name, specifier text, Requirement | None), None)`` or ``(None, skip reason)``."""
    text = _strip(line)
    if not text:
        return None, None
    if text.startswith('-') or '://' in text or text.startswith(('.', '/', '~')):
        return None, 'option'   # -r / -e / --index-url / URLs / paths: not checked
    if Requirement is not None:
        try:
            req = Requirement(text)
        except InvalidRequirement:
            return None, 'unreadable'
        if req.url:
            return None, 'option'
        if req.marker is not None and not req.marker.evaluate():
            return None, 'not_for_this_environment'
        return (req.name, str(req.specifier), req), None
    if ';' in text:
        return None, 'marker_unchecked'   # environment markers need packaging
    match = _NAME_RE.match(text)
    if not match or not _SIMPLE_SPEC_RE.match(match.group(3).strip()):
        return None, 'unreadable'
    return (match.group(1), match.group(3).strip(), None), None


def _satisfied(req: Any, version: str) -> Optional[bool]:
    if req is None or not str(req.specifier):
        return True
    try:
        return req.specifier.contains(Version(version), prereleases=True)
    except InvalidVersion:
        return None


def check_file(path: str, shown: str) -> Dict[str, Any]:
    """One ``requirements.txt`` against this interpreter."""
    result: Dict[str, Any] = {'file': shown, 'missing': [], 'mismatched': [], 'skipped': [],
                              'ok': 0, 'exact': Requirement is not None}
    try:
        if os.path.getsize(path) > MAX_REQUIREMENTS_BYTES:
            result['error'] = 'too_large'
            return result
        with open(path, encoding='utf-8', errors='replace') as fh:
            lines = fh.read().splitlines()[:MAX_REQUIREMENT_LINES]
    except OSError as exc:
        result['error'] = str(exc)
        return result
    for number, line in enumerate(lines, start=1):
        parsed, reason = parse_line(line)
        if parsed is None:
            if reason:
                result['skipped'].append({'line': number, 'text': line.strip()[:200],
                                          'reason': reason})
            continue
        name, spec, req = parsed
        version = _installed_version(name)
        if version is None:
            result['missing'].append({'name': name, 'spec': spec, 'line': number})
        elif _satisfied(req, version) is False:
            result['mismatched'].append({'name': name, 'spec': spec, 'installed': version,
                                         'line': number})
        else:
            result['ok'] += 1
    return result


def check_requirements(directories: Iterable[str], shown_base: str) -> List[Dict[str, Any]]:
    """Every ``requirements.txt`` found directly in ``directories`` (no duplicates)."""
    results: List[Dict[str, Any]] = []
    seen = set()
    for directory in directories:
        path = os.path.join(directory, REQUIREMENTS_FILE)
        real = os.path.realpath(path)
        if real in seen or not os.path.isfile(real):
            continue
        seen.add(real)
        shown = os.path.relpath(real, shown_base) if real.startswith(
            os.path.join(shown_base, '')) else real
        results.append(check_file(real, shown))
    return results
