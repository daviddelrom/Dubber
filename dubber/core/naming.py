import re
from dataclasses import dataclass

VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi")

_IMDB = re.compile(r"(tt\d+)")
_EPISODE = re.compile(r"S(\d{1,3})E(\d{1,3})", re.IGNORECASE)


@dataclass(frozen=True)
class NameInfo:
    imdb_id: str | None
    season: int | None
    episode: int | None


def parse_name(filename: str) -> NameInfo:
    """Extrae el ID de IMDb (tt1234567) y, si existe, temporada/episodio (S01E02)."""
    imdb = _IMDB.search(filename)
    ep = _EPISODE.search(filename)
    return NameInfo(
        imdb_id=imdb.group(1) if imdb else None,
        season=int(ep.group(1)) if ep else None,
        episode=int(ep.group(2)) if ep else None,
    )


def is_video(filename: str) -> bool:
    return filename.lower().endswith(VIDEO_EXTENSIONS)
