from PIL import Image, ImageOps


def display_dimensions(image: Image.Image) -> tuple[int, int]:
    """Read metadata only; orientations 5–8 exchange the display axes."""
    width, height = image.size
    if image.getexif().get(274, 1) in (5, 6, 7, 8):
        return height, width
    return width, height


def corrected(image: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(image)
