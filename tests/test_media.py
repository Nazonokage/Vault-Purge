import sqlite3
from pathlib import Path

import pytest
from PIL import Image, ImageFilter
from sqlmodel import Session, select

from vault_purge.core.classifier import classify
from vault_purge.core.hasher import analyze_image, blur_score
from vault_purge.core.video import analyze_video
from vault_purge.core.scanner import scan
from vault_purge.core.grouper import group_images
from vault_purge.storage.database import open_database
from vault_purge.storage.models import ImageRecord
from vault_purge.utils.thumb_cache import thumbnail
from conftest import make_video


@pytest.mark.parametrize('width,height,expected', [(100,200,'PORTRAIT'),(200,100,'LANDSCAPE'),(100,100,'SQUARE'),(0,1,'UNKNOWN')])
def test_orientation(width, height, expected):
    assert classify(width,height) == expected


def test_exif_and_blur(media):
    image = Image.open(media / 'photo.png')
    assert blur_score(image) > blur_score(image.filter(ImageFilter.GaussianBlur(4)))
    exif = Image.Exif()
    exif[274] = 6
    image.save(media / 'rotated.jpg', exif=exif)
    assert analyze_image(str(media / 'rotated.jpg'))['orientation'] == 'PORTRAIT'


def test_video_analysis_and_thumbnail(media):
    result = analyze_video(str(media / 'clip.avi'))
    assert result['duration'] == pytest.approx(3)
    assert (result['width'], result['height']) == (96,64)
    assert len(result['frame_hashes'].split(',')) == 3
    assert result['blur_score'] > 0
    blurred = analyze_video(str(make_video(media / 'blurred.avi', True)))
    assert blurred['blur_score'] < result['blur_score']
    assert thumbnail(str(media / 'clip.avi'), 64, 0, 0, 0).startswith(b'\xff\xd8')


def test_scan_cache_change_missing_and_corrupt(media, engine, monkeypatch):
    result = scan(media, engine, workers=1)
    assert result == dict(found=4, cached=0, analyzed=4, errors=0)
    import vault_purge.core.scanner as scanner
    original = scanner.analyze_media
    def forbidden(*args):
        raise AssertionError('Cached files must never be submitted for analysis')
    monkeypatch.setattr(scanner, 'analyze_media', forbidden)
    monkeypatch.setattr(scanner, 'md5_file', forbidden)
    assert scan(media, engine, workers=1)['cached'] == 4
    monkeypatch.undo()
    Image.new('RGB',(30,60),'red').save(media / 'photo.png')
    (media / 'copy.png').unlink()
    (media / 'bad.mp4').write_bytes(b'broken video')
    result = scan(media, engine, workers=1)
    assert result['analyzed'] == 1 and result['cached'] == 2 and result['errors'] == 1
    with Session(engine) as session:
        rows = {Path(r.path).name:r for r in session.exec(select(ImageRecord))}
        assert rows['copy.png'].status == 'missing'
        assert rows['bad.mp4'].status == 'error'
        assert rows['bad.mp4'].media_type == 'video'
        assert rows['photo.png'].orientation == 'PORTRAIT'


def test_classify_then_full_scan(media, engine):
    assert scan(media, engine, workers=1, classify_only=True)['analyzed'] == 4
    with Session(engine) as session:
        assert all(r.md5 is None for r in session.exec(select(ImageRecord)))
    assert scan(media, engine, workers=1)['analyzed'] == 4
    assert scan(media, engine, workers=1)['cached'] == 4


def record(id, media_type='image', phash='0', **kwargs):
    return ImageRecord(id=id, root='/media',path=f'/media/{id}',size=100,mtime_ns=1,ctime_ns=1,
                       md5=str(id),media_type=media_type,phash=phash, **kwargs)


def test_video_groups_require_all_samples_and_duration():
    a=record(1,'video',duration=3,frame_hashes='0,0,0')
    b=record(2,'video',duration=3.1,frame_hashes='0,1,0')
    c=record(3,'video',duration=8,frame_hashes='0,0,0')
    d=record(4,'video',duration=3,frame_hashes='0,ffff,0')
    image=record(5)
    groups=group_images([a,b,c,d,image],threshold=2)
    assert len(groups)==1
    assert {r.id for r in groups[0]['members']} == {1,2}


def test_no_transitive_chaining_and_exact_groups():
    a,b,c=record(1,phash='0'),record(2,phash='3'),record(3,phash='f')
    groups=group_images([a,b,c],2)
    assert [{r.id for r in g['members']} for g in groups] == [{1,2}]
    b.md5=a.md5
    assert group_images([b,a],2)[0]['kind']=='exact'
    assert group_images([b,a],2)[0]['recommendation']==group_images([a,b],2)[0]['recommendation']


def test_schema_upgrade_preserves_rows(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    engine=open_database(path)
    with Session(engine) as session:
        session.add(record(1));session.commit()
    engine.dispose()
    with sqlite3.connect(path) as connection:
        connection.execute('DROP INDEX ix_imagerecord_media_type')
        for name in ('media_type','duration','fps','frame_hashes','integrity'):
            connection.execute(f'ALTER TABLE imagerecord DROP COLUMN {name}')
        connection.execute('PRAGMA user_version=1')
    engine=open_database(path)
    with Session(engine) as session:
        row=session.get(ImageRecord,1)
        assert row.path=='/media/1' and row.media_type=='image' and row.duration is None
        assert row.integrity == 'unchecked'
    engine.dispose()
