import json
import re
import subprocess
from dataclasses import dataclass, field
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
    codec_id: str = ""
    channels: int | None = None
    width: int | None = None
    height: int | None = None
    hdr_signals: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Probe:
    duration_s: float | None
    tracks: list[TrackInfo]


@dataclass(frozen=True)
class FileIdentity:
    file_id: str
    relative_path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class MediaFileRef:
    file_id: str
    path: Path
    identity: FileIdentity


@dataclass(frozen=True)
class TrackMetadata:
    track_no: int
    type: str
    language: str
    codec_id: str
    channels: int | None
    width: int | None
    height: int | None
    hdr_signals: list[str]


@dataclass(frozen=True)
class MediaMetadata:
    identity: FileIdentity
    duration_s: float | None
    tracks: list[TrackMetadata]


@dataclass(frozen=True)
class ProbeError:
    message: str


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


def _parse_pixel_dimensions(value: object) -> tuple[int | None, int | None]:
    if not isinstance(value, str):
        return None, None
    match = re.fullmatch(r"(\d+)x(\d+)", value.strip())
    if match is None:
        return None, None
    try:
        width, height = (int(part) for part in match.groups())
    except ValueError:
        return None, None
    if width == 0 or height == 0:
        return None, None
    return width, height


def _parse_audio_channels(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        channels = value
    elif isinstance(value, str) and value.isdecimal():
        try:
            channels = int(value)
        except ValueError:
            return None
    else:
        return None
    return channels if channels > 0 else None


def _hdr_signals_for_transfer(transfer: object) -> list[str]:
    if transfer is None:
        return []
    normalized = str(transfer).strip().casefold()
    if normalized in {"16", "smpte2084", "smpte st 2084", "pq"}:
        return ["pq"]
    if normalized in {"18", "arib-std-b67", "hlg"}:
        return ["hlg"]
    return []


def _hdr_signals(properties: dict) -> list[str]:
    return _hdr_signals_for_transfer(
        properties.get("color_transfer_characteristics")
    )


def parse_probe(info: dict) -> Probe:
    """Interpreta la salida JSON de `mkvmerge -J`."""
    raw_tracks = info.get("tracks", [])
    if not isinstance(raw_tracks, list):
        raise MkvError("Salida de mkvmerge no válida: tracks debe ser una lista")
    tracks = []
    track_durations = []
    for t in raw_tracks:
        if not isinstance(t, dict):
            raise MkvError("Salida de mkvmerge no válida: pista debe ser un objeto")
        props = t.get("properties", {})
        if not isinstance(props, dict):
            raise MkvError("Salida de mkvmerge no válida: properties debe ser un objeto")
        width, height = _parse_pixel_dimensions(props.get("pixel_dimensions"))
        codec_id = props.get("codec_id")
        tracks.append(
            TrackInfo(
                track_no=t.get("id", 0),
                type=t.get("type", ""),
                language=props.get("language_ietf") or props.get("language") or "und",
                codec=t.get("codec", ""),
                name=props.get("track_name", ""),
                codec_id=codec_id if isinstance(codec_id, str) else "",
                channels=_parse_audio_channels(props.get("audio_channels")),
                width=width,
                height=height,
                hdr_signals=_hdr_signals(props),
            )
        )
        d = tag_duration_to_seconds(props.get("tag_duration"))
        if d:
            track_durations.append(d)

    container = info.get("container", {})
    if not isinstance(container, dict):
        raise MkvError("Salida de mkvmerge no válida: container debe ser un objeto")
    container_properties = container.get("properties", {})
    if not isinstance(container_properties, dict):
        raise MkvError(
            "Salida de mkvmerge no válida: container properties debe ser un objeto"
        )
    container_ns = container_properties.get("duration")
    if (
        isinstance(container_ns, (int, float))
        and not isinstance(container_ns, bool)
        and container_ns >= 0
    ):
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


def check_ffprobe() -> bool:
    try:
        subprocess.run(["ffprobe", "-version"], check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _read_probe_json(path: Path) -> dict:
    try:
        result = subprocess.run(
            ["mkvmerge", "-J", str(path)], check=False, capture_output=True, text=True
        )
    except OSError as e:
        raise MkvError(f"No se pudo ejecutar mkvmerge: {e}") from e
    if result.returncode > 1:
        raise MkvError((result.stdout or result.stderr).strip() or "mkvmerge falló")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise MkvError(f"Salida de mkvmerge no válida: {e}") from e
    if not isinstance(info, dict):
        raise MkvError("Salida de mkvmerge no válida: se esperaba un objeto JSON")
    return info


def _read_ffprobe_streams(path: Path) -> list[dict]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,color_transfer",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command, check=False, capture_output=True, text=True
        )
    except OSError as e:
        raise MkvError(f"No se pudo ejecutar ffprobe: {e}") from e
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise MkvError(message or f"ffprobe terminó con código {result.returncode}")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise MkvError(f"Salida de ffprobe no válida: {e}") from e
    if not isinstance(info, dict) or not isinstance(info.get("streams"), list):
        raise MkvError("Salida de ffprobe no válida: streams debe ser una lista")
    streams = info["streams"]
    if any(
        not isinstance(stream, dict)
        or not isinstance(stream.get("codec_type"), str)
        for stream in streams
    ):
        raise MkvError("Salida de ffprobe no válida: stream sin codec_type")
    return streams


def _ffprobe_hdr_signals_by_track(probe_result: Probe, streams: list[dict]) -> dict[int, list[str]]:
    video_track_indexes = [
        index for index, track in enumerate(probe_result.tracks) if track.type == "video"
    ]
    video_streams = [
        stream for stream in streams if stream["codec_type"] == "video"
    ]
    if len(video_track_indexes) != len(video_streams):
        raise MkvError(
            "No coincide el número de pistas de vídeo de mkvmerge y ffprobe"
        )
    return {
        track_index: _hdr_signals_for_transfer(stream.get("color_transfer"))
        for track_index, stream in zip(video_track_indexes, video_streams, strict=True)
    }


def probe(path: Path) -> Probe:
    return parse_probe(_read_probe_json(path))


def probe_media(file: MediaFileRef) -> MediaMetadata | ProbeError:
    if file.file_id != file.identity.file_id:
        return ProbeError("La identidad del archivo no coincide con su referencia")
    try:
        result = probe(file.path)
        hdr_signals = _ffprobe_hdr_signals_by_track(
            result, _read_ffprobe_streams(file.path)
        )
    except MkvError as error:
        return ProbeError(str(error))
    tracks = [
        TrackMetadata(
            track_no=track.track_no,
            type=track.type,
            language=track.language,
            codec_id=track.codec_id,
            channels=track.channels,
            width=track.width,
            height=track.height,
            hdr_signals=hdr_signals.get(index, []),
        )
        for index, track in enumerate(result.tracks)
    ]
    return MediaMetadata(
        identity=file.identity,
        duration_s=result.duration_s,
        tracks=tracks,
    )


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
