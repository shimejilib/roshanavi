"""ServiceCaller deadlines and the single retry of reads (no ROS graph needed)."""

from types import SimpleNamespace

import pytest

from roshanavi.api_errors import ApiError
from roshanavi.lifecycle import QUERY_TIMEOUT_SEC, LifecycleService
from roshanavi.params import ParamService
from roshanavi.service_call import ServiceCaller, ServiceErrors
from roshanavi.service_defaults import DEFAULT_SERVICE_TIMEOUT_SEC

ERRORS = ServiceErrors('x_unavailable', 'x_timeout', 'x_failed', 'test')


class FakeFuture:
    def __init__(self, answer):
        self.answer = answer

    def add_done_callback(self, fn):
        if self.answer is not None:
            fn(self)

    def cancel(self):
        pass

    def result(self):
        return self.answer


class FakeClient:
    """Does not answer the first ``silent`` calls, then answers ``'ok'``."""

    def __init__(self, silent):
        self.silent = silent
        self.calls = 0
        self.answer = 'ok'

    def wait_for_service(self, timeout_sec=None):
        return True

    def call_async(self, request):
        self.calls += 1
        return FakeFuture(None if self.calls <= self.silent else self.answer)


class FakeRuntime:
    def __init__(self, silent):
        self.client = FakeClient(silent)

    def create_client(self, srv_type, service, group=None):
        return self.client

    def destroy_client(self, client):
        pass


def caller(silent):
    runtime = FakeRuntime(silent)
    return ServiceCaller(runtime, ERRORS, 0.05), runtime.client


def test_default_deadline_is_five_seconds_everywhere():
    assert DEFAULT_SERVICE_TIMEOUT_SEC == 5.0 and QUERY_TIMEOUT_SEC == 5.0
    assert ParamService.__init__.__defaults__[0] == 5.0
    assert LifecycleService.__init__.__defaults__[0] == 5.0


def test_call_does_not_retry_by_default():
    svc, client = caller(silent=1)
    with pytest.raises(ApiError) as info:
        svc.call('/n', 'get_parameters', object, object())
    assert info.value.code == 'x_timeout' and client.calls == 1


def test_read_retries_once_after_a_timeout():
    svc, client = caller(silent=1)
    assert svc.call('/n', 'get_parameters', object, object(), retries=1) == 'ok'
    assert client.calls == 2


def test_gives_up_after_the_retry():
    svc, client = caller(silent=5)
    with pytest.raises(ApiError) as info:
        svc.call('/n', 'get_parameters', object, object(), retries=1)
    assert info.value.code == 'x_timeout' and client.calls == 2


def test_unavailable_service_is_not_retried():
    svc, client = caller(silent=0)
    client.wait_for_service = lambda timeout_sec=None: False
    with pytest.raises(ApiError) as info:
        svc.call('/n', 'get_parameters', object, object(), retries=3)
    assert info.value.code == 'x_unavailable'


def param_service(silent):
    runtime = FakeRuntime(silent)
    return ParamService(runtime, timeout_sec=0.05), runtime.client


def test_param_describe_and_get_retry_but_set_does_not(monkeypatch):
    svc, client = param_service(silent=1)
    client.answer = SimpleNamespace(descriptors=[], values=[])
    with pytest.raises(ApiError) as info:  # answered (empty) on the retry
        svc.describe('/n', 'rate')
    assert info.value.code == 'param_not_found' and client.calls == 2
    assert svc.get('/n', 'rate')['type'] == 'not_set' and client.calls == 3

    svc, client = param_service(silent=1)
    monkeypatch.setattr(svc, 'describe', lambda *a, **k: {
        'read_only': False, 'declared_type': 'double', 'dynamic_typing': False})
    with pytest.raises(ApiError) as info:
        svc.set('/n', 'rate', 'double', 1.0)
    assert info.value.code == 'param_timeout' and client.calls == 1


def test_service_timeout_flag():
    from roshanavi.main import parse_args
    assert parse_args([]).service_timeout == 5.0
    assert parse_args(['--service-timeout', '8']).service_timeout == 8.0
    with pytest.raises(SystemExit):
        parse_args(['--service-timeout', '0'])
