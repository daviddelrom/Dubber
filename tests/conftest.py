import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from dubber.db.session import make_engine
from dubber.jobs.runner import JobRunner
from dubber.web.app import create_app

needs_tools = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("mkvmerge")),
    reason="requiere ffmpeg y mkvmerge",
)


def make_video(path, seconds: float, lang: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=d={seconds}:s=64x64:r=10",
         "-f", "lavfi", "-i", f"sine=d={seconds}",
         "-c:v", "mpeg4", "-c:a", "aac",
         "-metadata:s:a:0", f"language={lang}", str(path)],
        check=True,
    )


@pytest.fixture
def library(tmp_path):
    esp, eng, dub = tmp_path / "esp", tmp_path / "eng", tmp_path / "dub"
    make_video(esp / "tt0000001_es.mkv", 2, "spa")
    make_video(eng / "tt0000001_en.mkv", 2, "eng")
    make_video(esp / "serie" / "tt0000002_S01E01_es.mkv", 2, "spa")
    make_video(eng / "serie" / "tt0000002_S01E01_en.mkv", 4, "eng")
    return {"esp": esp, "eng": eng, "dub": dub}


@pytest.fixture
def client(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    app = create_app(engine, JobRunner(engine))
    with TestClient(app) as c:
        c.engine = engine
        yield c


def wait_for_jobs(client, count=1, timeout=60):
    """Espera a que existan `count` trabajos en total y todos hayan terminado."""
    from sqlmodel import Session, select

    from dubber.db.models import Job

    end = time.time() + timeout
    while time.time() < end:
        with Session(client.engine) as s:
            jobs = s.exec(select(Job)).all()
        if len(jobs) >= count and all(j.status not in ("queued", "running") for j in jobs):
            return jobs
        time.sleep(0.2)
    raise AssertionError("los trabajos no terminaron")
