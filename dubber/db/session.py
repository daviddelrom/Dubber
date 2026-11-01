import os
from pathlib import Path

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (registra las tablas)

DEFAULT_DB = "dubber.db"


def make_engine(path: str | os.PathLike | None = None) -> Engine:
    path = path or os.environ.get("DUBBER_DB", DEFAULT_DB)
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

    SQLModel.metadata.create_all(engine)
    return engine


def get_root(session: Session, kind: str) -> models.LibraryRoot | None:
    from sqlmodel import select

    return session.exec(select(models.LibraryRoot).where(models.LibraryRoot.kind == kind)).first()
