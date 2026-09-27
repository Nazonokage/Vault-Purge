# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-09-27

### UI Enhancements
- Added **Grid / List view toggle**: Switch between card grid layout and detailed list view with compact 72px thumbnails, inline metadata, and persistent preference.
- Added **Show in folder**: Reveal selected media files and move destinations directly in the system file manager (Windows Explorer, macOS Finder, Linux).
- Added interactive directory browser dialog with drive selection, parent navigation, path typing, and pagination.
- Added media type, orientation, status, and match filters; sorting by path, size, modification date, sharpness, and video duration.
- Start with empty results and zero counts on every page load; no automatic scanning or reopening of earlier results.
- Scope browser results, duplicate groups, and counts to the manually selected scan's file membership, keeping earlier directories out of new scan results.
- Add persistent Scan history, Show last scan, Clear view, and confirmed Clear scan history controls.
- History clearing preserves media files, analysis cache, and move/restore records; cleared scan IDs are not reused.
- Record CLI and browser scans, including options, completion/failure, timestamps, and summary counts. Historical membership shows the latest cached file details rather than immutable snapshots.
- Schema v4 imports old cached directories as explicitly labelled history entries with unknown scan dates.
- Validation: 18 tests passed, including scan isolation, non-recursive membership, failed scans, persistence, clearing history, retained cache hits, and restoration after history clearing. Browser checks confirmed empty startup, explicit last-scan loading, and clearing generated test history.

### Integrity review — 2026-09-27
- Added integrity details: image checks passed, video samples decoded, unchecked, possible corruption, and access errors.
- Full image scans verify structure and decode every frame to catch truncated/corrupt data; orientation-only scans remain explicitly unchecked.
- Added a Possible corruption filter, failure reasons, and Prepare quarantine suggestions. Unsupported formats/codecs can produce the same flag.
- Suspect files use the existing preview/confirm workflow with `_corrupt_review` suggested as the destination; no permanent deletion is performed.
- Restore and startup recovery preserve integrity findings and error status. Repaired files clear their flags after successful re-analysis.
- Schema v3 preserves existing records; the next scan populates integrity results.
- Validation: 16 tests passed, including truncation, access-error classification, corrupt image/video scanning, preview-only safeguards, quarantine/restore, repaired files, and migration. JavaScript syntax check passed.

### Added — 2026-09-27
- Video scanning for MP4, MOV, MKV, AVI, WebM, M4V, MPEG/MPG, and WMV containers supported by the installed decoder.
- Video duration, frame rate, display dimensions, orientation, and cached frame thumbnails.
- Video exact-copy detection and possible-duplicate suggestions requiring similar duration and matching pHashes at 10%, 50%, and 90%; images and videos are grouped separately.
- Median sharpness of sampled video frames, labelled as a sample estimate in the review cards.
- Media-type filters and server-side sorting by path, size, modification time, sharpness, and duration, applied before pagination.
- Local folder selection dialog with drive selection, parent navigation, direct path entry, and paginated subfolders.
- SQLite schema v2 migration preserving existing records and move history; analysis-version invalidation for the new measurements.
- Regression tests covering video decoding, thumbnails, cache reuse, metadata updates, missing/corrupt files, schema upgrade, grouping, filters, sorting, directory browsing, and move/restore safeguards.
- Reproducible dependency lockfile, including the OpenCV headless decoder and development dependencies.

### Fixed — 2026-09-27
- Refresh committed move records before serialization so move and restore responses include their state.
- Exclude only non-restored backup destinations from scans.
- Avoid loading groups before checking whether a scan is already running on page reload.
- Correct README launch commands and clarify that the resolver only suggests a keeper.

### Validation — 2026-09-27
- 13 automated tests passed on Windows, including generated AVI videos and actual copy/verify/move/restore round trips in temporary folders.
- CLI help and JavaScript syntax checks passed.
- Browser-verified folder selection, a four-file mixed-media scan, video-only filtering, duration sorting, and video thumbnails using generated sample media.
- Video checks sample frames only; they do not compare audio or establish whole-clip identity. Duration depends on decoder metadata.

### Initial implementation
- Core logic for hashing (`hasher.py`), classifying (`classifier.py`), and grouping (`grouper.py`) images.
- Scanner (`scanner.py`) to parse directories for target files.
- Local storage and database models using `sqlmodel`.
- Web interface static files (HTML, JS, CSS) in `vault_purge/ui/static/`.
- Utilities for EXIF data parsing (`exif_handler.py`), thumbnail caching (`thumb_cache.py`), and file operations (`file_ops.py`).
- Initial setup in `pyproject.toml` with dependencies (`fastapi`, `pillow`, `ImageHash`, `sqlmodel`, etc.).
