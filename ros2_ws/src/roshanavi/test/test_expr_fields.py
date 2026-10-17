"""Message field access in the safe evaluator (transform nodes) and its security boundary."""

import pytest

from roshanavi.expr import (MAX_STR_LEN, ExprError, Expression, PayloadTemplate,
                            validate_message_names)
from roshanavi.msg_view import MsgView, to_plain

MSG = {'data': 'hello', 'count': 3, 'ratio': 0.5, 'flag': True,
       'linear': {'x': 1.5, 'y': -2.0, 'z': 0.0},
       'header': {'stamp': {'sec': 10, 'nanosec': 20}, 'frame_id': 'map'},
       'values': [10, 20, 30], 'points': [{'x': 1}, {'x': 2}], 'text': '  Mixed Case  '}


def ev(source, msg=None, names=('msg',), **extra):
    env = {name: MsgView(dict(msg or MSG)) for name in names}
    return Expression(source, names).evaluate({**env, **extra})


@pytest.mark.parametrize('source,expected', [
    ('msg.data', 'hello'),
    ('upper(msg.data)', 'HELLO'),
    ('lower("AbC")', 'abc'),
    ('strip(msg.text)', 'Mixed Case'),
    ('replace(msg.data, "l", "L")', 'heLLo'),
    ('len(msg.data)', 5),
    ('len(msg.values)', 3),
    ('msg.values[0] + msg.values[-1]', 40),
    ('msg.values[msg.count - 1]', 30),
    ('msg.points[1].x', 2),
    ('msg.linear.x * 0.5', 0.75),
    ('clamp(msg.linear.y, -1, 1)', -1),
    ('clamp(5, 0, 10)', 5),
    ('int("12") + msg.count', 15),
    ('msg.data != "" and msg.flag', True),
    ('msg.header.frame_id + "_out"', 'map_out'),
    ('str(msg.count) + "x"', '3x'),
])
def test_field_access(source, expected):
    assert ev(source) == expected


def test_whole_message_and_struct_values_become_plain_data():
    tmpl = PayloadTemplate({'header': '${msg.header}', 'copy': '${msg.values}',
                            'text': 'n=${msg.count}'}, ['msg'])
    out = tmpl.render({'msg': MsgView(MSG)})
    assert out == {'header': MSG['header'], 'copy': [10, 20, 30], 'text': 'n=3'}
    assert to_plain(ev('msg')) == MSG


def test_now_stamp_is_a_time_struct():
    stamp = to_plain(ev('now_stamp()'))
    assert set(stamp) == {'sec', 'nanosec'} and stamp['sec'] > 1_600_000_000
    assert 0 <= stamp['nanosec'] < 1_000_000_000


def test_multi_input_aliases():
    a, b = MsgView({'data': 2}), MsgView({'data': 3})
    assert Expression('msg1.data * msg2.data', ['msg1', 'msg2']).evaluate(
        {'msg1': a, 'msg2': b}) == 6
    assert Expression('camera.data', ['camera']).evaluate({'camera': a}) == 2


# ---- security boundary -----------------------------------------------------------------

@pytest.mark.parametrize('source', [
    'msg.__class__',
    'msg.__dict__',
    'msg._data',
    'msg.data.__class__',
    'msg.__class__.__mro__',
    'msg.values.__len__',
    'msg.header.__init__.__globals__',
    'msg.plain',          # a real method name on MsgView: still only a dict lookup
    'msg.field',
    'msg.from_message',
])
def test_dunder_and_python_attributes_are_rejected(source):
    with pytest.raises(ExprError) as info:
        ev(source)
    assert info.value.code in ('bad_field', 'no_field')


@pytest.mark.parametrize('source', [
    '"abc".upper',              # attribute on a literal
    '(1).real',
    'upper(msg.data).lower',    # attribute on a call result
    'now_stamp().sec',
    't.real',                   # attribute on a variable
    'pi.real',
    'other.data',               # not an input message name
    '(msg.values)[0].x.y if True else 0',  # fine base, but checked: see runtime test below
])
def test_attribute_access_outside_input_messages_is_rejected(source):
    if source.startswith('(msg.values)'):
        with pytest.raises(ExprError) as info:
            ev(source)
        assert info.value.code == 'not_struct'
        return
    with pytest.raises(ExprError) as info:
        Expression(source, ['msg'])
    assert info.value.code in ('field_base', 'unknown_name')


@pytest.mark.parametrize('source', [
    'getattr(msg, "__class__")',
    '__import__("os")',
    'type(msg)',
    'vars(msg)',
    'dir(msg)',
    'eval("1")',
    'msg.data.upper()',
    'msg.__class__.__subclasses__()',
])
def test_calls_other_than_whitelisted_functions_are_rejected(source):
    with pytest.raises(ExprError):
        Expression(source, ['msg'])


@pytest.mark.parametrize('source', [
    '[x for x in msg.values]',
    '[[y for y in msg.values] for x in msg.values]',
    '{x: 1 for x in msg.values}',
    '(x for x in msg.values)',
    'sum(x for x in msg.values)',
    'lambda: msg',
    'msg.values[0:2]',
    'msg.values[::-1]',
    'msg.values[0, 1]',
    'msg["data"] if False else 0',
    '(msg := 1)',
    'f"{msg.data}"',
    'upper(msg.data, *msg.values)',
])
def test_comprehensions_slices_and_other_syntax_are_rejected(source):
    with pytest.raises(ExprError):
        ev(source)


def test_non_integer_subscripts_are_rejected():
    for source in ('msg.values["0"]', 'msg["data"]', 'msg.values[1.0]', 'msg.values[None]'):
        with pytest.raises(ExprError) as info:
            Expression(source, ['msg'])
        assert info.value.code == 'bad_index', source
    with pytest.raises(ExprError) as info:
        ev('msg[0]')
    assert info.value.code == 'not_array'
    with pytest.raises(ExprError) as info:
        ev('msg.values[msg.data]')  # computed index: checked when evaluated
    assert info.value.code == 'bad_index'


@pytest.mark.parametrize('source,code', [
    ('msg.values[10 ** 9]', 'bad_index'),
    ('msg.values[2 ** 1000]', 'bad_index'),
    ('msg.values[2 ** 4000]', 'too_large'),
    ('msg.values[-(10 ** 7)]', 'bad_index'),
    ('msg.values[3]', 'index_range'),
    ('msg.values[True]', 'bad_index'),
    ('msg.nope', 'no_field'),
    ('msg.values.x', 'not_struct'),
    ('msg.data.x', 'not_struct'),
    ('msg.linear + 1', 'whole_message'),
    ('msg.values * 1000', 'whole_message'),
    ('upper(msg.linear)', 'not_string'),
    ('int(msg.linear)', 'bad_argument'),
    ('len(5)', 'bad_argument'),
    ('clamp(1, 5, 0)', 'bad_argument'),
])
def test_runtime_errors_have_codes(source, code):
    with pytest.raises(ExprError) as info:
        ev(source)
    assert info.value.code == code


def test_dos_caps_still_apply_to_message_data():
    big = {'data': 'x' * MAX_STR_LEN}
    with pytest.raises(ExprError):
        ev('msg.data + msg.data', big)
    with pytest.raises(ExprError):
        ev('msg.data * 2', big)
    with pytest.raises(ExprError):
        ev('replace(msg.data, "x", "yy")', big)
    with pytest.raises(ExprError):
        ev('replace("ab", "", msg.data)', {'data': 'z' * 6000})
    with pytest.raises(ExprError):
        ev('msg.count ** 5000')
    with pytest.raises(ExprError):
        ev('str(msg.values)', {'values': list(range(5000))})
    deep = 'msg' + '.a' * 60
    with pytest.raises(ExprError) as info:
        Expression(deep, ['msg'])
    assert info.value.code == 'too_deep'


def test_message_names_are_validated():
    for bad in ('i', 't', 'now', 'pi', 'upper', 'len', '__msg', 'Msg', '1msg', 'a-b'):
        with pytest.raises(ExprError):
            validate_message_names([bad])
    assert validate_message_names(['msg', 'msg1', 'cam_left']) == {'msg', 'msg1', 'cam_left'}


def test_message_name_must_be_bound_to_a_view():
    expr = Expression('msg.data', ['msg'])
    with pytest.raises(ExprError) as info:
        expr.evaluate({})
    assert info.value.code == 'no_message'
    with pytest.raises(ExprError):
        expr.evaluate({'msg': {'data': 'a plain dict is not accepted'}})


def test_payload_expressions_without_message_names_still_reject_fields():
    """Injection payloads (no message names) keep the P1 rules."""
    for source in ('msg.data', 'i.real', '"a"[0]'):
        with pytest.raises(ExprError):
            Expression(source)


def test_view_is_read_only_and_not_iterable():
    view = MsgView({'a': 1})
    with pytest.raises(AttributeError):
        view.a = 2
    with pytest.raises(AttributeError):
        del view._data
    with pytest.raises(TypeError):
        iter(view)
    assert view.field('a') == 1
