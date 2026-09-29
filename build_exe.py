import os
import sys
import subprocess
import hashlib
import json
from pathlib import Path

def build():
    root = Path(__file__).resolve().parent
    static_dir = root / "vault_purge" / "ui" / "static"
    media_tools = root / "vault_purge" / "media_tools"
    manifest_path = media_tools / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("Run tools/fetch_media_tools.py first to prepare the bundled media tools.")
    for package in json.loads(manifest_path.read_text(encoding="utf-8")):
        for filename, expected in package["binaries"].items():
            path = media_tools / filename
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise SystemExit(f"Missing or modified media tool: {filename}. Run tools/fetch_media_tools.py.")
    
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "vault-purge",
        "--add-data", f"{static_dir}{os.pathsep}vault_purge/ui/static",
        "--add-data", f"{media_tools}{os.pathsep}vault_purge/media_tools",
        "--collect-all", "vault_purge",
        "--collect-all", "sqlmodel",
        "--collect-all", "uvicorn",
        "--collect-all", "fastapi",
        "--collect-all", "cv2",
        "--collect-all", "PIL",
        "--collect-all", "imagehash",
        "--hidden-import", "pydantic_settings",
        "--hidden-import", "sqlite3",
        str(root / "vault_purge" / "cli" / "main.py"),
    ]
    
    print("Building executable with command:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(root))
    if result.returncode != 0:
        sys.exit(result.returncode)
    print("\nExecutable built successfully at dist/vault-purge.exe")

if __name__ == "__main__":
    build()
