import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi")

_IMDB = re.compile(r"(tt\d+)")
_EPISODE = re.compile(r"S(\d{1,3})E(\d{1,3})", re.IGNORECASE)
_ALTERNATE_EPISODE = re.compile(r"(?<!\d)(\d{1,3})x(\d{1,3})(?!\d)", re.IGNORECASE)
_YEAR = re.compile(r"(?<![A-Za-z0-9])((?:19|20)\d{2})(?![A-Za-z0-9])")
_PARENTHESIZED_YEAR = re.compile(r"\(((?:19|20)\d{2})\)")


@dataclass(frozen=True)
class NameInfo:
    imdb_id: str | None
    season: int | None
    episode: int | None
    year: int | None = None


def _year_match(stem: str) -> re.Match[str] | None:
    parenthesized = _PARENTHESIZED_YEAR.search(stem)
    if parenthesized is not None:
        return parenthesized
    matches = list(_YEAR.finditer(stem))
    return matches[-1] if matches else None


def parse_name(filename: str) -> NameInfo:
    """Extract IMDb, episode, and movie-year clues from a filename."""
    basename = Path(filename).name
    stem = Path(basename).stem
    imdb = _IMDB.search(basename)
    ep = _EPISODE.search(basename) or _ALTERNATE_EPISODE.search(basename)
    year = _year_match(stem)
    return NameInfo(
        imdb_id=imdb.group(1) if imdb else None,
        season=int(ep.group(1)) if ep else None,
        episode=int(ep.group(2)) if ep else None,
        year=int(year.group(1)) if year else None,
    )


def normalize_title(filename: str) -> str:
    """Normalize a filename title after removing parsed year and episode markers."""
    title = Path(Path(filename).name).stem
    year = _year_match(title)
    if year is not None:
        title = title[: year.start()] + " " + title[year.end() :]
    title = _EPISODE.sub(" ", title)
    title = _ALTERNATE_EPISODE.sub(" ", title)
    decomposed = unicodedata.normalize("NFKD", title).casefold()
    normalized = "".join(
        character
        if character.isalnum()
        else " "
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(normalized.split())


def is_video(filename: str) -> bool:
    return filename.lower().endswith(VIDEO_EXTENSIONS)
