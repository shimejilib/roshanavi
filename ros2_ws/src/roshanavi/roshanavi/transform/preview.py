"""Dry run of a transform for the editor's live preview (``POST /api/transforms/preview``).

Uses exactly the same :class:`~.compute.Computer` and ``msgutil.build`` as the
running node, on sample input messages sent by the editor (the latest message
the UI echoed, or the input type's default template when nothing has been
received yet). Never publishes anything. All problems come back as a list of
``{path, code, message, params}`` so the UI can show them at the field.
"""

import re
import time
from typing import Any, Dict, List, Mapping, Optional

from .. import msgutil
from ..launcher.schema import TransformSpec
from ..msg_view import MsgView
from ..pydantic_compat import ValidationError, validation_errors
from .compute import Computer, FieldError, aliases

MAX_SAMPLE_DEPTH = 32
_MSG_PATH_RE = re.compile(r'^([A-Za-z0-9_.]+): ')


def _spec_errors(exc: ValidationError) -> List[FieldError]:
    errors = []
    for err in validation_errors(exc):
        path = '.'.join(str(p) for p in err['loc'] if p != '__root__') or '(spec)'
        errors.append(FieldError(path, 'spec_invalid', err['msg']))
    return errors


def _depth(value: Any, level: int = 0) -> int:
    if level > MAX_SAMPLE_DEPTH:
        return level
    if isinstance(value, Mapping):
        return max([_depth(v, level + 1) for v in value.values()] or [level])
    if isinstance(value, list):
        return max([_depth(v, level + 1) for v in value] or [level])
    return level


def _sample_views(spec: TransformSpec, samples: Mapping[str, Any]) -> Dict[str, Any]:
    """``{alias: MsgView}`` plus the aliases that fell back to the type's template."""
    views: Dict[str, MsgView] = {}
    templated: List[str] = []
    errors: List[FieldError] = []
    for inp, alias in zip(spec.inputs, aliases(spec)):
        sample = samples.get(alias)
        if sample is None:
            try:
                sample = msgutil.template(inp.type)
            except msgutil.MsgUtilError as exc:
                errors.append(FieldError(f'inputs.{alias}', 'unknown_type', str(exc)))
                continue
            templated.append(alias)
        if not isinstance(sample, Mapping) or _depth(sample) > MAX_SAMPLE_DEPTH:
            errors.append(FieldError(f'inputs.{alias}', 'bad_sample',
                                     'the sample message must be a mapping'))
            continue
        views[alias] = MsgView(dict(sample))
    return {'views': views, 'templated': templated, 'errors': errors}


def _build_error(exc: msgutil.MsgUtilError) -> FieldError:
    match = _MSG_PATH_RE.match(str(exc))
    return FieldError(match.group(1) if match else '(output)', f'build_{exc.code}', str(exc))


def _result(ok: bool, errors: List[FieldError], **extra: Any) -> Dict[str, Any]:
    return {'ok': ok, 'errors': [e.to_dict() for e in errors], **extra}


def preview(raw_spec: Mapping[str, Any], samples: Optional[Mapping[str, Any]] = None
            ) -> Dict[str, Any]:
    try:
        spec = TransformSpec.model_validate(dict(raw_spec))
    except ValidationError as exc:
        return _result(False, _spec_errors(exc), passed=False, output=None)
    unknown = sorted(set(samples or {}) - set(aliases(spec)))
    if unknown:
        return _result(False, [FieldError('inputs', 'bad_sample',
                                          f'no input named {unknown[0]!r}')],
                       passed=False, output=None)
    if spec.mode == 'relay':
        alias = aliases(spec)[0]
        return _result(True, [], passed=True, relay=True,
                       output=(samples or {}).get(alias))
    prepared = _sample_views(spec, samples or {})
    if prepared['errors']:
        return _result(False, prepared['errors'], passed=False, output=None)
    computer = Computer(spec)
    outcome = computer.compute(prepared['views'], {'i': 0, 't': 0.0, 'now': time.time()})
    extra = {'templated': prepared['templated']}
    if outcome.errors:
        return _result(False, outcome.errors, passed=False, output=None, **extra)
    if not outcome.passed:
        return _result(True, [], passed=False, output=None, **extra)
    try:
        built = msgutil.build(spec.output.type, outcome.output)
    except msgutil.MsgUtilError as exc:
        return _result(False, [_build_error(exc)], passed=False, output=None, **extra)
    return _result(True, [], passed=True, output=msgutil.to_display(built), **extra)
