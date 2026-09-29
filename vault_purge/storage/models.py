from sqlmodel import Field, SQLModel


class ImageRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    root: str = Field(index=True)
    path: str = Field(index=True, unique=True)
    size: int
    mtime_ns: int
    ctime_ns: int
    version: int = 1
    md5: str | None = Field(default=None, index=True)
    phash: str | None = None
    width: int = 0
    height: int = 0
    orientation: str = Field(default="UNKNOWN", index=True)
    blur_score: float | None = None
    status: str = Field(default="active", index=True)
    error: str | None = None
    user_decision: str | None = None
    media_type: str = Field(default="image", index=True)
    duration: float | None = None
    fps: float | None = None
    frame_hashes: str | None = None
    integrity: str = "unchecked"
    codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    audio_fingerprint: str | None = None
    audio_version: int = 0
    analysis_note: str | None = None
    segments_json: str | None = None
    segments_version: int = 0


class MoveRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    image_id: int = Field(index=True)
    original: str
    destination: str
    md5: str
    state: str = "pending"
    created_at: str
    error: str | None = None


class ScanRecord(SQLModel, table=True):
    __table_args__ = {"sqlite_autoincrement": True}
    id: int | None = Field(default=None, primary_key=True)
    root: str
    started_at: str | None = None
    finished_at: str | None = None
    state: str = "running"
    recursive: bool = True
    classify_only: bool = False
    stats_json: str | None = None
    error: str | None = None


class ScanMember(SQLModel, table=True):
    scan_id: int = Field(primary_key=True)
    image_id: int = Field(primary_key=True)
