from pathlib import Path
from sqlalchemy import event
from sqlmodel import SQLModel, create_engine
from vault_purge.storage import models  # register tables


def open_database(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.resolve().as_posix()}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")

    # Explicit schema version; future releases must migrate rather than silently reuse it.
    with engine.begin() as connection:
        version = connection.exec_driver_sql("PRAGMA user_version").scalar()
        if version not in (0, 1, 2, 3, 4):
            raise RuntimeError(f"Unsupported database schema {version}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(imagerecord)")}
        for name, declaration in {"media_type": "TEXT NOT NULL DEFAULT 'image'", "duration": "FLOAT", "fps": "FLOAT", "frame_hashes": "TEXT", "integrity": "TEXT NOT NULL DEFAULT 'unchecked'"}.items():
            if name not in columns:
                connection.exec_driver_sql(f"ALTER TABLE imagerecord ADD COLUMN {name} {declaration}")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_imagerecord_media_type ON imagerecord(media_type)")
        if version < 4:
            # Older caches did not record scan dates. Keep them explicitly labelled.
            connection.exec_driver_sql("INSERT INTO scanrecord (root, state, recursive, classify_only) SELECT DISTINCT root, 'legacy', 1, 0 FROM imagerecord")
            connection.exec_driver_sql("INSERT INTO scanmember (scan_id, image_id) SELECT s.id, i.id FROM scanrecord s JOIN imagerecord i ON s.root = i.root WHERE s.state = 'legacy'")
        connection.exec_driver_sql("PRAGMA user_version=4")
    return engine
