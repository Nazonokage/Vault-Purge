import hashlib
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image, UnidentifiedImageError
from vault_purge.core.integrity import SuspectedCorruption

from vault_purge.core.classifier import classify
from vault_purge.utils.exif_handler import corrected, display_dimensions

ANALYSIS_VERSION = 3


def md5_file(path: str | Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def blur_score(image: Image.Image) -> float:
    gray = image.convert("L")
    gray.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.float32)
    if min(pixels.shape) < 3:
        return 0.0
    laplacian = (pixels[:-2, 1:-1] + pixels[2:, 1:-1] + pixels[1:-1, :-2]
                 + pixels[1:-1, 2:] - 4 * pixels[1:-1, 1:-1])
    return round(float(laplacian.var()), 4)


def analyze_image(path: str, hashing: bool = True) -> dict:
    """Top-level callable for Windows spawn workers; never send decoded pixels."""
    if hashing:
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                for index in range(getattr(image, "n_frames", 1)):
                    image.seek(index)
                    image.load()
        except (PermissionError, FileNotFoundError):
            raise
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as exc:
            raise SuspectedCorruption(f"Image integrity check failed (damaged or unsupported image): {exc}") from exc
    with Image.open(path) as image:
        width, height = display_dimensions(image)
        result = dict(width=width, height=height, orientation=classify(width, height), media_type="image",
                      duration=None, fps=None, frame_hashes=None, integrity="checked" if hashing else "unchecked")
        if hashing:
            fixed = corrected(image)
            result.update(phash=str(imagehash.phash(fixed)), blur_score=blur_score(fixed))
        return result


def analyze_media(path: str, hashing: bool = True) -> dict:
    from vault_purge.core.audio import AUDIO_EXTENSIONS, analyze_audio
    from vault_purge.core.video import VIDEO_EXTENSIONS, analyze_video
    if Path(path).suffix.lower() in AUDIO_EXTENSIONS:
        return analyze_audio(path, hashing)
    return analyze_video(path, hashing) if Path(path).suffix.lower() in VIDEO_EXTENSIONS else analyze_image(path, hashing)
