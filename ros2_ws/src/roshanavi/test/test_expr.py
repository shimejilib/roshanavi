import math
import random

import pytest

from roshanavi.expr import (MAX_SOURCE_LEN, MAX_STR_LEN, ExprError, Expression,
                            PayloadTemplate, evaluate)


@pytest.mark.parametrize('source,expected', [
    ('1 + 2 * 3', 7),
    ('2 ** 10', 1024),
    ('7 % 3', 1),
    ('7 // 2', 3),
    ('-i + 1', -4),
    ('+t', 2.5),
    ('i * 2 if i > 3 else 0', 10),
    ('1 < 2 <= 2', True),
    ('i == 5 and t > 2', True),
    ('not 0', True),
    ('0 or 7', 7),
    ('"a" + "b"', 'ab'),
    ('"ab" * 3', 'ababab'),
    ('str(i) + "x"', '5x'),
    ('int("12") + float("0.5")', 12.5),
    ('max(1, i, 3)', 5),
    ('min(4, 2)', 2),
    ('abs(-3)', 3),
    ('round(2.567, 2)', 2.57),
    ('floor(2.7) + ceil(2.1)', 5),
    ('sqrt(16)', 4.0),
    ('pi', math.pi),
    ('e', math.e),
])
def test_allowed_expressions(source, expected):
    assert evaluate(source, {'i': 5, 't': 2.5, 'now': 100.0}) == expected


def test_trig_and_now():
    assert evaluate('sin(0) + cos(0) + tan(0)') == 1.0
    assert evaluate('now', {'now': 123.0}) == 123.0


def test_random_functions_are_seedable():
    a = evaluate('uniform(0, 1) + randint(1, 6) + random()', rng=random.Random(1))
    b = evaluate('uniform(0, 1) + randint(1, 6) + random()', rng=random.Random(1))
    assert a == b
    assert 1 <= evaluate('randint(1, 3)', rng=random.Random(2)) <= 3


@pytest.mark.parametrize('source', [
    '__import__("os")',
    'open("/etc/passwd")',
    '(1).__class__',
    'i.real',
    '"abc"[0]',
    '[x for x in "ab"]',
    'lambda: 1',
    'eval("1")',
    'exec("1")',
    'foo',
    'max(*[1, 2])',
    'round(1.5, ndigits=1)',
    '[1, 2]',
    '{"a": 1}',
    '(1, 2)',
    'i := 3',
    'b"x"',
    'None',
    'f"{i}"',
    'x if True else 1',
])
def test_rejected_syntax(source):
    with pytest.raises(ExprError):
        evaluate(source)


@pytest.mark.parametrize('source', [
    '10 ** 10000',
    '2 ** 5000',
    '"a" * 100000',
    '"%999999999d" % 1',
    '1 / 0',
    'sqrt(-1)',
    'randint(5, 1)',
    '"a" + 1',
])
def test_runtime_limits_and_errors(source):
    with pytest.raises(ExprError):
        evaluate(source)


def test_source_length_cap():
    with pytest.raises(ExprError):
        Expression('1+' * MAX_SOURCE_LEN + '1')


def test_nesting_depth_cap():
    with pytest.raises(ExprError):
        Expression('(' * 60 + '1' + ')' * 60 + '+' + '+'.join(['1'] * 60))
    with pytest.raises(ExprError):
        Expression('-' * 100 + '1')


def test_string_concat_cap():
    big = 'x' * (MAX_STR_LEN // 2 + 1)
    with pytest.raises(ExprError):
        evaluate(f'"{big}" + "{big}"')


def test_payload_template_whole_and_embedded():
    tmpl = PayloadTemplate({'data': 'hello ${i}', 'value': '${i * 0.5}',
                            'nested': {'list': ['${i + 1}', 'plain', 3]}, 'flag': True})
    out = tmpl.render({'i': 4})
    assert out == {'data': 'hello 4', 'value': 2.0,
                   'nested': {'list': [5, 'plain', 3]}, 'flag': True}


def test_payload_template_multiple_placeholders():
    out = PayloadTemplate({'s': '${i}-${i * 2}!'}).render({'i': 3})
    assert out == {'s': '3-6!'}


def test_payload_template_reports_field_path():
    with pytest.raises(ExprError, match='a.b'):
        PayloadTemplate({'a': {'b': '${import_os}'}})


def test_payload_template_does_not_mutate_input():
    payload = {'data': '${i}'}
    PayloadTemplate(payload).render({'i': 1})
    assert payload == {'data': '${i}'}
