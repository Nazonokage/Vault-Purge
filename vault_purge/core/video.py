"""Bounded video sampling; these measurements describe samples, not the whole clip."""
import math
from contextlib import contextmanager
from statistics import median

import cv2
import imagehash
from PIL import Image

from vault_purge.core.classifier import classify
from vault_purge.core.hasher import blur_score
from vault_purge.core.integrity import SuspectedCorruption

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv"}


@contextmanager
def capture(path):
    video = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    try:
        if not video.isOpened():
            raise SuspectedCorruption("Video cannot be decoded (damaged file or unsupported codec)")
        video.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
        yield video
    finally:
        video.release()


def read_frame(video, fraction=0.0):
    count = video.get(cv2.CAP_PROP_FRAME_COUNT)
    if fraction and math.isfinite(count) and count > 0:
        if not video.set(cv2.CAP_PROP_POS_FRAMES, min(int(count * fraction), int(count) - 1)):
            raise ValueError("Video does not support frame seeking")
    ok, frame = video.read()
    if not ok:
        raise SuspectedCorruption("Unable to decode a video sample (possible damage or unsupported codec)")
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def video_thumbnail(path):
    with capture(path) as video:
        try:
            return read_frame(video, .5)
        except ValueError:
            video.set(cv2.CAP_PROP_POS_FRAMES, 0)
            return read_frame(video)


def analyze_video(path, hashing=True):
    with capture(path) as video:
        first = read_frame(video)
        width, height = first.size
        fps = video.get(cv2.CAP_PROP_FPS)
        count = video.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = fps if math.isfinite(fps) and fps > 0 else None
        duration = count / fps if fps and math.isfinite(count) and count > 0 else None
        result = dict(media_type="video", width=width, height=height, orientation=classify(width, height),
                      fps=fps, duration=duration, phash=None, frame_hashes=None, blur_score=None, integrity="sampled")
        if hashing:
            # Unknown-duration media remain available for exact duplicates only.
            samples = [read_frame(video, fraction) for fraction in (.1, .5, .9)] if duration else [first]
            result["blur_score"] = median(blur_score(frame) for frame in samples)
            if duration:
                hashes = [str(imagehash.phash(frame)) for frame in samples]
                result.update(phash=hashes[0], frame_hashes=",".join(hashes))
        return result
