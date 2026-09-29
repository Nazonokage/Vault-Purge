import logging
import signal
import time
from concurrent.futures.process import BrokenProcessPool

import pytest
import uvicorn
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from vault_purge.api.runtime import DiagnosticServer, run_server
from vault_purge.api.server import create_app
from vault_purge.api.settings import Settings
from vault_purge.core.scanner import scan
from vault_purge.storage.models import ImageRecord, ScanRecord


def interrupted_worker(*args):
    raise KeyboardInterrupt()


def broken_worker(*args):
    raise BrokenProcessPool("Worker stopped")


@pytest.mark.parametrize('worker,exception', [(interrupted_worker, KeyboardInterrupt), (broken_worker, BrokenProcessPool)])
def test_interrupted_worker_marks_scan_not_media(tmp_path, engine, monkeypatch, worker, exception):
    folder = tmp_path / 'media'; folder.mkdir()
    Image.new('RGB', (32, 32), 'red').save(folder / 'a.png')
    monkeypatch.setattr('vault_purge.core.scanner.analyze_media', worker)
    with pytest.raises(exception):
        scan(folder, engine, workers=1)
    with Session(engine) as session:
        history = session.exec(select(ScanRecord)).one()
        assert history.state == 'interrupted' and history.finished_at
        assert 'Scan interrupted' in history.error
        assert not session.exec(select(ImageRecord).where(ImageRecord.status == 'error')).all()


def test_api_recovers_after_worker_interrupt(tmp_path, monkeypatch):
    monkeypatch.setattr('vault_purge.api.server.scan', interrupted_worker)
    app = create_app(Settings(database=tmp_path / 'cache.sqlite3', workers=1))
    with TestClient(app) as client:
        headers = {'x-session-token': client.get('/api/settings').json()['session_token']}
        assert client.post('/api/scan', headers=headers, json={'path': str(tmp_path)}).status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get('/api/scan').json()
            if job['state'] != 'running':
                break
            time.sleep(.01)
        assert job['state'] == 'error' and 'interrupted' in job['error']
        assert client.put('/api/settings', headers=headers, json={}).status_code == 200


def test_shutdown_signal_recorded_without_suppressing_exit(caplog):
    logger = logging.getLogger('shutdown-test')
    server = DiagnosticServer(uvicorn.Config('unused:app'), logger)
    with caplog.at_level(logging.WARNING, logger=logger.name):
        server.handle_exit(signal.SIGINT, None)
    assert server.should_exit
    assert 'SIGINT' in caplog.text and 'sender is not available' in caplog.text


def test_runtime_logs_keyboard_interrupt(tmp_path, monkeypatch):
    class FakeServer:
        def __init__(self, *args):
            pass
        def run(self):
            raise KeyboardInterrupt()
    monkeypatch.setattr('vault_purge.api.runtime.DiagnosticServer', FakeServer)
    run_server(None, Settings(database=tmp_path / 'cache.sqlite3'), 8000)
    log = (tmp_path / 'diagnostics.log').read_text(encoding='utf-8')
    assert 'Server starting' in log and 'Interrupt reached' in log and 'Server stopped' in log
