import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_PROGRESS = re.compile(r"#GUI#progress (\d+)%")
_SPANISH = {"es", "spa", "esp"}


class MkvError(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class TrackInfo:
    track_no: int
    type: str
    language: str
    codec: str
    name: str


@dataclass(frozen=True)
class Probe:
    duration_s: float | None
    tracks: list[TrackInfo]


def is_spanish(language: str) -> bool:
    return language.lower().split("-")[0] in _SPANISH


def tag_duration_to_seconds(value: str | None) -> float | None:
    """Convierte '0:42:10.123000000' a segundos."""
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return None


def parse_probe(info: dict) -> Probe:
    """Interpreta la salida JSON de `mkvmerge -J`."""
    tracks = []
    track_durations = []
    for t in info.get("tracks", []):
        props = t.get("properties", {})
        tracks.append(
            TrackInfo(
                track_no=t.get("id", 0),
                type=t.get("type", ""),
                language=props.get("language_ietf") or props.get("language") or "und",
                codec=t.get("codec", ""),
                name=props.get("track_name", ""),
            )
        )
        d = tag_duration_to_seconds(props.get("tag_duration"))
        if d:
            track_durations.append(d)

    container_ns = info.get("container", {}).get("properties", {}).get("duration")
    if container_ns:
        duration = container_ns / 1e9
    else:
        duration = max(track_durations) if track_durations else None
    return Probe(duration_s=duration, tracks=tracks)


def check_mkvmerge() -> bool:
    try:
        subprocess.run(["mkvmerge", "--version"], check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def probe(path: Path) -> Probe:
    try:
        result = subprocess.run(
            ["mkvmerge", "-J", str(path)], check=False, capture_output=True, text=True
        )
    except OSError as e:
        raise MkvError(f"No se pudo ejecutar mkvmerge: {e}") from e
    if result.returncode > 1:
        raise MkvError((result.stdout or result.stderr).strip() or "mkvmerge falló")
    try:
        return parse_probe(json.loads(result.stdout))
    except json.JSONDecodeError as e:
        raise MkvError(f"Salida de mkvmerge no válida: {e}") from e


def build_merge_command(
    output: Path, esp_file: Path, eng_file: Path, spanish_audio_ids: list[int]
) -> list[str]:
    """Del archivo español se toma solo el audio en español (sin vídeo); del inglés, todo."""
    if not spanish_audio_ids:
        raise MkvError("El archivo en español no tiene pistas de audio en español")
    return [
        "mkvmerge", "--gui-mode", "-o", str(output),
        "-D",
        "-a", ",".join(str(i) for i in spanish_audio_ids),
        str(esp_file), str(eng_file),
    ]


def run_merge(
    command: list[str],
    on_progress: Callable[[int], None],
    is_cancelled: Callable[[], bool],
) -> str:
    """Ejecuta mkvmerge, informa del progreso (0-100) y devuelve su salida.

    Lanza Cancelled si se cancela y MkvError si mkvmerge termina con error.
    """
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if is_cancelled():
            proc.terminate()
            proc.wait()
            raise Cancelled()
        m = _PROGRESS.search(line)
        if m:
            on_progress(int(m.group(1)))
        else:
            lines.append(line.rstrip())
    code = proc.wait()
    output = "\n".join(lines)
    if code > 1:
        raise MkvError(output or f"mkvmerge terminó con código {code}")
    return output
