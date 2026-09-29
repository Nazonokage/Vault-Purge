"""Fetch pinned Windows tools, verify archives, and retain upstream notices."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "vault_purge" / "media_tools"
PACKAGES = [
    ("ffmpeg", "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip",
     "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba", {"ffmpeg.exe", "ffprobe.exe"}),
    ("chromaprint", "https://github.com/acoustid/chromaprint/releases/download/v1.6.1/chromaprint-fpcalc-1.6.1-windows-x86_64.zip",
     "735d6182b38e9f364b84ce6f4ccd682c75e2851de89735711d6b762d12b92a4e", {"fpcalc.exe"}),
]


def main():
    cache = ROOT / "build" / "tool_downloads"
    cache.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, url, checksum, binaries in PACKAGES:
        archive = cache / (name + ".zip")
        existing_checksum = None
        if archive.exists():
            with archive.open("rb") as source:
                existing_checksum = hashlib.file_digest(source, "sha256").hexdigest()
        if existing_checksum != checksum:
            print(f"Downloading {name}…", flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "VaultPurge-build"})
            with urllib.request.urlopen(request, timeout=120) as source, archive.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != checksum:
                raise RuntimeError(f"Checksum mismatch for {name}; archive was not extracted")
        found = set()
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                filename = Path(member.filename).name
                if filename in binaries:
                    (DEST / filename).write_bytes(package.read(member))
                    found.add(filename)
                elif not member.is_dir() and any(word in filename.lower() for word in ("license", "copying", "notice", "readme")):
                    notices = DEST / "licenses" / name
                    notices.mkdir(parents=True, exist_ok=True)
                    (notices / filename).write_bytes(package.read(member))
        if found != binaries:
            raise RuntimeError(f"Missing binaries in {name}: {binaries - found}")
        manifest.append(dict(name=name, url=url, sha256=checksum,
                             binaries={file: hashlib.sha256((DEST / file).read_bytes()).hexdigest() for file in sorted(found)}))
    license_path = DEST / "licenses" / "chromaprint" / "LICENSE.md"
    license_hash = "562cfe59627e0c4e8e3b066f3ff2e9736f83811ffe4c6c2c7796595aa7595ebd"
    if not license_path.is_file() or hashlib.sha256(license_path.read_bytes()).hexdigest() != license_hash:
        with urllib.request.urlopen("https://raw.githubusercontent.com/acoustid/chromaprint/v1.6.1/LICENSE.md", timeout=30) as source:
            notice = source.read()
        if hashlib.sha256(notice).hexdigest() != license_hash:
            raise RuntimeError("Chromaprint license checksum mismatch")
        license_path.parent.mkdir(parents=True, exist_ok=True)
        license_path.write_bytes(notice)
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Verified tools installed in {DEST}")


if __name__ == "__main__":
    main()
