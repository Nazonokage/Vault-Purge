# To-Do List

## UI Enhancements
- [x] **Sorting / Filtering**: Media type, orientation, status, and match filters; sort by path, size, modification date, sharpness, or video duration.
- [x] **Folder Selector**: Local directory browser dialog with drives, parent navigation, pagination, and editable path.
- [x] **Show File Location**: Reveal a selected media file in the system file manager.
- [x] **Layout Views**: Grid view and detailed List view toggle with compact thumbnails and persistent preference.

## Video Support
- [x] Scan videos alongside images, cache metadata, and generate frame thumbnails.
- [x] Exact duplicates and possible duplicates using duration and three sampled frame hashes.
- [x] Sampled-frame blur scores, reversible moves, and restore for videos.

## Implementation Roadmap

Implemented the first pass below. Music similarity and deep comparison remain advisory; broader real-media calibration and public release source materials are still pending. Windows media tools are bundled.

### Phase 1 — Scan Feedback
- [x] Show an animated progress strip and scanning indicator as soon as a scan starts.
- [x] Display live found, analyzed, cached, and error counts, plus elapsed time.
- [x] Emit progress updates during discovery and cache reuse, including scans where every file is cached.
- [x] Distinguish scanning, preparing results, completion, and failure states; stop the animation on completion or failure.
- [x] Support reduced-motion preferences and accessible status updates.
- [x] Keep progress indeterminate while the total file count is unknown; avoid an extra directory walk just to calculate a percentage.
- [x] Verify cached-only scans, empty folders, slow analysis, and scan failures.

### Phase 2 — Basic Audio Support
- [x] Add a shared FFmpeg/ffprobe integration for audio analysis and future video previews, with clear missing-tool errors, timeouts, and bounded workers.
- [x] Discover common audio formats: MP3, FLAC, WAV, M4A, OGG, and Opus.
- [x] Store audio metadata: duration, codec, sample rate, and channel count.
- [x] Make cache completeness checks depend on media type; audio must not require image hashes or blur scores.
- [x] Add database migrations and versioned audio analysis without losing existing scan or move history.
- [x] Detect exact-copy candidates using file hashes and existing duplicate-review behavior.
- [x] Decode the full audio stream for integrity checks; distinguish access failures, unsupported decoding, and suspected corruption without claiming every defect is detectable.
- [x] Add audio filters, audio cards, and playback controls with a clear fallback when the browser cannot play a file.
- [x] Reuse manual selection, move previews, quarantine review, and reversible move/restore for audio.
- [x] Define audio-specific suggested-keep rules; do not apply image resolution rules or assume bitrate alone proves better quality.
- [x] Test exact copies, corrupt/unreadable audio, metadata extraction, cache reuse/invalidation, and audio move/restore.

### Phase 3 — Similar Music Detection
- [x] Evaluate local Chromaprint fingerprints for near-identical whole recordings across different encodings; no online identification service is required.
- [x] Store versioned fingerprints and implement candidate filtering and similarity matching.
- [x] Keep exact-copy groups separate from possible-same-recording groups and show the evidence behind a match.
- [x] Verify matching against generated re-encoded tracks, unrelated fingerprints, and silence; keep uncertain results advisory.
- [ ] Calibrate thresholds on a broader real-music collection, including alternate recordings.
- [x] Treat short excerpts and edited clips as separate work in Phase 5.

### Phase 4 — Video Playback and Compatible Previews
- [x] Open videos in a player and serve browser-compatible originals with seeking support.
- [x] Generate a compatible preview on demand when direct playback fails, keeping the original untouched.
- [x] Show preview preparation progress and actionable conversion errors.
- [x] Cache previews using source identity and conversion settings; invalidate stale previews and enforce a cache size limit.
- [x] Bound concurrent conversions and clean up failed or incomplete preview files.
- [x] Reuse compatible previews for unsupported audio playback where appropriate.
- [x] Verify direct playback, seeking, conversion fallback, source changes, and cache cleanup.

### Phase 5 — Deep Comparison for Edited Clips
- [x] Add an optional deep-comparison mode with timestamped visual and audio fingerprints beyond the existing three video samples.
- [x] Detect trimmed clips by matching segments across time offsets.
- [x] Detect rearranged clips by matching segments independently of their order.
- [x] Show matching time ranges and overlap coverage in a separate shared-segment result type.
- [x] Keep audio-only similarity distinct from visual similarity; shared background music alone must not label videos as duplicates.
- [x] Bound analysis cost and cache segment fingerprints for repeat comparisons.
- [x] Test generated audio trims/reordering, video trims, synthetic reordered visual segments, silent video, and partial overlap.
- [ ] Expand real-video coverage for reordered scenes, unrelated videos sharing music, and difficult edits.

## Packaging and Release Decisions
- [x] Bundle FFmpeg/ffprobe and Chromaprint with the Windows executable, using pinned downloads and verified checksums.
- [x] Verify the packaged executable with an empty system PATH: scan generated audio/video, detect re-encoded music, convert audio/video previews, serve seeking requests, and compare audio segments.
- [x] Retain upstream notices and document the selected builds and licenses.
- [ ] Prepare corresponding source and build materials for the exact bundled tools and their included libraries before public redistribution.
- [x] Update README.md and CHANGELOG.md as each phase ships, documenting dependencies, supported behavior, and matching limitations.

## Validation — 2026-09-29
- [x] 37 automated tests passed, including existing image/video, file-operation, and worker-interruption checks.
- [x] JavaScript syntax and patch whitespace checks passed.
- [x] Windows executable built at `dist/vault-purge.exe` with bundled media tools; packaged scan and playback/comparison checks passed without tools on PATH.
- [x] Temporary packaged test server stopped after verification.
- [x] Save interrupted scan status and release the API lock after worker interrupts; record shutdown signals in a rotating diagnostics log.
- [ ] Identify the sender of the reported unexpected shutdown; existing terminal output does not identify it.

## v1.2 Release
- [x] Set the default loopback port to 47831; verify serve, custom-port, and scan-and-serve launches.
- [x] Add the README Mermaid architecture chart and offline-operation explanation.
- [x] Align project, application, and lockfile metadata at version 1.2.0.
