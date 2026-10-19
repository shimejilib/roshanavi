"""Project switching (examples copied to data, never overwritten) and the sample media."""

import itertools
import os
import shutil
import wave

import pytest

from roshanavi import sample_media
from roshanavi.launcher.catalog import ProjectCatalog
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.project import parse_project

EXAMPLES = os.environ.get('ROSHANAVI_EXAMPLES', '/examples')
needs_examples = pytest.mark.skipif(not os.path.isdir(EXAMPLES),
                                    reason='examples/ is not mounted')


def make_examples(root):
    for name in ('demo_project', 'perception_demo'):
        (root / name).mkdir(parents=True)
        (root / name / 'roshanavi.yaml').write_text(f'# {name} title\nversion: 1\n')
    (root / 'not a project').mkdir()
    return root


def test_catalog_lists_examples_and_data(tmp_path):
    data = tmp_path / 'data'
    (data / 'projects').mkdir(parents=True)
    (data / 'roshanavi.yaml').write_text('version: 1\n')
    (data / 'projects' / 'mine.yaml').write_text('version: 1\n')
    catalog = ProjectCatalog(str(data), str(make_examples(tmp_path / 'examples')))
    listing = catalog.list(str(data / 'roshanavi.yaml'))
    ids = [p['id'] for p in listing['projects']]
    assert ids == ['example:demo_project', 'example:perception_demo', 'data:roshanavi.yaml',
                   'data:projects/mine.yaml']
    assert [p['current'] for p in listing['projects']] == [False, False, True, False]
    assert listing['projects'][1]['title'] == 'perception_demo title'


def test_opening_an_example_copies_it_once(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    catalog = ProjectCatalog(str(data), str(make_examples(tmp_path / 'examples')))
    path = catalog.resolve('example:perception_demo')
    assert path == str(data / 'projects' / 'perception_demo.yaml')
    with open(path, 'a') as fh:
        fh.write('# my change\n')
    assert catalog.resolve('example:perception_demo') == path
    assert open(path).read().endswith('# my change\n')  # never overwritten
    assert catalog.list(path)['projects'][1]['current'] is True


@pytest.mark.parametrize('bad', ['data:../../etc/passwd', 'example:../x', '/etc/passwd', ''])
def test_only_listed_entries_open(tmp_path, bad):
    catalog = ProjectCatalog(str(tmp_path), str(make_examples(tmp_path / 'examples')))
    with pytest.raises(LauncherError) as info:
        catalog.resolve(bad)
    assert info.value.code == 'not_found'


@needs_examples
@pytest.mark.parametrize('name', ['demo_project', 'perception_demo', 'busy_demo'])
def test_bundled_examples_are_valid_projects(name):
    with open(os.path.join(EXAMPLES, name, 'roshanavi.yaml'), encoding='utf-8') as fh:
        project = parse_project(fh.read(), name)
    ids = {t.id for t in project.targets}
    if name == 'demo_project':
        assert {'image_filter', 'blob_detector', 'audio_level', 'state_machine'} <= ids
        assert all(not t.autostart for t in project.targets if t.package == 'roshanavi_examples')
    elif name == 'busy_demo':
        assert ids == {'busy_demo_driver', 'multi_default', 'multi_off', 'single_default'}
        assert all(not t.autostart for t in project.targets)       # the user starts them one by one
        by_id = {t.id: t for t in project.targets}
        assert [(by_id[i].params['executor'], by_id[i].params['qos_events'])
                for i in ('multi_default', 'multi_off', 'single_default')] == [
            ('multi', 'default'), ('multi', 'off'), ('single', 'default')]
        assert len({t.name for t in project.targets}) == 4          # distinct node names
        stats = {t.params['stats_topic'] for t in project.targets if 'stats_topic' in t.params}
        assert len(stats) == 3                                      # one stats topic per config
    else:
        assert {'image_filter', 'blob_detector', 'audio_level'} <= ids
        assert {d.source for d in project.dummies} == {'samples/blobs.mp4', 'samples/tone.wav'}


@needs_examples
def test_switch_project_api(client, lab):
    listing = client.get('/api/projects').json()
    assert 'example:perception_demo' in [p['id'] for p in listing['projects']]
    original = lab.launcher.project.path
    resp = client.post('/api/projects/open', json={'id': 'example:perception_demo'})
    assert resp.status_code == 200, resp.text
    state = resp.json()
    assert state['path'].endswith('projects/perception_demo.yaml') and state['error'] is None
    assert {t['id'] for t in client.get('/api/targets').json()['targets']} >= {'image_filter'}
    assert client.post('/api/projects/open', json={'id': 'nope'}).status_code == 404
    assert not os.path.exists(original)  # the previous project file was not written


@pytest.fixture
def lab(data_dir, tmp_path):
    from conftest import WS_ROOT
    from roshanavi.lab import Lab
    instance = Lab(data_dir=str(data_dir), period_sec=0.2, workspace=WS_ROOT,
                   project_path=str(tmp_path / 'project' / 'roshanavi.yaml'), autostart=False,
                   stop_timeouts=(3.0, 2.0), examples_dir=EXAMPLES).start()
    yield instance
    instance.stop()


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg is not installed')
def test_sample_media_generated_once(tmp_path):
    assert sorted(sample_media.ensure_samples(str(tmp_path))) == ['blobs.mp4', 'tone.wav']
    samples = tmp_path / 'samples'
    with wave.open(str(samples / 'tone.wav')) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert wav.getnframes() == 16000 * 12
    assert (samples / 'blobs.mp4').stat().st_size > 10_000
    before = (samples / 'tone.wav').stat().st_mtime_ns
    assert sample_media.ensure_samples(str(tmp_path)) == []
    assert (samples / 'tone.wav').stat().st_mtime_ns == before
    assert not list(samples.glob('*.part'))


def test_open_project_autostarts_the_new_targets(tmp_path, data_dir):
    """Regression: the autostart must run on the *new* registry, after the old one stopped."""
    from conftest import wait_for
    from roshanavi.launcher.service import Launcher
    first = tmp_path / 'first.yaml'
    second = tmp_path / 'second.yaml'
    dummy = ('dummies:\n- {{id: {id}, name: {id}, topic: /{id}, type: std_msgs/msg/String, '
             'mode: periodic, payload: {{data: x}}, rate_hz: 1, autostart: true}}\n')
    first.write_text('version: 1\n' + dummy.format(id='rn_first'))
    second.write_text('version: 1\n' + dummy.format(id='rn_second'))
    ticks = itertools.count(0, 10)  # every call is 10 s later: no autostart warm-up wait
    launcher = Launcher(str(tmp_path), str(data_dir), project_path=str(first), autostart=True,
                        clock=lambda: float(next(ticks)))
    try:
        launcher.observe([])
        wait_for(lambda: launcher.manager.get('rn_first')['status'] in ('starting', 'running'),
                 timeout=20)
        launcher.open_project(str(second))

        def started():
            launcher.observe([])  # the housekeeping tick that triggers the autostart
            return launcher.manager.get('rn_second')['status'] in ('starting', 'running')
        wait_for(started, timeout=20, interval=0.2)
        assert [t['id'] for t in launcher.manager.list()] == ['rn_second']
    finally:
        launcher.close()


# ---- the last opened project is remembered across restarts ----------------------------

def test_catalog_remembers_the_last_opened_project(tmp_path):
    data = tmp_path / 'data'
    (data / 'projects').mkdir(parents=True)
    (data / 'projects' / 'mine.yaml').write_text('version: 1\n')
    catalog = ProjectCatalog(str(data), str(make_examples(tmp_path / 'examples')))
    assert catalog.remembered_path() is None  # nothing opened yet
    catalog.remember('data:projects/mine.yaml')
    assert catalog.remembered_path() == str(data / 'projects' / 'mine.yaml')
    catalog.remember('example:perception_demo')
    assert catalog.remembered_path() == str(data / 'projects' / 'perception_demo.yaml')
    assert (data / 'projects' / 'perception_demo.yaml').is_file()  # copied like a normal open


@pytest.mark.parametrize('content', [
    'not json', '[]', '{}', '{"id": 3}', '{"id": "data:../../etc/passwd"}',
    '{"id": "data:projects/gone.yaml"}', '{"id": "example:vanished"}', '{"id": "/etc/passwd"}',
])
def test_an_invalid_remembered_project_is_ignored(tmp_path, content):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'last_project.json').write_text(content)
    catalog = ProjectCatalog(str(data), str(make_examples(tmp_path / 'examples')))
    assert catalog.remembered_path() is None


def test_a_remembered_project_that_was_deleted_is_ignored(tmp_path):
    data = tmp_path / 'data'
    (data / 'projects').mkdir(parents=True)
    mine = data / 'projects' / 'mine.yaml'
    mine.write_text('version: 1\n')
    catalog = ProjectCatalog(str(data))
    catalog.remember('data:projects/mine.yaml')
    mine.unlink()
    assert catalog.remembered_path() is None


def test_remembering_never_raises_when_the_data_dir_is_not_writable(tmp_path):
    catalog = ProjectCatalog(str(tmp_path / 'missing' / 'dir'))
    catalog.remember('data:roshanavi.yaml')  # logged, not raised
    assert catalog.remembered_path() is None


def make_lab(data_dir, tmp_path):
    from conftest import WS_ROOT
    from roshanavi.lab import Lab
    return Lab(data_dir=str(data_dir), period_sec=0.2, workspace=WS_ROOT,
               project_path=str(tmp_path / 'project' / 'roshanavi.yaml'), autostart=False,
               stop_timeouts=(3.0, 2.0)).start()


def test_lab_starts_on_the_remembered_project_and_falls_back_to_the_option(data_dir, tmp_path):
    mine = data_dir / 'projects' / 'mine.yaml'
    mine.parent.mkdir(parents=True)
    mine.write_text('version: 1\n')
    first = make_lab(data_dir, tmp_path)
    try:
        assert first.launcher.project.path == str(tmp_path / 'project' / 'roshanavi.yaml')  # --project
        first.catalog.remember('data:projects/mine.yaml')
    finally:
        first.stop()
    second = make_lab(data_dir, tmp_path)  # a "restart"
    try:
        assert second.launcher.project.path == str(mine)
        mine.unlink()  # the remembered file is gone: back to --project
    finally:
        second.stop()
    third = make_lab(data_dir, tmp_path)
    try:
        assert third.launcher.project.path == str(tmp_path / 'project' / 'roshanavi.yaml')
    finally:
        third.stop()


@needs_examples
def test_switching_through_the_api_is_remembered(client, lab, data_dir):
    assert client.post('/api/projects/open', json={'id': 'example:perception_demo'}).status_code == 200
    assert lab.catalog.remembered_path() == lab.launcher.project.path
    assert (data_dir / 'last_project.json').is_file()
    assert client.post('/api/projects/open', json={'id': 'nope'}).status_code == 404
    assert lab.catalog.remembered_path() == lab.launcher.project.path  # a failed switch changes nothing
