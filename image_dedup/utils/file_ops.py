"""Journaled copy/verify/remove operations. No overwrite, no permanent delete API."""
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from image_dedup.core.hasher import md5_file
from image_dedup.core.scanner import fingerprint
from image_dedup.storage.models import ImageRecord, MoveRecord


def checked_source(record):
    path = Path(record.path)
    if path.is_symlink() or not path.is_file() or path.resolve() != path:
        raise ValueError(f"File unavailable or redirected: {path}")
    if fingerprint(path) != (record.size, record.mtime_ns, record.ctime_ns):
        raise ValueError(f"File changed; scan again: {path}")
    if record.md5 and md5_file(path) != record.md5:
        raise ValueError(f"File contents changed; scan again: {path}")
    return path


def preview_moves(session, ids, destination):
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Select distinct image IDs")
    if not destination.strip():
        raise ValueError("Destination is required")
    plans = []
    destinations = set()
    for image_id in ids:
        record = session.get(ImageRecord, image_id)
        if not record or record.status != "active":
            raise ValueError(f"Image {image_id} is not available")
        source = checked_source(record)
        root = Path(record.root)
        base = Path(destination).expanduser()
        if not base.is_absolute():
            base = root / base
        base = base.resolve()
        if base == root or base in root.parents:
            raise ValueError("Choose a separate backup directory")
        target = base / source.relative_to(root)
        if base not in target.resolve().parents or target.resolve() != target:
            raise ValueError("Destination contains a redirected directory")
        if target.exists() or target.is_symlink() or str(target).casefold() in destinations:
            raise ValueError(f"Destination already exists or collides: {target}")
        destinations.add(str(target).casefold())
        plans.append(dict(id=image_id, source=str(source), destination=str(target),
                          size=record.size, mtime_ns=record.mtime_ns, ctime_ns=record.ctime_ns,
                          md5=record.md5 or md5_file(source)))
    return plans


def transfer(source: Path, destination: Path, digest: str):
    """Exclusive creation also supports moves between disks. Interrupted copies are journaled."""
    if source.is_symlink() or source.resolve() != source or destination.resolve() != destination:
        raise ValueError("A path was redirected")
    before = fingerprint(source)
    if md5_file(source) != digest:
        raise ValueError("Source contents changed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    shutil.copystat(source, destination)
    if md5_file(destination) != digest or fingerprint(source) != before or md5_file(source) != digest:
        raise ValueError("File changed during transfer; both paths retained for review")
    source.unlink()


def execute_moves(engine, plans):
    results = []
    with Session(engine) as session:
        # Check the complete plan before the first change.
        for plan in plans:
            record = session.get(ImageRecord, plan["id"])
            if not record or record.status != "active":
                raise ValueError("Selection is stale; create a new preview")
            checked_source(record)
            if (record.size, record.mtime_ns, record.ctime_ns) != (plan["size"], plan["mtime_ns"], plan["ctime_ns"]):
                raise ValueError("Preview is stale; create a new preview")
            if Path(plan["destination"]).exists():
                raise ValueError("A destination now exists; create a new preview")
        for plan in plans:
            record = session.get(ImageRecord, plan["id"])
            move = MoveRecord(image_id=record.id, original=record.path,
                              destination=plan["destination"], md5=plan["md5"],
                              created_at=datetime.now(timezone.utc).isoformat())
            session.add(move)
            session.commit()  # Journal must exist before touching the files.
            try:
                checked_source(record)
                transfer(Path(move.original), Path(move.destination), move.md5)
                move.state = "moved"
                record.status = "moved"
                record.user_decision = "move"
                session.add(record)
            except Exception as exc:
                move.state = "attention"
                move.error = str(exc)
            session.add(move)
            session.commit()
            results.append(move.model_dump())
            if move.state == "attention":
                break
    return results


def restore_move(engine, move_id):
    with Session(engine) as session:
        move = session.get(MoveRecord, move_id)
        if not move or move.state != "moved":
            raise ValueError("Only completed moves can be restored")
        source, target = Path(move.destination), Path(move.original)
        if target.exists() or target.is_symlink():
            raise ValueError("Original path is occupied; restore will not overwrite it")
        if not source.is_file() or md5_file(source) != move.md5:
            raise ValueError("Backup is missing or modified")
        move.state = "restoring"
        session.add(move)
        session.commit()
        try:
            transfer(source, target, move.md5)
            record = session.get(ImageRecord, move.image_id)
            record.size, record.mtime_ns, record.ctime_ns = fingerprint(target)
            record.status = "active"
            record.user_decision = "restored"
            move.state = "restored"
            session.add(record)
        except Exception as exc:
            move.state = "attention"
            move.error = str(exc)
        session.add(move)
        session.commit()
        return move.model_dump()


def recover_journal(engine):
    """Reconcile completed transfers after a crash; ambiguous cases remain untouched."""
    with Session(engine) as session:
        for move in session.exec(select(MoveRecord).where(MoveRecord.state.in_(["pending", "restoring"]))):
            restoring = move.state == "restoring"
            source = Path(move.destination if restoring else move.original)
            target = Path(move.original if restoring else move.destination)
            record = session.get(ImageRecord, move.image_id)
            if not source.exists() and target.is_file() and not target.is_symlink() and md5_file(target) == move.md5:
                move.state = "restored" if restoring else "moved"
                record.status = "active" if restoring else "moved"
                if restoring:
                    record.size, record.mtime_ns, record.ctime_ns = fingerprint(target)
                session.add(record)
            else:
                move.state = "attention"
                move.error = "Interrupted operation. Inspect original and destination; no files were changed by recovery."
            session.add(move)
        session.commit()
