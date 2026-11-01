from pathlib import Path

import pytest

from dubber.core import matching, mkv
from dubber.core.naming import is_video, parse_name


def test_parse_name_movie_and_episode():
    assert parse_name("tt1234567_pelicula.mkv") == parse_name("tt1234567.mkv")
    info = parse_name("Show tt7654321 s02e10.mkv")
    assert (info.imdb_id, info.season, info.episode) == ("tt7654321", 2, 10)
    assert parse_name("sin_id.mkv").imdb_id is None


def test_is_video():
    assert is_video("a.MKV") and is_video("a.mp4") and not is_video("a.srt")


def test_duration_status():
    assert matching.duration_status(100.0, 100.8) == (pytest.approx(0.8), "ideal")
    assert matching.duration_status(100.0, 102.0)[1] == "doubtful"
    assert matching.duration_status(None, 100.0) == (None, "doubtful")


def test_find_pairs_matches_by_imdb_and_episode():
    ref = matching.FileRef
    esp = [ref(1, "a", "tt1", None, None, 10.0), ref(2, "b", "tt2", 1, 1, 10.0),
           ref(3, "c", None, None, None, 10.0)]
    eng = [ref(11, "a", "tt1", None, None, 10.2), ref(12, "b", "tt2", 1, 2, 10.0)]
    pairs = matching.find_pairs(esp, eng)
    assert [(p.esp_id, p.eng_id, p.status) for p in pairs] == [(1, 11, "ideal")]


def test_parse_probe_prefers_container_duration_and_normalizes_language():
    info = {
        "container": {"properties": {"duration": 90_000_000_000}},
        "tracks": [
            {"id": 0, "type": "video", "codec": "V", "properties": {"tag_duration": "0:00:10.0"}},
            {"id": 1, "type": "audio", "codec": "A", "properties": {"language_ietf": "es-ES"}},
        ],
    }
    p = mkv.parse_probe(info)
    assert p.duration_s == 90.0
    assert mkv.is_spanish(p.tracks[1].language) and not mkv.is_spanish("en")


def test_parse_probe_without_duration_is_unknown():
    assert mkv.parse_probe({"tracks": []}).duration_s is None


def test_build_merge_command_takes_only_spanish_audio():
    cmd = mkv.build_merge_command(Path("o.mkv"), Path("es.mkv"), Path("en.mkv"), [1, 2])
    assert cmd[cmd.index("-a") + 1] == "1,2" and "-D" in cmd
    assert cmd.index("es.mkv") < cmd.index("en.mkv")
    with pytest.raises(mkv.MkvError):
        mkv.build_merge_command(Path("o.mkv"), Path("es.mkv"), Path("en.mkv"), [])
