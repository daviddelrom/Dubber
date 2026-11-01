from pathlib import Path

from dubber.core import matching, mkv
from dubber.core import consolidation
from dubber.core.review import ConfirmedGroup

ConsolidationManifest = getattr(consolidation, "ConsolidationManifest", None)
ReviewRequired = getattr(consolidation, "ReviewRequired", None)
plan_consolidation = getattr(consolidation, "plan_consolidation", None)


def _media(file_id, relative_path, tracks):
    identity = mkv.FileIdentity(file_id, relative_path, 100, 200)
    return mkv.MediaMetadata(identity=identity, duration_s=6000.0, tracks=tracks)


def _track(
    track_no,
    kind,
    language="und",
    codec_id="",
    channels=None,
    width=None,
    height=None,
    hdr_signals=None,
):
    return mkv.TrackMetadata(
        track_no=track_no,
        type=kind,
        language=language,
        codec_id=codec_id,
        channels=channels,
        width=width,
        height=height,
        hdr_signals=hdr_signals or [],
    )


def _group(*members):
    return ConfirmedGroup("confirmed-group", list(members))


def test_video_ranking_prefers_resolution_then_hdr_then_codec_then_path(tmp_path):
    group = _group(
        _media(
            "a",
            "z/film.mkv",
            [_track(0, "video", codec_id="V_MPEG4/ISO/AVC", width=1920, height=1080)],
        ),
        _media(
            "b",
            "b/film.mkv",
            [_track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1280, height=720, hdr_signals=["pq"])],
        ),
        _media(
            "c",
            "c/film.mkv",
            [_track(0, "video", codec_id="V_AV1", width=1920, height=1080, hdr_signals=["hlg"])],
        ),
        _media(
            "d",
            "a/film.mkv",
            [_track(0, "video", codec_id="V_AV1", width=1920, height=1080, hdr_signals=["pq"])],
        ),
    )

    manifest = plan_consolidation(group, {"eng"}, tmp_path)

    assert isinstance(manifest, ConsolidationManifest)
    assert manifest.video.source_file_id == "d"
    assert manifest.video.track_no == 0
    assert manifest.output_relpath == "a/film.mkv"


def test_audio_ranking_prefers_channels_before_codec_efficiency(tmp_path):
    group = _group(
        _media(
            "a",
            "film.mkv",
            [
                _track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080),
                _track(1, "audio", "eng", "A_OPUS", channels=2),
            ],
        ),
        _media(
            "b",
            "film-copy.mkv",
            [
                _track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1280, height=720),
                _track(1, "audio", "eng", "A_AAC", channels=6),
            ],
        ),
    )

    manifest = plan_consolidation(group, {"eng"}, tmp_path)

    assert isinstance(manifest, ConsolidationManifest)
    assert [(track.source_file_id, track.track_no) for track in manifest.audio] == [("b", 1)]


def test_audio_codec_efficiency_breaks_channel_tie(tmp_path):
    group = _group(
        _media(
            "a",
            "film.mkv",
            [
                _track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080),
                _track(1, "audio", "eng", "A_AAC", channels=6),
            ],
        ),
        _media(
            "b",
            "film-copy.mkv",
            [
                _track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1280, height=720),
                _track(1, "audio", "eng", "A_OPUS", channels=6),
            ],
        ),
    )

    manifest = plan_consolidation(group, {"eng"}, tmp_path)

    assert isinstance(manifest, ConsolidationManifest)
    assert manifest.audio[0].source_file_id == "b"


def test_language_filter_keeps_at_most_one_audio_per_selected_language(tmp_path):
    group = _group(
        _media(
            "a",
            "film.mkv",
            [
                _track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080),
                _track(1, "audio", "eng", "A_AAC", channels=2),
                _track(2, "audio", "eng", "A_OPUS", channels=2),
                _track(3, "audio", "spa", "A_AAC", channels=6),
                _track(4, "audio", "fra", "A_OPUS", channels=2),
            ],
        ),
        _media(
            "b",
            "film-copy.mkv",
            [
                _track(0, "video", codec_id="V_MPEG4/ISO/AVC", width=1280, height=720),
                _track(1, "audio", "spa", "A_OPUS", channels=6),
            ],
        ),
    )

    manifest = plan_consolidation(group, {"eng", "spa"}, tmp_path)

    assert isinstance(manifest, ConsolidationManifest)
    assert {track.language for track in manifest.audio} == {"eng", "spa"}
    assert len(manifest.audio) == 2
    assert len({track.language for track in manifest.audio}) == len(manifest.audio)


def test_sole_untagged_audio_is_treated_as_spanish(tmp_path):
    group = _group(
        _media(
            "a",
            "film.mkv",
            [
                _track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080),
                _track(1, "audio", "und", "A_AAC", channels=2),
            ],
        ),
        _media(
            "b",
            "film-copy.mkv",
            [
                _track(0, "video", codec_id="V_MPEG4/ISO/AVC", width=1280, height=720),
                _track(1, "audio", "eng", "A_AAC", channels=2),
            ],
        ),
    )

    manifest = plan_consolidation(group, {"spa"}, tmp_path)

    assert isinstance(manifest, ConsolidationManifest)
    assert len(manifest.audio) == 1
    assert manifest.audio[0].source_file_id == "a"
    assert manifest.audio[0].language == "spa"


def test_multiple_untagged_audio_tracks_require_review(tmp_path):
    group = _group(
        _media(
            "a",
            "film.mkv",
            [
                _track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080),
                _track(1, "audio", "und", "A_AAC", channels=2),
                _track(2, "audio", "eng", "A_OPUS", channels=2),
            ],
        ),
        _media(
            "b",
            "film-copy.mkv",
            [_track(0, "video", codec_id="V_MPEG4/ISO/AVC", width=1280, height=720)],
        ),
    )

    result = plan_consolidation(group, {"eng", "spa"}, tmp_path)

    assert isinstance(result, ReviewRequired)
    assert "untagged" in result.reason


def test_all_available_subtitles_keep_source_basename(tmp_path):
    group = _group(
        _media(
            "a",
            "season 1/film.mkv",
            [
                _track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080),
                _track(1, "subtitles", "eng", "S_TEXT/UTF8"),
            ],
        ),
        _media(
            "b",
            "film-copy.mkv",
            [
                _track(0, "video", codec_id="V_MPEG4/ISO/AVC", width=1280, height=720),
                _track(2, "subtitles", "spa", "S_TEXT/UTF8"),
            ],
        ),
    )

    manifest = plan_consolidation(group, {"eng"}, tmp_path)

    assert isinstance(manifest, ConsolidationManifest)
    assert [(track.language, track.name) for track in manifest.subtitles] == [
        ("spa", "film-copy.mkv — spa"),
        ("eng", "film.mkv — eng"),
    ]


def test_single_file_or_missing_video_returns_review_required(tmp_path):
    single = _group(
        _media(
            "a",
            "film.mkv",
            [_track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080)],
        )
    )
    no_video = _group(
        _media("a", "film.mkv", [_track(0, "audio", "eng", "A_AAC", channels=2)]),
        _media("b", "film-copy.mkv", [_track(0, "audio", "eng", "A_AAC", channels=2)]),
    )

    assert isinstance(plan_consolidation(single, {"eng"}, tmp_path), ReviewRequired)
    assert isinstance(plan_consolidation(no_video, {"eng"}, tmp_path), ReviewRequired)


def test_manifest_input_signature_changes_when_source_changes(tmp_path):
    members = [
        _media(
            "a",
            "film.mkv",
            [_track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080)],
        ),
        _media(
            "b",
            "film-copy.mkv",
            [_track(0, "video", codec_id="V_MPEG4/ISO/AVC", width=1280, height=720)],
        ),
    ]
    first = plan_consolidation(_group(*members), {"eng"}, tmp_path)
    changed = members[1]
    changed = mkv.MediaMetadata(
        identity=mkv.FileIdentity(changed.identity.file_id, changed.identity.relative_path, 101, 200),
        duration_s=changed.duration_s,
        tracks=changed.tracks,
    )
    second = plan_consolidation(_group(members[0], changed), {"eng"}, tmp_path)

    assert isinstance(first, ConsolidationManifest)
    assert isinstance(second, ConsolidationManifest)
    assert first.input_signature != second.input_signature


def test_output_path_must_not_escape_dub_root(tmp_path):
    group = _group(
        _media(
            "a",
            "../escape.mkv",
            [_track(0, "video", codec_id="V_MPEGH/ISO/HEVC", width=1920, height=1080)],
        ),
        _media(
            "b",
            "copy.mkv",
            [_track(0, "video", codec_id="V_MPEG4/ISO/AVC", width=1280, height=720)],
        ),
    )

    result = plan_consolidation(group, {"eng"}, tmp_path)

    assert isinstance(result, ReviewRequired)
    assert "path" in result.reason
