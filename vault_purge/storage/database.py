import os
import sys
import ctypes
from pathlib import Path
from sqlalchemy import event
from sqlmodel import SQLModel, create_engine
from vault_purge.storage import models  # register tables


def get_system_ram_bytes() -> int:
    """Detect total physical system RAM in bytes with a safe fallback."""
    try:
        if sys.platform == "win32":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullTotalPhys
        elif hasattr(os, "sysconf"):
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:
        pass
    return 8 * 1024 * 1024 * 1024  # Default fallback: 8 GB


def get_sqlite_memory_settings() -> tuple[int, int]:
    """Return (mmap_size_bytes, cache_size_kib) scaled to total system RAM."""
    ram_bytes = get_system_ram_bytes()
    ram_gb = ram_bytes / (1024 ** 3)
    if ram_gb >= 15.0:
        # 16GB+ RAM (e.g. 16GB DDR4): 1 GB mmap size, 128 MB RAM cache
        return 1024 * 1024 * 1024, -131072
    elif ram_gb >= 7.5:
        # 8GB - 16GB RAM: 512 MB mmap size, 64 MB RAM cache
        return 512 * 1024 * 1024, -65536
    else:
        # < 8GB RAM: 256 MB mmap size, 32 MB RAM cache
        return 256 * 1024 * 1024, -32768


def open_database(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.resolve().as_posix()}", connect_args={"check_same_thread": False, "timeout": 30})
    mmap_size, cache_size = get_sqlite_memory_settings()

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute(f"PRAGMA mmap_size={mmap_size}")
        connection.execute(f"PRAGMA cache_size={cache_size}")
        connection.execute("PRAGMA foreign_keys=ON")

    # Explicit schema version; future releases must migrate rather than silently reuse it.
    with engine.begin() as connection:
        version = connection.exec_driver_sql("PRAGMA user_version").scalar()
        if version not in (0, 1, 2, 3, 4, 5):
            raise RuntimeError(f"Unsupported database schema {version}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(imagerecord)")}
        for name, declaration in {"media_type": "TEXT NOT NULL DEFAULT 'image'", "duration": "FLOAT", "fps": "FLOAT", "frame_hashes": "TEXT", "integrity": "TEXT NOT NULL DEFAULT 'unchecked'"}.items():
            if name not in columns:
                connection.exec_driver_sql(f"ALTER TABLE imagerecord ADD COLUMN {name} {declaration}")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_imagerecord_media_type ON imagerecord(media_type)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_imagerecord_status_type ON imagerecord(status, media_type)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_imagerecord_status_blur ON imagerecord(status, blur_score)")
        for name, declaration in {"codec": "TEXT", "sample_rate": "INTEGER", "channels": "INTEGER",
                                  "audio_fingerprint": "TEXT", "audio_version": "INTEGER NOT NULL DEFAULT 0",
                                  "analysis_note": "TEXT", "segments_json": "TEXT",
                                  "segments_version": "INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in columns:
                connection.exec_driver_sql(f"ALTER TABLE imagerecord ADD COLUMN {name} {declaration}")
        if version < 4:
            # Older caches did not record scan dates. Keep them explicitly labelled.
            connection.exec_driver_sql("INSERT INTO scanrecord (root, state, recursive, classify_only) SELECT DISTINCT root, 'legacy', 1, 0 FROM imagerecord")
            connection.exec_driver_sql("INSERT INTO scanmember (scan_id, image_id) SELECT s.id, i.id FROM scanrecord s JOIN imagerecord i ON s.root = i.root WHERE s.state = 'legacy'")
        connection.exec_driver_sql("PRAGMA user_version=5")
    return engine
