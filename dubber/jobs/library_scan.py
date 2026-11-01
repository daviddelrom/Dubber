import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from ..core import naming
from ..core.mkv import (
    FileIdentity,
    MediaFileRef,
    MediaMetadata,
    ProbeError,
    TrackMetadata,
    probe_media,
)
from ..core.naming import is_video
from ..db.models_v2 import (
    V2MediaFile,
    V2Track,
)
from ..db.session import (
    DatabaseHandle,
    LegacyDatabaseError,
    open_v2_database,
)


@dataclass(frozen=True)
class LibraryConfig:
    source_root: Path
    output_root: Path
    language_mode: str | set[str] = "all"


@dataclass(frozen=True)
class ScanReport:
    files: list[MediaMetadata]
    indexed: int
    changed: int
    unreadable: list[FileIdentity]


@dataclass(frozen=True)
class ScanError:
    message: str


def _validate_config(config: LibraryConfig) -> tuple[Path, Path] | ScanError:
    source_root = config.source_root.expanduser().resolve()
    output_root = config.output_root.expanduser().resolve()
    if not source_root.is_dir():
        return ScanError(f"La raíz de biblioteca no es un directorio: {source_root}")
    if output_root != source_root / "dub":
        return ScanError("La carpeta de salida debe ser dub/ dentro de la biblioteca")
    if output_root.exists() and not output_root.is_dir():
        return ScanError(f"La carpeta de salida no es un directorio: {output_root}")
    if config.language_mode != "all" and (
        not isinstance(config.language_mode, set)
        or any(not isinstance(language, str) for language in config.language_mode)
    ):
        return ScanError("language_mode debe ser 'all' o un conjunto de idiomas")
    return source_root, output_root


def _raise_walk_error(error: OSError) -> None:
    raise error


def _discover_media(source_root: Path, output_root: Path) -> list[Path]:
    discovered = []
    for current_dir, directories, filenames in os.walk(
        source_root, topdown=True, followlinks=False, onerror=_raise_walk_error
    ):
        current_path = Path(current_dir)
        directories[:] = sorted(
            directory
            for directory in directories
            if not (current_path / directory).is_symlink()
            and (current_path / directory).resolve() != output_root
        )
        for filename in filenames:
            path = current_path / filename
            if path.is_symlink() or not is_video(filename) or not path.is_file():
                continue
            discovered.append(path)
    return sorted(
        discovered,
        key=lambda path: (
            path.relative_to(source_root).as_posix().casefold(),
            path.relative_to(source_root).as_posix(),
        ),
    )


def _file_id(source_root: Path, relative_path: str) -> str:
    value = f"{source_root.as_posix()}\0{relative_path}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(path: Path, source_root: Path) -> tuple[FileIdentity, str | None]:
    relative_path = path.relative_to(source_root).as_posix()
    try:
        stat = path.stat()
    except OSError as error:
        identity = FileIdentity(
            file_id=_file_id(source_root, relative_path),
            relative_path=relative_path,
            size=0,
            mtime_ns=0,
        )
        return identity, str(error)
    identity = FileIdentity(
        file_id=_file_id(source_root, relative_path),
        relative_path=relative_path,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )
    return identity, None


def _track_rows(session: Session, file_id: str) -> list[V2Track]:
    return session.exec(
        select(V2Track)
        .where(V2Track.file_id == file_id)
        .order_by(V2Track.track_no, V2Track.id)
    ).all()


def _restore_metadata(
    session: Session, row: V2MediaFile, identity: FileIdentity
) -> MediaMetadata | ScanError:
    tracks = []
    for track in _track_rows(session, row.file_id):
        try:
            hdr_signals = json.loads(track.hdr_signals_json)
        except json.JSONDecodeError as error:
            return ScanError(
                f"Metadatos HDR almacenados no válidos para {row.relative_path}: {error}"
            )
        if not isinstance(hdr_signals, list) or any(
            not isinstance(signal, str) for signal in hdr_signals
        ):
            return ScanError(
                f"Metadatos HDR almacenados no válidos para {row.relative_path}"
            )
        tracks.append(
            TrackMetadata(
                track_no=track.track_no,
                type=track.type,
                language=track.language,
                codec_id=track.codec_id,
                channels=track.channels,
                width=track.width,
                height=track.height,
                hdr_signals=hdr_signals,
            )
        )
    return MediaMetadata(identity=identity, duration_s=row.duration_s, tracks=tracks)


def _store_probe_result(
    session: Session,
    identity: FileIdentity,
    result: MediaMetadata | ProbeError,
) -> None:
    parsed_name = naming.parse_name(identity.relative_path)
    if isinstance(result, ProbeError):
        file_row = V2MediaFile(
            file_id=identity.file_id,
            relative_path=identity.relative_path,
            size=identity.size,
            mtime_ns=identity.mtime_ns,
            normalized_title=naming.normalize_title(identity.relative_path),
            year=parsed_name.year,
            season=parsed_name.season,
            episode=parsed_name.episode,
            duration_s=None,
            probe_status="error",
            probe_error=result.message,
        )
        tracks = []
    else:
        file_row = V2MediaFile(
            file_id=identity.file_id,
            relative_path=identity.relative_path,
            size=identity.size,
            mtime_ns=identity.mtime_ns,
            normalized_title=naming.normalize_title(identity.relative_path),
            year=parsed_name.year,
            season=parsed_name.season,
            episode=parsed_name.episode,
            duration_s=result.duration_s,
            probe_status="ok",
            probe_error=None,
        )
        tracks = [
            V2Track(
                file_id=identity.file_id,
                track_no=track.track_no,
                type=track.type,
                language=track.language,
                codec_id=track.codec_id,
                channels=track.channels,
                width=track.width,
                height=track.height,
                hdr_signals_json=json.dumps(track.hdr_signals),
            )
            for track in result.tracks
        ]

    for old_track in _track_rows(session, identity.file_id):
        session.delete(old_track)
    session.flush()
    session.merge(file_row)
    session.flush()
    session.add_all(tracks)


def _scan_with_database(
    database: DatabaseHandle, source_root: Path, paths: list[Path]
) -> ScanReport | ScanError:
    files = []
    unreadable = []
    changed = 0
    try:
        with Session(database.engine) as session:
            for path in paths:
                identity, stat_error = _identity(path, source_root)
                existing = session.get(V2MediaFile, identity.file_id)
                if (
                    existing is not None
                    and existing.size == identity.size
                    and existing.mtime_ns == identity.mtime_ns
                    and existing.probe_status == "ok"
                ):
                    restored = _restore_metadata(session, existing, identity)
                    if isinstance(restored, ScanError):
                        return restored
                    files.append(restored)
                    continue

                changed += 1
                if stat_error is not None:
                    result: MediaMetadata | ProbeError = ProbeError(
                        f"No se pudo consultar {identity.relative_path}: {stat_error}"
                    )
                else:
                    result = probe_media(
                        MediaFileRef(
                            file_id=identity.file_id,
                            path=path,
                            identity=identity,
                        )
                    )
                _store_probe_result(session, identity, result)
                if isinstance(result, ProbeError):
                    unreadable.append(identity)
                elif result.identity != identity:
                    return ScanError(
                        f"La identidad obtenida al explorar {identity.relative_path} no coincide"
                    )
                else:
                    files.append(result)
            session.commit()
    except SQLAlchemyError as error:
        return ScanError(f"No se pudo consultar la biblioteca v2: {error}")
    return ScanReport(
        files=files,
        indexed=len(paths),
        changed=changed,
        unreadable=unreadable,
    )


def scan_library(
    config: LibraryConfig, *, database_path: Path | None = None
) -> ScanReport | ScanError:
    validated = _validate_config(config)
    if isinstance(validated, ScanError):
        return validated
    source_root, output_root = validated
    try:
        paths = _discover_media(source_root, output_root)
    except OSError as error:
        return ScanError(f"No se pudo recorrer la biblioteca: {error}")

    database = open_v2_database(database_path)
    if isinstance(database, LegacyDatabaseError):
        return ScanError(database.message)
    try:
        return _scan_with_database(database, source_root, paths)
    finally:
        database.engine.dispose()
