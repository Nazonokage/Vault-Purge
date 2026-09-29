"""Audio integrity and local, advisory whole-recording fingerprints."""
import json
from pathlib import Path
import tempfile

from vault_purge.core.media_tools import probe, finite_number, run_tool, ffmpeg_input

AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".wma", ".aiff", ".aif"}
AUDIO_VERSION = 1


def raw_fingerprint(path, seconds=120):
    # Normalize through the restricted local decoder; fpcalc only sees our WAV.
    with tempfile.TemporaryDirectory(prefix="vault-purge-audio-") as folder:
        wav = Path(folder) / "audio.wav"
        run_tool("ffmpeg", [*ffmpeg_input(path), "-t", str(seconds), "-map", "0:a:0", "-vn",
                            "-ac", "1", "-ar", "11025", "-c:a", "pcm_s16le", str(wav)], max(180, seconds))
        result = json.loads(run_tool("fpcalc", ["-algorithm", "2", "-raw", "-json", "-length", str(seconds), str(wav)], max(180, seconds)))
    values = result.get("fingerprint", [])
    if isinstance(values, str):
        values = [int(v) for v in values.split(",") if v]
    return values


def audio_fingerprint(path):
    # Bounded first 120 seconds. Raw subfingerprints are compared locally.
    values = raw_fingerprint(path)
    return json.dumps(values) if len(values) >= 80 and len(set(values)) >= 16 else None


def analyze_audio(path, hashing=True):
    info = probe(path)
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        from vault_purge.core.media_tools import UnsupportedMedia
        raise UnsupportedMedia("No readable audio stream was found")
    stream = streams[0]
    duration = finite_number(stream.get("duration")) or finite_number(info.get("format", {}).get("duration"))
    result = dict(media_type="audio", width=0, height=0, orientation="UNKNOWN", duration=duration,
                  fps=None, phash=None, frame_hashes=None, blur_score=None, codec=stream.get("codec_name"),
                  sample_rate=int(stream.get("sample_rate") or 0), channels=int(stream.get("channels") or 0),
                  audio_fingerprint=None, audio_version=AUDIO_VERSION, analysis_note=None,
                  integrity="unchecked")
    if hashing:
        run_tool("ffmpeg", [*ffmpeg_input(path), "-xerror", "-map", "0:a", "-vn", "-f", "null", "-"],
                 min(7200, max(120, (duration or 300) * 2)))
        result["integrity"] = "checked"
        try:
            result["audio_fingerprint"] = audio_fingerprint(path)
            if not result["audio_fingerprint"]:
                result["analysis_note"] = "Too short or repetitive for reliable music similarity; exact matching remains available."
        except Exception as exc:
            # Fingerprinting is optional evidence, not an integrity verdict.
            result["analysis_note"] = f"Music similarity unavailable: {exc}"
    return result


def music_similarity(left, right):
    if not left.duration or not right.duration or abs(left.duration - right.duration) > max(2, min(left.duration, right.duration) * .02):
        return None
    if not left.audio_fingerprint or not right.audio_fingerprint:
        return None
    a, b = json.loads(left.audio_fingerprint), json.loads(right.audio_fingerprint)
    if min(len(a), len(b)) < 80 or min(len(set(a)), len(set(b))) < 16:
        return None
    best = 0
    for offset in range(-12, 13):
        x, y = (a[offset:], b) if offset >= 0 else (a, b[-offset:])
        length = min(len(x), len(y))
        if length < 80:
            continue
        score = 1 - sum(((u ^ v) & 0xffffffff).bit_count() for u, v in zip(x[:length], y[:length])) / (32 * length)
        best = max(best, score)
    return round(best, 4) if best >= .90 else None
