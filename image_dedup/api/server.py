import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from image_dedup.api.settings import Settings
from image_dedup.core.grouper import group_images
from image_dedup.core.scanner import fingerprint, scan
from image_dedup.storage.database import open_database
from image_dedup.storage.models import ImageRecord, MoveRecord
from image_dedup.utils.file_ops import execute_moves, preview_moves, recover_journal, restore_move
from image_dedup.utils.thumb_cache import thumbnail


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
    job = {"state": "idle", "stats": None, "error": None}
    group_cache = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        pool.shutdown(wait=True)
        engine.dispose()

    app = FastAPI(title="Image Dedup", lifespan=lifespan)
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
        return job.copy()

    @app.post("/api/scan", status_code=202)
    def start_scan(body: ScanRequest):
        path = Path(body.path).expanduser()
        if not path.is_dir():
            raise HTTPException(400, "Choose an existing directory")
        require_lock()
        job.update(state="running", stats=None, error=None)
        invalidate()

        def run():
            try:
                stats = scan(path, engine, workers=settings.workers, classify_only=body.classify_only,
                             recursive=body.recursive, force=body.force,
                             progress=lambda stats: job.update(stats=stats.copy()))
                job.update(state="complete", stats=stats)
            except Exception as exc:
                job.update(state="error", error=str(exc))
            finally:
                invalidate()
                lock.release()
        pool.submit(run)
        return {"state": "running"}

    @app.get("/api/summary")
    def summary():
        with Session(engine) as session:
            counts = dict(session.exec(select(ImageRecord.status, func.count()).group_by(ImageRecord.status)).all())
            roots = session.exec(select(ImageRecord.root).distinct()).all()
            blurry = session.exec(select(func.count()).select_from(ImageRecord).where(ImageRecord.status == "active", ImageRecord.blur_score < settings.blur_threshold)).one()
            return {"counts": counts, "roots": roots, "blurry": blurry}

    @app.get("/api/images")
    def images(orientation: str | None = None, status: str = "active", blurry: bool = False,
               root: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=200)):
        query = select(ImageRecord).where(ImageRecord.status == status)
        if orientation:
            query = query.where(ImageRecord.orientation == orientation)
        if root:
            query = query.where(ImageRecord.root == root)
        if blurry:
            query = query.where(ImageRecord.blur_score < settings.blur_threshold)
        with Session(engine) as session:
            total = session.exec(select(func.count()).select_from(query.subquery())).one()
            return {"total": total, "items": session.exec(query.order_by(ImageRecord.path).offset(offset).limit(limit)).all()}

    @app.get("/api/groups")
    def groups(root: str | None = None, kind: str | None = None, orientation: str | None = None,
               offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        if lock.locked():
            raise HTTPException(409, "Wait for the current operation to finish")
        key = (root, settings.phash_threshold)
        if key not in group_cache:
            with Session(engine) as session:
                query = select(ImageRecord).where(ImageRecord.status == "active")
                if root:
                    query = query.where(ImageRecord.root == root)
                result = group_images(session.exec(query).all(), settings.phash_threshold)
                group_cache[key] = [{**g, "members": [r.model_dump() for r in g["members"]]} for g in result]
        result = [g for g in group_cache[key] if (not kind or g["kind"] == kind)
                  and (not orientation or any(r["orientation"] == orientation for r in g["members"]))]
        return {"total": len(result), "items": result[offset:offset + limit]}

    @app.get("/thumb/{image_id}")
    def thumb(image_id: int):
        with Session(engine) as session:
            record = session.get(ImageRecord, image_id)
            if not record or record.status != "active":
                raise HTTPException(404, "Image unavailable")
            path = Path(record.path)
            try:
                if path.is_symlink() or path.resolve() != path:
                    raise ValueError("Image path changed")
                size, mtime, ctime = fingerprint(path)
                data = thumbnail(str(path), settings.thumb_size, mtime, size, ctime)
            except Exception:
                raise HTTPException(404, "Image unavailable; scan again")
            return Response(data, media_type="image/jpeg")

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

    @app.post("/api/move")
    def move(body: ConfirmRequest):
        if settings.dry_run or not body.confirm:
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

    static = Path(__file__).resolve().parents[1] / "ui" / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app
