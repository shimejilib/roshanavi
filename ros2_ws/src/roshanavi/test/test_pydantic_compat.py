"""pydantic_compat: one model vocabulary and v1-shaped errors on pydantic 1.10 and 2.x.

The expected values are what pydantic 1.10 (Jazzy) reports; the same test runs on Lyrical's
pydantic 2, so error messages and envelopes stay identical across distros.
"""

from typing import Any, Dict, List, Literal, Optional, Union

import pytest

from roshanavi.pydantic_compat import (CompatModel, Field, StrictAliasModel, StrictBool,
                                       StrictFloat, StrictInt, StrictModel, StrictStr,
                                       ValidationError, checked_type, confloat, conint, constr,
                                       root_validator, validation_errors, validator)


def _no_upper(value: Any) -> Any:
    if not isinstance(value, str) or value != value.lower():
        raise ValueError(f'lower case only: {value!r}')
    return value


Lower = checked_type(_no_upper, 'Lower')


class Sub(CompatModel):
    x: int


class Other(StrictModel):
    kind: Literal['other']


class Model(StrictModel):
    req: int
    i: conint(ge=1, le=10) = 1
    g: conint(gt=0, lt=5) = 1
    f: confloat(gt=0, le=3.5) = 1.0
    s: constr(min_length=1, max_length=3) = 'a'
    p: constr(regex=r'^[a-z]+$') = 'a'
    b: bool = False
    si: StrictInt = 1
    sf: StrictFloat = 1.0
    ss: StrictStr = 'a'
    u: Union[StrictBool, StrictInt, StrictFloat, StrictStr] = 1
    lit: Literal['eq', 'ne'] = 'eq'
    l: List[int] = Field(default_factory=list, max_items=2)
    l2: List[int] = Field(default_factory=list, min_items=1)
    d: Dict[str, int] = {}
    sub: Optional[Sub] = None
    lower: List[Lower] = Field(default_factory=list)
    name: Optional[str] = None


CASES = [
    ({'i': 0}, [(('i',), 'value_error.number.not_ge',
                 'ensure this value is greater than or equal to 1', {'limit_value': 1})]),
    ({'i': 11}, [(('i',), 'value_error.number.not_le',
                  'ensure this value is less than or equal to 10', {'limit_value': 10})]),
    ({'g': 0}, [(('g',), 'value_error.number.not_gt', 'ensure this value is greater than 0',
                 {'limit_value': 0})]),
    ({'g': 5}, [(('g',), 'value_error.number.not_lt', 'ensure this value is less than 5',
                 {'limit_value': 5})]),
    ({'f': 0}, [(('f',), 'value_error.number.not_gt', 'ensure this value is greater than 0',
                 {'limit_value': 0})]),
    ({'f': 4}, [(('f',), 'value_error.number.not_le',
                 'ensure this value is less than or equal to 3.5', {'limit_value': 3.5})]),
    ({'i': 'x'}, [(('i',), 'type_error.integer', 'value is not a valid integer', None)]),
    ({'f': 'x'}, [(('f',), 'type_error.float', 'value is not a valid float', None)]),
    ({'s': ''}, [(('s',), 'value_error.any_str.min_length',
                  'ensure this value has at least 1 characters', {'limit_value': 1})]),
    ({'s': 'abcd'}, [(('s',), 'value_error.any_str.max_length',
                      'ensure this value has at most 3 characters', {'limit_value': 3})]),
    ({'s': [1]}, [(('s',), 'type_error.str', 'str type expected', None)]),
    ({'p': 'A'}, [(('p',), 'value_error.str.regex', 'string does not match regex "^[a-z]+$"',
                   {'pattern': '^[a-z]+$'})]),
    ({'b': 'maybe'}, [(('b',), 'type_error.bool', 'value could not be parsed to a boolean',
                       None)]),
    ({'si': '1'}, [(('si',), 'type_error.integer', 'value is not a valid integer', None)]),
    ({'sf': '1'}, [(('sf',), 'type_error.float', 'value is not a valid float', None)]),
    ({'ss': 1}, [(('ss',), 'type_error.str', 'str type expected', None)]),
    ({'lit': 'zz'}, [(('lit',), 'value_error.const', "unexpected value; permitted: 'eq', 'ne'",
                      {'given': 'zz', 'permitted': ('eq', 'ne')})]),
    ({'l': [1, 2, 3]}, [(('l',), 'value_error.list.max_items',
                         'ensure this value has at most 2 items', {'limit_value': 2})]),
    ({'l2': []}, [(('l2',), 'value_error.list.min_items',
                   'ensure this value has at least 1 items', {'limit_value': 1})]),
    ({'l': 'x'}, [(('l',), 'type_error.list', 'value is not a valid list', None)]),
    ({'d': 'x'}, [(('d',), 'type_error.dict', 'value is not a valid dict', None)]),
    ({'d': {'k': 'v'}}, [(('d', 'k'), 'type_error.integer', 'value is not a valid integer',
                          None)]),
    ({'sub': 3}, [(('sub',), 'type_error.dict', 'value is not a valid dict', None)]),
    ({'sub': {}}, [(('sub', 'x'), 'value_error.missing', 'field required', None)]),
    ({'zz': 1}, [(('zz',), 'value_error.extra', 'extra fields not permitted', None)]),
    ({'req': None}, [(('req',), 'type_error.none.not_allowed', 'none is not an allowed value',
                      None)]),
    ({'lower': ['ok', 'NO']}, [(('lower', 1), 'value_error', "lower case only: 'NO'", None)]),
]


def _shape(errors: List[Dict[str, Any]]) -> List[Any]:
    return [(e['loc'], e['type'], e['msg'], e.get('ctx')) for e in errors]


@pytest.mark.parametrize('data,expected', CASES)
def test_errors_have_the_v1_shape_and_wording(data, expected):
    with pytest.raises(ValidationError) as info:
        Model.model_validate({'req': 1, **data})
    assert _shape(validation_errors(info.value)) == expected


def test_missing_field():
    with pytest.raises(ValidationError) as info:
        Model.model_validate({})
    assert _shape(validation_errors(info.value)) == [
        (('req',), 'value_error.missing', 'field required', None)]


def test_union_errors_point_at_the_field_not_the_member():
    with pytest.raises(ValidationError) as info:
        Model.model_validate({'req': 1, 'u': [1]})
    errors = validation_errors(info.value)
    assert {e['loc'] for e in errors} == {('u',)}
    assert len(errors) == 4


def test_union_of_models_drops_the_member_name():
    class Holder(StrictModel):
        source: Union[Sub, Other]

    with pytest.raises(ValidationError) as info:
        Holder.model_validate({'source': {'kind': 'nope'}})
    locs = {e['loc'] for e in validation_errors(info.value)}
    assert locs <= {('source', 'x'), ('source', 'kind')}
    assert ('source', 'kind') in locs


def test_v1_semantics_kept():
    # str fields take numbers (YAML ``name: 123``); $ matches before a trailing newline (re)
    assert Model.model_validate({'req': 1, 'name': 123}).name == '123'
    assert Model.model_validate({'req': 1, 'p': 'abc\n'}).p == 'abc\n'
    assert Model.model_validate({'req': 1}).model_dump()['sub'] is None
    copy = Model.model_validate({'req': 1}).model_copy(update={'req': 2})
    assert copy.req == 2


class WithValidators(StrictAliasModel):
    topic: str
    for_: float = Field(1.0, alias='for')
    names: List[str] = Field(default_factory=list)
    filled: Optional[str] = None

    @validator('names', pre=True)
    def _one_or_many(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value

    @validator('topic')
    def _absolute(cls, value: str) -> str:
        if not value.startswith('/'):
            raise ValueError('topic must be absolute')
        return value

    @root_validator(skip_on_failure=True)
    def _fill(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values['for_'] > 10:
            raise ValueError('for is too long')
        values['filled'] = values.get('filled') or values['topic']
        return values


def test_validators_and_aliases():
    model = WithValidators.model_validate({'topic': '/a', 'for': 2, 'names': 'n'})
    assert (model.for_, model.names, model.filled) == (2.0, ['n'], '/a')
    assert WithValidators.model_validate({'topic': '/a', 'for_': 3}).for_ == 3.0
    assert model.model_dump(by_alias=True)['for'] == 2.0
    with pytest.raises(ValidationError) as info:
        WithValidators.model_validate({'topic': 'a'})
    assert _shape(validation_errors(info.value)) == [
        (('topic',), 'value_error', 'topic must be absolute', None)]
    with pytest.raises(ValidationError) as info:
        WithValidators.model_validate({'topic': '/a', 'for': 11})
    errors = validation_errors(info.value)
    assert [e['msg'] for e in errors] == ['for is too long']
    assert [p for p in errors[0]['loc'] if p != '__root__'] == []
