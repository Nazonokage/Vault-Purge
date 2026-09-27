from pathlib import Path

from fastapi.testclient import TestClient
from vault_purge.api.server import create_app
from vault_purge.api.settings import Settings
from vault_purge.core.scanner import scan


def test_sibling_suggestion_collision_and_explicit_move(media, tmp_path):
    app = create_app(Settings(database=tmp_path / 'moves.sqlite3', workers=1))
    scan(media, app.state.engine, workers=1)
    with TestClient(app) as client:
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        row = client.get('/api/images').json()['items'][0]
        ids = {'ids': [row['id']]}
        destination = client.post('/api/move/destination', headers=headers, json=ids).json()['destination']
        assert Path(destination) == media.parent / 'media_moved'
        assert not Path(destination).exists()
        Path(destination).mkdir()
        destination = client.post('/api/move/destination', headers=headers, json=ids).json()['destination']
        assert Path(destination).name == 'media_moved_2'
        preview = client.post('/api/move/preview', headers=headers, json={**ids, 'destination': destination}).json()
        assert not Path(destination).exists()
        body = {'token': preview['token'], 'confirm': True}
        assert client.post('/api/move', headers=headers, json=body).status_code == 400
        body['allow_move'] = True
        result = client.post('/api/move', headers=headers, json=body).json()['items'][0]
        assert result['state'] == 'moved'
        assert Path(result['destination']).parent == Path(destination)
        assert client.get('/api/settings').json()['dry_run'] is True
        assert Path(result['destination']).is_file()
        assert not Path(result['original']).exists()
