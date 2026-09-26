from functools import lru_cache
from io import BytesIO
from PIL import Image, ImageOps


@lru_cache(maxsize=256)
def thumbnail(path: str, size: int, mtime_ns: int, file_size: int, ctime_ns: int) -> bytes:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=82)
        return output.getvalue()
