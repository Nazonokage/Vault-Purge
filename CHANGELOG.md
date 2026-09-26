# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Core logic for hashing (`hasher.py`), classifying (`classifier.py`), and grouping (`grouper.py`) images.
- Scanner (`scanner.py`) to parse directories for target files.
- Local storage and database models using `sqlmodel`.
- Web interface static files (HTML, JS, CSS) in `image_dedup/ui/static/`.
- Utilities for EXIF data parsing (`exif_handler.py`), thumbnail caching (`thumb_cache.py`), and file operations (`file_ops.py`).
- Initial setup in `pyproject.toml` with dependencies (`fastapi`, `pillow`, `ImageHash`, `sqlmodel`, etc.).

### Planned
- Filter/sort functionality in the UI.
- File/folder selector dialog for choosing the target scan directory.
