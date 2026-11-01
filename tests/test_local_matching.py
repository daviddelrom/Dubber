import pytest

from dubber.core import matching, mkv
from dubber.core import naming


def _api(module, name):
    function = getattr(module, name, None)
    assert callable(function), f"{module.__name__}.{name} must be implemented"
    return function


def _media(file_id, filename, duration_s):
    identity = mkv.FileIdentity(
        file_id=file_id,
        relative_path=filename,
        size=1,
        mtime_ns=1,
    )
    return mkv.MediaMetadata(identity=identity, duration_s=duration_s, tracks=[])


def _member_ids(group):
    return {member.identity.file_id for member in group.members}


def test_parse_name_supports_both_episode_conventions():
    parse_name = naming.parse_name

    standard = parse_name("Serie.S01E02.mkv")
    alternate = parse_name("Serie.1x02.mkv")

    assert (standard.season, standard.episode) == (1, 2)
    assert (alternate.season, alternate.episode) == (1, 2)


def test_parse_name_extracts_movie_year():
    info = naming.parse_name("Amelie (2001).mkv")

    assert getattr(info, "year", None) == 2001


def test_parenthesized_year_wins_over_year_like_title_token():
    filename = "2001 A Space Odyssey (1968).mkv"

    assert naming.parse_name(filename).year == 1968
    assert _api(naming, "normalize_title")(filename) == "2001 a space odyssey"


def test_normalize_title_handles_accents_punctuation_year_and_episode():
    normalize_title = _api(naming, "normalize_title")

    assert normalize_title("Amélie (2001).mkv") == "amelie"
    assert normalize_title("Serie.S01E02.mkv") == "serie"
    assert normalize_title("Serie.1x02.mkv") == "serie"


def test_jaccard_similarity_has_exact_boundary_values():
    similarity = _api(matching, "jaccard_similarity")

    shared = {f"shared-{index}" for index in range(39)}
    at_threshold = shared | {f"right-{index}" for index in range(11)}
    below_shared = {f"below-{index}" for index in range(38)}
    below_left = below_shared | {f"left-{index}" for index in range(6)}
    below_right = below_shared | {f"right-{index}" for index in range(6)}

    assert similarity(shared, at_threshold) == 0.78
    assert similarity(below_left, below_right) == 0.76
    assert similarity(set(), set()) == 0.0


def test_identical_movie_title_year_and_compatible_duration_auto_group():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Amelie (2001).mkv", 6000.0),
        _media("b", "Amelie.2001.mkv", 5880.0),
    ]

    result = build(files)

    assert len(result.auto_groups) == 1
    assert _member_ids(result.auto_groups[0]) == {"a", "b"}
    assert result.review_groups == []
    assert result.unique_files == []


def test_same_title_with_conflicting_year_is_reviewed_not_auto_grouped():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "The Thing (1982).mkv", 6000.0),
        _media("b", "The Thing (2011).mkv", 6000.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert len(result.review_groups) == 1
    assert _member_ids(result.review_groups[0]) == {"a", "b"}


def test_missing_duration_routes_exact_title_match_to_review():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Arrival (2016).mkv", 6000.0),
        _media("b", "Arrival.2016.mkv", None),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert len(result.review_groups) == 1
    assert _member_ids(result.review_groups[0]) == {"a", "b"}


@pytest.mark.parametrize("duration", [0.0, -1.0, float("inf"), float("nan")])
def test_invalid_duration_is_treated_as_unknown(duration):
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Arrival (2016).mkv", duration),
        _media("b", "Arrival.2016.mkv", 6000.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert len(result.review_groups) == 1


def test_missing_movie_year_routes_exact_title_match_to_review():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Arrival (2016).mkv", 6000.0),
        _media("b", "Arrival.mkv", 6000.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert len(result.review_groups) == 1
    assert _member_ids(result.review_groups[0]) == {"a", "b"}


def test_episode_number_forms_auto_group_when_series_and_duration_match():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Serie.S01E02.mkv", 2500.0),
        _media("b", "Serie.1x02.mkv", 2400.0),
    ]

    result = build(files)

    assert len(result.auto_groups) == 1
    assert _member_ids(result.auto_groups[0]) == {"a", "b"}
    assert result.review_groups == []


def test_different_episode_numbers_are_not_grouped():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Serie.S01E02.mkv", 2500.0),
        _media("b", "Serie.S01E03.mkv", 2500.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert result.review_groups == []
    assert {file.file_id for file in result.unique_files} == {"a", "b"}


def test_episode_duration_boundary_uses_five_percent_of_longer_duration():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Serie.S01E02.mkv", 10_000.0),
        _media("b", "Serie.1x02.mkv", 9_500.0),
    ]

    result = build(files)

    assert len(result.auto_groups) == 1


def test_episode_duration_over_five_percent_is_reviewed():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Serie.S01E02.mkv", 10_000.0),
        _media("b", "Serie.1x02.mkv", 9_499.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert len(result.review_groups) == 1


def test_fuzzy_candidate_at_threshold_is_reviewed_not_auto_grouped():
    build = _api(matching, "build_candidate_groups")
    shared = " ".join(f"common{index}" for index in range(39))
    left = " ".join(
        [shared, *(f"left{index}" for index in range(5)), "2020", "1080p", "x265"]
    )
    right = " ".join(
        [shared, *(f"right{index}" for index in range(6)), "2020", "bluray", "x264"]
    )
    files = [_media("a", f"{left}.mkv", 6000.0), _media("b", f"{right}.mkv", 6000.0)]

    result = build(files)

    assert result.auto_groups == []
    assert len(result.review_groups) == 1
    assert _member_ids(result.review_groups[0]) == {"a", "b"}


def test_fuzzy_candidate_below_threshold_remains_unique():
    build = _api(matching, "build_candidate_groups")
    shared = " ".join(f"common{index}" for index in range(38))
    left = " ".join([shared, *(f"left{index}" for index in range(6)), "2020"])
    right = " ".join([shared, *(f"right{index}" for index in range(6)), "2020"])

    result = build(
        [
            _media("a", f"{left}.mkv", 6000.0),
            _media("b", f"{right}.mkv", 6000.0),
        ]
    )

    assert result.auto_groups == []
    assert result.review_groups == []
    assert {file.file_id for file in result.unique_files} == {"a", "b"}


def test_fuzzy_candidate_with_conflicting_years_remains_unique():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Alpha Beta Gamma Delta 2020.mkv", 6000.0),
        _media("b", "Alpha Beta Gamma Delta Epsilon 2021.mkv", 6000.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert result.review_groups == []
    assert {file.file_id for file in result.unique_files} == {"a", "b"}


def test_fuzzy_candidate_with_incompatible_duration_remains_unique():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Alpha Beta Gamma Delta 2020.mkv", 6000.0),
        _media("b", "Alpha Beta Gamma Delta Epsilon 2020.mkv", 5000.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert result.review_groups == []
    assert {file.file_id for file in result.unique_files} == {"a", "b"}


def test_low_similarity_candidates_remain_unique():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Alpha Beta 2020.mkv", 6000.0),
        _media("b", "Gamma Delta 2020.mkv", 6000.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert result.review_groups == []
    assert {file.file_id for file in result.unique_files} == {"a", "b"}


def test_fuzzy_one_token_title_does_not_create_review_candidate():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Arrival.2020.1080p.mkv", 6000.0),
        _media("b", "Arrival.2020.bluray.mkv", 6000.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert result.review_groups == []
    assert {file.file_id for file in result.unique_files} == {"a", "b"}


def test_duration_boundary_uses_two_percent_or_120_seconds():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Film (2020).mkv", 10_000.0),
        _media("b", "Film.2020.mkv", 9_800.0),
    ]

    result = build(files)

    assert len(result.auto_groups) == 1


def test_movie_duration_over_two_percent_is_reviewed():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Film (2020).mkv", 10_000.0),
        _media("b", "Film.2020.mkv", 9_799.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert len(result.review_groups) == 1


def test_transitive_incompatible_duration_component_goes_to_review():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("a", "Film (2020).mkv", 1000.0),
        _media("b", "Film.2020.mkv", 1100.0),
        _media("c", "Film 2020.mkv", 1200.0),
    ]

    result = build(files)

    assert result.auto_groups == []
    assert len(result.review_groups) == 1
    assert _member_ids(result.review_groups[0]) == {"a", "b", "c"}


def test_grouping_is_deterministic_and_does_not_duplicate_auto_members():
    build = _api(matching, "build_candidate_groups")
    files = [
        _media("b", "Film.2020.mkv", 6000.0),
        _media("c", "Unique (2022).mkv", 5000.0),
        _media("a", "Film (2020).mkv", 6000.0),
    ]

    result = build(files)
    reversed_result = build(list(reversed(files)))

    assert [
        _member_ids(group) for group in result.auto_groups
    ] == [_member_ids(group) for group in reversed_result.auto_groups]
    auto_member_ids = [
        member.identity.file_id
        for group in result.auto_groups
        for member in group.members
    ]
    assert len(auto_member_ids) == len(set(auto_member_ids))
    assert {file.file_id for file in result.unique_files} == {"c"}
