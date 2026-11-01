import json
import os
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from ..core import matching, mkv
from ..core.naming import is_video, parse_name
from ..db.models import Job, LibraryRoot, Match, MediaFile, Track, utcnow
from ..db.session import get_root


class JobContext:
    """Acceso del trabajo a su propia fila: log, progreso y cancelación."""

    def __init__(self, engine: Engine, job_id: int):
        self.engine = engine
        self.job_id = job_id

    def _update(self, fn) -> None:
        with Session(self.engine) as s:
            job = s.get(Job, self.job_id)
            fn(job)
            s.add(job)
            s.commit()

    def log(self, message: str) -> None:
        self._update(lambda j: setattr(j, "log", j.log + message + "\n"))

    def progress(self, value: float) -> None:
        self._update(lambda j: setattr(j, "progress", max(0.0, min(100.0, value))))

    def cancelled(self) -> bool:
        with Session(self.engine) as s:
            return bool(s.get(Job, self.job_id).cancel_requested)


def _roots(session: Session, *kinds: str) -> dict[str, LibraryRoot]:
    found = {}
    for kind in kinds:
        root = get_root(session, kind)
        if root is None or (kind != "dub" and not Path(root.path).is_dir()):
            raise mkv.MkvError(f"La carpeta '{kind}' no está definida o no existe")
        found[kind] = root
    return found


def run_scan(engine: Engine, ctx: JobContext) -> None:
    with Session(engine) as s:
        roots = _roots(s, "esp", "eng")

    for kind, root in roots.items():
        _scan_root(engine, ctx, kind, root)
        if ctx.cancelled():
            raise mkv.Cancelled()

    with Session(engine) as s:
        _rebuild_matches(s, roots["esp"].id, roots["eng"].id)
        s.commit()
    ctx.progress(100)


def _scan_root(engine: Engine, ctx: JobContext, kind: str, root: LibraryRoot) -> None:
    base = Path(root.path)
    found = {}
    for dirpath, _, files in os.walk(base):
        for name in files:
            if is_video(name):
                full = Path(dirpath) / name
                found[str(full.relative_to(base))] = full

    with Session(engine) as s:
        existing = {}
        # Archivos que ya no existen: se borran con sus pistas y coincidencias.
        for f in s.exec(select(MediaFile).where(MediaFile.root_id == root.id)):
            if f.relpath in found:
                existing[f.relpath] = f.id
            else:
                _delete_file(s, f)
        s.commit()

    total = max(len(found), 1)
    changed = 0
    for i, (relpath, full) in enumerate(sorted(found.items()), 1):
        if ctx.cancelled():
            return
        stat = full.stat()
        with Session(engine) as s:
            f = s.get(MediaFile, existing[relpath]) if relpath in existing else None
            if f and f.size == stat.st_size and f.mtime == stat.st_mtime and f.error is None:
                continue
            changed += 1
            name = parse_name(full.name)
            if f is None:
                f = MediaFile(root_id=root.id, relpath=relpath, size=0, mtime=0)
            f.size, f.mtime = stat.st_size, stat.st_mtime
            f.imdb_id, f.season, f.episode = name.imdb_id, name.season, name.episode
            f.scanned_at = utcnow()
            s.add(f)
            s.flush()
            for t in s.exec(select(Track).where(Track.file_id == f.id)):
                s.delete(t)
            try:
                info = mkv.probe(full)
                f.duration_s, f.error = info.duration_s, None
                for t in info.tracks:
                    s.add(Track(file_id=f.id, track_no=t.track_no, type=t.type,
                                language=t.language, codec=t.codec, name=t.name))
            except mkv.MkvError as e:
                f.duration_s, f.error = None, str(e)[:500]
                ctx.log(f"[{kind}] Error al analizar {relpath}: {f.error}")
            s.add(f)
            s.commit()
        base_pct = 0 if kind == "esp" else 50
        ctx.progress(base_pct + 50 * i / total)
    ctx.log(f"[{kind}] {len(found)} archivos, {changed} analizados de nuevo")


def _delete_file(s: Session, f: MediaFile) -> None:
    for t in s.exec(select(Track).where(Track.file_id == f.id)):
        s.delete(t)
    for m in s.exec(select(Match).where((Match.esp_file_id == f.id) | (Match.eng_file_id == f.id))):
        s.delete(m)
    s.delete(f)


def _ref(f: MediaFile) -> matching.FileRef:
    return matching.FileRef(f.id, f.relpath, f.imdb_id, f.season, f.episode, f.duration_s)


def _rebuild_matches(s: Session, esp_root_id: int, eng_root_id: int) -> None:
    esp = [_ref(f) for f in s.exec(select(MediaFile).where(MediaFile.root_id == esp_root_id))]
    eng_files = {f.id: f for f in s.exec(select(MediaFile).where(MediaFile.root_id == eng_root_id))}
    pairs = matching.find_pairs(esp, [_ref(f) for f in eng_files.values()])
    wanted = {(p.esp_id, p.eng_id) for p in pairs}

    for m in s.exec(select(Match)):
        if (m.esp_file_id, m.eng_file_id) not in wanted:
            s.delete(m)

    for p in pairs:
        m = s.exec(
            select(Match).where(Match.esp_file_id == p.esp_id, Match.eng_file_id == p.eng_id)
        ).first() or Match(esp_file_id=p.esp_id, eng_file_id=p.eng_id, output_relpath="")
        m.duration_diff_s = p.duration_diff_s
        m.output_relpath = str(Path(eng_files[p.eng_id].relpath).with_suffix(".mkv"))
        # Las decisiones manuales (aprobada/descartada) se conservan.
        if m.status in (matching.IDEAL, matching.DOUBTFUL) or m.id is None:
            m.status = p.status
        s.add(m)


def run_merge(engine: Engine, ctx: JobContext, params: dict) -> None:
    match_ids = params.get("match_ids", [])
    overwrite = bool(params.get("overwrite", False))
    with Session(engine) as s:
        roots = _roots(s, "esp", "eng", "dub")
        paths = {k: Path(r.path) for k, r in roots.items()}

    total = max(len(match_ids), 1)
    failed = 0
    for i, match_id in enumerate(match_ids):
        if ctx.cancelled():
            raise mkv.Cancelled()
        with Session(engine) as s:
            m = s.get(Match, match_id)
            if m is None or m.status not in (matching.IDEAL, "approved"):
                ctx.log(f"Coincidencia {match_id}: omitida (no está lista para mezclar)")
                continue
            esp = paths["esp"] / s.get(MediaFile, m.esp_file_id).relpath
            eng = paths["eng"] / s.get(MediaFile, m.eng_file_id).relpath
            spanish = [
                t.track_no
                for t in s.exec(select(Track).where(Track.file_id == m.esp_file_id,
                                                    Track.type == "audio"))
                if mkv.is_spanish(t.language)
            ]
            output = paths["dub"] / m.output_relpath
            out_rel = m.output_relpath

        if output.exists() and not overwrite:
            ctx.log(f"{out_rel}: ya existe, se omite")
            continue

        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_name(output.name + ".partial")
        try:
            command = mkv.build_merge_command(partial, esp, eng, spanish)
            ctx.log(f"Mezclando {out_rel}")
            mkv.run_merge(
                command,
                on_progress=lambda pct, i=i: ctx.progress(100 * (i + pct / 100) / total),
                is_cancelled=ctx.cancelled,
            )
            os.replace(partial, output)
            with Session(engine) as s:
                m = s.get(Match, match_id)
                m.merged_at = utcnow()
                s.add(m)
                s.commit()
        except mkv.Cancelled:
            partial.unlink(missing_ok=True)
            raise
        except mkv.MkvError as e:
            partial.unlink(missing_ok=True)
            failed += 1
            ctx.log(f"Error en {out_rel}: {e}")
    ctx.progress(100)
    if failed:
        raise mkv.MkvError(f"{failed} mezcla(s) fallaron")


def execute(engine: Engine, job_id: int) -> None:
    """Punto de entrada del hilo: ejecuta el trabajo y fija su estado final."""
    ctx = JobContext(engine, job_id)
    with Session(engine) as s:
        job = s.get(Job, job_id)
        if job.cancel_requested:
            _finish(engine, job_id, "cancelled")
            return
        job.status = "running"
        kind, params = job.kind, json.loads(job.params_json)
        s.add(job)
        s.commit()
    try:
        if kind == "scan":
            run_scan(engine, ctx)
        elif kind == "merge":
            run_merge(engine, ctx, params)
        else:
            raise mkv.MkvError(f"Tipo de trabajo desconocido: {kind}")
        _finish(engine, job_id, "done")
    except mkv.Cancelled:
        _finish(engine, job_id, "cancelled")
    except Exception as e:  # el hilo nunca debe morir sin dejar el estado
        ctx.log(f"Error: {e}")
        _finish(engine, job_id, "failed")


def _finish(engine: Engine, job_id: int, status: str) -> None:
    with Session(engine) as s:
        job = s.get(Job, job_id)
        job.status, job.finished_at = status, utcnow()
        s.add(job)
        s.commit()
