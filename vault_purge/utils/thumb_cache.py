from functools import lru_cache
from io import BytesIO
from PIL import Image, ImageOps
from pathlib import Path
from vault_purge.core.video import VIDEO_EXTENSIONS, video_thumbnail


@lru_cache(maxsize=256)
def thumbnail(path: str, size: int, mtime_ns: int, file_size: int, ctime_ns: int) -> bytes:
    if Path(path).suffix.lower() in VIDEO_EXTENSIONS:
        image = video_thumbnail(path)
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=82)
        return output.getvalue()
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=82)
        return output.getvalue()
