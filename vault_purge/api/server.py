import secrets
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, delete
from sqlmodel import Session, select
from starlette.middleware.trustedhost import TrustedHostMiddleware
from vault_purge import __version__

from vault_purge.api.settings import Settings
from vault_purge.core.grouper import group_images
from vault_purge.core.scanner import fingerprint, scan
from vault_purge.storage.database import open_database
from vault_purge.storage.models import ImageRecord, MoveRecord, ScanRecord, ScanMember
from vault_purge.utils.file_ops import execute_moves, preview_moves, recover_journal, restore_move, reveal_file, suggest_destination
from vault_purge.utils.thumb_cache import thumbnail
from vault_purge.utils.folders import browse_folders
from vault_purge.core.playback import PreviewCache
from vault_purge.core.deep_compare import SEGMENTS_VERSION, extract_segments, compare_segments

SortOrder = Literal["name", "size_desc", "size_asc", "newest", "oldest", "blur", "duration"]


def public_media(record):
    return record.model_dump(exclude={"audio_fingerprint", "segments_json"})


class ScanRequest(BaseModel):
    path: str
    classify_only: bool = False
    recursive: bool = True
    force: bool = False


class PreviewRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=10000)
    destination: str


class ConfirmRequest(BaseModel):
    token: str
    confirm: bool = False
    allow_move: bool = False


class DestinationRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=10000)


class CompareRequest(BaseModel):
    ids: list[int] = Field(min_length=2, max_length=2)


class Preferences(BaseModel):
    dry_run: bool = True
    show_recommendation: bool = True
    phash_threshold: int = Field(default=10, ge=0, le=20)
    blur_threshold: float = Field(default=100, ge=0)


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine = open_database(settings.database)
    recover_journal(engine)
    pool = ThreadPoolExecutor(max_workers=1)
    lock = threading.Lock()
    token = secrets.token_urlsafe(32)
    previews = {}
    job = {"state": "idle", "stats": None, "error": None, "scan_id": None}
    group_cache = {}
    playback = PreviewCache(settings.database.resolve().parent / "previews")
    comparison = {"state": "idle", "result": None, "error": None}

    @asynccontextmanager
    async def lifespan(app):
        yield
        pool.shutdown(wait=True)
        playback.close()
        engine.dispose()

    app = FastAPI(title="Vault Purge", version=__version__, lifespan=lifespan)
    app.state.engine = engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not secrets.compare_digest(request.headers.get("x-session-token", ""), token):
            return JSONResponse({"detail": "Session token required; reload the page"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def require_lock():
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "A scan or file operation is running")

    def invalidate():
        group_cache.clear()
        previews.clear()
        thumbnail.cache_clear()

    def scan_filter(scan_id):
        with Session(engine) as session:
            if not session.get(ScanRecord, scan_id):
                raise HTTPException(404, "Scan history entry was cleared or does not exist")
        return ImageRecord.id.in_(select(ScanMember.image_id).where(ScanMember.scan_id == scan_id))

    @app.get("/api/scans")
    def scan_history(offset: int = Query(0, ge=0), limit: int = Query(48, ge=1, le=200)):
        with Session(engine) as session:
            total = session.exec(select(func.count()).select_from(ScanRecord)).one()
            rows = session.exec(select(ScanRecord).order_by(ScanRecord.id.desc()).offset(offset).limit(limit)).all()
            return {"total": total, "items": rows}

    @app.delete("/api/scans")
    def clear_scan_history():
        require_lock()
        try:
            with Session(engine) as session:
                session.exec(delete(ScanMember))
                session.exec(delete(ScanRecord))
                session.commit()
            job.update(state="idle", stats=None, error=None, scan_id=None)
            invalidate()
            return {"cleared": True}
        finally:
            lock.release()

    @app.get("/api/settings")
    def get_settings():
        return {**settings.model_dump(mode="json"), "session_token": token}

    @app.put("/api/settings")
    def put_settings(preferences: Preferences):
        require_lock()
        try:
            for key, value in preferences.model_dump().items():
                setattr(settings, key, value)
            invalidate()
            return get_settings()
        finally:
            lock.release()

    @app.get("/api/scan")
    def scan_status():
        result = job.copy()
        result["elapsed"] = round((time.monotonic() if job["state"] == "running" else job.get("finished", time.monotonic())) - job["started"], 1) if job.get("started") else 0
        return result

    @app.post("/api/folders")
    def folders(path: str | None = None, offset: int = Query(0, ge=0)):
        try:
            return browse_folders(path, offset)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, f"Cannot browse this folder: {exc}")

    @app.post("/api/scan", status_code=202)
    def start_scan(body: ScanRequest):
        path = Path(body.path).expanduser()
        if not path.is_dir():
            raise HTTPException(400, "Choose an existing directory")
        require_lock()
        job.update(state="running", stats=None, error=None, scan_id=None, started=time.monotonic())
        invalidate()

        def run():
            try:
                stats = scan(path, engine, workers=settings.workers, classify_only=body.classify_only,
                             recursive=body.recursive, force=body.force,
                             progress=lambda stats: job.update(stats=stats.copy()),
                             on_started=lambda scan_id: job.update(scan_id=scan_id))
                job.update(state="complete", stats=stats)
            except (Exception, KeyboardInterrupt) as exc:
                job.update(state="error", error=str(exc) or "Scan interrupted because an analysis worker or the server was stopped. Scan again to continue using cached results.")
            finally:
                job["finished"] = time.monotonic()
                invalidate()
                lock.release()
        pool.submit(run)
        return {"state": "running"}

    @app.get("/api/summary")
    def summary(scan_id: int | None = None):
        with Session(engine) as session:
            condition = scan_filter(scan_id) if scan_id is not None else True
            counts = dict(session.exec(select(ImageRecord.status, func.count()).where(condition).group_by(ImageRecord.status)).all())
            roots = session.exec(select(ImageRecord.root).where(condition).distinct()).all()
            blurry = session.exec(select(func.count()).select_from(ImageRecord).where(condition, ImageRecord.status == "active", ImageRecord.blur_score < settings.blur_threshold)).one()
            return {"counts": counts, "roots": roots, "blurry": blurry}

    @app.get("/api/images")
    def images(orientation: str | None = None, status: str = "active", blurry: bool = False,
               scan_id: int | None = None,
               integrity: Literal["unchecked", "checked", "sampled", "suspect", "unreadable", "unsupported"] | None = None,
               root: str | None = None, media_type: Literal["image", "video", "audio"] | None = None,
               sort: SortOrder = "name", offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=200)):
        query = select(ImageRecord).where(ImageRecord.status == status)
        if scan_id is not None:
            query = query.where(scan_filter(scan_id))
        if orientation:
            query = query.where(ImageRecord.orientation == orientation)
        if root:
            query = query.where(ImageRecord.root == root)
        if blurry:
            query = query.where(ImageRecord.blur_score < settings.blur_threshold)
        if media_type:
            query = query.where(ImageRecord.media_type == media_type)
        if integrity:
            query = query.where(ImageRecord.integrity == integrity)
        ordering = {"name": ImageRecord.path, "size_desc": ImageRecord.size.desc(), "size_asc": ImageRecord.size,
                    "newest": ImageRecord.mtime_ns.desc(), "oldest": ImageRecord.mtime_ns,
                    "blur": ImageRecord.blur_score.asc().nulls_last(), "duration": ImageRecord.duration.desc().nulls_last()}[sort]
        with Session(engine) as session:
            total = session.exec(select(func.count()).select_from(query.subquery())).one()
            return {"total": total, "items": [public_media(r) for r in session.exec(query.order_by(ordering, ImageRecord.path, ImageRecord.id).offset(offset).limit(limit))]}

    @app.get("/api/groups")
    def groups(root: str | None = None, kind: str | None = None, orientation: str | None = None,
               scan_id: int | None = None,
               media_type: Literal["image", "video", "audio"] | None = None, sort: SortOrder = "name",
               offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        if lock.locked():
            raise HTTPException(409, "Wait for the current operation to finish")
        condition = scan_filter(scan_id) if scan_id is not None else True
        key = (root, settings.phash_threshold, scan_id)
        if key not in group_cache:
            with Session(engine) as session:
                query = select(ImageRecord).where(ImageRecord.status == "active", condition)
                if root:
                    query = query.where(ImageRecord.root == root)
                result = group_images(session.exec(query).all(), settings.phash_threshold)
                group_cache[key] = [{**g, "members": [public_media(r) for r in g["members"]]} for g in result]
        result = [g for g in group_cache[key] if (not kind or g["kind"] == kind)
                  and (not orientation or any(r["orientation"] == orientation for r in g["members"]))
                  and (not media_type or g["members"][0]["media_type"] == media_type)]
        def sort_group(group):
            members = group["members"]
            value = {"name": min(r["path"] for r in members),
                     "size_desc": -sum(r["size"] for r in members), "size_asc": sum(r["size"] for r in members),
                     "newest": -max(r["mtime_ns"] for r in members), "oldest": min(r["mtime_ns"] for r in members),
                     "blur": min((r["blur_score"] for r in members if r["blur_score"] is not None), default=float("inf")),
                     "duration": -max((r["duration"] or 0 for r in members), default=0)}[sort]
            return value, group["id"]
        result.sort(key=sort_group)
        return {"total": len(result), "items": result[offset:offset + limit]}

    @app.get("/thumb/{image_id}")
    def thumb(image_id: int):
        with Session(engine) as session:
            record = session.get(ImageRecord, image_id)
            if not record:
                raise HTTPException(404, "Image unavailable")
            path = Path(record.path)
            if not path.exists() and record.status == "moved":
                move = session.exec(
                    select(MoveRecord)
                    .where(MoveRecord.image_id == image_id, MoveRecord.state == "moved")
                    .order_by(MoveRecord.id.desc())
                ).first()
                if move and Path(move.destination).exists():
                    path = Path(move.destination)
            if record.status not in {"active", "moved"} and not path.exists():
                raise HTTPException(404, "Image unavailable")
            try:
                if path.is_symlink() or path.resolve() != path:
                    raise ValueError("Image path changed")
                size, mtime, ctime = fingerprint(path)
                data = thumbnail(str(path), settings.thumb_size, mtime, size, ctime)
            except Exception:
                raise HTTPException(404, "Image unavailable; scan again")
            return Response(data, media_type="image/jpeg")

    def playable_record(media_id):
        with Session(engine) as session:
            record = session.get(ImageRecord, media_id)
            if not record or record.media_type not in {"video", "audio"} or record.status != "active":
                raise HTTPException(404, "Available audio or video required")
            path = Path(record.path)
            try:
                if path.is_symlink() or path.resolve() != path or fingerprint(path) != (record.size, record.mtime_ns, record.ctime_ns):
                    raise ValueError("File changed; scan again")
            except (OSError, ValueError) as exc:
                raise HTTPException(409, str(exc))
            return record, path

    @app.get("/media/{media_id}")
    def original_media(media_id: int):
        record, path = playable_record(media_id)
        return FileResponse(path)

    @app.get("/api/compare")
    def comparison_status():
        return comparison.copy()

    @app.post("/api/compare", status_code=202)
    def start_comparison(body: CompareRequest):
        if len(set(body.ids)) != 2:
            raise HTTPException(400, "Select two different audio or video files")
        require_lock()
        try:
            records = [playable_record(media_id)[0] for media_id in body.ids]
            comparison.update(state="running", result=None, error=None)
            def work():
                try:
                    segments = []
                    for record in records:
                        current, path = playable_record(record.id)
                        if current.segments_json and current.segments_version == SEGMENTS_VERSION:
                            data = json.loads(current.segments_json)
                        else:
                            data = extract_segments(path, current.media_type)
                            playable_record(current.id)  # Reject analysis of a changed source.
                            with Session(engine) as session:
                                row = session.get(ImageRecord, current.id)
                                row.segments_json = json.dumps(data)
                                row.segments_version = SEGMENTS_VERSION
                                session.add(row)
                                session.commit()
                        segments.append(data)
                    result = compare_segments(*segments, records[0].duration, records[1].duration)
                    for record in records:
                        playable_record(record.id)
                    result["files"] = [dict(id=r.id, path=r.path) for r in records]
                    comparison.update(state="complete", result=result)
                except Exception as exc:
                    comparison.update(state="error", error=str(exc))
                finally:
                    lock.release()
            pool.submit(work)
        except Exception:
            lock.release()
            raise
        return {"state": "running"}

    @app.post("/api/media/{media_id}/preview")
    def prepare_playback(media_id: int):
        record, path = playable_record(media_id)
        try:
            key, status = playback.request(path, record.media_type, record.duration)
            return {"key": key, "state": status["state"], "error": status["error"]}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/media/{media_id}/preview/{key}")
    def playback_status(media_id: int, key: str):
        record, path = playable_record(media_id)
        if key != playback.key(path, record.media_type):
            raise HTTPException(409, "Preview source changed; prepare it again")
        status = playback.status(key)
        if not status:
            raise HTTPException(404, "Preview unavailable")
        return {"state": status["state"], "error": status["error"], "url": f"/media/{media_id}/preview/{key}" if status["state"] == "ready" else None}

    @app.get("/media/{media_id}/preview/{key}")
    def serve_playback(media_id: int, key: str):
        record, path = playable_record(media_id)
        if key != playback.key(path, record.media_type):
            raise HTTPException(409, "Preview source changed")
        status = playback.status(key)
        if not status or status["state"] != "ready":
            raise HTTPException(404, "Preview unavailable")
        return FileResponse(status["path"], media_type="video/mp4" if record.media_type == "video" else "audio/mp4")

    @app.post("/api/move/preview")
    def preview(body: PreviewRequest):
        require_lock()
        try:
            with Session(engine) as session:
                plans = preview_moves(session, body.ids, body.destination)
            preview_token = secrets.token_urlsafe(24)
            previews.clear()
            previews[preview_token] = (time.monotonic(), plans)
            return {"token": preview_token, "dry_run": settings.dry_run, "items": plans}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))
        finally:
            lock.release()

    @app.post("/api/move/destination")
    def destination(body: DestinationRequest):
        try:
            with Session(engine) as session:
                return {"destination": suggest_destination(session, body.ids)}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/move")
    def move(body: ConfirmRequest):
        if (settings.dry_run and not body.allow_move) or not body.confirm:
            raise HTTPException(400, "Disable preview-only mode and explicitly confirm first")
        require_lock()
        try:
            preview = previews.pop(body.token, None)
            if not preview or time.monotonic() - preview[0] > 600:
                raise ValueError("Preview expired; create a fresh preview")
            return {"items": execute_moves(engine, preview[1])}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))
        finally:
            invalidate()
            lock.release()

    @app.get("/api/moves")
    def moves(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        with Session(engine) as session:
            return session.exec(select(MoveRecord).order_by(MoveRecord.id.desc()).offset(offset).limit(limit)).all()

    @app.post("/api/moves/{move_id}/restore")
    def restore(move_id: int, body: ConfirmRequest):
        if settings.dry_run or not body.confirm:
            raise HTTPException(400, "Disable preview-only mode and confirm restore")
        require_lock()
        try:
            return restore_move(engine, move_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))
        finally:
            invalidate()
            lock.release()

    @app.post("/api/images/{image_id}/reveal")
    def reveal_image(image_id: int):
        with Session(engine) as session:
            record = session.get(ImageRecord, image_id)
            if not record:
                raise HTTPException(404, "Media record not found")
            path = Path(record.path)
            if not path.exists():
                move = session.exec(
                    select(MoveRecord)
                    .where(MoveRecord.image_id == image_id, MoveRecord.state == "moved")
                    .order_by(MoveRecord.id.desc())
                ).first()
                if move and Path(move.destination).exists():
                    path = Path(move.destination)
                else:
                    raise HTTPException(404, "File does not exist on disk")
            try:
                reveal_file(path)
            except Exception as exc:
                raise HTTPException(500, f"Failed to reveal file: {exc}")
            return {"revealed": True, "path": str(path)}

    @app.post("/api/moves/{move_id}/reveal")
    def reveal_move(move_id: int, target: Literal["original", "destination"] = "destination"):
        with Session(engine) as session:
            move = session.get(MoveRecord, move_id)
            if not move:
                raise HTTPException(404, "Move record not found")
            path_str = move.destination if target == "destination" else move.original
            path = Path(path_str)
            if not path.exists():
                raise HTTPException(404, f"File does not exist on disk: {path_str}")
            try:
                reveal_file(path)
            except Exception as exc:
                raise HTTPException(500, f"Failed to reveal file: {exc}")
            return {"revealed": True, "path": str(path)}

    static = Path(__file__).resolve().parents[1] / "ui" / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app

