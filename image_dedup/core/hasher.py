import hashlib
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image

from image_dedup.core.classifier import classify
from image_dedup.utils.exif_handler import corrected, display_dimensions

ANALYSIS_VERSION = 1


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
    with Image.open(path) as image:
        width, height = display_dimensions(image)
        result = dict(width=width, height=height, orientation=classify(width, height))
        if hashing:
            fixed = corrected(image)
            result.update(phash=str(imagehash.phash(fixed)), blur_score=blur_score(fixed))
        return result
