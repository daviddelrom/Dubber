import json
import subprocess
from types import SimpleNamespace

import pytest

from dubber.core import mkv
from dubber.core.mkv import parse_probe


@pytest.fixture
def probe_info():
    return {
        "tracks": [
            {
                "id": 0,
                "type": "video",
                "codec": "HEVC/H.265/MPEG-H",
                "properties": {
                    "codec_id": "V_MPEGH/ISO/HEVC",
                    "pixel_dimensions": "3840x2160",
                    "color_transfer_characteristics": "16",
                    "color_primaries": "9",
                },
            },
            {
                "id": 1,
                "type": "audio",
                "codec": "AAC",
                "properties": {
                    "codec_id": "A_AAC",
                    "audio_channels": 6,
                },
            },
        ]
    }


@pytest.fixture
def ffprobe_info():
    return {
        "streams": [
            {"index": 0, "codec_type": "video", "color_transfer": "smpte2084"},
            {"index": 1, "codec_type": "audio"},
        ]
    }


def test_parse_probe_reports_video_dimensions(probe_info):
    video = parse_probe(probe_info).tracks[0]

    assert (getattr(video, "width", None), getattr(video, "height", None)) == (
        3840,
        2160,
    )


def test_parse_probe_reports_video_codec_id(probe_info):
    video = parse_probe(probe_info).tracks[0]

    assert getattr(video, "codec_id", None) == "V_MPEGH/ISO/HEVC"


@pytest.mark.parametrize("transfer", ["16", "18"])
def test_parse_probe_detects_positive_hdr_transfers(probe_info, transfer):
    probe_info["tracks"][0]["properties"]["color_transfer_characteristics"] = transfer
    video = parse_probe(probe_info).tracks[0]

    assert getattr(video, "hdr_signals", None)


def test_parse_probe_does_not_infer_hdr_from_bt2020_primaries_alone(probe_info):
    video_info = probe_info["tracks"][0]
    del video_info["properties"]["color_transfer_characteristics"]

    video = parse_probe(probe_info).tracks[0]

    assert getattr(video, "hdr_signals", None) == []


def test_parse_probe_rejects_malformed_track_properties():
    with pytest.raises(mkv.MkvError, match="properties"):
        parse_probe({"tracks": [{"properties": []}]})


def test_parse_probe_treats_invalid_quality_values_as_unknown():
    info = {
        "tracks": [
            {
                "id": 0,
                "type": "video",
                "properties": {"pixel_dimensions": "unknown", "color_primaries": "9"},
            },
            {"id": 1, "type": "audio", "properties": {"audio_channels": "unknown"}},
        ]
    }

    video, audio = parse_probe(info).tracks

    assert (video.width, video.height, video.hdr_signals) == (None, None, [])
    assert audio.channels is None


def test_parse_probe_does_not_truncate_noninteger_channel_count():
    info = {
        "tracks": [
            {"id": 0, "type": "audio", "properties": {"audio_channels": 6.5}}
        ]
    }

    audio = parse_probe(info).tracks[0]

    assert audio.channels is None


def test_parse_probe_reports_audio_channels(probe_info):
    audio = parse_probe(probe_info).tracks[1]

    assert getattr(audio, "channels", None) == 6


def test_parse_probe_reports_audio_codec_id(probe_info):
    audio = parse_probe(probe_info).tracks[1]

    assert getattr(audio, "codec_id", None) == "A_AAC"


def test_probe_media_returns_identity_and_track_metadata(
    monkeypatch, tmp_path, probe_info, ffprobe_info
):
    identity = SimpleNamespace(
        file_id="file-1",
        relative_path="movie.mkv",
        size=123,
        mtime_ns=456,
    )
    media_file = SimpleNamespace(
        file_id="file-1",
        path=tmp_path / "movie.mkv",
        identity=identity,
    )
    mkvmerge_result = subprocess.CompletedProcess(
        args=["mkvmerge", "-J", str(media_file.path)],
        returncode=0,
        stdout=json.dumps(probe_info),
        stderr="",
    )
    ffprobe_result = subprocess.CompletedProcess(
        args=["ffprobe"],
        returncode=0,
        stdout=json.dumps(ffprobe_info),
        stderr="",
    )
    results = {"mkvmerge": mkvmerge_result, "ffprobe": ffprobe_result}
    commands = []

    def run(command, *args, **kwargs):
        commands.append(command)
        return results[command[0]]

    monkeypatch.setattr(mkv.subprocess, "run", run)

    metadata = mkv.probe_media(media_file)

    assert metadata.identity == identity
    assert metadata.duration_s is None
    assert metadata.tracks[0].codec_id == "V_MPEGH/ISO/HEVC"
    assert metadata.tracks[0].hdr_signals == ["pq"]
    assert metadata.tracks[1].channels == 6
    assert len(commands) == 2
    assert commands[0] == ["mkvmerge", "-J", str(media_file.path)]
    assert commands[1] == [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,color_transfer",
        "-of",
        "json",
        str(media_file.path),
    ]


def test_probe_media_returns_probe_error_for_mkvmerge_failure(monkeypatch, tmp_path):
    identity = SimpleNamespace(
        file_id="file-1",
        relative_path="movie.mkv",
        size=123,
        mtime_ns=456,
    )
    media_file = SimpleNamespace(
        file_id="file-1",
        path=tmp_path / "movie.mkv",
        identity=identity,
    )
    completed = subprocess.CompletedProcess(
        args=["mkvmerge", "-J", str(media_file.path)],
        returncode=2,
        stdout="",
        stderr="invalid media",
    )
    monkeypatch.setattr(mkv.subprocess, "run", lambda *args, **kwargs: completed)

    result = mkv.probe_media(media_file)

    assert isinstance(result, mkv.ProbeError)
    assert result.message == "invalid media"


def test_probe_media_returns_probe_error_for_missing_ffprobe(
    monkeypatch, tmp_path, probe_info
):
    identity = mkv.FileIdentity("file-1", "movie.mkv", 123, 456)
    media_file = mkv.MediaFileRef("file-1", tmp_path / "movie.mkv", identity)

    def run(command, *args, **kwargs):
        if command[0] == "ffprobe":
            raise FileNotFoundError("ffprobe not found")
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(probe_info),
            stderr="",
        )

    monkeypatch.setattr(mkv.subprocess, "run", run)

    result = mkv.probe_media(media_file)

    assert isinstance(result, mkv.ProbeError)
    assert "ffprobe" in result.message


def test_probe_media_returns_probe_error_for_ffprobe_failure(
    monkeypatch, tmp_path, probe_info
):
    identity = mkv.FileIdentity("file-1", "movie.mkv", 123, 456)
    media_file = mkv.MediaFileRef("file-1", tmp_path / "movie.mkv", identity)

    def run(command, *args, **kwargs):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args=command, returncode=1, stdout="", stderr="invalid stream data"
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(probe_info),
            stderr="",
        )

    monkeypatch.setattr(mkv.subprocess, "run", run)

    result = mkv.probe_media(media_file)

    assert isinstance(result, mkv.ProbeError)
    assert result.message == "invalid stream data"


def test_probe_media_maps_hdr_by_video_track_ordinal(monkeypatch, tmp_path):
    identity = mkv.FileIdentity("file-1", "movie.mkv", 123, 456)
    media_file = mkv.MediaFileRef("file-1", tmp_path / "movie.mkv", identity)
    mkvmerge_info = {
        "tracks": [
            {"id": 0, "type": "video", "properties": {}},
            {"id": 1, "type": "audio", "properties": {}},
            {"id": 2, "type": "video", "properties": {}},
        ]
    }
    ffprobe_info = {
        "streams": [
            {"index": 0, "codec_type": "audio"},
            {"index": 1, "codec_type": "video", "color_transfer": "smpte2084"},
            {"index": 2, "codec_type": "subtitle"},
            {"index": 3, "codec_type": "video", "color_transfer": "arib-std-b67"},
        ]
    }
    results = [
        subprocess.CompletedProcess(
            args=["mkvmerge"], returncode=0, stdout=json.dumps(mkvmerge_info), stderr=""
        ),
        subprocess.CompletedProcess(
            args=["ffprobe"], returncode=0, stdout=json.dumps(ffprobe_info), stderr=""
        ),
    ]
    monkeypatch.setattr(mkv.subprocess, "run", lambda *args, **kwargs: results.pop(0))

    result = mkv.probe_media(media_file)

    assert [track.hdr_signals for track in result.tracks] == [["pq"], [], ["hlg"]]


def test_probe_media_rejects_mismatched_video_stream_counts(
    monkeypatch, tmp_path, probe_info
):
    identity = mkv.FileIdentity("file-1", "movie.mkv", 123, 456)
    media_file = mkv.MediaFileRef("file-1", tmp_path / "movie.mkv", identity)
    ffprobe_info = {
        "streams": [
            {"index": 0, "codec_type": "video", "color_transfer": "smpte2084"},
            {"index": 1, "codec_type": "video", "color_transfer": "arib-std-b67"},
        ]
    }
    results = [
        subprocess.CompletedProcess(
            args=["mkvmerge"], returncode=0, stdout=json.dumps(probe_info), stderr=""
        ),
        subprocess.CompletedProcess(
            args=["ffprobe"], returncode=0, stdout=json.dumps(ffprobe_info), stderr=""
        ),
    ]
    monkeypatch.setattr(mkv.subprocess, "run", lambda *args, **kwargs: results.pop(0))

    result = mkv.probe_media(media_file)

    assert isinstance(result, mkv.ProbeError)
    assert "vídeo" in result.message


def test_probe_media_keeps_unknown_ffprobe_transfer_non_hdr(
    monkeypatch, tmp_path, probe_info
):
    identity = mkv.FileIdentity("file-1", "movie.mkv", 123, 456)
    media_file = mkv.MediaFileRef("file-1", tmp_path / "movie.mkv", identity)
    ffprobe_info = {
        "streams": [{"index": 0, "codec_type": "video", "color_transfer": "unknown"}]
    }
    results = [
        subprocess.CompletedProcess(
            args=["mkvmerge"], returncode=0, stdout=json.dumps(probe_info), stderr=""
        ),
        subprocess.CompletedProcess(
            args=["ffprobe"], returncode=0, stdout=json.dumps(ffprobe_info), stderr=""
        ),
    ]
    monkeypatch.setattr(mkv.subprocess, "run", lambda *args, **kwargs: results.pop(0))

    result = mkv.probe_media(media_file)

    assert result.tracks[0].hdr_signals == []
