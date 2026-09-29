"""Experimental bounded segment evidence; never feeds duplicate/move decisions."""
from collections import Counter, defaultdict

import imagehash
import numpy as np
from PIL import Image

from vault_purge.core.media_tools import run_tool, ffmpeg_input, probe
from vault_purge.core.audio import raw_fingerprint

SEGMENTS_VERSION = 1
MAX_SECONDS = 1800
VIDEO_STEP = 2.0
# Chromaprint algorithm 2: 4096-point frames, 1365-sample hop at 11025 Hz.
# https://github.com/acoustid/chromaprint/blob/v1.6.1/src/fingerprinter_configuration.cpp
AUDIO_STEP = 1365 / 11025


def extract_segments(path, media_type):
    result = dict(video=[], audio=[], notes=[], limit_seconds=MAX_SECONDS)
    if media_type == "video":
        data = run_tool("ffmpeg", [*ffmpeg_input(path), "-map", "0:v:0", "-an", "-t", str(MAX_SECONDS),
                                  "-vf", "fps=1/2,scale=32:32", "-pix_fmt", "gray", "-f", "rawvideo", "-"], 1800)
        for offset in range(0, len(data) - 1023, 1024):
            pixels = np.frombuffer(data[offset:offset + 1024], dtype=np.uint8).reshape(32, 32)
            result["video"].append(int(str(imagehash.phash(Image.fromarray(pixels))), 16) if pixels.std() >= 8 else None)
    info = probe(path)
    if any(stream.get("codec_type") == "audio" for stream in info.get("streams", [])):
        try:
            result["audio"] = raw_fingerprint(path, MAX_SECONDS)
        except Exception as exc:
            result["notes"].append(f"Audio segment analysis unavailable: {exc}")
    else:
        result["notes"].append("No audio stream")
    return result


def matching_ranges(a, b, step, bits, threshold, minimum):
    """Vote for candidate offsets, then require sustained, varied matching runs."""
    index = defaultdict(list)
    for j, value in enumerate(b):
        if value is not None:
            for shift in range(0, bits, 8):
                index[(shift, (value >> shift) & 255)].append(j)
    offsets = Counter()
    stride = max(1, int(1 / step))
    for i in range(0, len(a), stride):
        value = a[i]
        if value is None:
            continue
        candidates = set()
        for shift in range(0, bits, 8):
            bucket = index.get((shift, (value >> shift) & 255), [])
            if len(bucket) <= 100:
                candidates.update(bucket)
        for j in candidates:
            if ((value ^ b[j]) & ((1 << bits) - 1)).bit_count() <= threshold:
                offsets[j - i] += 1
    matches = []
    for offset, votes in offsets.most_common(32):
        if votes < 3:
            continue
        start = max(0, -offset)
        end = min(len(a), len(b) - offset)
        run = []
        def finish():
            if len(run) >= minimum and len({a[i] for i in run}) >= min(8, minimum):
                matches.append(dict(left_start=round(run[0] * step, 2), left_end=round((run[-1] + 1) * step, 2),
                                    right_start=round((run[0] + offset) * step, 2), right_end=round((run[-1] + offset + 1) * step, 2)))
            run.clear()
        for i in range(start, end):
            x, y = a[i], b[i + offset]
            if x is not None and y is not None and ((x ^ y) & ((1 << bits) - 1)).bit_count() <= threshold:
                run.append(i)
            else:
                finish()
        finish()
    # Prefer the longest evidence and suppress almost-identical offset alternatives.
    selected = []
    for match in sorted(matches, key=lambda r: -(r["left_end"] - r["left_start"])):
        if any(abs(match["left_start"] - old["left_start"]) < max(2, step) and
               abs(match["right_start"] - old["right_start"]) < max(2, step) for old in selected):
            continue
        selected.append(match)
        if len(selected) == 20:
            break
    return sorted(selected, key=lambda r: r["left_start"])


def coverage(ranges, side, duration):
    intervals = sorted((r[f"{side}_start"], min(r[f"{side}_end"], duration)) for r in ranges)
    total, end = 0, 0
    for start, stop in intervals:
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return round(min(1, total / duration), 3) if duration else 0


def compare_segments(left, right, left_duration, right_duration):
    output = {"notes": left.get("notes", []) + right.get("notes", []), "limit_seconds": MAX_SECONDS}
    for kind, step, bits, threshold, minimum in (("video", VIDEO_STEP, 64, 8, 3), ("audio", AUDIO_STEP, 32, 5, 64)):
        ranges = matching_ranges(left[kind], right[kind], step, bits, threshold, minimum)
        output[kind] = dict(ranges=ranges, left_coverage=coverage(ranges, "left", left_duration or MAX_SECONDS),
                            right_coverage=coverage(ranges, "right", right_duration or MAX_SECONDS))
    return output
