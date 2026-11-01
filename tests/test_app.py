from sqlmodel import Session, select

from dubber.core import mkv
from dubber.db.models import Job, Match, MediaFile

from .conftest import make_video, needs_tools, wait_for_jobs


def configure(client, library):
    r = client.post("/settings", data={k: str(v) for k, v in library.items()},
                    follow_redirects=False)
    assert r.status_code == 303


def test_pages_render_empty(client):
    for url in ("/library", "/matches", "/jobs", "/settings"):
        assert client.get(url).status_code == 200


def test_settings_validation(client, tmp_path):
    r = client.post("/settings", data={"esp": "/no/existe", "eng": str(tmp_path),
                                       "dub": str(tmp_path / "out")})
    assert "La carpeta no existe" in r.text


def test_rejects_foreign_origin(client):
    r = client.post("/scan", headers={"origin": "http://evil.example"}, follow_redirects=False)
    assert r.status_code == 403


@needs_tools
def test_scan_match_merge_end_to_end(client, library):
    configure(client, library)
    client.post("/scan")
    jobs = wait_for_jobs(client, 1)
    assert jobs[0].status == "done", jobs[0].log

    with Session(client.engine) as s:
        matches = {m.output_relpath: m for m in s.exec(select(Match))}
    assert matches["tt0000001_en.mkv"].status == "ideal"
    assert matches["serie/tt0000002_S01E01_en.mkv"].status == "doubtful"

    ideal = matches["tt0000001_en.mkv"]
    doubtful = matches["serie/tt0000002_S01E01_en.mkv"]

    # Una dudosa no se mezcla hasta aprobarla
    client.post("/matches/merge", data={"match_ids": [ideal.id, doubtful.id]})
    wait_for_jobs(client, 2)
    out = library["dub"] / "tt0000001_en.mkv"
    assert out.exists() and not (library["dub"] / "serie").exists()

    langs = [(t.type, t.language) for t in mkv.probe(out).tracks]
    assert ("audio", "es") in langs and ("audio", "en") in langs
    assert sum(1 for t, _ in langs if t == "video") == 1
    assert not list(library["dub"].rglob("*.partial"))

    client.post(f"/matches/{doubtful.id}/status", data={"status": "approved"})
    client.post("/matches/merge", data={"match_ids": [doubtful.id]})
    wait_for_jobs(client, 3)
    assert (library["dub"] / "serie" / "tt0000002_S01E01_en.mkv").exists()


@needs_tools
def test_rescan_is_incremental_and_keeps_manual_decisions(client, library):
    configure(client, library)
    client.post("/scan")
    wait_for_jobs(client, 1)
    with Session(client.engine) as s:
        doubtful = s.exec(select(Match).where(Match.status == "doubtful")).one()
        before = {f.id: f.scanned_at for f in s.exec(select(MediaFile))}
    client.post(f"/matches/{doubtful.id}/status", data={"status": "approved"})

    make_video(library["esp"] / "tt0000003_es.mkv", 2, "spa")
    client.post("/scan")
    wait_for_jobs(client, 2)

    with Session(client.engine) as s:
        assert s.get(Match, doubtful.id).status == "approved"
        after = {f.id: f.scanned_at for f in s.exec(select(MediaFile))}
    assert all(after[i] == t for i, t in before.items())
    assert len(after) == len(before) + 1


@needs_tools
def test_deleted_file_is_removed_on_rescan(client, library):
    configure(client, library)
    client.post("/scan")
    wait_for_jobs(client, 1)
    (library["eng"] / "tt0000001_en.mkv").unlink()
    client.post("/scan")
    wait_for_jobs(client, 2)
    with Session(client.engine) as s:
        assert s.exec(select(Match).where(Match.output_relpath == "tt0000001_en.mkv")).first() is None


def test_scan_without_settings_fails_cleanly(client):
    client.post("/scan")
    jobs = wait_for_jobs(client, 1)
    assert jobs[0].status == "failed" and "no está definida" in jobs[0].log


def test_interrupted_jobs_are_failed_on_startup(tmp_path):
    from dubber.db.session import make_engine
    from dubber.jobs.runner import JobRunner

    engine = make_engine(tmp_path / "x.db")
    with Session(engine) as s:
        s.add(Job(kind="scan", status="running"))
        s.commit()
    JobRunner(engine).shutdown()
    with Session(engine) as s:
        assert s.exec(select(Job)).one().status == "failed"
