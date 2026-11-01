import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from ..core import consolidation, matching
from ..core.mkv import FileIdentity, MediaMetadata
from ..core.review import ConfirmedGroup, ReviewError, resolve_review_group
from ..db.models_v2 import (
    V2CandidateGroup,
    V2CandidateGroupMember,
    V2Job,
    V2LibraryConfig,
    V2MediaFile,
    V2OutputRecord,
    utcnow,
)
from ..db.session import DatabaseHandle
from . import library_scan
from .library_scan import LibraryConfig, ScanError, scan_library


@dataclass(frozen=True)
class JobRef:
    job_id: str


@dataclass(frozen=True)
class BatchReport:
    job_id: str
    status: str
    progress: dict[str, Any]
    log: list[str]
    scanned: int
    consolidated: list[consolidation.CompletedOutput]
    review: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    errors: list[dict[str, Any]]


def _new_id() -> str:
    return uuid.uuid4().hex


def _initial_report(job_id: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "status": "queued",
        "progress": {"phase": "queued", "completed": 0, "total": 0},
        "log": [],
        "scanned": 0,
        "consolidated": [],
        "review": [],
        "skipped": [],
        "errors": [],
        "config": None,
    }


def _serialize_identity(identity: FileIdentity) -> dict[str, Any]:
    return {
        "file_id": identity.file_id,
        "relative_path": identity.relative_path,
        "size": identity.size,
        "mtime_ns": identity.mtime_ns,
    }


def _serialize_output(output: consolidation.CompletedOutput) -> dict[str, Any]:
    return {
        "path": str(output.path),
        "size": output.size,
        "mtime_ns": output.mtime_ns,
        "group_signature": output.group_signature,
        "input_signature": output.input_signature,
        "settings_signature": output.settings_signature,
    }


def _deserialize_output(value: dict[str, Any]) -> consolidation.CompletedOutput:
    return consolidation.CompletedOutput(
        path=Path(value["path"]),
        size=value["size"],
        mtime_ns=value["mtime_ns"],
        group_signature=value["group_signature"],
        input_signature=value["input_signature"],
        settings_signature=value["settings_signature"],
    )


class V2BatchRunner:
    def __init__(self, database: DatabaseHandle):
        self.database = database
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="dubber-v2-job"
        )
        self._mark_interrupted_jobs_failed()

    def _mark_interrupted_jobs_failed(self) -> None:
        with Session(self.database.engine) as session:
            interrupted = session.exec(
                select(V2Job).where(V2Job.status.in_(["queued", "running"]))
            ).all()
            for job in interrupted:
                report = json.loads(job.report_json)
                report["status"] = "failed"
                report["log"].append("Interrupted: the application stopped")
                report["errors"].append(
                    {"message": "The application stopped before the job completed"}
                )
                job.status = "failed"
                job.finished_at = utcnow()
                job.log = "\n".join(report["log"])
                job.report_json = json.dumps(report)
                session.add(job)
            session.commit()

    def _save_report(
        self,
        job_id: str,
        report: dict[str, Any],
        *,
        status: str | None = None,
    ) -> None:
        with Session(self.database.engine) as session:
            job = session.get(V2Job, job_id)
            if job is None:
                raise ValueError(f"Unknown v2 job: {job_id}")
            if status is not None:
                job.status = status
                report["status"] = status
                if status not in {"queued", "running"}:
                    job.finished_at = utcnow()
            progress = report["progress"]
            job.phase = progress["phase"]
            job.completed = progress["completed"]
            job.total = progress["total"]
            job.log = "\n".join(report["log"])
            job.report_json = json.dumps(report, ensure_ascii=False)
            session.add(job)
            session.commit()

    def _load_report(self, job_id: str) -> dict[str, Any]:
        with Session(self.database.engine) as session:
            job = session.get(V2Job, job_id)
            if job is None:
                raise ValueError(f"Unknown v2 job: {job_id}")
            try:
                report = json.loads(job.report_json)
            except json.JSONDecodeError as error:
                raise ValueError(f"Stored job report is invalid: {error}") from error
        if not isinstance(report, dict):
            raise ValueError("Stored job report is not an object")
        report["status"] = job.status
        return report

    def get_job_report(self, job_id: str) -> BatchReport:
        report = self._load_report(job_id)
        return BatchReport(
            job_id=job_id,
            status=report["status"],
            progress=report["progress"],
            log=report["log"],
            scanned=report["scanned"],
            consolidated=[
                _deserialize_output(output)
                for output in report["consolidated"]
            ],
            review=report["review"],
            skipped=report["skipped"],
            errors=report["errors"],
        )

    def submit_scan_and_consolidate(self, config: LibraryConfig) -> JobRef:
        source_root = config.source_root.expanduser().resolve()
        output_root = config.output_root.expanduser().resolve()
        if not source_root.is_dir() or output_root != source_root / "dub":
            raise ValueError("Configure an existing source directory and its dub/ output")
        if config.language_mode != "all" and not isinstance(config.language_mode, set):
            raise ValueError("language_mode must be 'all' or a set of languages")
        if config.language_mode != "all" and any(
            not isinstance(language, str) or not language.strip()
            for language in config.language_mode
        ):
            raise ValueError("selected languages must be non-empty strings")
        job_id = _new_id()
        report = _initial_report(job_id)
        report["config"] = {
            "source_root": str(source_root),
            "output_root": str(output_root),
            "language_mode": config.language_mode
            if config.language_mode == "all"
            else sorted(config.language_mode),
        }
        with Session(self.database.engine) as session:
            saved_config = session.get(V2LibraryConfig, 1)
            if saved_config is None:
                saved_config = V2LibraryConfig(
                    id=1,
                    source_root=str(source_root),
                    output_root=str(output_root),
                )
            saved_config.source_root = str(source_root)
            saved_config.output_root = str(output_root)
            if config.language_mode == "all":
                saved_config.language_mode = "all"
                saved_config.selected_languages_json = "[]"
            else:
                saved_config.language_mode = "selected"
                saved_config.selected_languages_json = json.dumps(
                    sorted(config.language_mode)
                )
            session.add(saved_config)
            session.add(
                V2Job(
                    job_id=job_id,
                    batch_id=job_id,
                    kind="scan",
                    status="queued",
                    report_json=json.dumps(report, ensure_ascii=False),
                )
            )
            session.commit()
        self._pool.submit(
            self._run_batch,
            job_id,
            LibraryConfig(source_root, output_root, config.language_mode),
        )
        return JobRef(job_id)

    def submit_review_resolution(
        self, job_id: str, group_id: str, partition: list[list[str]]
    ) -> JobRef:
        report = self._load_report(job_id)
        if report["status"] not in {"completed", "running"}:
            raise ValueError("Only a current batch with review items can be resolved")
        review_item = next(
            (item for item in report["review"] if item["group_id"] == group_id), None
        )
        if review_item is None:
            raise ValueError(f"Unknown current-batch review group: {group_id}")
        group = self._load_review_group(job_id, group_id)
        resolved = resolve_review_group(group, partition)
        if isinstance(resolved, ReviewError):
            raise ValueError(resolved.message)
        review_job_id = _new_id()
        review_report = dict(report)
        review_report["job_id"] = review_job_id
        review_report["status"] = "queued"
        review_report["progress"] = {
            "phase": "queued",
            "completed": 0,
            "total": len(resolved),
        }
        review_report["log"] = list(report["log"])
        review_report["review"] = [
            item for item in report["review"] if item["group_id"] != group_id
        ]
        with Session(self.database.engine) as session:
            session.add(
                V2Job(
                    job_id=review_job_id,
                    batch_id=job_id,
                    kind="review",
                    status="queued",
                    report_json=json.dumps(review_report, ensure_ascii=False),
                )
            )
            session.commit()
        self._pool.submit(
            self._run_review_resolution,
            review_job_id,
            job_id,
            group_id,
            partition,
        )
        return JobRef(review_job_id)

    def cancel(self, job_id: str) -> None:
        with Session(self.database.engine) as session:
            job = session.get(V2Job, job_id)
            if job is None:
                raise ValueError(f"Unknown v2 job: {job_id}")
            if job.status in {"queued", "running"}:
                job.cancel_requested = True
                session.add(job)
                session.commit()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _is_cancelled(self, job_id: str) -> bool:
        with Session(self.database.engine) as session:
            job = session.get(V2Job, job_id)
            return job is None or job.cancel_requested

    def _store_candidate_groups(
        self,
        batch_id: str,
        auto_groups: list[matching.AutoGroup],
        review_groups: list[matching.ReviewGroup],
    ) -> tuple[list[matching.AutoGroup], list[matching.ReviewGroup]]:
        scoped_auto = []
        scoped_review = []
        with Session(self.database.engine) as session:
            for group in auto_groups:
                scoped_id = f"{batch_id}:{group.group_id}"
                scoped = matching.AutoGroup(scoped_id, group.members)
                session.add(
                    V2CandidateGroup(
                        group_id=scoped_id,
                        batch_id=batch_id,
                        confidence="high",
                        status="auto",
                    )
                )
                session.add_all(
                    V2CandidateGroupMember(
                        group_id=scoped_id,
                        file_id=member.identity.file_id,
                    )
                    for member in group.members
                )
                scoped_auto.append(scoped)
            for group in review_groups:
                scoped_id = f"{batch_id}:{group.group_id}"
                scoped = matching.ReviewGroup(scoped_id, group.members, group.reason)
                session.add(
                    V2CandidateGroup(
                        group_id=scoped_id,
                        batch_id=batch_id,
                        confidence="review",
                        status="review",
                        reason=group.reason,
                    )
                )
                session.add_all(
                    V2CandidateGroupMember(
                        group_id=scoped_id,
                        file_id=member.identity.file_id,
                    )
                    for member in group.members
                )
                scoped_review.append(scoped)
            session.commit()
        return scoped_auto, scoped_review

    def _serialize_review(self, group: matching.ReviewGroup) -> dict[str, Any]:
        return {
            "group_id": group.group_id,
            "reason": group.reason,
            "members": [
                {
                    **_serialize_identity(member.identity),
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
                for member in group.members
            ],
        }

    def _load_review_group(
        self, batch_id: str, group_id: str
    ) -> matching.ReviewGroup:
        with Session(self.database.engine) as session:
            group_row = session.get(V2CandidateGroup, group_id)
            if (
                group_row is None
                or group_row.batch_id != batch_id
                or group_row.confidence != "review"
            ):
                raise ValueError("Review group does not belong to this current batch")
            member_rows = session.exec(
                select(V2CandidateGroupMember)
                .where(V2CandidateGroupMember.group_id == group_id)
                .order_by(V2CandidateGroupMember.file_id)
            ).all()
            members = []
            for member_row in member_rows:
                file_row = session.get(V2MediaFile, member_row.file_id)
                if file_row is None or file_row.probe_status != "ok":
                    raise ValueError("Review group contains missing or unreadable media")
                identity = FileIdentity(
                    file_id=file_row.file_id,
                    relative_path=file_row.relative_path,
                    size=file_row.size,
                    mtime_ns=file_row.mtime_ns,
                )
                restored = library_scan._restore_metadata(session, file_row, identity)
                if isinstance(restored, ScanError):
                    raise ValueError(restored.message)
                members.append(restored)
            reason = group_row.reason or "Manual review"
        return matching.ReviewGroup(group_id, members, reason)

    def _all_languages(self, members: list[MediaMetadata]) -> set[str]:
        languages = set()
        for member in members:
            audio_tracks = [track for track in member.tracks if track.type == "audio"]
            for track in audio_tracks:
                language = consolidation._language_code(track.language)
                if language == "und" and len(audio_tracks) == 1:
                    language = "spa"
                if language != "und":
                    languages.add(language)
        return languages

    def _output_state(
        self, manifest: consolidation.ConsolidationManifest
    ) -> tuple[bool, bool]:
        output_path = (
            manifest.source_root / "dub" / manifest.output_relpath
        ).resolve()
        with Session(self.database.engine) as session:
            record = session.get(V2OutputRecord, manifest.group_signature)
        if record is None:
            return False, False
        if Path(record.output_path).resolve() != output_path:
            return False, False
        try:
            stat = output_path.stat()
        except OSError:
            return False, True
        unchanged = (
            stat.st_size == record.output_size
            and stat.st_mtime_ns == record.output_mtime_ns
        )
        valid = (
            unchanged
            and record.input_signature == manifest.input_signature
            and record.settings_signature == manifest.settings_signature
        )
        return valid, True

    def _save_output_record(
        self, output: consolidation.CompletedOutput
    ) -> None:
        with Session(self.database.engine) as session:
            session.merge(
                V2OutputRecord(
                    group_signature=output.group_signature,
                    output_path=str(output.path.resolve()),
                    input_signature=output.input_signature,
                    settings_signature=output.settings_signature,
                    output_size=output.size,
                    output_mtime_ns=output.mtime_ns,
                )
            )
            session.commit()

    def _append_error(
        self, report: dict[str, Any], message: str, group_id: str | None = None
    ) -> None:
        report["errors"].append(
            {"group_id": group_id, "message": message}
        )
        report["log"].append(message)

    def _run_batch(self, job_id: str, config: LibraryConfig) -> None:
        report = self._load_report(job_id)
        report["status"] = "running"
        report["progress"] = {"phase": "scanning", "completed": 0, "total": 0}
        report["log"].append("Scanning the configured library")
        self._save_report(job_id, report, status="running")
        if self._is_cancelled(job_id):
            report["log"].append("Batch cancelled before scan")
            self._save_report(job_id, report, status="cancelled")
            return

        scan_result = scan_library(config, database_path=self.database.path)
        if isinstance(scan_result, ScanError):
            self._append_error(report, scan_result.message)
            self._save_report(job_id, report, status="failed")
            return
        report["scanned"] = scan_result.indexed
        report["progress"] = {
            "phase": "grouping",
            "completed": scan_result.indexed,
            "total": scan_result.indexed,
        }
        report["log"].append(f"Scanned {scan_result.indexed} media files")
        for identity in scan_result.unreadable:
            with Session(self.database.engine) as session:
                file_row = session.get(V2MediaFile, identity.file_id)
                message = file_row.probe_error if file_row else "Probe failed"
            report["errors"].append(
                {
                    "file_id": identity.file_id,
                    "relative_path": identity.relative_path,
                    "message": message or "Probe failed",
                }
            )

        grouped = matching.build_candidate_groups(scan_result.files)
        auto_groups, review_groups = self._store_candidate_groups(
            job_id, grouped.auto_groups, grouped.review_groups
        )
        report["review"] = [
            self._serialize_review(group) for group in review_groups
        ]
        report["skipped"] = [
            {
                **_serialize_identity(identity),
                "reason": "unique source file",
            }
            for identity in grouped.unique_files
        ]
        report["progress"] = {
            "phase": "consolidating",
            "completed": 0,
            "total": len(auto_groups),
        }
        self._save_report(job_id, report, status="running")

        for index, group in enumerate(auto_groups):
            if self._is_cancelled(job_id):
                report["log"].append("Batch cancelled")
                self._save_report(job_id, report, status="cancelled")
                return
            selected_languages = (
                self._all_languages(group.members)
                if config.language_mode == "all"
                else set(config.language_mode)
            )
            manifest = consolidation.plan_consolidation(
                ConfirmedGroup(group.group_id, group.members),
                selected_languages,
                config.source_root,
            )
            if isinstance(manifest, consolidation.ReviewRequired):
                review_group = matching.ReviewGroup(
                    group.group_id, group.members, manifest.reason
                )
                with Session(self.database.engine) as session:
                    group_row = session.get(V2CandidateGroup, group.group_id)
                    if group_row:
                        group_row.confidence = "review"
                        group_row.status = "review"
                        group_row.reason = manifest.reason
                        session.add(group_row)
                        session.commit()
                report["review"].append(self._serialize_review(review_group))
                report["progress"]["completed"] = index + 1
                report["log"].append(manifest.reason)
                self._save_report(job_id, report, status="running")
                continue

            already_valid, owned = self._output_state(manifest)
            if already_valid:
                report["skipped"].append(
                    {
                        "group_id": group.group_id,
                        "relative_path": manifest.output_relpath,
                        "reason": "unchanged consolidated output",
                    }
                )
                report["progress"]["completed"] = index + 1
                self._save_report(job_id, report, status="running")
                continue

            def progress(percent: int) -> None:
                report["progress"]["completed"] = index + percent / 100
                self._save_report(job_id, report, status="running")

            result = consolidation.execute_consolidation(
                manifest,
                is_cancelled=lambda: self._is_cancelled(job_id),
                on_progress=progress,
                replace_existing=owned,
            )
            if isinstance(result, consolidation.CompletedOutput):
                try:
                    self._save_output_record(result)
                except SQLAlchemyError as error:
                    self._append_error(
                        report,
                        f"Output was published but its database record could not be saved: {error}",
                        group.group_id,
                    )
                report["consolidated"].append(_serialize_output(result))
                report["log"].append(f"Consolidated {result.path}")
            elif isinstance(result, consolidation.Cancelled):
                report["log"].append("Batch cancelled")
                self._save_report(job_id, report, status="cancelled")
                return
            else:
                self._append_error(report, result.message, group.group_id)
            report["progress"]["completed"] = index + 1
            self._save_report(job_id, report, status="running")

        report["progress"]["phase"] = "completed"
        report["progress"]["completed"] = report["progress"]["total"]
        report["log"].append("Batch completed")
        self._save_report(job_id, report, status="completed")

    def _run_review_resolution(
        self,
        review_job_id: str,
        batch_id: str,
        group_id: str,
        partition: list[list[str]],
    ) -> None:
        report = self._load_report(review_job_id)
        initial_consolidated_count = len(report["consolidated"])
        initial_skipped_count = len(report["skipped"])
        initial_errors_count = len(report["errors"])
        initial_log_count = len(report["log"])
        report["status"] = "running"
        report["progress"]["phase"] = "review"
        report["log"].append("Applying current-batch review choice")
        self._save_report(review_job_id, report, status="running")
        try:
            group = self._load_review_group(batch_id, group_id)
            result = resolve_review_group(group, partition)
            if isinstance(result, ReviewError):
                self._append_error(report, result.message, group_id)
                self._save_report(review_job_id, report, status="failed")
                return
        except ValueError as error:
            self._append_error(report, str(error), group_id)
            self._save_report(review_job_id, report, status="failed")
            return

        report["progress"]["total"] = len(result)
        for index, confirmed in enumerate(result):
            if self._is_cancelled(review_job_id):
                self._save_report(review_job_id, report, status="cancelled")
                return
            if len(confirmed.members) < 2:
                report["skipped"].append(
                    {
                        "group_id": confirmed.group_id,
                        "relative_path": confirmed.members[0].identity.relative_path,
                        "reason": "marked as a separate item",
                    }
                )
                report["progress"]["completed"] = index + 1
                continue

            batch_config = self._load_report(batch_id).get("config")
            if not isinstance(batch_config, dict):
                raise ValueError("The current batch has no configuration snapshot")
            config_root = Path(batch_config["source_root"])
            if batch_config["language_mode"] != "all":
                selected_languages = set(batch_config["language_mode"])
            else:
                selected_languages = self._all_languages(confirmed.members)
            manifest = consolidation.plan_consolidation(
                confirmed, selected_languages, config_root
            )
            if isinstance(manifest, consolidation.ReviewRequired):
                self._append_error(report, manifest.reason, confirmed.group_id)
                report["progress"]["completed"] = index + 1
                continue
            already_valid, owned = self._output_state(manifest)
            if already_valid:
                report["skipped"].append(
                    {
                        "group_id": confirmed.group_id,
                        "relative_path": manifest.output_relpath,
                        "reason": "unchanged consolidated output",
                    }
                )
                report["progress"]["completed"] = index + 1
                continue
            def progress(percent: int) -> None:
                report["progress"]["completed"] = index + percent / 100
                self._save_report(review_job_id, report, status="running")

            result = consolidation.execute_consolidation(
                manifest,
                is_cancelled=lambda: self._is_cancelled(review_job_id),
                on_progress=progress,
                replace_existing=owned,
            )
            if isinstance(result, consolidation.CompletedOutput):
                try:
                    self._save_output_record(result)
                except SQLAlchemyError as error:
                    self._append_error(
                        report,
                        f"Output was published but its database record could not be saved: {error}",
                        confirmed.group_id,
                    )
                report["consolidated"].append(_serialize_output(result))
                report["log"].append(f"Consolidated {result.path}")
            elif isinstance(result, consolidation.Cancelled):
                self._save_report(review_job_id, report, status="cancelled")
                return
            else:
                self._append_error(report, result.message, confirmed.group_id)
            report["progress"]["completed"] = index + 1

        with Session(self.database.engine) as session:
            original_group = session.get(V2CandidateGroup, group_id)
            if original_group:
                original_group.status = "resolved-current-batch"
                session.add(original_group)
                session.commit()
        parent_report = self._load_report(batch_id)
        parent_report["review"] = [
            item for item in parent_report["review"] if item["group_id"] != group_id
        ]
        parent_report["consolidated"].extend(
            report["consolidated"][initial_consolidated_count:]
        )
        parent_report["skipped"].extend(report["skipped"][initial_skipped_count:])
        parent_report["errors"].extend(report["errors"][initial_errors_count:])
        parent_report["log"].extend(report["log"][initial_log_count:])
        self._save_report(batch_id, parent_report, status="completed")
        report["progress"]["phase"] = "completed"
        self._save_report(review_job_id, report, status="completed")

    def read_output_languages(self, output_path: Path) -> set[str]:
        from ..core.mkv import probe

        return {
            consolidation._language_code(track.language)
            for track in probe(output_path).tracks
            if track.type == "audio"
        }
