import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import Session, select

from ..core import consolidation
from ..core.mkv import check_ffprobe, check_mkvmerge
from ..db.models_v2 import V2Job, V2LibraryConfig
from ..db.session import DatabaseHandle
from ..jobs.batch import BatchReport, V2BatchRunner
from ..jobs.library_scan import LibraryConfig

HERE = Path(__file__).parent


class ReviewPartitionRequest(BaseModel):
    partition: list[list[str]]


def _report_payload(report: BatchReport) -> dict:
    return {
        "job_id": report.job_id,
        "status": report.status,
        "progress": report.progress,
        "log": report.log,
        "scanned": report.scanned,
        "consolidated": [
            {
                "path": str(output.path),
                "size": output.size,
                "mtime_ns": output.mtime_ns,
                "group_signature": output.group_signature,
                "input_signature": output.input_signature,
                "settings_signature": output.settings_signature,
            }
            for output in report.consolidated
        ],
        "review": report.review,
        "skipped": report.skipped,
        "errors": report.errors,
    }


def create_library_app(
    database: DatabaseHandle, runner: V2BatchRunner | None = None
) -> FastAPI:
    batch_runner = runner or V2BatchRunner(database)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        batch_runner.shutdown()
        if runner is None:
            database.engine.dispose()

    app = FastAPI(title="Dubber", lifespan=lifespan)
    app.state.v2_database = database
    app.state.batch_runner = batch_runner
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse(
                    {"detail": "Origin not allowed"}, status_code=403
                )
        return await call_next(request)

    def page(request: Request, template: str, **context):
        return templates.TemplateResponse(request, template, context)

    def get_settings() -> V2LibraryConfig | None:
        with Session(database.engine) as session:
            return session.get(V2LibraryConfig, 1)

    @app.get("/", response_class=HTMLResponse)
    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request):
        config = get_settings()
        roots = {
            "source_root": config.source_root if config else "",
            "language_mode": config.language_mode if config else "all",
            "selected_languages": (
                json.loads(config.selected_languages_json) if config else []
            ),
        }
        return page(
            request,
            "settings_v2.html",
            roots=roots,
            mkvmerge=check_mkvmerge(),
            ffprobe=check_ffprobe(),
            database_path=database.path,
        )

    @app.post("/settings")
    def save_settings(
        source_root: str = Form(...),
        language_mode: str = Form("all"),
        selected_languages: list[str] = Form(default=[]),
    ):
        source = Path(source_root).expanduser().resolve()
        if not source.is_dir():
            return HTMLResponse(
                "Source directory does not exist or is not accessible",
                status_code=422,
            )
        if language_mode not in {"all", "selected"}:
            raise HTTPException(status_code=422, detail="Invalid language mode")
        languages = sorted(
            {
                consolidation._language_code(language.strip())
                for field in selected_languages
                for language in field.split(",")
                if language.strip()
            }
        )
        if language_mode == "selected" and not languages:
            raise HTTPException(
                status_code=422, detail="Choose at least one audio language"
            )
        config = V2LibraryConfig(
            id=1,
            source_root=str(source),
            output_root=str(source / "dub"),
            language_mode=language_mode,
            selected_languages_json=json.dumps(languages),
        )
        with Session(database.engine) as session:
            session.merge(config)
            session.commit()
        return RedirectResponse("/", status_code=303)

    @app.get("/library", response_class=HTMLResponse)
    def library(request: Request):
        config = get_settings()
        return page(
            request,
            "library_v2.html",
            config=config,
            database_path=database.path,
        )

    @app.post("/jobs/scan")
    def start_scan():
        config = get_settings()
        if config is None:
            raise HTTPException(
                status_code=400, detail="Save a source folder before scanning"
            )
        languages: str | set[str]
        if config.language_mode == "all":
            languages = "all"
        else:
            try:
                languages = set(json.loads(config.selected_languages_json))
            except json.JSONDecodeError as error:
                raise HTTPException(
                    status_code=500, detail=f"Stored language settings are invalid: {error}"
                ) from error
        try:
            job = batch_runner.submit_scan_and_consolidate(
                LibraryConfig(
                    source_root=Path(config.source_root),
                    output_root=Path(config.output_root),
                    language_mode=languages,
                )
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return JSONResponse({"job_id": job.job_id}, status_code=202)

    @app.post("/jobs/{job_id}/reviews/{group_id}")
    def resolve_review(
        job_id: str, group_id: str, request: ReviewPartitionRequest
    ):
        try:
            job = batch_runner.submit_review_resolution(
                job_id, group_id, request.partition
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse({"job_id": job.job_id}, status_code=202)

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request):
        with Session(database.engine) as session:
            rows = session.exec(
                select(V2Job).order_by(V2Job.created_at.desc()).limit(50)
            ).all()
            job_cards = []
            for row in rows:
                try:
                    report = json.loads(row.report_json)
                except json.JSONDecodeError as error:
                    report = {
                        "errors": [
                            {"message": f"Stored job report is invalid: {error}"}
                        ]
                    }
                job_cards.append({"job": row, "report": report})
        return page(request, "jobs_v2.html", jobs=job_cards)

    @app.get("/jobs/{job_id}")
    def job_report(job_id: str):
        try:
            report = batch_runner.get_job_report(job_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return JSONResponse(_report_payload(report))

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        try:
            batch_runner.cancel(job_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return RedirectResponse("/jobs", status_code=303)

    return app


def create_app() -> FastAPI:
    from ..db.session import LegacyDatabaseError, open_v2_database

    database = open_v2_database()
    if isinstance(database, LegacyDatabaseError):
        raise RuntimeError(database.message)
    return create_library_app(database)
