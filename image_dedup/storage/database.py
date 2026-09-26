from pathlib import Path
from sqlalchemy import event
from sqlmodel import SQLModel, create_engine
from image_dedup.storage import models  # register tables


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
        if version not in (0, 1):
            raise RuntimeError(f"Unsupported database schema {version}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA user_version=1")
    return engine
