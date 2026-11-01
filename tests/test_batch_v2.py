import shutil
import subprocess
import time
from pathlib import Path

import pytest

from dubber.core.consolidation import CompletedOutput
from dubber.core.mkv import FileIdentity, TrackMetadata
from dubber.db.session import DatabaseHandle, open_v2_database
from dubber.jobs import batch
from dubber.jobs.library_scan import LibraryConfig

needs_mkv_tools = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("mkvmerge")),
    reason="requires ffmpeg, ffprobe and mkvmerge",
)


def _make_video(path: Path, language: str, width: int = 128):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x72:rate=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-metadata:s:a:0",
            f"language={language}",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _wait(runner, job_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        report = runner.get_job_report(job_id)
        if report.status not in {"queued", "running"}:
            return report
        time.sleep(0.05)
    raise AssertionError(f"batch job {job_id} did not finish")


def _runner(tmp_path, monkeypatch):
    monkeypatch.setenv("DUBBER_DB", str(tmp_path / "dubber-v2.db"))
    database = open_v2_database()
    assert isinstance(database, DatabaseHandle)
    return batch.V2BatchRunner(database)


@needs_mkv_tools
def test_batch_auto_consolidates_confident_group_and_skips_unchanged_output(
    tmp_path, monkeypatch
):
    source = tmp_path / "library"
    _make_video(source / "Film (2020).mkv", "eng", width=128)
    _make_video(source / "Film.2020.mkv", "spa", width=64)
    runner = _runner(tmp_path, monkeypatch)
    config = LibraryConfig(source, source / "dub", "all")

    first_job = runner.submit_scan_and_consolidate(config)
    first_report = _wait(runner, first_job.job_id)

    assert first_report.status == "completed", first_report.errors
    assert first_report.scanned == 2
    assert len(first_report.consolidated) == 1
    assert isinstance(first_report.consolidated[0], CompletedOutput)
    output = source / "dub" / "Film (2020).mkv"
    assert output.is_file()
    assert runner.read_output_languages(output) == {"eng", "spa"}

    second_job = runner.submit_scan_and_consolidate(config)
    second_report = _wait(runner, second_job.job_id)

    assert second_report.status == "completed"
    assert second_report.consolidated == []
    assert len(second_report.skipped) == 1
    runner.shutdown()
    runner.database.engine.dispose()


@needs_mkv_tools
def test_batch_keeps_review_nonblocking_and_same_choice_is_batch_scoped(
    tmp_path, monkeypatch
):
    source = tmp_path / "library"
    _make_video(source / "Certain (2020).mkv", "eng", width=128)
    _make_video(source / "Certain.2020.mkv", "spa", width=64)
    _make_video(source / "Arrival (2016).mkv", "eng", width=128)
    _make_video(source / "Arrival.mkv", "spa", width=64)
    runner = _runner(tmp_path, monkeypatch)
    config = LibraryConfig(source, source / "dub", "all")

    job = runner.submit_scan_and_consolidate(config)
    report = _wait(runner, job.job_id)

    assert report.status == "completed", report.errors
    assert len(report.consolidated) == 1
    assert len(report.review) == 1
    review = report.review[0]
    assert {member["relative_path"] for member in review["members"]} == {
        "Arrival (2016).mkv",
        "Arrival.mkv",
    }

    with pytest.raises(ValueError):
        runner.submit_review_resolution(
            job.job_id, review["group_id"], [[review["members"][0]["file_id"]]]
        )
    review_job = runner.submit_review_resolution(
        job.job_id,
        review["group_id"],
        [[member["file_id"] for member in review["members"]]],
    )
    review_report = _wait(runner, review_job.job_id)

    assert review_report.status == "completed"
    assert len(review_report.consolidated) == 2
    assert review_report.review == []
    updated_batch = runner.get_job_report(job.job_id)
    assert len(updated_batch.consolidated) == 2
    assert len({output.path for output in updated_batch.consolidated}) == 2

    next_job = runner.submit_scan_and_consolidate(config)
    next_report = _wait(runner, next_job.job_id)
    assert len(next_report.review) == 1
    assert len(next_report.skipped) == 1
    runner.shutdown()
    runner.database.engine.dispose()


@needs_mkv_tools
def test_corrupt_file_is_reported_without_blocking_other_group(tmp_path, monkeypatch):
    source = tmp_path / "library"
    _make_video(source / "Film (2020).mkv", "eng", width=128)
    _make_video(source / "Film.2020.mkv", "spa", width=64)
    (source / "broken.mkv").write_bytes(b"not media")
    runner = _runner(tmp_path, monkeypatch)
    config = LibraryConfig(source, source / "dub", "all")

    job = runner.submit_scan_and_consolidate(config)
    report = _wait(runner, job.job_id)

    assert report.status == "completed", report.errors
    assert len(report.consolidated) == 1
    assert any("broken.mkv" in error["message"] for error in report.errors)
    runner.shutdown()
    runner.database.engine.dispose()


def test_review_partition_is_validated_before_queueing(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        runner.submit_scan_and_consolidate(
            LibraryConfig(tmp_path / "missing", tmp_path / "missing" / "dub", "all")
        )
    runner.shutdown()
    runner.database.engine.dispose()
