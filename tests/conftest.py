from pathlib import Path
import cv2
import numpy as np
import pytest
from PIL import Image

from vault_purge.storage.database import open_database


@pytest.fixture
def engine(tmp_path):
    engine = open_database(tmp_path / 'cache.sqlite3')
    yield engine
    engine.dispose()


def make_video(path: Path, blurred=False):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (96, 64))
    assert writer.isOpened(), 'Test video encoder unavailable'
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8)
    try:
        for i in range(30):
            pixels = np.roll(frame, i, axis=1)
            if blurred:
                pixels = cv2.GaussianBlur(pixels, (15, 15), 4)
            writer.write(pixels)
    finally:
        writer.release()
    return path


@pytest.fixture
def media(tmp_path):
    folder = tmp_path / 'media'
    folder.mkdir()
    rng = np.random.default_rng(7)
    Image.fromarray(rng.integers(0, 255, (80, 120, 3), dtype=np.uint8)).save(folder / 'photo.png')
    (folder / 'copy.png').write_bytes((folder / 'photo.png').read_bytes())
    make_video(folder / 'clip.avi')
    (folder / 'copy.avi').write_bytes((folder / 'clip.avi').read_bytes())
    return folder
