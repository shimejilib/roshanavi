"""Pydantic (v1) models shared by the REST API and the ``roshanavi.yaml`` project file.

These check *shape* (types, unknown keys, id format). Values that need the
workspace (package/executable exist, paths contained) are checked by
:mod:`.command` when a target is registered or started.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import (BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr,
                      confloat, conint, constr, root_validator)

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
    mode: Literal['once', 'periodic', 'stream']
    payload: Optional[Dict[str, Any]] = None
    rate_hz: Optional[confloat(gt=0, le=1000)] = None
    count: Optional[conint(ge=1, le=10_000_000)] = None
    source: Optional[constr(max_length=1024)] = None
    loop: bool = False
    qos: QosSpec = Field(default_factory=QosSpec)
    autostart: bool = False
    auto_restart: bool = False

    @root_validator(skip_on_failure=True)
    def _mode_fields(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        mode = values['mode']
        if mode != 'once' and values.get('rate_hz') is None:
            raise ValueError(f'mode "{mode}" needs "rate_hz"')
        if mode == 'stream' and not values.get('source'):
            raise ValueError('mode "stream" needs "source" (a file in the data dir)')
        return values


class ProjectSpec(_Strict):
    version: Literal[1] = PROJECT_VERSION
    targets: List[TargetSpec] = Field(default_factory=list, max_items=100)
    dummies: List[DummySpec] = Field(default_factory=list, max_items=100)
    watch_topics: List[constr(min_length=1, max_length=256)] = Field(default_factory=list,
                                                                     max_items=200)

    @root_validator(skip_on_failure=True)
    def _unique_ids(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        seen = set()
        for item in [*values.get('targets', []), *values.get('dummies', [])]:
            if item.id in seen:
                raise ValueError(f'duplicate id {item.id!r} (ids must be unique across '
                                 'targets and dummies)')
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
