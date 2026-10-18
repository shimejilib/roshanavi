"""Scenario file schema (docs/design/scenarios.md): pydantic models + a loader with line numbers.

A scenario is YAML::

    version: 1
    name: state_machine
    setup:  [{run: {...}, wait_for_node: /sm}]
    guards: [{never: {topic: /state, where: [...]}}]
    steps:  [{send: {...}}, {expect: {...}}, {wait: 1.0}, {stop: cam}]

Each step / guard / setup item is a mapping with exactly one kind key. Unknown
keys are rejected. Errors carry the path (``steps.1.expect.within``) and the
line of the offending YAML node, with the message in plain Japanese.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Type, Union

import yaml

from ..launcher.schema import (ClassSpec, DummySpec, FunctionSpec, ID_PATTERN, KindName,
                               METHOD_PATTERN, ParamValue, QosSpec, TransformSpec)
from ..media.options import MediaOptions
from ..pydantic_compat import (BaseModel, Field, StrictAliasModel, StrictBool, StrictFloat,
                               StrictInt, StrictStr, ValidationError, checked_type, confloat,
                               conint, constr, root_validator, validation_errors, validator)

SCENARIO_VERSION = 1
MAX_SCENARIO_BYTES = 512 * 1024
MAX_STEPS = 500
MAX_WHERE = 32
MAX_SECONDS = 3600.0
MAX_REGEX_LEN = 500
FIELD_PATH_RE = r'^[A-Za-z][A-Za-z0-9_]*(\.([A-Za-z][A-Za-z0-9_]*|\d{1,7}))*\Z'
TOPIC_RE = re.compile(r'^/[A-Za-z0-9_/]*\Z')
STEP_ID_RE = r'^[A-Za-z0-9_/][A-Za-z0-9_/.-]{0,127}\Z'

OPS = ('eq', 'ne', 'lt', 'le', 'gt', 'ge', 'range', 'approx', 'regex', 'contains', 'exists',
       'len_eq', 'len_range')
Scalar = Union[StrictBool, StrictInt, StrictFloat, StrictStr]
Seconds = confloat(gt=0, le=MAX_SECONDS)


class ScenarioSchemaError(ValueError):
    """Invalid scenario file. ``errors``: ``[{path, line, message}]`` (line may be None)."""

    def __init__(self, source: str, errors: List[Dict[str, Any]]):
        self.source = source
        self.errors = errors
        self.code = 'invalid_scenario'
        parts = []
        for err in errors:
            where = f' ({err["line"]} 行目)' if err.get('line') else ''
            parts.append(f'{err["path"] or "(全体)"}{where}: {err["message"]}')
        super().__init__(f'{source}: ' + '; '.join(parts))


class _Strict(StrictAliasModel):
    pass


def check_topic(value: str) -> str:
    """Absolute ROS topic names only (``/a/b``); validated with rclpy's own rules."""
    if not isinstance(value, str) or not TOPIC_RE.match(value) or '//' in value \
            or (len(value) > 1 and value.endswith('/')) or len(value) > 256:
        raise ValueError(f'チャンネル (トピック) の名前は /my_topic のような絶対名にしてください: {value!r}')
    from rclpy.exceptions import InvalidTopicNameException
    from rclpy.validate_full_topic_name import validate_full_topic_name
    try:
        validate_full_topic_name(value)
    except InvalidTopicNameException as exc:
        raise ValueError(f'チャンネル (トピック) の名前が不正です: {value!r} ({exc})') from exc
    return value


# A topic name inside a list (each item checked; the error points at the item)
TopicName = checked_type(check_topic, 'TopicName')


# ---- where conditions --------------------------------------------------------------------

class Condition(_Strict):
    field: constr(regex=FIELD_PATH_RE, max_length=256)
    op: Literal[OPS]  # type: ignore[valid-type]
    value: Any = None
    tol: Optional[confloat(ge=0)] = None
    min: Optional[Union[StrictInt, StrictFloat]] = None
    max: Optional[Union[StrictInt, StrictFloat]] = None

    @root_validator(skip_on_failure=True)
    def _operands(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        op, value = values['op'], values.get('value')
        lo, hi = values.get('min'), values.get('max')
        if op in ('eq', 'ne', 'contains') and value is None:
            raise ValueError(f'op "{op}" には value が必要です')
        if op in ('lt', 'le', 'gt', 'ge', 'approx') and not _is_number(value):
            raise ValueError(f'op "{op}" の value は数値にしてください')
        if op == 'len_eq' and (not isinstance(value, int) or isinstance(value, bool)
                               or value < 0):
            raise ValueError('op "len_eq" の value は 0 以上の整数にしてください')
        if op in ('range', 'len_range'):
            if lo is None and hi is None:
                raise ValueError(f'op "{op}" には min か max (または両方) が必要です')
            if lo is not None and hi is not None and lo > hi:
                raise ValueError('min が max より大きくなっています')
        if op == 'regex':
            if not isinstance(value, str) or len(value) > MAX_REGEX_LEN:
                raise ValueError(f'op "regex" の value は {MAX_REGEX_LEN} 文字までの文字列にしてください')
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f'正規表現が不正です: {exc}') from exc
        if op not in ('range', 'len_range') and (lo is not None or hi is not None):
            raise ValueError(f'min / max は range と len_range だけで使えます (op "{op}")')
        if op != 'approx' and values.get('tol') is not None:
            raise ValueError('tol は approx だけで使えます')
        return values


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class _TopicCheck(_Strict):
    topic: str
    type: Optional[constr(max_length=256)] = None
    kind: Optional[KindName] = None
    label: Optional[constr(max_length=200)] = None

    _topic = validator('topic', allow_reuse=True)(check_topic)


def _limit_where(value: List[Condition]) -> List[Condition]:
    if len(value) > MAX_WHERE:
        raise ValueError(f'where の条件は {MAX_WHERE} 個までです')
    return value


# ---- steps --------------------------------------------------------------------------------

class _Payload(_Strict):
    """``data`` = message fields (``${...}`` allowed); ``value`` = a value of ``kind``."""

    topic: str
    type: Optional[constr(max_length=256)] = None
    kind: Optional[KindName] = None
    data: Any = None
    value: Any = None
    qos: Optional[QosSpec] = None
    label: Optional[constr(max_length=200)] = None

    _topic = validator('topic', allow_reuse=True)(check_topic)

    @root_validator(skip_on_failure=True)
    def _payload(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get('data') is not None and values.get('value') is not None:
            raise ValueError('data (メッセージのフィールド) と value (データの種類の値) は片方だけにしてください')
        if values.get('value') is not None and not values.get('kind'):
            raise ValueError('value を使うときは kind (データの種類) も書いてください')
        if values.get('kind') in ('image', 'audio') and values.get('value') is not None:
            raise ValueError('画像・音声は start の media (data ディレクトリのファイル) で送ってください')
        data = values.get('data')
        if data is not None and not isinstance(data, dict):
            raise ValueError('data はメッセージのフィールドの対応 ({data: ...} など) にしてください')
        return values


class SendStep(_Payload):
    pass


class MediaStart(MediaOptions):
    source: constr(min_length=1, max_length=1024)


class StartStep(_Strict):
    id: Optional[constr(regex=STEP_ID_RE)] = None
    target: Optional[constr(regex=ID_PATTERN)] = None
    topic: Optional[str] = None
    type: Optional[constr(max_length=256)] = None
    kind: Optional[KindName] = None
    data: Any = None
    value: Any = None
    rate_hz: Optional[confloat(gt=0, le=1000)] = None
    count: Optional[conint(ge=1, le=10_000_000)] = None
    stream: Optional[constr(min_length=1, max_length=1024)] = None
    loop: bool = False
    media: Optional[MediaStart] = None
    qos: Optional[QosSpec] = None
    label: Optional[constr(max_length=200)] = None

    @validator('topic')
    def _topic(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else check_topic(value)

    @root_validator(skip_on_failure=True)
    def _shape(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get('target'):
            extra = [k for k in ('topic', 'type', 'kind', 'data', 'value', 'rate_hz', 'count',
                                 'stream', 'media', 'qos') if values.get(k) is not None]
            if extra:
                raise ValueError(f'target (起動設定のノード) と一緒には使えません: {", ".join(extra)}')
            values['id'] = values.get('id') or values['target']
            return values
        if not values.get('topic'):
            raise ValueError('topic (送り先) か target (起動するノードの ID) が必要です')
        values['id'] = values.get('id') or values['topic']
        sources = [k for k in ('stream', 'media') if values.get(k) is not None]
        if len(sources) > 1:
            raise ValueError('stream と media は片方だけにしてください')
        if values.get('media') is not None:
            return values
        if values.get('rate_hz') is None:
            raise ValueError('周期送信 (start) には rate_hz (Hz) が必要です')
        if values.get('data') is not None and values.get('value') is not None:
            raise ValueError('data と value は片方だけにしてください')
        if values.get('value') is not None and not values.get('kind'):
            raise ValueError('value を使うときは kind (データの種類) も書いてください')
        if values.get('data') is not None and not isinstance(values['data'], dict):
            raise ValueError('data はメッセージのフィールドの対応にしてください')
        return values


class StopStep(_Strict):
    """``stop: <id>`` stops what an earlier start / play began; ``stop: {target: <id>}``
    stops a project target (input / function node ...) even if the scenario did not start it."""

    id: Optional[constr(regex=STEP_ID_RE)] = None
    target: Optional[constr(regex=ID_PATTERN)] = None
    label: Optional[constr(max_length=200)] = None

    @root_validator(skip_on_failure=True)
    def _one(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if (values.get('id') is None) == (values.get('target') is None):
            raise ValueError('stop には id (start / play の id) か target (起動設定の ID) の'
                             'どちらか 1 つを書いてください')
        return values


class PlayStep(_Strict):
    id: Optional[constr(regex=STEP_ID_RE)] = None
    bag: constr(min_length=1, max_length=1024)
    topics: List[TopicName] = Field(default_factory=list, max_items=100)
    rate: confloat(gt=0, le=100) = 1.0
    loop: bool = False
    wait: bool = False
    timeout: Seconds = 600.0  # type: ignore[valid-type]
    label: Optional[constr(max_length=200)] = None

    @root_validator(skip_on_failure=True)
    def _id(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        values['id'] = values.get('id') or 'bag'
        if values.get('wait') and values.get('loop'):
            raise ValueError('loop: true の再生は終わらないので wait: true にできません')
        return values


class WaitStep(_Strict):
    seconds: Seconds  # type: ignore[valid-type]
    label: Optional[constr(max_length=200)] = None


class ExpectStep(_TopicCheck):
    within: Seconds  # type: ignore[valid-type]
    count: conint(ge=1, le=100000) = 1
    where: List[Condition] = Field(default_factory=list)

    _where = validator('where', allow_reuse=True)(_limit_where)


class AlwaysStep(_TopicCheck):
    for_: Seconds = Field(..., alias='for')  # type: ignore[valid-type]
    where: List[Condition] = Field(default_factory=list)
    min_count: conint(ge=0, le=100000) = 1

    _where = validator('where', allow_reuse=True)(_limit_where)


class NeverStep(_TopicCheck):
    for_: Seconds = Field(..., alias='for')  # type: ignore[valid-type]
    where: List[Condition] = Field(default_factory=list)

    _where = validator('where', allow_reuse=True)(_limit_where)


class RateStep(_TopicCheck):
    for_: Seconds = Field(..., alias='for')  # type: ignore[valid-type]
    min_hz: Optional[confloat(ge=0)] = None
    max_hz: Optional[confloat(gt=0)] = None

    @root_validator(skip_on_failure=True)
    def _bounds(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        lo, hi = values.get('min_hz'), values.get('max_hz')
        if lo is None and hi is None:
            raise ValueError('min_hz か max_hz (または両方) が必要です')
        if lo is not None and hi is not None and lo > hi:
            raise ValueError('min_hz が max_hz より大きくなっています')
        return values


class _Pair(_Strict):
    input: str
    output: str
    for_: Seconds = Field(5.0, alias='for')  # type: ignore[valid-type]
    label: Optional[constr(max_length=200)] = None

    _input = validator('input', allow_reuse=True)(check_topic)
    _output = validator('output', allow_reuse=True)(check_topic)


class ThroughputStep(_Pair):
    min_ratio: confloat(gt=0, le=100)
    max_ratio: Optional[confloat(gt=0, le=100)] = None


class LatencyStep(_Pair):
    match: Literal['header.stamp', 'order'] = 'header.stamp'
    p50_ms: Optional[confloat(gt=0)] = None
    p95_ms: Optional[confloat(gt=0)] = None
    max_ms: Optional[confloat(gt=0)] = None
    min_samples: conint(ge=1, le=100000) = 3

    @root_validator(skip_on_failure=True)
    def _limits(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if all(values.get(k) is None for k in ('p50_ms', 'p95_ms', 'max_ms')):
            raise ValueError('p50_ms / p95_ms / max_ms のどれかで上限を決めてください')
        return values


NODE_NAME_RE = re.compile(r'^/?[A-Za-z_~][A-Za-z0-9_/]*\Z')
MIN_GROWTH_SEC = 10.0


def check_node(value: str) -> str:
    """A node name, absolute (``/ns/name``) or relative to ``/`` (``name``)."""
    if not isinstance(value, str) or not NODE_NAME_RE.match(value) or '//' in value \
            or len(value) > 256 or (len(value) > 1 and value.endswith('/')):
        raise ValueError(f'ノード名は /my_node のように書いてください: {value!r}')
    return value if value.startswith('/') else '/' + value


class ResourcesStep(_Strict):
    """CPU (average over ``for``, 100 = one core) and memory (peak RSS) of one node."""
    node: str
    cpu_max: Optional[confloat(gt=0, le=100000)] = None
    mem_max_mb: Optional[confloat(gt=0, le=10_000_000)] = None
    for_: Seconds = Field(5.0, alias='for')  # type: ignore[valid-type]
    label: Optional[constr(max_length=200)] = None

    _node = validator('node', allow_reuse=True)(check_node)

    @root_validator(skip_on_failure=True)
    def _limits(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get('cpu_max') is None and values.get('mem_max_mb') is None:
            raise ValueError('cpu_max か mem_max_mb (または両方) が必要です')
        return values


class MemGrowthStep(_Strict):
    """Memory growth (least-squares slope of RSS, MB/min) of one node over ``for``."""
    node: str
    max_mb_per_min: confloat(ge=0, le=1_000_000)
    for_: Seconds = Field(..., alias='for')  # type: ignore[valid-type]
    label: Optional[constr(max_length=200)] = None

    _node = validator('node', allow_reuse=True)(check_node)

    @validator('for_')
    def _long_enough(cls, value: float) -> float:
        if value < MIN_GROWTH_SEC:
            raise ValueError(f'増え方を測るには for を {MIN_GROWTH_SEC:g} 秒以上にしてください')
        return value


class CallStep(_Strict):
    """``call: {node, method}``: call an action method of a class node (docs/design/nodes.md).

    Publishes ``std_msgs/Empty`` on ``<node>/<method>`` and waits until the node reports the
    call (its status), so the next step sees the effect."""

    node: str
    method: constr(regex=METHOD_PATTERN)
    timeout: Seconds = 5.0  # type: ignore[valid-type]
    label: Optional[constr(max_length=200)] = None

    _node = validator('node', allow_reuse=True)(check_node)


STEP_MODELS: Dict[str, Type[BaseModel]] = {
    'send': SendStep, 'start': StartStep, 'stop': StopStep, 'play': PlayStep, 'wait': WaitStep,
    'expect': ExpectStep, 'always': AlwaysStep, 'never': NeverStep, 'rate': RateStep,
    'throughput': ThroughputStep, 'latency': LatencyStep, 'resources': ResourcesStep,
    'mem_growth': MemGrowthStep, 'call': CallStep,
}
INPUT_STEPS = ('send', 'start', 'stop', 'play', 'call')
CHECK_STEPS = ('expect', 'always', 'never', 'rate', 'throughput', 'latency', 'resources',
               'mem_growth')
RESOURCE_STEPS = ('resources', 'mem_growth')  # read a node's process, not topics


# ---- guards / setup -------------------------------------------------------------------------

class AlwaysGuard(_TopicCheck):
    where: List[Condition]
    _where = validator('where', allow_reuse=True)(_limit_where)


class NeverGuard(_TopicCheck):
    where: List[Condition] = Field(default_factory=list)
    _where = validator('where', allow_reuse=True)(_limit_where)


GUARD_MODELS: Dict[str, Type[BaseModel]] = {'always': AlwaysGuard, 'never': NeverGuard}


class RunSetup(_Strict):
    package: constr(min_length=1, max_length=100)
    executable: constr(min_length=1, max_length=128)
    name: Optional[constr(max_length=256)] = None
    namespace: Optional[constr(max_length=256)] = None
    params: Dict[constr(max_length=200), ParamValue] = Field(default_factory=dict)
    remaps: Dict[constr(max_length=256), constr(max_length=256)] = Field(default_factory=dict)
    args: List[constr(max_length=4096)] = Field(default_factory=list, max_items=64)


class LaunchSetup(_Strict):
    package: constr(min_length=1, max_length=100)
    file: constr(min_length=1, max_length=128)
    args: Dict[constr(max_length=100), Scalar] = Field(default_factory=dict)


SETUP_KINDS = ('run', 'launch', 'cmd', 'target', 'function', 'class', 'transform', 'dummy')


def setup_field(kind: str) -> str:
    return 'class_' if kind == 'class' else kind   # ``class`` is a Python keyword


class SetupItem(_Strict):
    run: Optional[RunSetup] = None
    launch: Optional[LaunchSetup] = None
    cmd: Optional[List[constr(max_length=4096)]] = Field(None, max_items=100)
    target: Optional[constr(regex=ID_PATTERN)] = None
    function: Optional[Dict[str, Any]] = None
    class_: Optional[Dict[str, Any]] = Field(None, alias='class')
    transform: Optional[Dict[str, Any]] = None
    dummy: Optional[Dict[str, Any]] = None
    wait_for_node: List[constr(min_length=1, max_length=256)] = Field(default_factory=list,
                                                                      max_items=32)
    wait_timeout: Seconds = 15.0  # type: ignore[valid-type]
    label: Optional[constr(max_length=200)] = None

    @validator('wait_for_node', pre=True)
    def _nodes(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value

    @root_validator(skip_on_failure=True)
    def _one_kind(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        kinds = [k for k in SETUP_KINDS if values.get(setup_field(k)) is not None]
        if len(kinds) != 1:
            raise ValueError(f'setup の各項目には {", ".join(SETUP_KINDS)} のどれか 1 つを書いてください'
                             f' (今: {", ".join(kinds) or "なし"})')
        return values

    @property
    def kind(self) -> str:
        return next(k for k in SETUP_KINDS if getattr(self, setup_field(k)) is not None)


NODE_SPECS: Dict[str, Type[BaseModel]] = {'function': FunctionSpec, 'class': ClassSpec,
                                          'transform': TransformSpec,
                                          'dummy': DummySpec}


class _Top(_Strict):
    version: Literal[1] = SCENARIO_VERSION
    name: constr(min_length=1, max_length=128)
    description: Optional[constr(max_length=4000)] = None
    setup: List[Any] = Field(default_factory=list, max_items=32)
    guards: List[Any] = Field(default_factory=list, max_items=32)
    steps: List[Any] = Field(..., min_items=1, max_items=MAX_STEPS)


# ---- parsed result ------------------------------------------------------------------------

@dataclass(frozen=True)
class StepEntry:
    kind: str
    spec: Any
    line: Optional[int] = field(default=None, compare=False)


@dataclass(frozen=True)
class SetupEntry:
    item: SetupItem
    node_spec: Any = None  # FunctionSpec / TransformSpec / DummySpec for those kinds
    line: Optional[int] = field(default=None, compare=False)


@dataclass(frozen=True)
class Scenario:
    name: str
    version: int = SCENARIO_VERSION
    description: Optional[str] = None
    setup: Tuple[SetupEntry, ...] = ()
    guards: Tuple[StepEntry, ...] = ()
    steps: Tuple[StepEntry, ...] = ()
    source: str = 'scenario'
    raw: Dict[str, Any] = field(default_factory=dict, compare=False)

    def topics(self) -> List[str]:
        """Every topic that a check or guard reads (pre-subscribed at start)."""
        found: List[str] = []
        for entry in (*self.guards, *self.steps):
            for topic in check_topics(entry):
                if topic not in found:
                    found.append(topic)
        return found


def check_topics(entry: StepEntry) -> List[str]:
    spec = entry.spec
    if entry.kind in ('throughput', 'latency'):
        return [spec.input, spec.output]
    if entry.kind in RESOURCE_STEPS:
        return []
    if entry.kind in CHECK_STEPS or isinstance(spec, (AlwaysGuard, NeverGuard)):
        return [spec.topic]
    return []


# ---- YAML with positions --------------------------------------------------------------------

Path = Tuple[Union[str, int], ...]


def _line_of(node: Optional[yaml.Node], path: Path) -> Optional[int]:
    """Line (1-based) of the deepest YAML node along ``path``."""
    if node is None:
        return None
    best = node.start_mark.line + 1
    current = node
    for part in path:
        nxt = None
        if isinstance(current, yaml.MappingNode):
            for key, value in current.value:
                if getattr(key, 'value', None) == str(part):
                    nxt, best = value, key.start_mark.line + 1
                    break
        elif isinstance(current, yaml.SequenceNode) and isinstance(part, int) \
                and 0 <= part < len(current.value):
            nxt = current.value[part]
            best = nxt.start_mark.line + 1
        if nxt is None:
            break
        current = nxt
    return best


_MESSAGES = {
    'value_error.extra': '使えないキーです (書き間違いがないか確認してください)',
    'value_error.missing': '必須の項目がありません',
    'type_error.float': '数値にしてください',
    'type_error.integer': '整数にしてください',
    'type_error.str': '文字列にしてください',
    'type_error.bool': 'true か false にしてください',
    'type_error.list': '配列 ([...] や - の並び) にしてください',
    'type_error.dict': '対応 ({key: value}) にしてください',
    'value_error.number.not_gt': '{limit_value} より大きい数にしてください',
    'value_error.number.not_ge': '{limit_value} 以上にしてください',
    'value_error.number.not_le': '{limit_value} 以下にしてください',
    'value_error.number.not_lt': '{limit_value} 未満にしてください',
    'value_error.const': '{given} は使えません (使えるのは {permitted})',
    'value_error.str.regex': '形式が正しくありません',
    'value_error.any_str.max_length': '{limit_value} 文字までにしてください',
    'value_error.any_str.min_length': '空にできません',
    'value_error.list.max_items': '{limit_value} 個までにしてください',
    'value_error.list.min_items': '{limit_value} 個以上必要です',
}


def _message(err: Dict[str, Any]) -> str:
    template = _MESSAGES.get(err.get('type', ''))
    if template is None:
        return err['msg']
    ctx = {k: (', '.join(map(str, v)) if isinstance(v, (list, tuple)) else v)
           for k, v in (err.get('ctx') or {}).items()}
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        return err['msg']


class _Collector:
    def __init__(self, root: Optional[yaml.Node]):
        self.root = root
        self.errors: List[Dict[str, Any]] = []

    def add(self, path: Path, message: str) -> None:
        self.errors.append({'path': '.'.join(str(p) for p in path),
                            'line': _line_of(self.root, path), 'message': message})

    def from_validation(self, prefix: Path, exc: ValidationError) -> None:
        for err in validation_errors(exc):
            loc = tuple(p for p in err['loc'] if p != '__root__')
            self.add(prefix + loc, _message(err))

    def line(self, path: Path) -> Optional[int]:
        return _line_of(self.root, path)


def _single_key(col: _Collector, path: Path, item: Any, kinds: Sequence[str],
                what: str) -> Optional[Tuple[str, Any]]:
    if not isinstance(item, dict) or len(item) != 1:
        col.add(path, f'{what}は「種類: 内容」の 1 つのキーにしてください (使える種類: {", ".join(kinds)})')
        return None
    kind, body = next(iter(item.items()))
    if kind not in kinds:
        col.add(path + (str(kind),), f'{what}の種類 {kind!r} はありません (使える種類: {", ".join(kinds)})')
        return None
    return str(kind), body


def _step_body(kind: str, body: Any) -> Any:
    if kind == 'wait' and not isinstance(body, dict):
        return {'seconds': body}
    if kind == 'stop' and isinstance(body, str):
        return {'id': body}
    return {} if body is None else body


def _parse_steps(col: _Collector, items: List[Any]) -> List[StepEntry]:
    steps: List[StepEntry] = []
    started: Dict[str, int] = {}
    for i, item in enumerate(items):
        found = _single_key(col, ('steps', i), item, tuple(STEP_MODELS), 'ステップ')
        if found is None:
            continue
        kind, body = found
        try:
            spec = STEP_MODELS[kind].model_validate(_step_body(kind, body))
        except ValidationError as exc:
            col.from_validation(('steps', i, kind), exc)
            continue
        if kind in ('start', 'play'):
            if spec.id in started:
                col.add(('steps', i, kind, 'id'),
                        f'id {spec.id!r} は {started[spec.id] + 1} 番目のステップでも使っています '
                        '(止める前に同じ id で始め直せません)')
            started[spec.id] = i
        if kind == 'stop' and spec.id is not None:
            if spec.id not in started:
                col.add(('steps', i, kind), f'stop {spec.id!r}: それより前の start / play にこの id がありません')
            started.pop(spec.id, None)
        steps.append(StepEntry(kind, spec, col.line(('steps', i))))
    return steps


def _parse_guards(col: _Collector, items: List[Any]) -> List[StepEntry]:
    guards = []
    for i, item in enumerate(items):
        found = _single_key(col, ('guards', i), item, tuple(GUARD_MODELS), 'ガード')
        if found is None:
            continue
        kind, body = found
        try:
            guards.append(StepEntry(kind, GUARD_MODELS[kind].model_validate(body or {}),
                                    col.line(('guards', i))))
        except ValidationError as exc:
            col.from_validation(('guards', i, kind), exc)
    return guards


def _parse_setup(col: _Collector, items: List[Any]) -> List[SetupEntry]:
    entries = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            col.add(('setup', i), f'setup の各項目は対応にしてください (例: {{run: {{package: ..., '
                    'executable: ...}}}})')
            continue
        try:
            setup = SetupItem.model_validate(item)
        except ValidationError as exc:
            col.from_validation(('setup', i), exc)
            continue
        node_spec = None
        if setup.kind in NODE_SPECS:
            body = dict(getattr(setup, setup_field(setup.kind)))
            body.setdefault('name', f'scenario_{setup.kind}_{i}')
            body.pop('autostart', None)
            try:
                node_spec = NODE_SPECS[setup.kind].model_validate(
                    {**body, 'id': f'scn-{setup.kind}-{i}'})
            except ValidationError as exc:
                col.from_validation(('setup', i, setup.kind), exc)
                continue
        entries.append(SetupEntry(setup, node_spec, col.line(('setup', i))))
    return entries


def parse_data(raw: Any, source: str = 'scenario',
               root: Optional[yaml.Node] = None) -> Scenario:
    """Validate already-loaded data (from YAML or the API's JSON)."""
    col = _Collector(root)
    if not isinstance(raw, dict):
        col.add((), 'シナリオの一番外側は対応 (name: ... / steps: ...) にしてください')
        raise ScenarioSchemaError(source, col.errors)
    try:
        top = _Top.model_validate(raw)
    except ValidationError as exc:
        col.from_validation((), exc)
        raise ScenarioSchemaError(source, col.errors) from exc
    setup = _parse_setup(col, top.setup)
    guards = _parse_guards(col, top.guards)
    steps = _parse_steps(col, top.steps)
    if col.errors:
        raise ScenarioSchemaError(source, col.errors)
    return Scenario(name=top.name, version=top.version, description=top.description,
                    setup=tuple(setup), guards=tuple(guards), steps=tuple(steps), source=source,
                    raw=raw)


def parse_text(text: str, source: str = 'scenario') -> Scenario:
    """Parse YAML text; errors carry line numbers."""
    if len(text.encode('utf-8')) > MAX_SCENARIO_BYTES:
        raise ScenarioSchemaError(source, [{'path': '', 'line': None,
                                            'message': f'{MAX_SCENARIO_BYTES // 1024} KB を超えています'}])
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, 'problem_mark', None)
        problem = getattr(exc, 'problem', None) or str(exc)
        raise ScenarioSchemaError(source, [{
            'path': '', 'line': mark.line + 1 if mark else None,
            'message': f'YAML の書き方が正しくありません ({problem}'
                       + (f', {mark.column + 1} 文字目)' if mark else ')')}]) from exc
    return parse_data(raw, source, root)


def load_file(path: str) -> Scenario:
    import os
    try:
        if os.path.getsize(path) > MAX_SCENARIO_BYTES:
            raise ScenarioSchemaError(os.path.basename(path), [{
                'path': '', 'line': None, 'message': f'{MAX_SCENARIO_BYTES // 1024} KB を超えています'}])
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    except OSError as exc:
        raise ScenarioSchemaError(os.path.basename(path), [{
            'path': '', 'line': None, 'message': f'ファイルを読めません: {exc}'}]) from exc
    return parse_text(text, os.path.basename(path))


# ---- canonical dump (UI saves) ----------------------------------------------------------------

def _clean(model: BaseModel) -> Dict[str, Any]:
    return model.model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)


def _keep(model: BaseModel, *keys: str) -> Dict[str, Any]:
    """Like :func:`_clean` but always writes ``keys`` (e.g. a default ``for``)."""
    out = _clean(model)
    full = model.model_dump(by_alias=True)
    for key in keys:
        if full.get(key) is not None:
            out[key] = full[key]
    return out


def step_to_raw(entry: StepEntry) -> Dict[str, Any]:
    spec = entry.spec
    if entry.kind == 'wait' and spec.label is None:
        return {'wait': spec.seconds}
    if entry.kind == 'stop' and spec.label is None and spec.id is not None:
        return {'stop': spec.id}
    if entry.kind in ('throughput', 'latency'):
        return {entry.kind: _keep(spec, 'input', 'output', 'for')}
    if entry.kind in RESOURCE_STEPS:
        return {entry.kind: _keep(spec, 'node', 'for')}
    if entry.kind == 'start':
        body = _keep(spec, 'id')
        if body.get('id') in (spec.target, spec.topic):
            body.pop('id')
        return {'start': body}
    if entry.kind == 'play':
        return {'play': _keep(spec, 'bag')}
    return {entry.kind: _clean(spec)}


def to_raw(scenario: Scenario) -> Dict[str, Any]:
    out: Dict[str, Any] = {'version': scenario.version, 'name': scenario.name}
    if scenario.description:
        out['description'] = scenario.description
    if scenario.setup:
        out['setup'] = [e.item.model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)
                        for e in scenario.setup]
    if scenario.guards:
        out['guards'] = [{g.kind: _clean(g.spec)} for g in scenario.guards]
    out['steps'] = [step_to_raw(s) for s in scenario.steps]
    return out


HEADER = ('# roshanavi のシナリオ (docs/design/scenarios.md)。Scenarios タブか\n'
          '# `ros2 run roshanavi scenario run <このファイル>` で実行できます。\n')


def dump(scenario: Scenario) -> str:
    return HEADER + yaml.safe_dump(to_raw(scenario), sort_keys=False, allow_unicode=True,
                                   default_flow_style=None, width=100)
