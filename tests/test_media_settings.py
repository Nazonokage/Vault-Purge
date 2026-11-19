from fastapi.testclient import TestClient
from sqlmodel import Session

from vault_purge.api.server import create_app
from vault_purge.api.settings import Settings
from vault_purge.storage.models import ImageRecord


def test_image_and_video_settings_apply_independently(tmp_path):
    app = create_app(Settings(database=tmp_path / 'media-settings.sqlite3'))
    with Session(app.state.engine) as session:
        for media_type in ('image', 'video'):
            for i in range(2):
                session.add(ImageRecord(root=str(tmp_path), path=str(tmp_path / f'{media_type}{i}'),
                                        size=100, mtime_ns=0, ctime_ns=0, media_type=media_type,
                                        md5=f'{media_type}{i}', phash=f'{i:016x}', blur_score=100,
                                        duration=10 if media_type == 'video' else None,
                                        frame_hashes=','.join([f'{i:016x}'] * 3) if media_type == 'video' else None))
        session.commit()
    with TestClient(app) as client:
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        response = client.put('/api/settings', headers=headers, json={
            'phash_threshold': 0, 'video_phash_threshold': 1,
            'blur_threshold': 50, 'video_blur_threshold': 150,
        })
        assert response.status_code == 200
        assert client.get('/api/groups?media_type=image').json()['total'] == 0
        assert client.get('/api/groups?media_type=video').json()['total'] == 1
        assert client.get('/api/images?media_type=image&blurry=true').json()['total'] == 0
        assert client.get('/api/images?media_type=video&blurry=true').json()['total'] == 2
        assert client.get('/api/summary').json()['blurry'] == 2
        # General settings changes preserve media-specific values.
        response = client.put('/api/settings', headers=headers, json={'dry_run': False}).json()
        assert response['phash_threshold'] == 0 and response['video_blur_threshold'] == 150
        client.put('/api/settings', headers=headers, json={
            'phash_threshold': 1, 'video_phash_threshold': 0,
            'blur_threshold': 150, 'video_blur_threshold': 50,
        })
        assert client.get('/api/groups?media_type=image').json()['total'] == 1
        assert client.get('/api/groups?media_type=video').json()['total'] == 0
        assert client.get('/api/images?media_type=image&blurry=true').json()['total'] == 2
        assert client.get('/api/images?media_type=video&blurry=true').json()['total'] == 0
        assert client.get('/api/images?blurry=true').json()['total'] == 2
        assert client.put('/api/settings', headers=headers, json={'video_phash_threshold': 21}).status_code == 422
        assert client.put('/api/settings', headers=headers, json={'video_blur_threshold': -1}).status_code == 422


def test_existing_visual_settings_supply_video_defaults(tmp_path):
    app = create_app(Settings(database=tmp_path / 'legacy-settings.sqlite3',
                              phash_threshold=4, blur_threshold=72))
    with TestClient(app) as client:
        settings = client.get('/api/settings').json()
        assert settings['video_phash_threshold'] == 4
        assert settings['video_blur_threshold'] == 72
