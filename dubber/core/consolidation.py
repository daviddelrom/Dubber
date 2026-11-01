import hashlib
import json
import os
import re
import selectors
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .matching import AutoGroup
from .mkv import MediaMetadata, TrackMetadata
from .review import ConfirmedGroup

_VIDEO_CODEC_RANK = {
    "av1": 7,
    "hevc": 6,
    "vp9": 5,
    "avc": 4,
    "mpeg4": 3,
    "mpeg2": 2,
}
_AUDIO_CODEC_RANK = {
    "opus": 8,
    "eac3": 7,
    "aac": 6,
    "ac3": 5,
    "dts": 4,
    "mp3": 3,
    "pcm": 2,
}
_LANGUAGE_ALIASES = {
    "en": "eng",
    "eng": "eng",
    "es": "spa",
    "spa": "spa",
    "esp": "spa",
    "fr": "fra",
    "fra": "fra",
    "de": "deu",
    "deu": "deu",
    "ger": "deu",
    "it": "ita",
    "ita": "ita",
    "pt": "por",
    "por": "por",
    "ja": "jpn",
    "jpn": "jpn",
    "zh": "zho",
    "zho": "zho",
    "und": "und",
    "": "und",
}
_PROGRESS = re.compile(r"#GUI#progress (\d+)%")


@dataclass(frozen=True)
class TrackRef:
    source_file_id: str
    source_path: Path
    source_relpath: str
    track_no: int
    type: str
    language: str
    codec_id: str
    channels: int | None
    width: int | None
    height: int | None
    hdr_signals: tuple[str, ...]
    name: str


@dataclass(frozen=True)
class ConsolidationManifest:
    group_id: str
    group_signature: str
    source_root: Path
    video: TrackRef
    audio: list[TrackRef]
    subtitles: list[TrackRef]
    output_relpath: str
    input_signature: str
    settings_signature: str


@dataclass(frozen=True)
class ReviewRequired:
    reason: str


@dataclass(frozen=True)
class CompletedOutput:
    path: Path
    size: int
    mtime_ns: int
    group_signature: str
    input_signature: str
    settings_signature: str


@dataclass(frozen=True)
class MergeError:
    message: str


@dataclass(frozen=True)
class Cancelled:
    message: str = "Consolidation cancelled"


def _language_code(language: str) -> str:
    normalized = language.casefold().split("-", maxsplit=1)[0]
    return _LANGUAGE_ALIASES.get(normalized, normalized if len(normalized) == 3 else "und")


def _is_untagged(language: str) -> bool:
    return _language_code(language) == "und"


def _codec_family(codec_id: str, kind: str) -> str:
    codec = codec_id.upper()
    if kind == "video":
        if "AV1" in codec:
            return "av1"
        if "HEVC" in codec or "H265" in codec:
            return "hevc"
        if "VP9" in codec:
            return "vp9"
        if "AVC" in codec or "H264" in codec:
            return "avc"
        if "MPEG4" in codec or "MPEG-4" in codec:
            return "mpeg4"
        if "MPEG2" in codec or "MPEG-2" in codec:
            return "mpeg2"
        return "unknown"
    if "OPUS" in codec:
        return "opus"
    if "E-AC-3" in codec or "EAC3" in codec:
        return "eac3"
    if "AAC" in codec:
        return "aac"
    if "AC-3" in codec or "AC3" in codec:
        return "ac3"
    if "DTS" in codec:
        return "dts"
    if "MP3" in codec or "MPEG/L3" in codec:
        return "mp3"
    if any(token in codec for token in ("PCM", "LPCM")):
        return "pcm"
    return "unknown"


def _track_ref(
    member: MediaMetadata,
    track: TrackMetadata,
    source_root: Path,
    language: str | None = None,
    name: str | None = None,
) -> TrackRef:
    relative = PurePosixPath(member.identity.relative_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"unsafe source path: {member.identity.relative_path}")
    return TrackRef(
        source_file_id=member.identity.file_id,
        source_path=source_root.joinpath(*relative.parts),
        source_relpath=relative.as_posix(),
        track_no=track.track_no,
        type=track.type,
        language=language or _language_code(track.language),
        codec_id=track.codec_id,
        channels=track.channels,
        width=track.width,
        height=track.height,
        hdr_signals=tuple(sorted(track.hdr_signals)),
        name=name if name is not None else "",
    )


def _video_rank(track: TrackRef) -> tuple[int, int, int, int, int, str, int]:
    width = track.width or 0
    height = track.height or 0
    codec_family = _codec_family(track.codec_id, "video")
    hdr = int(bool(set(track.hdr_signals) & {"pq", "hlg"}))
    return (
        -(width * height),
        -height,
        -width,
        -hdr,
        -_VIDEO_CODEC_RANK.get(codec_family, 0),
        track.source_relpath.casefold(),
        track.track_no,
    )


def _audio_rank(track: TrackRef) -> tuple[int, int, str, int]:
    codec_family = _codec_family(track.codec_id, "audio")
    return (
        -(track.channels or 0),
        -_AUDIO_CODEC_RANK.get(codec_family, 0),
        track.source_relpath.casefold(),
        track.track_no,
    )


def _manifest_signature(
    group: ConfirmedGroup,
    selected_languages: set[str],
    video: TrackRef,
    audio: list[TrackRef],
    subtitles: list[TrackRef],
) -> tuple[str, str, str]:
    files = [
        {
            "file_id": member.identity.file_id,
            "relative_path": member.identity.relative_path,
            "size": member.identity.size,
            "mtime_ns": member.identity.mtime_ns,
            "duration_s": member.duration_s,
            "tracks": [
                {
                    "track_no": track.track_no,
                    "type": track.type,
                    "language": track.language,
                    "codec_id": track.codec_id,
                    "channels": track.channels,
                    "width": track.width,
                    "height": track.height,
                    "hdr_signals": track.hdr_signals,
                }
                for track in member.tracks
            ],
        }
        for member in sorted(
            group.members, key=lambda item: item.identity.relative_path
        )
    ]
    settings = sorted(_language_code(language) for language in selected_languages)
    canonical = json.dumps(
        {
            "files": files,
            "video": [video.source_file_id, video.track_no],
            "audio": [[track.source_file_id, track.track_no] for track in audio],
            "subtitles": [
                [track.source_file_id, track.track_no] for track in subtitles
            ],
            "settings": settings,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    group_signature = hashlib.sha256(
        "\0".join(sorted(member.identity.file_id for member in group.members)).encode(
            "utf-8"
        )
    ).hexdigest()
    settings_signature = hashlib.sha256(
        json.dumps(settings, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return signature, group_signature, settings_signature


def plan_consolidation(
    group: ConfirmedGroup | AutoGroup,
    selected_languages: set[str],
    source_root: Path,
) -> ConsolidationManifest | ReviewRequired:
    if len(group.members) < 2:
        return ReviewRequired("A single source file does not need consolidation")
    if any(
        not isinstance(language, str) or not language.strip()
        for language in selected_languages
    ):
        return ReviewRequired("Selected audio languages are invalid")

    video_candidates = []
    audio_candidates: dict[str, list[TrackRef]] = {}
    subtitle_candidates = []
    try:
        for member in group.members:
            audio_tracks = [track for track in member.tracks if track.type == "audio"]
            untagged = [track for track in audio_tracks if _is_untagged(track.language)]
            if len(audio_tracks) > 1 and untagged:
                return ReviewRequired(
                    f"{member.identity.relative_path} has untagged audio among multiple audio tracks"
                )
            for track in member.tracks:
                if track.type == "video":
                    video_candidates.append(_track_ref(member, track, source_root))
                elif track.type == "audio":
                    language = "spa" if len(audio_tracks) == 1 and _is_untagged(track.language) else _language_code(track.language)
                    audio_candidates.setdefault(language, []).append(
                        _track_ref(member, track, source_root, language=language)
                    )
                elif track.type in {"subtitles", "subtitle"}:
                    language = _language_code(track.language)
                    basename = PurePosixPath(member.identity.relative_path).name
                    label = f"{basename} — {language}"
                    subtitle_candidates.append(
                        _track_ref(
                            member,
                            track,
                            source_root,
                            language=language,
                            name=label,
                        )
                    )
    except ValueError as error:
        return ReviewRequired(f"Unsafe source path: {error}")

    if not video_candidates:
        return ReviewRequired("No video track is available in this group")
    video = min(video_candidates, key=_video_rank)
    normalized_languages = {_language_code(language) for language in selected_languages}
    audio = [
        min(candidates, key=_audio_rank)
        for language, candidates in sorted(audio_candidates.items())
        if language in normalized_languages
    ]
    subtitles = sorted(
        subtitle_candidates,
        key=lambda track: (
            track.source_relpath.casefold(),
            track.track_no,
            track.language,
        ),
    )

    relative_video_path = PurePosixPath(video.source_relpath)
    output_relpath = relative_video_path.with_suffix(".mkv").as_posix()
    signature, group_signature, settings_signature = _manifest_signature(
        group, selected_languages, video, audio, subtitles
    )
    return ConsolidationManifest(
        group_id=group.group_id,
        group_signature=group_signature,
        source_root=source_root.resolve(),
        video=video,
        audio=audio,
        subtitles=subtitles,
        output_relpath=output_relpath,
        input_signature=signature,
        settings_signature=settings_signature,
    )


def build_merge_command(
    manifest: ConsolidationManifest, partial_path: Path
) -> list[str] | MergeError:
    output_root = manifest.source_root / "dub"
    output_relpath = PurePosixPath(manifest.output_relpath)
    if output_relpath.is_absolute() or ".." in output_relpath.parts:
        return MergeError("Output path escapes the dub directory")
    output_path = output_root.joinpath(*output_relpath.parts)
    if not output_path.resolve().is_relative_to(output_root.resolve()):
        return MergeError("Output path escapes the dub directory")

    tracks = [manifest.video, *manifest.audio, *manifest.subtitles]
    per_input: dict[Path, dict[str, list[TrackRef]]] = {}
    for track in tracks:
        if not track.source_path.resolve().is_relative_to(manifest.source_root.resolve()):
            return MergeError("Source path escapes the library directory")
        categories = per_input.setdefault(
            track.source_path, {"video": [], "audio": [], "subtitles": []}
        )
        key = "subtitles" if track.type in {"subtitle", "subtitles"} else track.type
        if key not in categories:
            return MergeError(f"Unsupported track type: {track.type}")
        categories[key].append(track)

    command = ["mkvmerge", "--gui-mode", "-o", str(partial_path)]
    for source_path in sorted(
        per_input,
        key=lambda path: next(
            track.source_relpath for track in tracks if track.source_path == path
        ).casefold(),
    ):
        categories = per_input[source_path]
        for kind, option, disable_option in (
            ("video", "--video-tracks", "--no-video"),
            ("audio", "--audio-tracks", "--no-audio"),
            ("subtitles", "--subtitle-tracks", "--no-subtitles"),
        ):
            selected = categories[kind]
            if selected:
                command.extend(
                    [option, ",".join(str(track.track_no) for track in selected)]
                )
            else:
                command.append(disable_option)
        for track in sorted(
            tracks,
            key=lambda item: (item.track_no, item.type),
        ):
            if track.source_path != source_path:
                continue
            if track.type in {"audio", "subtitle", "subtitles"}:
                command.extend(["--language", f"{track.track_no}:{track.language}"])
            if track.name:
                command.extend(["--track-name", f"{track.track_no}:{track.name}"])
        command.append(str(source_path))
    return command


def _remove_partial(partial_path: Path) -> str | None:
    try:
        partial_path.unlink(missing_ok=True)
    except OSError as error:
        return f"Could not remove temporary output {partial_path}: {error}"
    return None


def _merge_failure(partial_path: Path, message: str) -> MergeError:
    cleanup_error = _remove_partial(partial_path)
    if cleanup_error:
        message = f"{message}; {cleanup_error}"
    return MergeError(message)


def execute_consolidation(
    manifest: ConsolidationManifest,
    *,
    is_cancelled: Callable[[], bool] = lambda: False,
    on_progress: Callable[[int], None] = lambda _progress: None,
    replace_existing: bool = False,
) -> CompletedOutput | MergeError | Cancelled:
    output_root = manifest.source_root / "dub"
    relative_output = PurePosixPath(manifest.output_relpath)
    if relative_output.is_absolute() or ".." in relative_output.parts:
        return MergeError("Output path escapes the dub directory")
    output_path = output_root.joinpath(*relative_output.parts)
    if not output_path.resolve().is_relative_to(output_root.resolve()):
        return MergeError("Output path escapes the dub directory")
    if output_path.exists() and not replace_existing:
        return MergeError(f"Output already exists and is not owned by this group: {output_path}")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return MergeError(f"Could not create output directory: {error}")

    partial_path = output_path.with_name(f"{output_path.stem}.partial.mkv")
    cleanup_error = _remove_partial(partial_path)
    if cleanup_error:
        return MergeError(cleanup_error)
    if is_cancelled():
        return Cancelled()

    command = build_merge_command(manifest, partial_path)
    if isinstance(command, MergeError):
        return command
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
    except OSError as error:
        return _merge_failure(partial_path, f"Could not start mkvmerge: {error}")
    if process.stdout is None:
        process.terminate()
        process.wait()
        return _merge_failure(partial_path, "mkvmerge output stream was not available")

    output_buffer = bytearray()
    line_buffer = ""
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            stream_open = True
            while stream_open:
                if is_cancelled():
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    cleanup_error = _remove_partial(partial_path)
                    if cleanup_error:
                        return MergeError(cleanup_error)
                    return Cancelled()
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        stream_open = False
                        break
                    output_buffer.extend(chunk)
                    line_buffer += chunk.decode("utf-8", errors="replace")
                    lines = line_buffer.splitlines(keepends=True)
                    line_buffer = ""
                    if lines and not lines[-1].endswith(("\n", "\r")):
                        line_buffer = lines.pop()
                    for line in lines:
                        match = _PROGRESS.search(line)
                        if match:
                            on_progress(int(match.group(1)))
            if line_buffer:
                match = _PROGRESS.search(line_buffer)
                if match:
                    on_progress(int(match.group(1)))
        return_code = process.wait()
    except OSError as error:
        process.terminate()
        process.wait()
        return _merge_failure(
            partial_path, f"Could not read mkvmerge output: {error}"
        )
    finally:
        process.stdout.close()

    process_output = output_buffer.decode("utf-8", errors="replace").strip()
    if return_code > 1:
        return _merge_failure(
            partial_path,
            process_output or f"mkvmerge exited with code {return_code}",
        )
    try:
        if not partial_path.is_file() or partial_path.stat().st_size <= 0:
            return _merge_failure(
                partial_path, "mkvmerge did not produce a valid temporary output"
            )
        if output_path.exists() and not replace_existing:
            return _merge_failure(
                partial_path, f"Output appeared during consolidation: {output_path}"
            )
        if replace_existing:
            os.replace(partial_path, output_path)
        else:
            os.link(partial_path, output_path)
            partial_path.unlink()
        stat = output_path.stat()
    except OSError as error:
        return _merge_failure(
            partial_path, f"Could not publish consolidated output: {error}"
        )
    return CompletedOutput(
        path=output_path,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        group_signature=manifest.group_signature,
        input_signature=manifest.input_signature,
        settings_signature=manifest.settings_signature,
    )
