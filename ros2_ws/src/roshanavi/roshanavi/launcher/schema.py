"""Pydantic (v1) models shared by the REST API and the ``roshanavi.yaml`` project file.

These check *shape* (types, unknown keys, id format). Values that need the
workspace (package/executable exist, paths contained) are checked by
:mod:`.command` when a target is registered or started.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import (BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr,
                      confloat, conint, constr, root_validator)

from .. import data_kinds
from ..heavy_types import is_heavy
from ..media.options import MediaOptions
from . import validate

ParamValue = Union[StrictBool, StrictInt, StrictFloat, StrictStr]
KindName = Literal['string', 'float', 'int', 'bool', 'numbers', 'json', 'image', 'audio', 'bytes',
                   'message']
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
    # Informational: the launch file this target was decomposed from (docs/design/launcher.md).
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
    # データの種類 the UI chose (docs/design/nodes.md); informational, must fit ``type``.
    kind: Optional[KindName] = None
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
        _check_kind(values.get('kind'), values['type'])
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


def _check_kind(kind: Optional[str], type_name: str) -> None:
    if kind is not None and not data_kinds.fits(kind, type_name):
        raise ValueError(f'type {type_name} does not carry data kind {kind!r}')


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


MODULE_PATTERN = r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,7}\Z'
FUNCTION_PATTERN = r'^[A-Za-z][A-Za-z0-9_]{0,63}\Z'
MAX_FUNCTION_INPUTS = 8
# pkg/Name or pkg/msg/Name only: function node types are also written into generated code.
MSG_TYPE_PATTERN = r'^[A-Za-z][A-Za-z0-9_]*/(msg/)?[A-Za-z][A-Za-z0-9_]*\Z'
RESERVED_MODULE_TOPS = ('roshanavi',)  # never re-import the tool's own package from source


class FunctionInput(_Strict):
    topic: constr(min_length=1, max_length=256)
    # データの種類: what the function receives (``message``: the message as a dict).
    kind: KindName = 'string'
    # Explicit type: a compatible type of an existing topic (Float32 ...) or, for kind
    # ``message``, the ROS type. Default: the kind's type (data_kinds).
    type: Optional[constr(regex=MSG_TYPE_PATTERN, max_length=256)] = None


class FunctionOutput(FunctionInput):
    qos: QosSpec = Field(default_factory=QosSpec)


class FunctionSpec(_Strict):
    """A function node (``ros2 run roshanavi function``): a plain Python function as a node."""

    id: constr(regex=ID_PATTERN)
    name: constr(min_length=1, max_length=256)
    namespace: Optional[constr(max_length=256)] = None
    module: constr(regex=MODULE_PATTERN)     # e.g. my_pkg.logic (a workspace package)
    function: constr(regex=FUNCTION_PATTERN)  # a top-level function of that module
    call: Literal['on_message', 'periodic', 'multi_input'] = 'on_message'
    inputs: List[FunctionInput] = Field(default_factory=list, max_items=MAX_FUNCTION_INPUTS)
    output: FunctionOutput
    rate_hz: Optional[confloat(gt=0, le=1000)] = None   # periodic
    trigger: constr(max_length=256) = 'any'  # multi_input: 'any' or one input topic
    autostart: bool = False
    auto_restart: bool = False

    @root_validator(skip_on_failure=True)
    def _consistent(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        call, inputs = values['call'], values['inputs']
        if values['module'].split('.')[0] in RESERVED_MODULE_TOPS:
            raise ValueError('module must be one of your workspace packages, not roshanavi')
        if call == 'on_message' and len(inputs) != 1:
            raise ValueError('call "on_message" takes exactly one input')
        if call == 'multi_input' and len(inputs) < 2:
            raise ValueError('call "multi_input" takes 2 or more inputs')
        if call == 'periodic':
            if inputs:
                raise ValueError('call "periodic" takes no inputs')
            if values.get('rate_hz') is None:
                raise ValueError('call "periodic" needs "rate_hz"')
        topics = [i.topic for i in inputs]
        if len(set(topics)) != len(topics):
            raise ValueError(f'input topics must be unique: {topics}')
        if values['trigger'] != 'any' and values['trigger'] not in topics:
            raise ValueError('trigger must be "any" or one of the input topics')
        for port in [*inputs, values['output']]:
            if port.kind == 'message' and not port.type:
                raise ValueError(f'{port.topic}: kind "message" needs a "type"')
            if port.type:
                _check_kind(port.kind, port.type)
        return values


class ProjectSpec(_Strict):
    version: Literal[1] = PROJECT_VERSION
    targets: List[TargetSpec] = Field(default_factory=list, max_items=100)
    dummies: List[DummySpec] = Field(default_factory=list, max_items=100)
    transforms: List[TransformSpec] = Field(default_factory=list, max_items=100)
    functions: List[FunctionSpec] = Field(default_factory=list, max_items=100)
    watch_topics: List[constr(min_length=1, max_length=256)] = Field(default_factory=list,
                                                                     max_items=200)

    @root_validator(skip_on_failure=True)
    def _unique_ids(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        seen = set()
        for item in [*values.get('targets', []), *values.get('dummies', []),
                     *values.get('transforms', []), *values.get('functions', [])]:
            if item.id in seen:
                raise ValueError(f'duplicate id {item.id!r} (ids must be unique across '
                                 'targets, dummies, transforms and functions)')
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
