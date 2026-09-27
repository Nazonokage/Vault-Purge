import os
import sys
import subprocess
from pathlib import Path

def build():
    root = Path(__file__).resolve().parent
    static_dir = root / "vault_purge" / "ui" / "static"
    
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "vault-purge",
        "--add-data", f"{static_dir}{os.pathsep}vault_purge/ui/static",
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
