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


class MoveRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    image_id: int = Field(index=True)
    original: str
    destination: str
    md5: str
    state: str = "pending"
    created_at: str
    error: str | None = None
