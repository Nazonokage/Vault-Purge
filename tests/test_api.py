from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from vault_purge.api.settings import Settings
from vault_purge.api.server import create_app
from vault_purge.core.scanner import scan
from vault_purge.storage.models import ImageRecord


def test_filters_folders_sort_and_moves(media, tmp_path):
    app=create_app(Settings(database=tmp_path/'api.sqlite3',workers=1))
    scan(media,app.state.engine,workers=1)
    with TestClient(app) as client:
        assert client.get('/').status_code==200
        token=client.get('/api/settings').json()['session_token']
        headers={'x-session-token':token}
        assert client.post('/api/folders').status_code==403
        assert client.post('/api/folders',headers={**headers,'origin':'https://example.com'}).status_code==403
        folders=client.post('/api/folders',params={'path':str(tmp_path)},headers=headers).json()
        assert str(media) in folders['items']
        assert client.post('/api/folders',params={'path':str(media/'photo.png')},headers=headers).status_code==400
        videos=client.get('/api/images?media_type=video&sort=duration&limit=1').json()
        assert videos['total']==2 and len(videos['items'])==1
        video_id=videos['items'][0]['id']
        assert client.get(f'/thumb/{video_id}').content.startswith(b'\xff\xd8')
        groups=client.get('/api/groups?media_type=video').json()
        assert groups['total']==1 and groups['items'][0]['kind']=='exact'
        assert client.get('/api/images?sort=invalid').status_code==422
        data=client.get('/api/images?sort=size_desc').json()['items']
        assert [r['size'] for r in data]==sorted((r['size'] for r in data),reverse=True)
        assert client.get('/api/images?media_type=image&orientation=PORTRAIT').json()['total']==0
        preview=client.post('/api/move/preview',headers=headers,json={'ids':[video_id],'destination':'_duplicates_backup'}).json()
        confirm={'token':preview['token'],'confirm':True}
        assert client.post('/api/move',headers=headers,json=confirm).status_code==400
        assert Path(preview['items'][0]['source']).exists()
        assert client.put('/api/settings',headers=headers,json={'dry_run':False}).status_code==200
        preview=client.post('/api/move/preview',headers=headers,json={'ids':[video_id],'destination':'_duplicates_backup'}).json()
        moved=client.post('/api/move',headers=headers,json={'token':preview['token'],'confirm':True}).json()['items'][0]
        assert moved['state']=='moved'
        assert Path(moved['destination']).is_file() and not Path(moved['original']).exists()
        restored=client.post(f"/api/moves/{moved['id']}/restore",headers=headers,json={'token':'','confirm':True}).json()
        assert restored['state']=='restored' and Path(moved['original']).is_file()
        assert scan(media,app.state.engine,workers=1)['cached']==4


def test_stale_preview_and_no_overwrite(media, tmp_path):
    app=create_app(Settings(database=tmp_path/'safety.sqlite3',dry_run=False))
    scan(media,app.state.engine,workers=1)
    with TestClient(app) as client:
        headers={'x-session-token':client.get('/api/settings').json()['session_token']}
        row=client.get('/api/images?media_type=image').json()['items'][0]
        body={'ids':[row['id']],'destination':'backup'}
        preview=client.post('/api/move/preview',headers=headers,json=body).json()
        target=Path(preview['items'][0]['destination'])
        target.parent.mkdir();target.write_bytes(b'keep existing')
        assert client.post('/api/move',headers=headers,json={'token':preview['token'],'confirm':True}).status_code==400
        assert target.read_bytes()==b'keep existing' and Path(row['path']).exists()
        assert client.post('/api/move/preview',headers=headers,json=body).status_code==400
        body['destination']='another-backup'
        preview=client.post('/api/move/preview',headers=headers,json=body).json()
        Path(row['path']).write_bytes(b'changed')
        assert client.post('/api/move',headers=headers,json={'token':preview['token'],'confirm':True}).status_code==400
        assert not Path(preview['items'][0]['destination']).exists()


def test_reveal_media_and_moves(media, tmp_path, monkeypatch):
    app = create_app(Settings(database=tmp_path/'reveal.sqlite3', dry_run=False, workers=1))
    scan(media, app.state.engine, workers=1)
    launched = []
    monkeypatch.setattr("vault_purge.utils.file_ops.subprocess.Popen", lambda cmd: launched.append(cmd))
    with TestClient(app) as client:
        token = client.get('/api/settings').json()['session_token']
        headers = {'x-session-token': token}
        images = client.get('/api/images').json()['items']
        img_id = images[0]['id']
        img_path = images[0]['path']

        # Test revealing active image
        res = client.post(f'/api/images/{img_id}/reveal', headers=headers)
        assert res.status_code == 200 and res.json()['revealed'] is True
        assert len(launched) == 1

        # Test non-existent image id
        assert client.post('/api/images/99999/reveal', headers=headers).status_code == 404

        # Test move and reveal move destination
        preview = client.post('/api/move/preview', headers=headers, json={'ids': [img_id], 'destination': 'reveal_dest'}).json()
        moved = client.post('/api/move', headers=headers, json={'token': preview['token'], 'confirm': True}).json()['items'][0]
        move_id = moved['id']

        # Reveal moved destination via moves api
        res = client.post(f'/api/moves/{move_id}/reveal?target=destination', headers=headers)
        assert res.status_code == 200 and res.json()['revealed'] is True
        assert len(launched) == 2

        # Reveal moved image directly via images api (resolves destination)
        res_img = client.post(f'/api/images/{img_id}/reveal', headers=headers)
        assert res_img.status_code == 200 and res_img.json()['revealed'] is True
        assert len(launched) == 3

        # Thumb also works for moved image
        assert client.get(f'/thumb/{img_id}').status_code == 200

        # Reveal original when file moved away should fail (original not on disk)
        assert client.post(f'/api/moves/{move_id}/reveal?target=original', headers=headers).status_code == 404


def test_reveal_file_platform_support(tmp_path, monkeypatch):
    import os
    from vault_purge.utils.file_ops import reveal_file
    import pytest

    test_file = tmp_path / "test.jpg"
    test_file.write_bytes(b"content")

    # Missing file raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        reveal_file(tmp_path / "missing.jpg")

    commands = []
    monkeypatch.setattr("subprocess.Popen", lambda cmd: commands.append(cmd))

    monkeypatch.setattr("platform.system", lambda: "Windows")
    reveal_file(test_file)
    norm = os.path.normpath(str(test_file.resolve()))
    assert commands[-1] == f'explorer /select,"{norm}"'

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    reveal_file(test_file)
    assert commands[-1] == ["open", "-R", str(test_file.resolve())]

    monkeypatch.setattr("platform.system", lambda: "Linux")
    reveal_file(test_file)
    assert commands[-1] == ["xdg-open", str(test_file.resolve().parent)]


def test_favicon_and_proactor_patch(tmp_path):
    import sys
    from vault_purge import patch_asyncio_windows_proactor
    app = create_app(Settings(database=tmp_path / "favicon.sqlite3"))
    with TestClient(app) as client:
        res = client.get("/favicon.ico")
        assert res.status_code == 204

    # Test patch_asyncio_windows_proactor doesn't raise error
    patch_asyncio_windows_proactor()




