"""Host / Origin / Content-Type guard (DNS rebinding and CSRF)."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from roshanavi.server import create_app


def make(lab, **kw):
    return TestClient(create_app(lab, static_dir=None, live_period=0.2, **kw),
                      base_url='http://localhost')


@pytest.fixture
def client(lab):
    with make(lab) as c:
        yield c


@pytest.mark.parametrize('host', ['localhost', 'localhost:6871', '127.0.0.1:6871', '[::1]:6871',
                                  'LOCALHOST'])
def test_loopback_hosts_allowed(client, host):
    assert client.get('/api/traffic', headers={'Host': host}).status_code == 200


@pytest.mark.parametrize('host', ['evil.com', 'evil.com:6871', 'localhost.evil.com', '', '10.0.0.5'])
def test_foreign_hosts_blocked(client, host):
    r = client.get('/api/traffic', headers={'Host': host})
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'forbidden_host'


def test_allowed_host_flag(lab):
    with make(lab, allowed_hosts=['lab.example']) as c:
        assert c.get('/api/traffic', headers={'Host': 'lab.example:8443'}).status_code == 200
        assert c.get('/api/traffic', headers={'Host': 'evil.com'}).status_code == 403


def test_health_endpoint_ok_but_still_host_checked(client):
    assert client.get('/api/health').json() == {'status': 'ok'}
    assert client.get('/api/health', headers={'Host': 'evil.com'}).status_code == 403


def test_ws_foreign_host_closed_1008(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect('ws://localhost/ws/live', headers={'Host': 'evil.com'}):
            pass
    assert exc.value.code == 1008


@pytest.mark.parametrize('origin', ['http://evil.com', 'https://evil.com:5173', 'null',
                                    'file://', 'ftp://localhost', 'http://localhost.evil.com'])
def test_ws_bad_origin_rejected(client, origin):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect('ws://localhost/ws/live', headers={'Origin': origin}):
            pass
    assert exc.value.code == 1008


def test_ws_bad_origin_rejected_for_echo(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect('ws://localhost/ws/echo/chatter',
                                      headers={'Origin': 'http://evil.com'}):
            pass
    assert exc.value.code == 1008


@pytest.mark.parametrize('origin', ['http://localhost:5173', 'http://127.0.0.1:6871',
                                    'http://[::1]:5173', 'https://localhost'])
def test_ws_localhost_origin_accepted(client, origin):
    with client.websocket_connect('ws://localhost/ws/live', headers={'Origin': origin}) as ws:
        assert 'traffic' in ws.receive_json()


def test_ws_without_origin_accepted(client):
    with client.websocket_connect('ws://localhost/ws/live') as ws:
        assert 'traffic' in ws.receive_json()


def test_allowed_origin_flag(lab):
    with make(lab, allowed_origins=['https://ui.example:8443']) as c:
        with c.websocket_connect('ws://localhost/ws/live',
                                 headers={'Origin': 'https://ui.example:8443'}) as ws:
            assert 'traffic' in ws.receive_json()


def test_text_plain_post_rejected(client):
    r = client.post('/api/inject', content='{"mode":"once"}',
                    headers={'Content-Type': 'text/plain'})
    assert r.status_code == 415
    assert r.json()['error']['code'] == 'unsupported_media_type'


def test_form_post_and_missing_content_type_rejected(client):
    assert client.post('/api/inject', data={'mode': 'once'}).status_code == 415
    assert client.put('/api/traffic/x/monitor', content='{"enabled":true}',
                      headers={'Content-Type': ''}).status_code == 415


def test_json_post_passes_guard_and_delete_without_body_ok(client):
    r = client.post('/api/inject', json={'mode': 'once'})
    assert r.status_code == 400  # reached the handler (validation error), not the guard
    r = client.delete('/api/inject/nope')
    assert r.status_code == 404
    r = client.post('/api/inject', content='{"mode":"once"}',
                    headers={'Content-Type': 'application/json; charset=utf-8'})
    assert r.status_code != 415


def test_monitor_endpoint_roundtrip(client, lab):
    r = client.put('/api/traffic/cam/monitor', json={'enabled': True})
    assert r.status_code == 200 and r.json() == {'topic': '/cam', 'enabled': True}
    assert client.put('/api/traffic/a/b/monitor', json={'enabled': False}).json()['topic'] == '/a/b'
    assert client.put('/api/traffic/cam/monitor', json={'enabled': 'maybe'}).status_code == 422
    assert client.put('/api/traffic/cam/monitor', json={}).status_code == 422
