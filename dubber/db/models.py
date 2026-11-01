from datetime import datetime, timezone

from sqlmodel import Field, SQLModel, UniqueConstraint


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LibraryRoot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(unique=True, index=True)  # esp | eng | dub
    path: str


class MediaFile(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("root_id", "relpath"),)

    id: int | None = Field(default=None, primary_key=True)
    root_id: int = Field(foreign_key="libraryroot.id", index=True)
    relpath: str
    size: int
    mtime: float
    imdb_id: str | None = Field(default=None, index=True)
    season: int | None = None
    episode: int | None = None
    duration_s: float | None = None
    error: str | None = None
    scanned_at: datetime = Field(default_factory=utcnow)


class Track(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="mediafile.id", index=True)
    track_no: int
    type: str
    language: str
    codec: str = ""
    name: str = ""


class Match(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("esp_file_id", "eng_file_id"),)

    id: int | None = Field(default=None, primary_key=True)
    esp_file_id: int = Field(foreign_key="mediafile.id", index=True)
    eng_file_id: int = Field(foreign_key="mediafile.id", index=True)
    duration_diff_s: float | None = None
    status: str = "doubtful"  # ideal | doubtful | approved | discarded
    output_relpath: str
    merged_at: datetime | None = None


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str  # scan | merge
    status: str = Field(default="queued", index=True)  # queued | running | done | failed | cancelled
    progress: float = 0.0
    params_json: str = "{}"
    log: str = ""
    cancel_requested: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
