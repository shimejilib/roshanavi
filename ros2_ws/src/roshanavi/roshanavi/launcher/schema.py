"""Pydantic (v1) models shared by the REST API and the ``roshanavi.yaml`` project file.

These check *shape* (types, unknown keys, id format). Values that need the
workspace (package/executable exist, paths contained) are checked by
:mod:`.command` when a target is registered or started.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import (BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr,
                      confloat, conint, constr, root_validator)

from ..heavy_types import is_heavy
from ..media.options import MediaOptions
from . import validate

ParamValue = Union[StrictBool, StrictInt, StrictFloat, StrictStr]
ID_PATTERN = validate.TARGET_ID_RE.pattern
PROJECT_VERSION = 1


class _Strict(BaseModel):
    class Config:
        extra = 'forbid'


class QosSpec(_Strict):
    reliability: Literal['reliable', 'best_effort'] = 'reliable'
    durability: Literal['volatile', 'transient_local'] = 'volatile'
    depth: conint(ge=1, le=1000) = 10


class TargetSpec(_Strict):
    """A process to launch: ``ros2 run`` (kind run) or ``ros2 launch`` (kind launch)."""

    id: constr(regex=ID_PATTERN)
    kind: Literal['run', 'launch']
    package: constr(max_length=100)
    executable: Optional[constr(max_length=128)] = None
    launch_file: Optional[constr(max_length=128)] = None
    args: List[constr(max_length=4096)] = Field(default_factory=list, max_items=64)
    params: Dict[constr(max_length=200), ParamValue] = Field(default_factory=dict)
    params_file: Optional[constr(max_length=1024)] = None
    remaps: Dict[constr(max_length=256), constr(max_length=256)] = Field(default_factory=dict)
    namespace: Optional[constr(max_length=256)] = None
    name: Optional[constr(max_length=256)] = None
    role: Literal['mine', 'dependency'] = 'dependency'
    autostart: bool = False
    auto_restart: bool = False
    # Informational: the launch file this target was decomposed from (§4.16).
    imported_from: Optional[constr(max_length=1024)] = None

    @root_validator(skip_on_failure=True)
    def _kind_fields(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values['kind'] == 'run':
            if not values.get('executable'):
                raise ValueError('kind "run" needs "executable"')
            if values.get('launch_file'):
                raise ValueError('kind "run" does not take "launch_file"')
        else:
            if not values.get('launch_file'):
                raise ValueError('kind "launch" needs "launch_file"')
            unsupported = [k for k in ('executable', 'params_file', 'namespace', 'name')
                           if values.get(k)] + [k for k in ('params', 'remaps') if values.get(k)]
            if unsupported:
                raise ValueError(f'kind "launch" does not take {unsupported}; '
                                 'pass launch arguments as args ["name:=value"]')
        return values


class DummySpec(_Strict):
    """A persistent dummy node: one injection run by ``ros2 run roshanavi dummy``."""

    id: constr(regex=ID_PATTERN)
    name: constr(min_length=1, max_length=256)
    namespace: Optional[constr(max_length=256)] = None
    topic: constr(min_length=1, max_length=256)
    type: constr(min_length=1, max_length=256)
    mode: Literal['once', 'periodic', 'stream', 'media']
    payload: Optional[Dict[str, Any]] = None
    rate_hz: Optional[confloat(gt=0, le=1000)] = None
    count: Optional[conint(ge=1, le=10_000_000)] = None
    source: Optional[constr(max_length=1024)] = None
    loop: bool = False
    qos: QosSpec = Field(default_factory=QosSpec)
    media: Optional[MediaOptions] = None
    autostart: bool = False
    auto_restart: bool = False

    @root_validator(skip_on_failure=True)
    def _mode_fields(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        mode = values['mode']
        if mode == 'media':
            if not values.get('source'):
                raise ValueError('mode "media" needs "source" (a file or folder in the data dir)')
            return values
        if mode != 'once' and values.get('rate_hz') is None:
            raise ValueError(f'mode "{mode}" needs "rate_hz"')
        if mode == 'stream' and not values.get('source'):
            raise ValueError('mode "stream" needs "source" (a file in the data dir)')
        return values


ALIAS_PATTERN = r'^[a-z][a-z0-9_]{0,31}$'
MAX_TRANSFORM_INPUTS = 8
RESERVED_ALIASES = ('i', 't', 'now', 'pi', 'e')


class TransformInput(_Strict):
    topic: constr(min_length=1, max_length=256)
    type: constr(min_length=1, max_length=256)
    # Name of this input in expressions; default ``msg`` (one input) or ``msg1``, ``msg2`` ...
    alias: Optional[constr(regex=ALIAS_PATTERN)] = None


class TransformOutput(_Strict):
    topic: constr(min_length=1, max_length=256)
    type: Optional[constr(min_length=1, max_length=256)] = None  # relay: the input type
    qos: QosSpec = Field(default_factory=QosSpec)


class DelaySpec(_Strict):
    """Fixed delay (``min_ms`` only) or a uniformly random one in [min_ms, max_ms]."""

    min_ms: confloat(ge=0, le=60_000) = 0
    max_ms: Optional[confloat(ge=0, le=60_000)] = None

    @root_validator(skip_on_failure=True)
    def _order(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get('max_ms') is not None and values['max_ms'] < values['min_ms']:
            raise ValueError('delay max_ms must be >= min_ms')
        return values


class TransformSpec(_Strict):
    """A transform node (``ros2 run roshanavi transform``): topic(s) in -> topic out."""

    id: constr(regex=ID_PATTERN)
    name: constr(min_length=1, max_length=256)
    namespace: Optional[constr(max_length=256)] = None
    inputs: List[TransformInput] = Field(..., min_items=1, max_items=MAX_TRANSFORM_INPUTS)
    output: TransformOutput
    mode: Literal['map', 'relay'] = 'map'
    # Output message template; strings with ${...} are expressions over the inputs.
    # map mode without mapping: forward the input message unchanged (filter / delay only).
    mapping: Optional[Dict[str, Any]] = None
    condition: Optional[constr(max_length=1000)] = None
    trigger: constr(max_length=32) = 'any'  # 'any' input update, or one input alias
    delay: Optional[DelaySpec] = None
    throttle_hz: Optional[confloat(gt=0, le=1000)] = None
    drop_ratio: confloat(ge=0, le=1) = 0
    autostart: bool = False
    auto_restart: bool = False

    @root_validator(skip_on_failure=True)
    def _consistent(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        inputs = values['inputs']
        single = len(inputs) == 1
        named = [inp if inp.alias else inp.copy(update={'alias': 'msg' if single else f'msg{n}'})
                 for n, inp in enumerate(inputs, start=1)]
        aliases = [inp.alias for inp in named]
        if len(set(aliases)) != len(aliases):
            raise ValueError(f'input aliases must be unique: {aliases}')
        reserved = sorted(set(aliases) & set(RESERVED_ALIASES))
        if reserved:
            raise ValueError(f'input alias {reserved[0]!r} is reserved')
        values['inputs'] = named
        if values['trigger'] != 'any' and values['trigger'] not in aliases:
            raise ValueError(f'trigger must be "any" or one of {aliases}')
        output = values['output']
        if values['mode'] == 'relay':
            _check_relay(values, named)
            if output.type is None:
                values['output'] = output.copy(update={'type': named[0].type})
            return values
        if output.type is None:
            if values.get('mapping') is not None or not single:
                raise ValueError('output.type is required for a mapping')
            values['output'] = output.copy(update={'type': named[0].type})
        heavy = [t for t in [*(i.type for i in named), values['output'].type] if is_heavy(t)]
        if heavy:
            raise ValueError(f'{heavy[0]} is a large type: use mode "relay" (relay / delay / '
                             'throttle / drop only; no field expressions)')
        if values.get('mapping') is None and not single:
            raise ValueError('several inputs need a mapping that combines them')
        return values


def _check_relay(values: Dict[str, Any], inputs: List[TransformInput]) -> None:
    if len(inputs) != 1:
        raise ValueError('mode "relay" takes exactly one input')
    if values.get('mapping') is not None or values.get('condition'):
        raise ValueError('mode "relay" forwards messages unchanged (no mapping / condition); '
                         'use mode "map"')
    out_type = values['output'].type
    if out_type is not None and _same_type(out_type, inputs[0].type) is False:
        raise ValueError('mode "relay" cannot change the type (output.type must be the input '
                         'type)')


def _same_type(a: str, b: str) -> bool:
    def norm(name: str) -> str:
        parts = name.split('/')
        return f'{parts[0]}/msg/{parts[-1]}' if len(parts) >= 2 else name
    return norm(a) == norm(b)


class ProjectSpec(_Strict):
    version: Literal[1] = PROJECT_VERSION
    targets: List[TargetSpec] = Field(default_factory=list, max_items=100)
    dummies: List[DummySpec] = Field(default_factory=list, max_items=100)
    transforms: List[TransformSpec] = Field(default_factory=list, max_items=100)
    watch_topics: List[constr(min_length=1, max_length=256)] = Field(default_factory=list,
                                                                     max_items=200)

    @root_validator(skip_on_failure=True)
    def _unique_ids(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        seen = set()
        for item in [*values.get('targets', []), *values.get('dummies', []),
                     *values.get('transforms', [])]:
            if item.id in seen:
                raise ValueError(f'duplicate id {item.id!r} (ids must be unique across '
                                 'targets, dummies and transforms)')
            seen.add(item.id)
        return values


def param_text(value: ParamValue) -> str:
    """Parameter value as rcl expects it after ``name:=`` (YAML scalar text)."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def clean_dict(model: BaseModel) -> Dict[str, Any]:
    """Field-ordered dict without None / empty collections (stable, readable YAML)."""
    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if v is not None and v != [] and v != {}}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    return strip(model.dict())
