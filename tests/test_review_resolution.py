from importlib import import_module

import pytest

from dubber.core import matching, mkv


def _api(name):
    module = import_module("dubber.core.review")
    function = getattr(module, name, None)
    assert callable(function), f"dubber.core.review.{name} must be implemented"
    return module, function


def _media(file_id, filename, year, duration_s=6000.0):
    identity = mkv.FileIdentity(file_id, filename, 1, 1)
    return mkv.MediaMetadata(identity=identity, duration_s=duration_s, tracks=[])


def _review_group(files):
    result = matching.build_candidate_groups(files)
    assert len(result.review_groups) == 1
    return result.review_groups[0]


def test_same_partition_resolves_one_current_batch_group():
    files = [
        _media("a", "Arrival (2016).mkv", 2016),
        _media("b", "Arrival.mkv", None),
    ]
    group = _review_group(files)
    module, resolve = _api("resolve_review_group")

    result = resolve(group, [["a", "b"]])

    assert len(result) == 1
    assert isinstance(result[0], module.ConfirmedGroup)
    assert result[0].group_id == group.group_id
    assert {member.identity.file_id for member in result[0].members} == {"a", "b"}


def test_separate_partition_splits_members_for_current_batch_only():
    files = [
        _media("a", "Arrival (2016).mkv", 2016),
        _media("b", "Arrival.mkv", None),
    ]
    group = _review_group(files)
    module, resolve = _api("resolve_review_group")

    result = resolve(group, [["a"], ["b"]])

    assert len(result) == 2
    assert all(isinstance(item, module.ConfirmedGroup) for item in result)
    assert [{member.identity.file_id for member in item.members} for item in result] == [
        {"a"},
        {"b"},
    ]
    assert result[0].group_id != result[1].group_id


@pytest.mark.parametrize(
    "partition",
    [
        [],
        [["a"]],
        [["a", "b", "b"]],
        [["a", "unknown"]],
        [["a"], []],
    ],
)
def test_invalid_partition_returns_review_error(partition):
    files = [
        _media("a", "Arrival (2016).mkv", 2016),
        _media("b", "Arrival.mkv", None),
    ]
    group = _review_group(files)
    module, resolve = _api("resolve_review_group")

    result = resolve(group, partition)

    assert isinstance(result, module.ReviewError)
    assert result.message


def test_review_resolution_does_not_persist_decisions_between_grouping_runs():
    files = [
        _media("a", "Arrival (2016).mkv", 2016),
        _media("b", "Arrival.mkv", None),
    ]
    group = _review_group(files)
    _, resolve = _api("resolve_review_group")

    resolve(group, [["a", "b"]])
    next_scan = matching.build_candidate_groups(files)

    assert next_scan.auto_groups == []
    assert len(next_scan.review_groups) == 1
    assert {member.identity.file_id for member in next_scan.review_groups[0].members} == {
        "a",
        "b",
    }


def test_resolving_one_review_group_leaves_other_batch_groups_available():
    files = [
        _media("a", "Arrival (2016).mkv", 2016),
        _media("b", "Arrival.mkv", None),
        _media("c", "Heat (1995).mkv", 1995),
        _media("d", "Heat.mkv", None),
    ]
    review_groups = matching.build_candidate_groups(files).review_groups
    assert len(review_groups) == 2
    other_group = review_groups[1]
    _, resolve = _api("resolve_review_group")

    resolve(review_groups[0], [["a", "b"]])

    assert len(review_groups) == 2
    assert review_groups[1] is other_group
