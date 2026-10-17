"""JUnit XML for CI: one ``<testsuite>`` per scenario, one ``<testcase>`` per step / guard."""

import xml.etree.ElementTree as ET
from typing import Iterable, List

from .result import CANCELLED, ERROR, FAILED, SKIPPED, Result

_CONTROL = {c: None for c in range(32) if c not in (9, 10, 13)}


def _text(value: str) -> str:
    """XML 1.0 cannot carry most control characters."""
    return str(value).translate(_CONTROL)


def _case(suite: ET.Element, classname: str, name: str, seconds: float, status: str,
          message: str, body: str = '') -> None:
    case = ET.SubElement(suite, 'testcase', classname=_text(classname), name=_text(name),
                         time=f'{max(seconds, 0.0):.3f}')
    if status == FAILED:
        ET.SubElement(case, 'failure', message=_text(message)[:1000]).text = _text(body or message)
    elif status in (ERROR, CANCELLED):
        ET.SubElement(case, 'error', message=_text(message)[:1000]).text = _text(body or message)
    elif status == SKIPPED:
        ET.SubElement(case, 'skipped', message=_text(message or 'skipped'))


def _suite(root: ET.Element, result: Result) -> None:
    cases: List[tuple] = []
    classname = f'roshanavi.scenario.{result.name}'
    if result.schema_errors or (result.status == ERROR and not result.steps):
        cases.append(('00 schema', 0.0, ERROR, result.message, ''))
    for s in result.setup:
        cases.append((f'setup {s.index + 1:02d} {s.summary}', 0.0, s.status, s.message,
                      '\n'.join([s.message, *s.log_tail])))
    for s in result.steps:
        body = '\n'.join([s.message, *(h['message'] for h in s.hints)])
        cases.append((f'{s.index + 1:02d} {s.kind}: {s.summary}', s.duration_sec or 0.0, s.status,
                       s.message, body))
    for g in result.guards:
        cases.append((f'guard {g.index + 1:02d} {g.kind}: {g.summary}', 0.0, g.status,
                       g.message, ''))
    failures = sum(1 for c in cases if c[2] == FAILED)
    errors = sum(1 for c in cases if c[2] in (ERROR, CANCELLED))
    skipped = sum(1 for c in cases if c[2] == SKIPPED)
    suite = ET.SubElement(root, 'testsuite', name=_text(result.name), tests=str(len(cases)),
                          failures=str(failures), errors=str(errors), skipped=str(skipped),
                          time=f'{result.duration_sec:.3f}', file=_text(result.file))
    for name, seconds, status, message, body in cases:
        _case(suite, classname, name, seconds, status, message, body)


def to_junit(results: Iterable[Result]) -> str:
    results = list(results)
    root = ET.Element('testsuites', name='roshanavi scenarios')
    for result in results:
        _suite(root, result)
    totals = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    for suite in root:
        for key in totals:
            totals[key] += int(suite.get(key, '0'))
    for key, value in totals.items():
        root.set(key, str(value))
    root.set('time', f'{sum(r.duration_sec for r in results):.3f}')
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'
