import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from dubber.db.session import open_v2_database
from dubber.web.app import create_app
from dubber.web.library_app import create_library_app


class FakeRunner:
    def __init__(self):
        self.configs = []
        self.reviews = []

    def submit_scan_and_consolidate(self, config):
        self.configs.append(config)
        return type("JobRef", (), {"job_id": "job-1"})()

    def submit_review_resolution(self, job_id, group_id, partition):
        self.reviews.append((job_id, group_id, partition))
        return type("JobRef", (), {"job_id": "review-job"})()

    def get_job_report(self, job_id):
        return type(
            "Report",
            (),
            {
                "job_id": job_id,
                "status": "completed",
                "progress": {"phase": "completed", "completed": 1, "total": 1},
                "log": ["done"],
                "scanned": 1,
                "consolidated": [],
                "review": [],
                "skipped": [],
                "errors": [],
            },
        )()

    def shutdown(self):
        pass


def _client(tmp_path):
    database = open_v2_database(tmp_path / "library.db")
    assert not hasattr(database, "message")
    runner = FakeRunner()
    app = create_library_app(database, runner)
    return TestClient(app), runner, database


def test_home_has_one_folder_settings_and_no_legacy_language_folders(tmp_path):
    client, runner, database = _client(tmp_path)
    response = client.get("/")

    assert response.status_code == 200
    assert "Carpeta de origen" in response.text
    assert 'name="source_root"' in response.text
    assert "Carpeta de español" not in response.text
    assert "Carpeta de inglés" not in response.text
    assert "library.db" in response.text
    assert "ffprobe" in response.text
    client.close()
    runner.shutdown()
    database.engine.dispose()


def test_settings_are_saved_and_scan_posts_return_job_reference(tmp_path):
    client, runner, database = _client(tmp_path)
    source = tmp_path / "library"
    source.mkdir()

    saved = client.post(
        "/settings",
        data={"source_root": str(source), "language_mode": "selected", "selected_languages": ["eng", "spa"]},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/"

    submitted = client.post("/jobs/scan")

    assert submitted.status_code == 202
    assert submitted.json() == {"job_id": "job-1"}
    assert runner.configs[0].source_root == source
    assert runner.configs[0].output_root == source / "dub"
    assert runner.configs[0].language_mode == {"eng", "spa"}
    client.close()
    runner.shutdown()
    database.engine.dispose()


def test_scan_without_saved_source_returns_clear_client_error(tmp_path):
    client, runner, database = _client(tmp_path)

    response = client.post("/jobs/scan")

    assert response.status_code == 400
    assert "source folder" in response.json()["detail"].lower()
    client.close()
    runner.shutdown()
    database.engine.dispose()


def test_review_route_accepts_current_batch_partition_and_returns_job(tmp_path):
    client, runner, database = _client(tmp_path)
    source = tmp_path / "library"
    source.mkdir()
    client.post("/settings", data={"source_root": str(source)})

    response = client.post(
        "/jobs/original-job/reviews/group-1",
        json={"partition": [["file-a", "file-b"]]},
    )

    assert response.status_code == 202
    assert response.json() == {"job_id": "review-job"}
    assert runner.reviews == [
        ("original-job", "group-1", [["file-a", "file-b"]])
    ]
    client.close()
    runner.shutdown()
    database.engine.dispose()


def test_job_report_route_returns_persisted_batch_shape(tmp_path):
    client, runner, database = _client(tmp_path)

    response = client.get("/jobs/job-1")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["progress"]["phase"] == "completed"
    client.close()
    runner.shutdown()
    database.engine.dispose()


def test_settings_reject_nonexistent_source_directory(tmp_path):
    client, runner, database = _client(tmp_path)

    response = client.post(
        "/settings",
        data={"source_root": str(tmp_path / "missing")},
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "does not exist" in response.text
    client.close()
    runner.shutdown()
    database.engine.dispose()


def test_default_app_uses_v2_database_and_does_not_mutate_legacy_db(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "dubber-v2.db"
    monkeypatch.setenv("DUBBER_DB", str(database_path))
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
    with sqlite3.connect(database_path) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "v2_library_config" in names
    assert "libraryroot" not in names

    legacy_path = tmp_path / "legacy.db"
    with sqlite3.connect(legacy_path) as connection:
        connection.execute("CREATE TABLE libraryroot (id INTEGER PRIMARY KEY)")
    before = hashlib.sha256(legacy_path.read_bytes()).digest()
    monkeypatch.setenv("DUBBER_DB", str(legacy_path))

    with pytest.raises(RuntimeError, match="esquema desconocido"):
        create_app()
    assert hashlib.sha256(legacy_path.read_bytes()).digest() == before
