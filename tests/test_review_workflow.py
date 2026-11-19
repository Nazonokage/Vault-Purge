from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from vault_purge.api.server import create_app
from vault_purge.api.settings import Settings
from vault_purge.core.scanner import scan
from vault_purge.storage.models import ImageRecord, MoveRecord, ScanRecord


def interrupted_analysis(path, full):
    from concurrent.futures.process import BrokenProcessPool
    from vault_purge.core.hasher import analyze_media
    if Path(path).stem == '2':
        raise BrokenProcessPool('Worker stopped mid-scan')
    return analyze_media(path, full)


def test_move_removes_singleton_and_restore_rebuilds_group(media, tmp_path):
    app = create_app(Settings(database=tmp_path / 'review.sqlite3', workers=1, dry_run=False))
    scans = []
    scan(media, app.state.engine, workers=1, on_started=scans.append)
    with TestClient(app) as client:
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        params = {'scan_id': scans[0], 'media_type': 'video'}
        group = client.get('/api/groups', params=params).json()['items'][0]
        duplicate = next(r for r in group['members'] if r['id'] != group['recommendation']['id'])
        preview = client.post('/api/move/preview', headers=headers,
                              json={'ids': [duplicate['id']], 'destination': 'backup'}).json()
        moved = client.post('/api/move', headers=headers,
                            json={'token': preview['token'], 'confirm': True}).json()['items'][0]
        assert client.get('/api/groups', params=params).json() == {'total': 0, 'items': []}
        remaining = client.get('/api/images', params=params).json()
        assert remaining['total'] == 1
        assert remaining['items'][0]['id'] == group['recommendation']['id']
        review = client.get('/api/images', params={**params, 'status': 'all', 'review_first': True}).json()
        assert review['total'] == 1 and review['items'][0]['duplicate_kind'] is None
        counts = client.get('/api/summary', params={'scan_id': scans[0]}).json()['counts']
        assert counts['active'] == 3 and counts['moved'] == 1
        assert client.post(f"/api/moves/{moved['id']}/restore", headers=headers,
                           json={'token': '', 'confirm': True}).json()['state'] == 'restored'
        restored = client.get('/api/groups', params=params).json()
        assert restored['total'] == 1
        assert {r['id'] for r in restored['items'][0]['members']} == {r['id'] for r in group['members']}
        review = client.get('/api/images', params={**params, 'status': 'all', 'review_first': True}).json()
        assert review['total'] == 2 and all(r['duplicate_kind'] == 'exact' for r in review['items'])


def test_history_pages_have_exact_totals_for_large_histories(tmp_path):
    app = create_app(Settings(database=tmp_path / 'pages.sqlite3'))
    with Session(app.state.engine) as session:
        image = ImageRecord(root=str(tmp_path), path=str(tmp_path / 'a.png'), size=0, mtime_ns=0, ctime_ns=0)
        session.add(image)
        session.flush()
        session.add_all([MoveRecord(image_id=image.id, original=image.path,
                                    destination=str(tmp_path / f'backup/{i}.png'), md5='test',
                                    state='moved', created_at='2026-11-19') for i in range(4001)])
        session.commit()
    with TestClient(app) as client:
        ids = []
        for offset in range(0, 4001, 48):
            page = client.get('/api/moves', params={'paginated': True, 'offset': offset, 'limit': 48}).json()
            assert page['total'] == 4001
            ids.extend(r['id'] for r in page['items'])
        assert len(ids) == len(set(ids)) == 4001
        assert ids == sorted(ids, reverse=True)
        assert client.get('/api/moves?paginated=true&offset=4001').json() == {'total': 4001, 'items': []}
        assert isinstance(client.get('/api/moves').json(), list)  # Existing API clients still work.


def test_4000_file_progress_and_cached_rescan(tmp_path, engine, monkeypatch):
    import vault_purge.core.scanner as scanner

    folder = tmp_path / 'large'
    folder.mkdir()
    Image.new('RGB', (8, 8), 'red').save(folder / '0000.png')
    payload = (folder / '0000.png').read_bytes()
    for i in range(1, 4000):
        (folder / f'{i:04}.png').write_bytes(payload)
    real_walk = scanner.walk_images
    walks = []

    def counted_walk(*args):
        walks.append(1)
        yield from real_walk(*args)

    monkeypatch.setattr(scanner, 'walk_images', counted_walk)
    for cached in (False, True):
        updates = []
        result = scan(folder, engine, workers=2, progress=updates.append)
        assert len(walks) == (2 if cached else 1)
        assert result['cached' if cached else 'analyzed'] == 4000
        discovery = [s for s in updates if s['stage'] == 'discovery']
        assert discovery[-1]['found'] == 4000
        assert all(s['total'] is None for s in discovery)
        processing = [s for s in updates if s['stage'] == 'processing']
        assert all(s['total'] == 4000 for s in processing)
        done = [s['processed'] for s in processing]
        assert done == sorted(done) and done[-1] == 4000
        assert processing[-1]['errors'] == 0


def test_mixed_rescan_counts_cache_before_analysis(media, engine):
    scan(media, engine, workers=1)
    (media / 'copy.png').unlink()
    Image.new('RGB', (16, 16), 'blue').save(media / 'copy.png')
    updates = []
    scan(media, engine, workers=1, progress=updates.append)
    first_analysis = next(s for s in updates if s['analyzed'])
    assert first_analysis['cached'] == 3
    assert first_analysis['processed'] == first_analysis['total'] == 4


def test_discovery_failure_reports_partial_count_and_failed_history(tmp_path, engine, monkeypatch):
    import pytest

    def interrupted_walk(*args):
        yield tmp_path / 'found.png'
        raise OSError('Drive disconnected')

    monkeypatch.setattr('vault_purge.core.scanner.walk_images', interrupted_walk)
    updates = []
    with pytest.raises(OSError, match='disconnected'):
        scan(tmp_path, engine, workers=1, progress=updates.append)
    assert updates[-1]['found'] == 1 and updates[-1]['total'] is None
    with Session(engine) as session:
        assert session.exec(select(ScanRecord)).one().state == 'error'


def test_processing_interruption_preserves_progress_and_completed_batches(tmp_path, engine, monkeypatch):
    import pytest
    from concurrent.futures.process import BrokenProcessPool
    from vault_purge.storage.models import ScanMember

    for i in range(4):
        Image.new('RGB', (16, 16), 'red').save(tmp_path / f'{i}.png')
    monkeypatch.setattr('vault_purge.core.scanner.analyze_media', interrupted_analysis)
    updates = []
    with pytest.raises(BrokenProcessPool):
        scan(tmp_path, engine, workers=1, progress=updates.append)
    assert updates[-1]['total'] == 4 and updates[-1]['processed'] == 2
    with Session(engine) as session:
        assert session.exec(select(ScanRecord)).one().state == 'interrupted'
        assert len(session.exec(select(ScanMember)).all()) == 2
        assert len(session.exec(select(ImageRecord).where(ImageRecord.status == 'active')).all()) == 2
