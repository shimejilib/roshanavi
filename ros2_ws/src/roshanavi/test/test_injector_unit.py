import random

import pytest

from roshanavi.bagplay import build_bag_command
from roshanavi.injector import Injector, PayloadSource, StreamSource
from roshanavi.jobs import InjectError, InjectSpec, validate_topic


def spec(**kw):
    base = dict(mode='periodic', topic='/x', type='std_msgs/msg/String',
                payload={'data': 'n=${i}'}, rate_hz=10.0)
    base.update(kw)
    return InjectSpec(**base)


def test_payload_source_renders_each_send():
    src = PayloadSource(spec(count=3), random.Random(0))
    assert [src.get(i, 0.0) for i in range(3)] == [{'data': f'n={i}'} for i in range(3)]
    assert src.has(2) and not src.has(3)


def test_payload_source_once_and_unbounded():
    once = PayloadSource(spec(mode='once'), random.Random(0))
    assert once.has(0) and not once.has(1)
    forever = PayloadSource(spec(count=None), random.Random(0))
    assert forever.has(10 ** 6)


def test_payload_source_uses_time_variable():
    src = PayloadSource(spec(payload={'data': '${t * 2}'}), random.Random(0))
    assert src.get(0, 1.5) == {'data': 3.0}


def test_payload_source_rejects_bad_expression():
    with pytest.raises(InjectError) as info:
        PayloadSource(spec(payload={'data': '${__import__("os")}'}), random.Random(0))
    assert info.value.code == 'invalid_expression'


def test_stream_source_order_loop_and_count():
    records = [{'a': 1}, {'a': 2}]
    once = StreamSource(records, loop=False, count=None)
    assert [once.get(i, 0) for i in range(2)] == records
    assert not once.has(2)
    looping = StreamSource(records, loop=True, count=5)
    assert looping.get(3, 0) == {'a': 2}
    assert looping.has(4) and not looping.has(5)


def test_validate_topic():
    assert validate_topic('/ok/topic') == '/ok/topic'
    for bad in ('', None, 'bad name', '/a//b', '/1abc'):
        with pytest.raises(InjectError):
            validate_topic(bad)


def test_bag_command():
    cmd = build_bag_command('/data/bag', InjectSpec(mode='bag', loop=True, bag_rate=2.0,
                                                    bag_topics=('/a', '/b')))
    assert cmd == ['ros2', 'bag', 'play', '/data/bag', '--rate', '2.0', '--loop',
                   '--topics', '/a', '/b']
    with pytest.raises(InjectError):
        build_bag_command('/data/bag', InjectSpec(mode='bag', bag_rate=0.0))
    with pytest.raises(InjectError):
        build_bag_command('/data/bag', InjectSpec(mode='bag', bag_topics=('bad topic',)))


@pytest.mark.parametrize('kwargs,code', [
    (dict(mode='nope'), 'invalid_request'),
    (dict(topic='bad topic'), 'invalid_request'),
    (dict(type=None), 'invalid_request'),
    (dict(type='std_msgs/msg/Nope'), 'unknown_type'),
    (dict(rate_hz=None), 'invalid_request'),
    (dict(rate_hz=5000.0), 'invalid_request'),
    (dict(payload={'nope': 1}), 'invalid_field'),
    (dict(payload={'data': '${1/0}'}), 'invalid_expression'),
    (dict(mode='stream', source='../etc/passwd'), 'forbidden_path'),
    (dict(mode='stream', source='missing.jsonl'), 'not_found'),
    (dict(mode='bag', source='/etc'), 'forbidden_path'),
    (dict(qos={'reliability': 'weird'}), 'invalid_request'),
])
def test_injector_rejects_invalid_specs(tmp_path, kwargs, code):
    injector = Injector(runtime=None, data_dir=str(tmp_path))  # validation never touches ROS
    with pytest.raises(InjectError) as info:
        injector._create(spec(**kwargs))
    assert info.value.code == code


def test_injector_stream_validation_checks_first_record(tmp_path):
    (tmp_path / 's.jsonl').write_text('{"wrong": 1}\n')
    injector = Injector(runtime=None, data_dir=str(tmp_path))
    with pytest.raises(InjectError) as info:
        injector._create(spec(mode='stream', source='s.jsonl'))
    assert info.value.code == 'invalid_field'
