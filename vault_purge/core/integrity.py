"""Integrity findings are evidence for review, never deletion decisions."""


class SuspectedCorruption(ValueError):
    """The decoder rejected media; unsupported formats can produce the same result."""


def failure_kind(error):
    if isinstance(error, SuspectedCorruption):
        return "suspect"
    if isinstance(error, (PermissionError, FileNotFoundError, OSError)):
        return "unreadable"
    return "unchecked"
