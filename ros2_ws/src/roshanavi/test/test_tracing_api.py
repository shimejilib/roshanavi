"""詳細計測モード API without LTTng: availability reasons, errors, request validation."""

from roshanavi.tracing.service import TracingService


def test_status_when_tracing_is_off(client):
    status = client.get('/api/tracing').json()
    assert status['available'] is False and status['reason'] == 'disabled'
    assert status['active'] is False and status['unsupported'] == []


def test_enabling_unavailable_tracing_is_a_409(client):
    resp = client.put('/api/tracing', json={'enabled': True})
    assert resp.status_code == 409
    assert resp.json()['error']['code'] == 'tracing_unavailable'


def test_request_must_be_json_and_strict(client):
    resp = client.put('/api/tracing', content='enabled=true',
                      headers={'Content-Type': 'text/plain'})
    assert resp.status_code == 415
    assert client.put('/api/tracing', json={'enabled': True, 'x': 1}).status_code == 422


def test_missing_tools_are_reported_with_the_reason():
    service = TracingService('auto', check=lambda: 'not_installed')
    service.start()
    status = service.status()
    assert status['available'] is False and status['reason'] == 'not_installed'
    assert service.worker_pid() is None and service.snapshot() is None
    assert 'lttng-tools' in service.unavailable_message()
    service.close()


def test_live_frame_carries_the_tracing_status(client):
    with client.websocket_connect('ws://localhost/ws/live') as ws:
        frame = ws.receive_json()
    assert frame['tracing']['reason'] == 'disabled'
