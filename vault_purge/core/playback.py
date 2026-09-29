"""Bounded, on-demand preview cache. Source files are never rewritten."""
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vault_purge.core.media_tools import run_tool, ffmpeg_input

PREVIEW_VERSION = 1


def signature(path):
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class PreviewCache:
    def __init__(self, directory, limit=1024 * 1024 * 1024):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.Lock()
        self.jobs = {}
        # Only files owned by this cache are eligible for cleanup.
        for path in self.directory.glob("*.partial.*"):
            path.unlink(missing_ok=True)

    def key(self, path, media_type):
        return hashlib.sha256(json.dumps([str(path), signature(path), media_type, PREVIEW_VERSION]).encode()).hexdigest()

    def request(self, path, media_type, duration):
        key = self.key(path, media_type)
        suffix = ".mp4" if media_type == "video" else ".m4a"
        output = self.directory / (key + suffix)
        with self.lock:
            if len(self.jobs) > 128:
                self.jobs = {k: v for k, v in self.jobs.items() if v["state"] == "preparing" or k == key}
            if output.is_file():
                output.touch()
                self.jobs[key] = dict(state="ready", path=str(output), error=None)
            elif key not in self.jobs or self.jobs[key]["state"] in {"ready", "error"}:
                if sum(j["state"] == "preparing" for j in self.jobs.values()) >= 4:
                    raise ValueError("Preview queue is full. Wait for a preview to finish.")
                self.jobs[key] = dict(state="preparing", path=None, error=None)
                self.pool.submit(self._convert, key, Path(path), media_type, duration, output)
            return key, self.jobs[key].copy()

    def status(self, key):
        with self.lock:
            job = self.jobs.get(key)
            if job and job["state"] == "ready" and not Path(job["path"]).is_file():
                return dict(state="error", path=None, error="Preview expired. Prepare it again.")
            return job.copy() if job else None

    def _convert(self, key, path, media_type, duration, output):
        temporary = output.with_name(output.stem + ".partial" + output.suffix)
        try:
            before = signature(path)
            args = [*ffmpeg_input(path), "-y"]
            if media_type == "video":
                args += ["-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                         "-c:v", "libx264", "-preset", "fast", "-crf", "24", "-pix_fmt", "yuv420p"]
            else:
                args += ["-map", "0:a:0", "-vn"]
            args += ["-c:a", "aac", "-ac", "2", "-b:a", "160k", "-threads", "2",
                     "-movflags", "+faststart", "-fs", str(self.limit), str(temporary)]
            run_tool("ffmpeg", args, min(7200, max(180, (duration or 300) * 4)))
            if signature(path) != before or self.key(path, media_type) != key:
                raise ValueError("Source changed while preparing preview; scan again")
            if temporary.stat().st_size >= self.limit * .98:
                raise ValueError("Preview exceeds the cache limit; use an external player")
            with self.lock:
                needed = temporary.stat().st_size
                candidates = sorted((p for p in self.directory.iterdir() if p.suffix in {".mp4", ".m4a"}
                                     and ".partial." not in p.name), key=lambda p: p.stat().st_mtime)
                total = sum(p.stat().st_size for p in candidates)
                for old in candidates:
                    if total + needed <= self.limit:
                        break
                    size = old.stat().st_size
                    try:
                        old.unlink()
                        total -= size
                    except OSError:
                        continue  # An actively served preview can be locked on Windows.
                if total + needed > self.limit:
                    raise ValueError("Preview cache is busy or full; close other players and retry")
                temporary.replace(output)
                self.jobs[key] = dict(state="ready", path=str(output), error=None)
        except Exception as exc:
            with self.lock:
                self.jobs[key] = dict(state="error", path=None, error=str(exc))
        finally:
            temporary.unlink(missing_ok=True)

    def close(self):
        self.pool.shutdown(wait=True)
