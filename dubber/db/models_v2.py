from datetime import datetime, timezone

from sqlalchemy import MetaData, UniqueConstraint
from sqlmodel import Field, SQLModel


class V2SQLModel(SQLModel):
    metadata = MetaData()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class V2SchemaVersion(V2SQLModel, table=True):
    __tablename__ = "v2_schema_version"

    id: int = Field(default=1, primary_key=True)
    version: int


class V2LibraryConfig(V2SQLModel, table=True):
    __tablename__ = "v2_library_config"

    id: int = Field(default=1, primary_key=True)
    source_root: str
    output_root: str
    language_mode: str = "all"
    selected_languages_json: str = "[]"


class V2MediaFile(V2SQLModel, table=True):
    __tablename__ = "v2_media_file"

    file_id: str = Field(primary_key=True)
    relative_path: str
    size: int
    mtime_ns: int
    normalized_title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    duration_s: float | None = None
    probe_status: str = "ok"
    probe_error: str | None = None


class V2Track(V2SQLModel, table=True):
    __tablename__ = "v2_track"
    __table_args__ = (UniqueConstraint("file_id", "track_no"),)

    id: int | None = Field(default=None, primary_key=True)
    file_id: str = Field(foreign_key="v2_media_file.file_id", index=True)
    track_no: int
    type: str
    language: str
    codec_id: str = ""
    codec_family: str | None = None
    channels: int | None = None
    width: int | None = None
    height: int | None = None
    hdr_signals_json: str = "[]"
    name: str = ""


class V2CandidateGroup(V2SQLModel, table=True):
    __tablename__ = "v2_candidate_group"

    group_id: str = Field(primary_key=True)
    batch_id: str = Field(index=True)
    confidence: str
    status: str = "candidate"
    reason: str | None = None
    winning_video_file_id: str | None = Field(
        default=None, foreign_key="v2_media_file.file_id"
    )
    output_relpath: str | None = None
    input_signature: str | None = None


class V2CandidateGroupMember(V2SQLModel, table=True):
    __tablename__ = "v2_candidate_group_member"

    group_id: str = Field(
        foreign_key="v2_candidate_group.group_id", primary_key=True
    )
    file_id: str = Field(
        foreign_key="v2_media_file.file_id", primary_key=True
    )


class V2Job(V2SQLModel, table=True):
    __tablename__ = "v2_job"

    job_id: str = Field(primary_key=True)
    batch_id: str = Field(index=True)
    kind: str
    status: str = "queued"
    phase: str = "queued"
    completed: int = 0
    total: int = 0
    log: str = ""
    report_json: str = "{}"
    cancel_requested: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class V2OutputRecord(V2SQLModel, table=True):
    __tablename__ = "v2_output_record"

    group_signature: str = Field(primary_key=True)
    output_path: str
    input_signature: str
    settings_signature: str
    output_size: int
    output_mtime_ns: int
