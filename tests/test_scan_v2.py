from importlib import import_module
from pathlib import Path

from dubber.core import mkv


def _api(name):
    module = import_module("dubber.jobs.library_scan")
    function = getattr(module, name, None)
    assert callable(function), f"dubber.jobs.library_scan.{name} must be implemented"
    return module, function


def _config(source_root: Path, language_mode="all"):
    module, _ = _api("scan_library")
    return module.LibraryConfig(
        source_root=source_root,
        output_root=source_root / "dub",
        language_mode=language_mode,
    )


def _write(path: Path, content=b"source"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _metadata(media_file, duration_s=6000.0):
    return mkv.MediaMetadata(
        identity=media_file.identity,
        duration_s=duration_s,
        tracks=[
            mkv.TrackMetadata(
                track_no=0,
                type="video",
                language="und",
                codec_id="V_MPEGH/ISO/HEVC",
                channels=None,
                width=1920,
                height=1080,
                hdr_signals=[],
            )
        ],
    )


def test_scan_recursively_indexes_supported_extensions_and_excludes_output(
    tmp_path, monkeypatch
):
    source = tmp_path / "library"
    _write(source / "Movies" / "Film.MKV")
    _write(source / "Shows" / "Episode.mp4")
    _write(source / "nested" / "dub" / "still-a-source.avi")
    _write(source / "dub" / "already-consolidated.mkv")
    _write(source / "captions.srt")
    monkeypatch.setenv("DUBBER_DB", str(tmp_path / "library.db"))
    module, scan = _api("scan_library")
    probed = []

    def fake_probe(media_file):
        probed.append(media_file.identity.relative_path)
        return _metadata(media_file)

    monkeypatch.setattr(module, "probe_media", fake_probe)

    report = scan(_config(source))

    assert report.indexed == 3
    assert report.changed == 3
    assert report.unreadable == []
    assert {file.identity.relative_path for file in report.files} == {
        "Movies/Film.MKV",
        "Shows/Episode.mp4",
        "nested/dub/still-a-source.avi",
    }
    assert "dub/already-consolidated.mkv" not in probed


def test_unchanged_files_reuse_persisted_metadata_without_reprobing(
    tmp_path, monkeypatch
):
    source = tmp_path / "library"
    _write(source / "Film.mkv")
    monkeypatch.setenv("DUBBER_DB", str(tmp_path / "library.db"))
    module, scan = _api("scan_library")
    calls = []

    def fake_probe(media_file):
        calls.append(media_file.identity.file_id)
        return _metadata(media_file)

    monkeypatch.setattr(module, "probe_media", fake_probe)
    first_report = scan(_config(source))

    def unexpected_probe(_media_file):
        raise AssertionError("an unchanged readable file must not be probed again")

    monkeypatch.setattr(module, "probe_media", unexpected_probe)
    second_report = scan(_config(source))

    assert len(calls) == 1
    assert first_report.changed == 1
    assert second_report.indexed == 1
    assert second_report.changed == 0
    assert second_report.files[0].identity == first_report.files[0].identity
    assert second_report.files[0].tracks == first_report.files[0].tracks


def test_changed_file_is_reprobed_and_metadata_is_refreshed(tmp_path, monkeypatch):
    source = tmp_path / "library"
    path = _write(source / "Film.mkv", b"first")
    monkeypatch.setenv("DUBBER_DB", str(tmp_path / "library.db"))
    module, scan = _api("scan_library")
    probe_count = 0

    def first_probe(media_file):
        nonlocal probe_count
        probe_count += 1
        return _metadata(media_file, duration_s=1000.0)

    monkeypatch.setattr(module, "probe_media", first_probe)
    first_report = scan(_config(source))
    path.write_bytes(b"changed content")

    def second_probe(media_file):
        nonlocal probe_count
        probe_count += 1
        return _metadata(media_file, duration_s=2000.0)

    monkeypatch.setattr(module, "probe_media", second_probe)
    second_report = scan(_config(source))

    assert probe_count == 2
    assert second_report.changed == 1
    assert second_report.files[0].duration_s == 2000.0
    assert first_report.files[0].identity.file_id == second_report.files[0].identity.file_id


def test_probe_error_is_reported_and_scan_continues(tmp_path, monkeypatch):
    source = tmp_path / "library"
    _write(source / "bad.mkv")
    _write(source / "good.mkv")
    monkeypatch.setenv("DUBBER_DB", str(tmp_path / "library.db"))
    module, scan = _api("scan_library")

    def fake_probe(media_file):
        if media_file.identity.relative_path == "bad.mkv":
            return mkv.ProbeError("corrupt media")
        return _metadata(media_file)

    monkeypatch.setattr(module, "probe_media", fake_probe)

    report = scan(_config(source))

    assert report.indexed == 2
    assert report.changed == 2
    assert len(report.unreadable) == 1
    assert report.unreadable[0].relative_path == "bad.mkv"
    assert [file.identity.relative_path for file in report.files] == ["good.mkv"]


def test_invalid_library_root_returns_scan_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DUBBER_DB", str(tmp_path / "library.db"))
    module, scan = _api("scan_library")
    report = scan(_config(tmp_path / "missing"))

    assert isinstance(report, module.ScanError)
    assert "directorio" in report.message


def test_scan_uses_explicit_database_path_instead_of_environment_default(
    tmp_path, monkeypatch
):
    source = tmp_path / "library"
    _write(source / "Film.mkv")
    environment_database = tmp_path / "environment.db"
    explicit_database = tmp_path / "explicit.db"
    monkeypatch.setenv("DUBBER_DB", str(environment_database))
    module, scan = _api("scan_library")
    monkeypatch.setattr(module, "probe_media", lambda media_file: _metadata(media_file))

    report = scan(_config(source), database_path=explicit_database)

    assert report.indexed == 1
    assert explicit_database.is_file()
    assert not environment_database.exists()
