import hashlib
import sqlite3
from pathlib import Path

from dubber.db import session
from sqlalchemy import inspect
from sqlmodel import Session, select


def _api(name):
    function = getattr(session, name, None)
    assert callable(function), f"dubber.db.session.{name} must be implemented"
    return function


def test_default_v2_database_path_is_separate_from_legacy_default(monkeypatch):
    monkeypatch.delenv("DUBBER_DB", raising=False)
    database_path = _api("default_database_path")()

    assert Path(database_path).name == "dubber-v2.db"
    assert Path(database_path).name != session.DEFAULT_DB


def test_default_v2_database_path_honors_explicit_override(monkeypatch, tmp_path):
    override = tmp_path / "custom-library.db"
    monkeypatch.setenv("DUBBER_DB", str(override))

    assert _api("default_database_path")() == override


def test_legacy_database_is_rejected_without_modification(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE libraryroot (id INTEGER PRIMARY KEY, kind TEXT)")
        connection.execute("INSERT INTO libraryroot (id, kind) VALUES (1, 'esp')")
    before = hashlib.sha256(path.read_bytes()).digest()

    result = _api("open_v2_database")(path)
    error_type = getattr(session, "LegacyDatabaseError", None)

    assert error_type is not None
    assert isinstance(result, error_type)
    assert hashlib.sha256(path.read_bytes()).digest() == before
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert tables == {"libraryroot"}


def test_fresh_v2_database_creates_only_v2_tables_and_schema_marker(tmp_path):
    handle = _api("open_v2_database")(tmp_path / "dubber-v2.db")
    handle_type = getattr(session, "DatabaseHandle", None)

    assert handle_type is not None
    assert isinstance(handle, handle_type)
    inspector = inspect(handle.engine)
    assert set(inspector.get_table_names()) == {
        "v2_library_config",
        "v2_media_file",
        "v2_track",
        "v2_candidate_group",
        "v2_candidate_group_member",
        "v2_job",
        "v2_output_record",
        "v2_schema_version",
    }
    with Session(handle.engine) as database:
        versions = database.exec(select(session.V2SchemaVersion)).all()
    assert [(item.id, item.version) for item in versions] == [
        (1, session.V2_SCHEMA_VERSION)
    ]
    handle.engine.dispose()


def test_opening_existing_v2_database_does_not_change_it(tmp_path):
    path = tmp_path / "dubber-v2.db"
    first = _api("open_v2_database")(path)
    first.engine.dispose()
    before = hashlib.sha256(path.read_bytes()).digest()

    second = _api("open_v2_database")(path)
    second.engine.dispose()

    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_incompatible_v2_schema_version_is_rejected_without_modification(tmp_path):
    path = tmp_path / "dubber-v2.db"
    handle = _api("open_v2_database")(path)
    with Session(handle.engine) as database:
        version = database.get(session.V2SchemaVersion, 1)
        version.version = session.V2_SCHEMA_VERSION + 1
        database.add(version)
        database.commit()
    handle.engine.dispose()
    before = hashlib.sha256(path.read_bytes()).digest()

    result = _api("open_v2_database")(path)

    assert isinstance(result, session.LegacyDatabaseError)
    assert hashlib.sha256(path.read_bytes()).digest() == before
