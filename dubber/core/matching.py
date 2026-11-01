import hashlib
import math
from dataclasses import dataclass

from . import naming
from .mkv import FileIdentity, MediaMetadata

DURATION_TOLERANCE_S = 1.0

IDEAL = "ideal"
DOUBTFUL = "doubtful"
MOVIE_AUTO_TOLERANCE = 0.02
EPISODE_AUTO_TOLERANCE = 0.05
MIN_DURATION_TOLERANCE_S = 120.0
FUZZY_REVIEW_THRESHOLD = 0.78

_RELEASE_TOKENS = {
    "480p",
    "576p",
    "720p",
    "1080p",
    "1440p",
    "2160p",
    "4k",
    "8k",
    "bluray",
    "brrip",
    "bdrip",
    "web",
    "webrip",
    "webdl",
    "hdtv",
    "dvdrip",
    "remux",
    "x264",
    "h264",
    "avc",
    "x265",
    "h265",
    "hevc",
    "av1",
    "aac",
    "ac3",
    "eac3",
    "dts",
    "truehd",
    "atmos",
    "flac",
    "mp3",
    "opus",
}


@dataclass(frozen=True)
class FileRef:
    id: int
    relpath: str
    imdb_id: str | None
    season: int | None
    episode: int | None
    duration_s: float | None


@dataclass(frozen=True)
class Pair:
    esp_id: int
    eng_id: int
    duration_diff_s: float | None
    status: str


@dataclass(frozen=True)
class AutoGroup:
    group_id: str
    members: list[MediaMetadata]


@dataclass(frozen=True)
class ReviewGroup:
    group_id: str
    members: list[MediaMetadata]
    reason: str


@dataclass(frozen=True)
class GroupingResult:
    auto_groups: list[AutoGroup]
    review_groups: list[ReviewGroup]
    unique_files: list[FileIdentity]


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _duration_tolerance(left: float, right: float, fraction: float) -> float:
    return max(MIN_DURATION_TOLERANCE_S, max(left, right) * fraction)


def _usable_duration(value: float | None) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    ):
        return float(value)
    return None


def _fuzzy_tokens(filename: str) -> set[str]:
    tokens = set(naming.normalize_title(filename).split())
    return tokens - _RELEASE_TOKENS


def _clues_compatible(
    left: MediaMetadata,
    right: MediaMetadata,
    left_name: naming.NameInfo,
    right_name: naming.NameInfo,
) -> bool:
    if (
        left_name.year is not None
        and right_name.year is not None
        and left_name.year != right_name.year
    ):
        return False
    left_duration = _usable_duration(left.duration_s)
    right_duration = _usable_duration(right.duration_s)
    if left_duration is not None and right_duration is not None:
        tolerance = _duration_tolerance(
            left_duration, right_duration, MOVIE_AUTO_TOLERANCE
        )
        if abs(left_duration - right_duration) > tolerance:
            return False
    return True


def _classify_candidate(
    left: MediaMetadata, right: MediaMetadata
) -> tuple[str, str] | None:
    left_path = left.identity.relative_path
    right_path = right.identity.relative_path
    left_name = naming.parse_name(left_path)
    right_name = naming.parse_name(right_path)
    left_title = naming.normalize_title(left_path)
    right_title = naming.normalize_title(right_path)

    left_is_episode = left_name.season is not None or left_name.episode is not None
    right_is_episode = right_name.season is not None or right_name.episode is not None
    if left_is_episode or right_is_episode:
        if (
            not left_is_episode
            or not right_is_episode
            or left_name.season != right_name.season
            or left_name.episode != right_name.episode
            or not left_title
            or left_title != right_title
        ):
            return None
        left_duration = _usable_duration(left.duration_s)
        right_duration = _usable_duration(right.duration_s)
        if left_duration is None or right_duration is None:
            return "review", "episode identity matches but duration is unknown"
        tolerance = _duration_tolerance(
            left_duration, right_duration, EPISODE_AUTO_TOLERANCE
        )
        if abs(left_duration - right_duration) <= tolerance:
            return "auto", "matching episode identity and compatible duration"
        return "review", "episode identity matches but duration differs"

    if left_title and left_title == right_title:
        left_duration = _usable_duration(left.duration_s)
        right_duration = _usable_duration(right.duration_s)
        if (
            left_name.year is None
            or right_name.year is None
            or left_name.year != right_name.year
            or left_duration is None
            or right_duration is None
        ):
            return "review", "exact title has missing or conflicting clues"
        tolerance = _duration_tolerance(
            left_duration, right_duration, MOVIE_AUTO_TOLERANCE
        )
        if abs(left_duration - right_duration) <= tolerance:
            return "auto", "matching title, year, and compatible duration"
        return "review", "exact title has incompatible durations"

    left_tokens = _fuzzy_tokens(left_path)
    right_tokens = _fuzzy_tokens(right_path)
    if (
        len(left_tokens) < 2
        or len(right_tokens) < 2
        or jaccard_similarity(left_tokens, right_tokens) < FUZZY_REVIEW_THRESHOLD
        or not _clues_compatible(left, right, left_name, right_name)
    ):
        return None
    return "review", "fuzzy title candidate requires review"


def _group_id(members: list[MediaMetadata]) -> str:
    file_ids = sorted(member.identity.file_id for member in members)
    digest = hashlib.sha256("\0".join(file_ids).encode("utf-8")).hexdigest()
    return f"group-{digest[:16]}"


def build_candidate_groups(files: list[MediaMetadata]) -> GroupingResult:
    ordered = sorted(
        files,
        key=lambda file: (
            file.identity.relative_path.casefold(),
            file.identity.relative_path,
            file.identity.file_id,
        ),
    )
    edges: dict[tuple[int, int], tuple[str, str]] = {}
    adjacency: dict[int, set[int]] = {}
    for left_index, left in enumerate(ordered):
        for right_index in range(left_index + 1, len(ordered)):
            candidate = _classify_candidate(left, ordered[right_index])
            if candidate is None:
                continue
            edge = (left_index, right_index)
            edges[edge] = candidate
            adjacency.setdefault(left_index, set()).add(right_index)
            adjacency.setdefault(right_index, set()).add(left_index)

    auto_groups = []
    review_groups = []
    visited: set[int] = set()
    for start in sorted(adjacency):
        if start in visited:
            continue
        component = set()
        pending = [start]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(adjacency[current] - component)
        visited.update(component)
        indexes = sorted(component)
        members = [ordered[index] for index in indexes]
        component_edges = [
            edge
            for edge in edges
            if edge[0] in component and edge[1] in component
        ]
        review_reasons = {
            edges[edge][1]
            for edge in component_edges
            if edges[edge][0] == "review"
        }
        group_id = _group_id(members)
        if review_reasons:
            review_groups.append(
                ReviewGroup(
                    group_id=group_id,
                    members=members,
                    reason="; ".join(sorted(review_reasons)),
                )
            )
        else:
            auto_groups.append(AutoGroup(group_id=group_id, members=members))

    grouped = set(adjacency)
    unique_files = [
        file.identity for index, file in enumerate(ordered) if index not in grouped
    ]
    return GroupingResult(
        auto_groups=auto_groups,
        review_groups=review_groups,
        unique_files=unique_files,
    )


def duration_status(esp: float | None, eng: float | None, tolerance: float = DURATION_TOLERANCE_S):
    """Devuelve (diferencia, estado). Una duración desconocida nunca es 'ideal'."""
    if esp is None or eng is None:
        return None, DOUBTFUL
    diff = abs(esp - eng)
    return diff, IDEAL if diff <= tolerance else DOUBTFUL


def _index(files: list[FileRef]) -> dict[tuple, FileRef]:
    index: dict[tuple, FileRef] = {}
    for f in sorted(files, key=lambda f: f.relpath):
        if not f.imdb_id:
            continue
        # Con claves repetidas gana el primero por ruta, para que el resultado sea determinista.
        index.setdefault((f.imdb_id, f.season, f.episode), f)
    return index


def find_pairs(esp_files: list[FileRef], eng_files: list[FileRef]) -> list[Pair]:
    esp, eng = _index(esp_files), _index(eng_files)
    pairs = []
    for key in sorted(esp.keys() & eng.keys(), key=lambda k: (k[0], k[1] or 0, k[2] or 0)):
        diff, status = duration_status(esp[key].duration_s, eng[key].duration_s)
        pairs.append(Pair(esp[key].id, eng[key].id, diff, status))
    return pairs
