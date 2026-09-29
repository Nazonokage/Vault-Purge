import json
import shutil
import time
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from vault_purge.api.server import create_app
from vault_purge.api.settings import Settings
from vault_purge.core.audio import analyze_audio, music_similarity
from vault_purge.core.deep_compare import matching_ranges, compare_segments, extract_segments
from vault_purge.core.media_tools import executable, run_tool, ffmpeg_input, ToolUnavailable
from vault_purge.core.playback import PreviewCache
from vault_purge.core.scanner import scan
from vault_purge.storage.models import ImageRecord


@pytest.fixture
def audio(tmp_path):
    for name in ('ffmpeg', 'ffprobe', 'fpcalc'):
        try:
            executable(name)
        except ToolUnavailable:
            pytest.skip('Prepare media tools with tools/fetch_media_tools.py')
    folder = tmp_path / 'audio'
    folder.mkdir()
    rng = np.random.default_rng(22)
    rate = 22050
    t = np.arange(rate // 2) / rate
    chunks = []
    for _ in range(80):
        frequency = rng.choice([220, 261.63, 293.66, 329.63, 392, 440, 523.25])
        tone = sum(np.sin(2 * np.pi * frequency * harmonic * t) / harmonic for harmonic in range(1, 5))
        chunks.append(tone * np.minimum(t * 20, 1) * np.minimum((.5 - t) * 20, 1))
    samples = (np.concatenate(chunks) * 8000).astype('<i2')
    path = folder / 'song.wav'
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(rate); stream.writeframes(samples.tobytes())
    return folder


def test_audio_scan_similarity_cache_integrity_and_moves(audio, tmp_path):
    source = audio / 'song.wav'
    shutil.copyfile(source, audio / 'copy.wav')
    run_tool('ffmpeg', [*ffmpeg_input(source), '-c:a', 'libmp3lame', '-b:a', '128k', str(audio / 'encoded.mp3')])
    app = create_app(Settings(database=tmp_path / 'audio.sqlite3', workers=1, dry_run=False))
    assert scan(audio, app.state.engine, workers=1)['analyzed'] == 3
    updates = []
    assert scan(audio, app.state.engine, workers=1, progress=lambda s: updates.append(s.copy()))['cached'] == 3
    assert updates[-1]['cached'] == 3 and any(s['cached'] == 1 for s in updates)
    with TestClient(app) as client:
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        rows = client.get('/api/images?media_type=audio').json()['items']
        assert len(rows) == 3 and all(r['integrity'] == 'checked' for r in rows)
        assert all(r['blur_score'] is None and r['channels'] == 1 for r in rows)
        groups = client.get('/api/groups?media_type=audio').json()['items']
        assert {g['kind'] for g in groups} == {'exact', 'near'}
        assert max(len(g['members']) for g in groups) == 3
        media_id = rows[0]['id']
        response = client.get(f'/media/{media_id}', headers={'Range': 'bytes=0-9'})
        assert response.status_code == 206 and len(response.content) == 10
        assert client.post(f'/api/media/{media_id}/preview').status_code == 403
        result = client.post(f'/api/media/{media_id}/preview', headers=headers).json()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = client.get(f"/api/media/{media_id}/preview/{result['key']}").json()
            if status['state'] != 'preparing':
                break
            time.sleep(.05)
        assert status['state'] == 'ready', status
        assert client.get(status['url']).status_code == 200
        preview = client.post('/api/move/preview', headers=headers, json={'ids': [media_id], 'destination': 'backup'}).json()
        move = client.post('/api/move', headers=headers, json={'token': preview['token'], 'confirm': True}).json()['items'][0]
        assert move['state'] == 'moved'
        assert client.get(f'/media/{media_id}').status_code == 404
        assert client.post(f"/api/moves/{move['id']}/restore", headers=headers, json={'token': '', 'confirm': True}).json()['state'] == 'restored'
        assert scan(audio, app.state.engine, workers=1)['cached'] == 3
        Path(rows[0]['path']).write_bytes(b'broken')
        assert client.get(f'/media/{media_id}').status_code == 409
        assert scan(audio, app.state.engine, workers=1)['errors'] == 1
        assert client.get('/api/images?media_type=audio&status=error&integrity=suspect').json()['total'] == 1


def test_audio_metadata_then_full_and_tool_failure(audio, engine, monkeypatch):
    assert scan(audio, engine, workers=1, classify_only=True)['analyzed'] == 1
    assert scan(audio, engine, workers=1)['analyzed'] == 1
    monkeypatch.setenv('VAULT_PURGE_FFPROBE', str(audio / 'missing.exe'))
    with pytest.raises(ToolUnavailable):
        analyze_audio(audio / 'song.wav')


def test_preview_failure_cleanup_and_cache_limit(audio, tmp_path):
    cache = PreviewCache(tmp_path / 'previews', limit=100)
    try:
        key, _ = cache.request(audio / 'song.wav', 'audio', 40)
        deadline = time.monotonic() + 30
        while cache.status(key)['state'] == 'preparing' and time.monotonic() < deadline:
            time.sleep(.05)
        assert cache.status(key)['state'] == 'error'
        assert not list(cache.directory.glob('*.partial.*'))
    finally:
        cache.close()


def test_segment_offsets_rearrangement_and_repetition():
    rng = np.random.default_rng(55)
    a = [int(v) for v in rng.integers(0, 2**63, 30, dtype=np.int64)]
    b = a[20:30] + a[5:15]
    ranges = matching_ranges(a, b, 2, 64, 8, 3)
    assert any(r['left_start'] == 40 and r['right_start'] == 0 for r in ranges)
    assert any(r['left_start'] == 10 and r['right_start'] == 20 for r in ranges)
    assert matching_ranges([0] * 100, [0] * 100, 2, 64, 8, 3) == []
    unrelated = [int(v) for v in rng.integers(0, 2**63, 30, dtype=np.int64)]
    assert matching_ranges(a, unrelated, 2, 64, 8, 3) == []
    result = compare_segments({'video': a, 'audio': [], 'notes': []}, {'video': b, 'audio': [], 'notes': []}, 60, 40)
    assert result['video']['right_coverage'] == 1
    assert result['audio']['ranges'] == []


def test_real_audio_trim_segments(audio):
    source = audio / 'song.wav'
    trimmed = audio / 'trim.wav'
    run_tool('ffmpeg', [*ffmpeg_input(source), '-ss', '10', '-t', '25', str(trimmed)])
    left, right = extract_segments(source, 'audio'), extract_segments(trimmed, 'audio')
    result = compare_segments(left, right, 40, 25)
    assert result['audio']['ranges'], result
    assert result['audio']['right_coverage'] > .4
    rearranged = audio / 'reordered.wav'
    run_tool('ffmpeg', [*ffmpeg_input(source), '-filter_complex',
                       '[0:a]asplit=2[a][b];[a]atrim=start=20:end=40,asetpts=PTS-STARTPTS[x];[b]atrim=start=0:end=20,asetpts=PTS-STARTPTS[y];[x][y]concat=n=2:v=0:a=1[out]',
                       '-map', '[out]', str(rearranged)])
    reordered = compare_segments(left, extract_segments(rearranged, 'audio'), 40, 40)
    assert len(reordered['audio']['ranges']) >= 2
    assert reordered['audio']['right_coverage'] > .4


def test_empty_scan_reports_completion(tmp_path, engine):
    folder = tmp_path / 'empty'; folder.mkdir()
    updates = []
    assert scan(folder, engine, workers=1, progress=updates.append)['found'] == 0
    assert updates and updates[-1] == dict(found=0, cached=0, analyzed=0, errors=0)


def test_video_preview_and_deep_api_cache(audio, tmp_path, monkeypatch):
    import cv2
    folder = tmp_path / 'video'; folder.mkdir()
    source = folder / 'source.avi'
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 10, (96, 64))
    rng = np.random.default_rng(888)
    try:
        for _ in range(12):
            frame = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8)
            for _ in range(20):
                writer.write(frame)
    finally:
        writer.release()
    trimmed = folder / 'trim.mp4'
    run_tool('ffmpeg', [*ffmpeg_input(source), '-ss', '4', '-t', '16', '-c:v', 'libx264', str(trimmed)])
    app = create_app(Settings(database=tmp_path / 'video.sqlite3', workers=1))
    scan(folder, app.state.engine, workers=1)
    with TestClient(app) as client:
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        rows = client.get('/api/images?media_type=video').json()['items']
        ids = [r['id'] for r in rows]
        assert client.post('/api/compare', json={'ids': ids}).status_code == 403
        assert client.post('/api/compare', headers=headers, json={'ids': [ids[0], ids[0]]}).status_code == 400
        assert client.post('/api/compare', headers=headers, json={'ids': ids}).status_code == 202
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = client.get('/api/compare').json()
            if status['state'] != 'running':
                break
            time.sleep(.05)
        assert status['state'] == 'complete', status
        assert status['result']['video']['ranges']
        assert not status['result']['audio']['ranges']
        def forbidden(*args):
            raise AssertionError('Segments should come from cache')
        monkeypatch.setattr('vault_purge.api.server.extract_segments', forbidden)
        assert client.post('/api/compare', headers=headers, json={'ids': ids}).status_code == 202
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            cached = client.get('/api/compare').json()
            if cached['state'] != 'running':
                break
            time.sleep(.05)
        assert cached['state'] == 'complete'
        result = client.post(f'/api/media/{ids[0]}/preview', headers=headers).json()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            preview = client.get(f"/api/media/{ids[0]}/preview/{result['key']}").json()
            if preview['state'] != 'preparing':
                break
            time.sleep(.05)
        assert preview['state'] == 'ready', preview
        assert client.get(preview['url'], headers={'Range': 'bytes=0-31'}).status_code == 206


def test_music_rejects_silence_unrelated_and_different_duration():
    from types import SimpleNamespace
    rng = np.random.default_rng(4)
    a = [int(v) for v in rng.integers(0, 2**32, 200, dtype=np.uint64)]
    b = [int(v) for v in rng.integers(0, 2**32, 200, dtype=np.uint64)]
    def record(values, duration=40):
        return SimpleNamespace(duration=duration, audio_fingerprint=json.dumps(values))
    assert music_similarity(record(a), record(a)) == 1
    assert music_similarity(record(a), record(b)) is None
    assert music_similarity(record(a), record(a, 80)) is None
    assert music_similarity(record([0] * 200), record([0] * 200)) is None


def test_scan_progress_and_failure_api(tmp_path, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    def slow_scan(*args, **kwargs):
        kwargs['progress'](dict(found=3, cached=2, analyzed=0, errors=0))
        entered.set()
        release.wait(5)
        raise RuntimeError('Simulated scan failure')
    monkeypatch.setattr('vault_purge.api.server.scan', slow_scan)
    app = create_app(Settings(database=tmp_path / 'progress.sqlite3', workers=1))
    with TestClient(app) as client:
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        try:
            assert client.post('/api/scan', headers=headers, json={'path': str(tmp_path)}).status_code == 202
            assert entered.wait(2)
            job = client.get('/api/scan').json()
            assert job['state'] == 'running' and job['stats']['cached'] == 2 and job['elapsed'] >= 0
            assert client.post('/api/scan', headers=headers, json={'path': str(tmp_path)}).status_code == 409
        finally:
            release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get('/api/scan').json()
            if job['state'] != 'running':
                break
            time.sleep(.01)
        assert job['state'] == 'error' and job['error'] == 'Simulated scan failure'


def test_decoder_timeout_is_not_corruption(monkeypatch):
    import subprocess
    from vault_purge.core.integrity import failure_kind
    monkeypatch.setattr('vault_purge.core.media_tools.executable', lambda name: name)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('ffmpeg', 1)
    monkeypatch.setattr('vault_purge.core.media_tools.subprocess.run', timeout)
    with pytest.raises(RuntimeError, match='time limit') as error:
        run_tool('ffmpeg', [], timeout=1)
    assert failure_kind(error.value) == 'unchecked'


def test_preview_eviction_and_changed_source(tmp_path, monkeypatch):
    first, second = tmp_path / 'a.wav', tmp_path / 'b.wav'
    first.write_bytes(b'first'); second.write_bytes(b'second')
    monkeypatch.setattr('vault_purge.core.playback.run_tool', lambda name, args, timeout: Path(args[-1]).write_bytes(b'x' * 512))
    cache = PreviewCache(tmp_path / 'previews', limit=1000)
    def wait(key):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = cache.status(key)
            if status['state'] != 'preparing':
                return status
            time.sleep(.01)
        pytest.fail('Preview did not finish')
    try:
        key, _ = cache.request(first, 'audio', 1)
        assert wait(key)['state'] == 'ready'
        second_key, _ = cache.request(second, 'audio', 1)
        assert wait(second_key)['state'] == 'ready'
        assert cache.status(key)['state'] == 'error'
        assert sum(p.stat().st_size for p in cache.directory.iterdir()) <= 1000
        def change_source(name, args, timeout):
            Path(args[-1]).write_bytes(b'x' * 512)
            first.write_bytes(b'changed source')
        monkeypatch.setattr('vault_purge.core.playback.run_tool', change_source)
        changed_key, _ = cache.request(first, 'audio', 1)
        assert wait(changed_key)['state'] == 'error'
        assert not list(cache.directory.glob('*.partial.*'))
    finally:
        cache.close()
