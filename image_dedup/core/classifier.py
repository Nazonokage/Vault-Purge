def classify(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "UNKNOWN"
    if width == height:
        return "SQUARE"
    return "PORTRAIT" if height > width else "LANDSCAPE"
