from dataclasses import dataclass

DURATION_TOLERANCE_S = 1.0

IDEAL = "ideal"
DOUBTFUL = "doubtful"


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
