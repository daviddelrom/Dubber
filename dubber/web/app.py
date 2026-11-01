from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine
from sqlmodel import Session, col, select

from ..core.mkv import check_mkvmerge
from ..db.models import Job, LibraryRoot, Match, MediaFile, Track
from ..db.session import get_root, make_engine
from ..jobs.runner import JobRunner

HERE = Path(__file__).parent
KINDS = {"esp": "Español (doblado)", "eng": "Inglés (original)", "dub": "Salida"}
STATUS_LABELS = {
    "ideal": "Ideal", "doubtful": "Dudosa", "approved": "Aprobada", "discarded": "Descartada",
}


def create_legacy_app(
    engine: Engine | None = None, runner: JobRunner | None = None
) -> FastAPI:
    engine = engine or make_engine()
    runner = runner or JobRunner(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        runner.shutdown()

    app = FastAPI(title="Dubber", lifespan=lifespan)
    app.state.engine, app.state.runner = engine, runner
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(KINDS=KINDS, STATUS_LABELS=STATUS_LABELS)

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        # La app lanza procesos en tu equipo: una web ajena no debe poder enviar formularios.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return PlainTextResponse("Origen no permitido", status_code=403)
        return await call_next(request)

    def get_session():
        with Session(engine) as session:
            yield session

    def page(request: Request, name: str, **ctx):
        return templates.TemplateResponse(request, name, ctx)

    @app.get("/")
    def index():
        return RedirectResponse("/library", status_code=303)

    # --- Ajustes ---
    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request, session: Session = Depends(get_session)):
        roots = {r.kind: r.path for r in session.exec(select(LibraryRoot))}
        return page(request, "settings.html", roots=roots, mkvmerge=check_mkvmerge(), errors={})

    @app.post("/settings", response_class=HTMLResponse)
    def save_settings(
        request: Request,
        esp: str = Form(""), eng: str = Form(""), dub: str = Form(""),
        session: Session = Depends(get_session),
    ):
        values = {"esp": esp.strip(), "eng": eng.strip(), "dub": dub.strip()}
        errors = {}
        for kind, value in values.items():
            if not value:
                errors[kind] = "Obligatoria"
            elif kind != "dub" and not Path(value).expanduser().is_dir():
                errors[kind] = "La carpeta no existe"
        if errors:
            return page(request, "settings.html", roots=values, mkvmerge=check_mkvmerge(),
                        errors=errors)
        for kind, value in values.items():
            path = str(Path(value).expanduser().resolve())
            root = get_root(session, kind) or LibraryRoot(kind=kind, path=path)
            root.path = path
            session.add(root)
        session.commit()
        return RedirectResponse("/library", status_code=303)

    # --- Biblioteca ---
    @app.get("/library", response_class=HTMLResponse)
    def library(request: Request, kind: str = "", session: Session = Depends(get_session)):
        roots = {r.id: r for r in session.exec(select(LibraryRoot))}
        query = select(MediaFile).order_by(MediaFile.relpath)
        if kind in KINDS:
            ids = [r.id for r in roots.values() if r.kind == kind]
            query = query.where(col(MediaFile.root_id).in_(ids))
        files = session.exec(query).all()
        tracks: dict[int, list[Track]] = {}
        for t in session.exec(select(Track).order_by(Track.track_no)):
            tracks.setdefault(t.file_id, []).append(t)
        return page(request, "library.html", files=files, tracks=tracks, roots=roots,
                    kind=kind, configured=len(roots) >= 3)

    @app.post("/scan")
    def scan():
        runner.submit("scan")
        return RedirectResponse("/jobs", status_code=303)

    # --- Coincidencias ---
    @app.get("/matches", response_class=HTMLResponse)
    def matches(request: Request, session: Session = Depends(get_session)):
        files = {f.id: f for f in session.exec(select(MediaFile))}
        rows = session.exec(select(Match)).all()
        rows.sort(key=lambda m: files[m.eng_file_id].relpath)
        return page(request, "matches.html", matches=rows, files=files)

    @app.post("/matches/{match_id}/status")
    def set_status(match_id: int, status: str = Form(...), session: Session = Depends(get_session)):
        m = session.get(Match, match_id)
        if m and status in ("approved", "discarded"):
            m.status = status
            session.add(m)
            session.commit()
        return RedirectResponse("/matches", status_code=303)

    @app.post("/matches/merge")
    def merge(match_ids: list[int] = Form(default=[]), overwrite: bool = Form(False)):
        if match_ids:
            runner.submit("merge", {"match_ids": match_ids, "overwrite": overwrite})
            return RedirectResponse("/jobs", status_code=303)
        return RedirectResponse("/matches", status_code=303)

    # --- Cola ---
    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request, session: Session = Depends(get_session)):
        rows = session.exec(select(Job).order_by(col(Job.id).desc()).limit(50)).all()
        return page(request, "jobs.html", jobs=rows)

    @app.get("/jobs/{job_id}/card", response_class=HTMLResponse)
    def job_card(request: Request, job_id: int, session: Session = Depends(get_session)):
        job = session.get(Job, job_id)
        if job is None:
            return HTMLResponse("", status_code=404)
        return page(request, "_job.html", job=job)

    @app.post("/jobs/{job_id}/cancel")
    def cancel(job_id: int):
        runner.cancel(job_id)
        return RedirectResponse("/jobs", status_code=303)

    return app


def create_app(engine: Engine | None = None, runner: JobRunner | None = None) -> FastAPI:
    if engine is not None or runner is not None:
        return create_legacy_app(engine, runner)
    from .library_app import create_app as create_v2_app

    return create_v2_app()
