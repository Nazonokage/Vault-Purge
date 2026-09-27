from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session

from vault_purge.api.server import create_app
from vault_purge.api.settings import Settings
from vault_purge.core.hasher import analyze_image
from vault_purge.core.integrity import SuspectedCorruption, failure_kind
from vault_purge.core.scanner import scan
from vault_purge.storage.models import ImageRecord


def test_truncated_image_and_access_error_are_distinct(tmp_path):
    path = tmp_path / 'truncated.png'
    Image.new('RGB', (80, 80), 'red').save(path)
    path.write_bytes(path.read_bytes()[:-20])
    with pytest.raises(SuspectedCorruption):
        analyze_image(str(path))
    assert failure_kind(PermissionError('denied')) == 'unreadable'
    assert failure_kind(ValueError('changed during scan')) == 'unchecked'
    assert failure_kind(SuspectedCorruption('truncated')) == 'suspect'


def test_integrity_check_levels(tmp_path):
    path = tmp_path / 'valid.png'
    Image.new('RGB', (30, 60), 'red').save(path)
    assert analyze_image(str(path))['integrity'] == 'checked'
    assert analyze_image(str(path), False)['integrity'] == 'unchecked'


def test_corrupt_quarantine_and_restore_preserves_flag(tmp_path):
    folder = tmp_path / 'media'
    folder.mkdir()
    broken = folder / 'broken.png'
    broken.write_bytes(b'not an image')
    video = folder / 'broken.mp4'
    video.write_bytes(b'not a video')
    app = create_app(Settings(database=tmp_path / 'integrity.sqlite3', workers=1))
    assert scan(folder, app.state.engine, workers=1)['errors'] == 2
    with TestClient(app) as client:
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        data = client.get('/api/images?status=error&integrity=suspect').json()
        assert data['total'] == 2
        assert all(row['error'] for row in data['items'])
        row = next(row for row in data['items'] if row['media_type'] == 'image')
        payload = {'ids': [row['id']], 'destination': '_corrupt_review'}
        preview = client.post('/api/move/preview', headers=headers, json=payload).json()
        assert preview['items'][0]['integrity'] == 'suspect'
        assert preview['items'][0]['reason']
        assert client.post('/api/move', headers=headers, json={'token': preview['token'], 'confirm': True}).status_code == 400
        assert broken.exists()
        client.put('/api/settings', headers=headers, json={'dry_run': False})
        preview = client.post('/api/move/preview', headers=headers, json=payload).json()
        result = client.post('/api/move', headers=headers, json={'token': preview['token'], 'confirm': True}).json()['items'][0]
        assert result['state'] == 'moved'
        assert Path(result['destination']).read_bytes() == b'not an image'
        restored = client.post(f"/api/moves/{result['id']}/restore", headers=headers, json={'token': '', 'confirm': True}).json()
        assert restored['state'] == 'restored'
        assert broken.read_bytes() == b'not an image'
        assert client.get('/api/images?status=error&integrity=suspect').json()['total'] == 2
        with Session(app.state.engine) as session:
            record = session.get(ImageRecord, row['id'])
            record.integrity = 'unreadable'
            session.add(record)
            session.commit()
        assert client.post('/api/move/preview', headers=headers, json=payload).status_code == 400
        Image.new('RGB', (40, 30), 'blue').save(broken)
        scan(folder, app.state.engine, workers=1)
        assert client.get('/api/images?status=error&integrity=suspect').json()['total'] == 1
        assert client.get('/api/images?integrity=checked').json()['total'] == 1
