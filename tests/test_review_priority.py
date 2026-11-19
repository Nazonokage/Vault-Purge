from fastapi.testclient import TestClient
from sqlmodel import Session

from vault_purge.api.server import create_app
from vault_purge.api.settings import Settings
from vault_purge.storage.models import ImageRecord, ScanRecord, ScanMember


def test_errors_and_duplicates_sort_before_unique_files_across_pages(tmp_path):
    app = create_app(Settings(database=tmp_path / 'priority.sqlite3'))
    with Session(app.state.engine) as session:
        history = ScanRecord(root=str(tmp_path), state='complete')
        session.add(history)
        session.flush()
        scan_id = history.id
        specs = [
            ('a-unique', 900, 'active', 'unique-a', None),
            ('b-unique', 800, 'active', 'unique-b', None),
            ('y-exact', 10, 'active', 'same', None),
            ('z-exact', 20, 'active', 'same', None),
            ('w-near', 30, 'active', 'near-a', '0000000000000000'),
            ('x-near', 40, 'active', 'near-b', '0000000000000001'),
            ('zz-error', 1, 'error', None, None),
            ('zzz-error', 2, 'error', None, None),
            ('m-moved', 100, 'moved', 'same', None),
            ('n-missing', 100, 'missing', None, None),
        ]
        for name, size, status, digest, phash in specs:
            row = ImageRecord(root=str(tmp_path), path=str(tmp_path / name), size=size,
                              mtime_ns=0, ctime_ns=0, status=status, md5=digest, phash=phash)
            session.add(row)
            session.flush()
            session.add(ScanMember(scan_id=scan_id, image_id=row.id))
        # A matching file outside this scan must not promote its unique member.
        session.add(ImageRecord(root=str(tmp_path / 'other'), path=str(tmp_path / 'outside'),
                                size=900, mtime_ns=0, ctime_ns=0, md5='unique-a'))
        session.commit()
    with TestClient(app) as client:
        params = {'scan_id': scan_id, 'status': 'all', 'review_first': True, 'limit': 2}
        rows = []
        for offset in range(0, 8, 2):
            page = client.get('/api/images', params={**params, 'offset': offset}).json()
            assert page['total'] == 8
            rows.extend(page['items'])
        names = [r['path'].split('\\')[-1].split('/')[-1] for r in rows]
        assert names == ['zz-error', 'zzz-error', 'w-near', 'x-near', 'y-exact', 'z-exact', 'a-unique', 'b-unique']
        assert [r['duplicate_kind'] for r in rows] == [None, None, 'near', 'near', 'exact', 'exact', None, None]
        sized = client.get('/api/images', params={**params, 'limit': 20, 'sort': 'size_desc'}).json()['items']
        assert [r['size'] for r in sized] == [2, 1, 40, 30, 20, 10, 900, 800]
        active = client.get('/api/images', params={**params, 'status': 'active', 'limit': 20}).json()['items']
        assert len(active) == 6 and active[0]['duplicate_kind'] == 'near'
        # Default API ordering stays compatible for existing clients.
        ordinary = client.get('/api/images', params={'scan_id': scan_id}).json()['items']
        assert ordinary[0]['path'].endswith('a-unique')
