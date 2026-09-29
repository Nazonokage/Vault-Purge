"""Local media tools: bundled first, optional developer overrides, then PATH."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from vault_purge.core.integrity import SuspectedCorruption

TOOL_DIR = Path(__file__).resolve().parents[1] / "media_tools"


class ToolUnavailable(RuntimeError):
    pass


class UnsupportedMedia(ValueError):
    pass


def executable(name):
    filename = name + (".exe" if os.name == "nt" else "")
    override = os.environ.get(f"VAULT_PURGE_{name.upper()}")
    candidate = Path(override) if override else TOOL_DIR / filename
    if candidate.is_file():
        return str(candidate.resolve())
    if not override and (found := shutil.which(name)):
        return found
    raise ToolUnavailable(f"{name} is missing. Use the bundled application or run tools/fetch_media_tools.py.")


def run_tool(name, args, timeout=120):
    # Temporary files bound RAM even when a decoder emits excessive diagnostics.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run([executable(name), *map(str, args)], stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=errors, timeout=timeout,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{name} exceeded the {timeout:g}-second time limit") from exc
        errors.seek(0)
        error = errors.read(8192).decode("utf-8", errors="replace").strip()
        if result.returncode:
            if any(term in error.lower() for term in ("unknown decoder", "decoder not found", "unsupported codec", "decoding requested, but no decoder")):
                raise UnsupportedMedia(error)
            raise SuspectedCorruption(f"{name} could not decode the media (damage or unsupported format): {error}")
        output.seek(0)
        data = output.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise RuntimeError(f"{name} output exceeded the analysis limit")
        return data


def probe(path):
    with open(path, "rb"):
        pass  # Access failures must not be labelled corruption.
    return json.loads(run_tool("ffprobe", ["-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(path)], 30))


def finite_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def ffmpeg_input(path):
    return ["-hide_banner", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-threads", "1", "-i", str(path)]
