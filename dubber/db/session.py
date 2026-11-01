import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (registra las tablas)
from . import models_v2
from .models_v2 import V2SchemaVersion

DEFAULT_DB = "dubber.db"
DEFAULT_V2_DB = "dubber-v2.db"
V2_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class DatabaseHandle:
    path: Path
    engine: Engine


@dataclass(frozen=True)
class LegacyDatabaseError:
    path: Path
    message: str


def default_database_path() -> Path:
    configured_path = os.environ.get("DUBBER_DB")
    return Path(configured_path) if configured_path else Path(DEFAULT_V2_DB)


def _create_sqlite_engine(path: str | os.PathLike) -> Engine:
    engine = create_engine(
        f"sqlite:///{Path(path).resolve()}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def _existing_v2_database_state(
    path: Path,
) -> bool | LegacyDatabaseError:
    if not path.exists() or path.stat().st_size == 0:
        return False
    if not path.is_file():
        return LegacyDatabaseError(path, "La ruta de base de datos no es un archivo")

    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            objects = connection.execute(
                "SELECT type, name FROM sqlite_master "
                "WHERE type IN ('table', 'view', 'trigger') "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if not objects:
                return False
            tables = {name for object_type, name in objects if object_type == "table"}
            expected_tables = set(models_v2.V2SQLModel.metadata.tables)
            if (
                tables != expected_tables
                or any(object_type != "table" for object_type, _ in objects)
            ):
                return LegacyDatabaseError(
                    path,
                    "La base contiene un esquema desconocido o heredado; no se modificó",
                )
            version_rows = connection.execute(
                "SELECT id, version FROM v2_schema_version"
            ).fetchall()
    except sqlite3.Error as error:
        return LegacyDatabaseError(
            path, f"No se pudo validar el esquema de base de datos: {error}"
        )

    if version_rows != [(1, V2_SCHEMA_VERSION)]:
        return LegacyDatabaseError(
            path, "La versión del esquema no es compatible; no se modificó"
        )
    return True


def make_engine(path: str | os.PathLike | None = None) -> Engine:
    path = path or os.environ.get("DUBBER_DB", DEFAULT_DB)
    engine = _create_sqlite_engine(path)
    SQLModel.metadata.create_all(engine)
    return engine


def open_v2_database(
    path: str | os.PathLike | None = None,
) -> DatabaseHandle | LegacyDatabaseError:
    database_path = Path(path or default_database_path()).resolve()
    state = _existing_v2_database_state(database_path)
    if isinstance(state, LegacyDatabaseError):
        return state

    engine = _create_sqlite_engine(database_path)
    if state is False:
        models_v2.V2SQLModel.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT OR IGNORE INTO v2_schema_version (id, version) VALUES (1, ?)",
                (V2_SCHEMA_VERSION,),
            )
    return DatabaseHandle(path=database_path, engine=engine)


def get_root(session: Session, kind: str) -> models.LibraryRoot | None:
    from sqlmodel import select

    return session.exec(select(models.LibraryRoot).where(models.LibraryRoot.kind == kind)).first()
