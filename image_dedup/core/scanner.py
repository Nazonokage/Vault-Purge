import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from sqlmodel import Session, select

from image_dedup.core.hasher import ANALYSIS_VERSION, analyze_image, md5_file
from image_dedup.storage.models import ImageRecord, MoveRecord

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


def fingerprint(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def walk_images(root: Path, excluded: set[Path], recursive: bool = True):
    def fail(error):
        raise error
    for current, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        dirs[:] = sorted(d for d in dirs if d not in {".image_dedup", "_duplicates_backup"}
                         and not (Path(current) / d).is_symlink()
                         and (Path(current) / d).resolve() not in excluded)
        for name in sorted(files):
            path = Path(current) / name
            if path.suffix.lower() in EXTENSIONS and not path.is_symlink() and path.resolve() not in excluded:
                yield path.resolve()
        if not recursive:
            break


def scan(root: Path, engine, workers=4, classify_only=False, recursive=True, force=False, progress=None):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Scan path must be a directory")
    stats = dict(found=0, cached=0, analyzed=0, errors=0)
    seen = set()
    with Session(engine) as session:
        previous = {r.path: r for r in session.exec(select(ImageRecord).where(ImageRecord.root == str(root)))}
        excluded = {Path(m.destination).resolve() for m in session.exec(select(MoveRecord))}
        # Bound submitted work to a small batch, including decoded worker images.
        with ThreadPoolExecutor(max_workers=min(8, workers * 2)) as io_pool, ProcessPoolExecutor(max_workers=workers) as cpu_pool:
            batch = []

            def flush():
                for path, signature, record, md5_job, image_job in batch:
                    try:
                        data = image_job.result()
                        digest = md5_job.result() if md5_job else None
                        if fingerprint(path) != signature:
                            raise ValueError("File changed during scan; scan again")
                        for key, value in data.items():
                            setattr(record, key, value)
                        record.md5 = digest
                        record.error = None
                        record.status = "active"
                        stats["analyzed"] += 1
                    except Exception as exc:
                        record.error = str(exc)
                        record.status = "error"
                        record.md5 = record.phash = None
                        record.blur_score = None
                        stats["errors"] += 1
                    session.add(record)
                    if progress:
                        progress(stats)
                session.commit()
                batch.clear()

            for path in walk_images(root, excluded, recursive):
                stats["found"] += 1
                seen.add(str(path))
                try:
                    signature = fingerprint(path)
                except OSError:
                    stats["errors"] += 1
                    continue
                record = previous.get(str(path)) or session.exec(select(ImageRecord).where(ImageRecord.path == str(path))).first()
                if record and not force and record.status == "active" and record.version == ANALYSIS_VERSION and (record.size, record.mtime_ns, record.ctime_ns) == signature and (classify_only or (record.md5 and record.phash and record.blur_score is not None)):
                    record.root = str(root)
                    session.add(record)
                    stats["cached"] += 1
                    continue
                if record is None:
                    record = ImageRecord(root=str(root), path=str(path), size=signature[0], mtime_ns=signature[1], ctime_ns=signature[2])
                record.root = str(root)
                record.size, record.mtime_ns, record.ctime_ns = signature
                record.version = ANALYSIS_VERSION
                record.phash = None
                record.blur_score = None
                batch.append((path, signature, record, None if classify_only else io_pool.submit(md5_file, path), cpu_pool.submit(analyze_image, str(path), not classify_only)))
                if len(batch) >= workers * 2:
                    flush()
            flush()
        for path, record in previous.items():
            if path not in seen and record.status in {"active", "error"} and (recursive or Path(path).parent == root):
                record.status = "missing"
                session.add(record)
        session.commit()
    return stats
