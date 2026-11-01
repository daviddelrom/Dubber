import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dubber.core import consolidation, mkv
from dubber.core.review import ConfirmedGroup

needs_mkv_tools = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("mkvmerge")),
    reason="requires ffmpeg, ffprobe and mkvmerge",
)


def _run(command):
    subprocess.run(command, check=True, capture_output=True, text=True)


def _make_source(root: Path, name: str, language: str, width: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    silent_path = root / f"{name}-video.mkv"
    _run(
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
            str(silent_path),
        ]
    )
    subtitle_path = root / f"{name}.srt"
    subtitle_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nsubtitle\n", encoding="utf-8"
    )
    source_path = root / f"{name}.mkv"
    _run(
        [
            "mkvmerge",
            "-o",
            str(source_path),
            str(silent_path),
            "--language",
            f"0:{language}",
            str(subtitle_path),
        ]
    )
    silent_path.unlink()
    subtitle_path.unlink()
    return source_path


@needs_mkv_tools
def test_real_mux_selects_tracks_preserves_subtitle_provenance_and_sources(tmp_path):
    source_root = tmp_path / "source"
    first = _make_source(source_root / "high", "original", "eng", 128)
    second = _make_source(source_root / "low", "dubbed", "spa", 64)
    media_files = []
    for index, path in enumerate([first, second]):
        relative = path.relative_to(source_root).as_posix()
        stat = path.stat()
        identity = mkv.FileIdentity(str(index), relative, stat.st_size, stat.st_mtime_ns)
        metadata = mkv.probe_media(mkv.MediaFileRef(str(index), path, identity))
        assert isinstance(metadata, mkv.MediaMetadata)
        media_files.append(metadata)
    source_hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in (first, second)}
    manifest = consolidation.plan_consolidation(
        ConfirmedGroup("real-group", media_files), {"eng", "spa"}, source_root
    )
    assert isinstance(manifest, consolidation.ConsolidationManifest)

    result = consolidation.execute_consolidation(manifest)

    assert isinstance(result, consolidation.CompletedOutput)
    output = source_root / "dub" / "high" / "original.mkv"
    assert result.path == output
    output_tracks = mkv.probe(output).tracks
    assert [track.type for track in output_tracks].count("video") == 1
    assert {
        consolidation._language_code(track.language)
        for track in output_tracks
        if track.type == "audio"
    } == {"eng", "spa"}
    subtitles = [track for track in output_tracks if track.type == "subtitles"]
    assert len(subtitles) == 2
    assert {track.name for track in subtitles} == {
        "original.mkv — eng",
        "dubbed.mkv — spa",
    }
    assert {path: hashlib.sha256(path.read_bytes()).digest() for path in source_hashes} == source_hashes
    assert not output.with_name(output.stem + ".partial.mkv").exists()


def test_existing_unowned_output_is_not_replaced(tmp_path):
    source_root = tmp_path / "source"
    first = _make_source(source_root / "high", "original", "eng", 128)
    second = _make_source(source_root / "low", "dubbed", "spa", 64)
    media_files = []
    for index, path in enumerate((first, second)):
        relative = path.relative_to(source_root).as_posix()
        stat = path.stat()
        identity = mkv.FileIdentity(str(index), relative, stat.st_size, stat.st_mtime_ns)
        metadata = mkv.probe_media(mkv.MediaFileRef(str(index), path, identity))
        media_files.append(metadata)
    manifest = consolidation.plan_consolidation(
        ConfirmedGroup("collision-group", media_files), {"eng", "spa"}, source_root
    )
    assert isinstance(manifest, consolidation.ConsolidationManifest)
    output = source_root / "dub" / manifest.output_relpath
    output.parent.mkdir(parents=True)
    output.write_bytes(b"valuable existing file")
    previous = output.read_bytes()

    result = consolidation.execute_consolidation(manifest)

    assert isinstance(result, consolidation.MergeError)
    assert output.read_bytes() == previous


def test_cancel_before_merge_preserves_existing_output_and_removes_partial(tmp_path):
    source_root = tmp_path / "source"
    first = _make_source(source_root / "high", "original", "eng", 128)
    second = _make_source(source_root / "low", "dubbed", "spa", 64)
    media_files = []
    for index, path in enumerate((first, second)):
        relative = path.relative_to(source_root).as_posix()
        stat = path.stat()
        identity = mkv.FileIdentity(str(index), relative, stat.st_size, stat.st_mtime_ns)
        media_files.append(
            mkv.probe_media(mkv.MediaFileRef(str(index), path, identity))
        )
    manifest = consolidation.plan_consolidation(
        ConfirmedGroup("cancel-group", media_files), {"eng", "spa"}, source_root
    )
    assert isinstance(manifest, consolidation.ConsolidationManifest)
    output = source_root / "dub" / manifest.output_relpath
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous valid output")

    result = consolidation.execute_consolidation(
        manifest, is_cancelled=lambda: True, replace_existing=True
    )

    assert isinstance(result, consolidation.Cancelled)
    assert output.read_bytes() == b"previous valid output"
    assert not output.with_name(output.stem + ".partial.mkv").exists()


def test_process_failure_preserves_existing_output_and_cleans_partial(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    first = _make_source(source_root / "high", "original", "eng", 128)
    second = _make_source(source_root / "low", "dubbed", "spa", 64)
    media_files = []
    for index, path in enumerate((first, second)):
        relative = path.relative_to(source_root).as_posix()
        stat = path.stat()
        identity = mkv.FileIdentity(str(index), relative, stat.st_size, stat.st_mtime_ns)
        media_files.append(
            mkv.probe_media(mkv.MediaFileRef(str(index), path, identity))
        )
    manifest = consolidation.plan_consolidation(
        ConfirmedGroup("failure-group", media_files), {"eng", "spa"}, source_root
    )
    assert isinstance(manifest, consolidation.ConsolidationManifest)
    output = source_root / "dub" / manifest.output_relpath
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous valid output")
    calls = []

    class FailedProcess:
        def __init__(self, command, **kwargs):
            calls.append(command)
            read_fd, write_fd = os.pipe()
            os.write(write_fd, b"mux failed\n")
            os.close(write_fd)
            self.stdout = os.fdopen(read_fd, "rb", buffering=0)

        def wait(self, timeout=None):
            return 2

    def fail_run(command, **kwargs):
        return FailedProcess(command, **kwargs)

    monkeypatch.setattr(consolidation.subprocess, "Popen", fail_run)

    result = consolidation.execute_consolidation(
        manifest, replace_existing=True
    )

    assert isinstance(result, consolidation.MergeError)
    assert output.read_bytes() == b"previous valid output"
    assert not output.with_name(output.stem + ".partial.mkv").exists()
    assert calls
