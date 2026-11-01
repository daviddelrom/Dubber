import json
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import Engine
from sqlmodel import Session, select

from ..db.models import Job, utcnow
from . import tasks


class JobRunner:
    """Cola de trabajos en segundo plano. Un solo hilo: escaneos y mezclas se serializan."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dubber-job")
        self._fail_interrupted()

    def _fail_interrupted(self) -> None:
        # Si la app se cerró con trabajos en curso, quedaron huérfanos.
        with Session(self.engine) as s:
            for job in s.exec(select(Job).where(Job.status.in_(["queued", "running"]))):
                job.status, job.finished_at = "failed", utcnow()
                job.log += "Interrumpido: la aplicación se cerró\n"
                s.add(job)
            s.commit()

    def submit(self, kind: str, params: dict | None = None) -> int:
        with Session(self.engine) as s:
            job = Job(kind=kind, params_json=json.dumps(params or {}))
            s.add(job)
            s.commit()
            s.refresh(job)
            job_id = job.id
        self._pool.submit(tasks.execute, self.engine, job_id)
        return job_id

    def cancel(self, job_id: int) -> None:
        with Session(self.engine) as s:
            job = s.get(Job, job_id)
            if job and job.status in ("queued", "running"):
                job.cancel_requested = True
                s.add(job)
                s.commit()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
