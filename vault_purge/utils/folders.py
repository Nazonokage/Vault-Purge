"""Directory-only browser for the local web UI; never uploads files."""
import os
import string
from pathlib import Path


def browse_folders(path=None, offset=0, limit=100):
    if not path:
        roots = [Path(f"{letter}:/") for letter in string.ascii_uppercase if Path(f"{letter}:/").is_dir()] if os.name == "nt" else [Path("/")]
        return {"path": "", "parent": None, "items": [str(root) for root in roots], "total": len(roots)}
    current = Path(path).expanduser().resolve(strict=True)
    if not current.is_dir():
        raise ValueError("Choose a directory")
    directories = []
    with os.scandir(current) as entries:
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    directories.append(str(Path(entry.path)))
            except OSError:
                continue
    directories.sort(key=str.casefold)
    return {"path": str(current), "parent": str(current.parent) if current != current.parent else "",
            "items": directories[offset:offset + limit], "total": len(directories)}
