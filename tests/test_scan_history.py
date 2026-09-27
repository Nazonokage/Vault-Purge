from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from vault_purge.api.server import create_app
from vault_purge.api.settings import Settings
from vault_purge.core.scanner import scan
from vault_purge.storage.models import ImageRecord, MoveRecord, ScanRecord


def make_folder(path):
    path.mkdir()
    Image.new('RGB', (40, 30), 'red').save(path / 'a.png')
    (path / 'b.png').write_bytes((path / 'a.png').read_bytes())
    return path


def test_separate_scans_clear_history_keep_cache_and_moves(tmp_path):
    first = make_folder(tmp_path / 'first')
    second = make_folder(tmp_path / 'flashdrive')
    database = tmp_path / 'history.sqlite3'
    app = create_app(Settings(database=database, workers=1))
    ids = []
    scan(first, app.state.engine, workers=1, on_started=ids.append)
    scan(second, app.state.engine, workers=1, on_started=ids.append)
    with TestClient(app) as client:
        history = client.get('/api/scans').json()
        assert history['total'] == 2
        assert history['items'][0]['root'] == str(second)
        for scan_id, root in zip(ids, [first, second]):
            images = client.get('/api/images', params={'scan_id': scan_id}).json()
            assert images['total'] == 2
            assert all(Path(row['path']).parent == root for row in images['items'])
            assert client.get('/api/groups', params={'scan_id': scan_id}).json()['total'] == 1
            assert client.get('/api/summary', params={'scan_id': scan_id}).json()['counts']['active'] == 2
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        image = client.get('/api/images', params={'scan_id': ids[0]}).json()['items'][0]
        client.put('/api/settings', headers=headers, json={'dry_run': False})
        preview = client.post('/api/move/preview', headers=headers, json={'ids':[image['id']], 'destination':'backup'}).json()
        move = client.post('/api/move', headers=headers, json={'token':preview['token'], 'confirm':True}).json()['items'][0]
        assert move['state'] == 'moved'
        assert client.delete('/api/scans').status_code == 403
        assert client.delete('/api/scans', headers=headers).status_code == 200
        assert client.get('/api/scans').json()['total'] == 0
        assert client.get('/api/images', params={'scan_id': ids[0]}).status_code == 404
        assert client.get('/api/moves').json()[0]['state'] == 'moved'
        assert client.post(f"/api/moves/{move['id']}/restore", headers=headers, json={'token':'', 'confirm':True}).json()['state'] == 'restored'
        assert len(list(first.glob('*.png'))) == len(list(second.glob('*.png'))) == 2
        assert scan(second, app.state.engine, workers=1, on_started=ids.append)['cached'] == 2
        assert ids[-1] > ids[-2]
    reopened = create_app(Settings(database=database))
    with TestClient(reopened) as client:
        assert client.get('/api/scans').json()['total'] == 1
        assert client.get('/api/scan').json()['state'] == 'idle'


def test_nonrecursive_membership_and_failed_scan(tmp_path, engine):
    root = make_folder(tmp_path / 'root')
    make_folder(root / 'nested')
    ids = []
    scan(root, engine, workers=1, on_started=ids.append)
    scan(root, engine, workers=1, recursive=False, on_started=ids.append)
    from vault_purge.storage.models import ScanMember
    with Session(engine) as session:
        assert len(session.exec(select(ScanMember).where(ScanMember.scan_id == ids[0])).all()) == 4
        assert len(session.exec(select(ScanMember).where(ScanMember.scan_id == ids[1])).all()) == 2
    import pytest
    with pytest.raises(FileNotFoundError):
        scan(tmp_path / 'unplugged-drive', engine, workers=1, on_started=ids.append)
    with Session(engine) as session:
        failed = session.get(ScanRecord, ids[-1])
        assert failed.state == 'error' and failed.error
