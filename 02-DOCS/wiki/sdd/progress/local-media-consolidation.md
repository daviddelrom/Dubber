# Implementation progress — Local media consolidation

## T001 — 2026-11-01
- status: complete against revised plan
- red: `.venv/bin/python -m pytest -q tests/test_metadata.py` — 7 failed as expected, all by assertions for missing dimensions, codec IDs, positive HDR signals, unknown HDR representation, and audio channels; no collection/import errors.
- revised red: six new `ffprobe` integration assertions failed as expected while 11 existing tests passed.
- green: `.venv/bin/python -m pytest -q tests/test_metadata.py tests/test_core.py` — 24 passed; full suite — 32 passed.
- files: `tests/test_metadata.py`
- decision: test `mkvmerge -J` track properties and `ffprobe` transfer metadata separately; positive ST 2084/PQ and HLG count as HDR, while unknown transfer and BT.2020 primaries alone do not.
- blocker: none.
- skills: used `implement`, `testing-py`, and `python`; no missing skill or fallback.
- commit: deferred; project constitution assigns commit authorship to the responsible human.

## T002 — 2026-11-01
- status: complete against revised plan
- red: new `ffprobe` tests proved the implementation did not invoke the tool, surface missing/nonzero failures, map HDR by video ordinal, reject mismatched video counts, or override unknown transfer.
- green: `.venv/bin/python -m pytest -q tests/test_metadata.py tests/test_core.py` — 24 passed; `.venv/bin/python -m pytest -q` — 32 passed. One pre-existing Starlette/httpx deprecation warning remains.
- files: `dubber/core/mkv.py`, `tests/test_metadata.py`
- decision: `probe_media()` runs both local tools with argument lists, uses `ffprobe` video-stream color transfer as the HDR source, maps by video-track ordinal, and returns `ProbeError` for executable/probe failures or count mismatch. The legacy `probe()` API remains unchanged.
- real-file check: generated a small 10-bit HEVC Matroska sample with x265 ST 2084 VUI; `ffprobe` recognized `smpte2084` and `probe_media()` returned `["pq"]`. `mkvmerge -J` omitted the transfer metadata.
- skills: used `implement`, `testing-py`, and `python`; no missing skill or fallback.
- commit: deferred; project constitution assigns commit authorship to the responsible human.

## Plan revision — 2026-11-01
- decision: the user approved requiring local `ffprobe` alongside `mkvmerge` for HDR transfer metadata.
- plan: revised the T002 contract to run both tools, pair video tracks by video-stream ordinal, and return `ProbeError` if `ffprobe` fails or the video-stream counts differ.
- status: revised plan approved; T001/T002 complete; T003 is ready to start.
- environment: `/usr/bin/ffprobe` is available locally (FFmpeg 9.0.2).
- validation: targeted and full tests passed after implementation.

## T003 — 2026-11-01
- status: complete
- red: `.venv/bin/python -m pytest -q tests/test_local_matching.py` — 13 failed by expected assertions for missing candidate-group, normalization, episode/year parsing, and Jaccard APIs; no collection/import errors.
- green: `.venv/bin/python -m pytest -q tests/test_local_matching.py tests/test_core.py` — 32 passed before the final two incompatible-clue cases were added; full suite passed after implementation.
- files: `tests/test_local_matching.py`
- coverage: both episode conventions, year/title normalization, exact 0.78 and below-threshold Jaccard cases, movie/episode duration thresholds, fuzzy review and compatibility, unique files, ambiguous components, and determinism.
- commit: deferred; project constitution assigns commit authorship to the responsible human.

## T004 — 2026-11-01
- status: complete
- implementation: added conservative graph-based local grouping to `dubber/core/matching.py` and year/episode/title parsing to `dubber/core/naming.py`. Auto groups require exact normalized identity and sufficient clues; fuzzy matches go to Review only. Incompatible links place the full component in Review.
- safety: invalid, non-finite, or non-positive durations are treated as unknown; old IMDb-based `find_pairs()` remains intact.
- commit: deferred; project constitution assigns commit authorship to the responsible human.

## T005/T006 — 2026-11-01
- status: complete
- red: five v2 database tests failed by expected assertions while the path, opener, and v2 schema were absent.
- implementation: added isolated v2 SQLModel metadata/entities and a schema version marker; the existing `make_engine()` and legacy models remain unchanged.
- safety: v2 open validates existing SQLite tables and schema read-only before creating an engine or tables. Legacy/unknown/incompatible databases return `LegacyDatabaseError`; the test verifies the legacy file bytes/schema remain unchanged.
- files: `dubber/db/models_v2.py`, `dubber/db/session.py`, `tests/test_db_v2.py`
- validation: full suite — 63 passed at this checkpoint; one pre-existing Starlette/httpx deprecation warning remains.
- commit: deferred; project constitution assigns commit authorship to the responsible human.

## T007/T008 — 2026-11-01
- status: complete
- red: `.venv/bin/python -m pytest -q tests/test_scan_v2.py` — five assertions failed because the scanner API was not yet implemented; no collection/import errors.
- implementation: added `dubber/jobs/library_scan.py` with one-root validation, recursive supported-file discovery, exact `dub/` exclusion, stable IDs, incremental metadata/track persistence, and visible per-file probe errors while continuing other files.
- behavior: unchanged successful files reuse stored metadata; changed and previously unreadable files are probed again. Output is always the exact `<source>/dub` subtree.
- files: `dubber/jobs/library_scan.py`, `tests/test_scan_v2.py`
- targeted validation: scan, DB, and matcher tests — 38 passed at the time.

## T009/T010 — 2026-11-01
- status: complete
- red: `.venv/bin/python -m pytest -q tests/test_review_resolution.py` — nine assertions failed because the current-batch resolver API was absent.
- implementation: added in-memory partition validation and `ConfirmedGroup` results. Missing, duplicate, unknown, and empty partition entries return `ReviewError`; no DB write or stored decision exists.
- tests: same-item and separate-item partitions, invalid inputs, later regrouping, and unaffected review groups in the current batch. End-to-end job queue continuation remains assigned to T015.
- files: `dubber/core/review.py`, `tests/test_review_resolution.py`
- targeted validation: review and matcher tests — 36 passed at the time.

## PR1 T001-T010 checkpoint — 2026-11-01
- status: complete
- validation: `.venv/bin/python -m pytest -q` — 79 passed, 1 pre-existing Starlette/httpx deprecation warning; `git diff --check` passed.
- next at that checkpoint: PR2 T011-T020.

## PR2 T011-T020 checkpoint — 2026-11-01
- status: complete
- T011/T012: added planner coverage and implementation for video/audio ranking, language selection, subtitle provenance, untagged audio, source-root resolution, and deterministic signatures. `tests/test_consolidation_plan.py` passes.
- T013/T014: added real-MKV execution coverage and atomic `mkvmerge` publication, including error/cancel handling and preservation of sources and prior output. `tests/test_consolidation_executor.py` passes.
- T015/T016: added end-to-end scan/group/consolidate jobs, non-blocking current-batch review, error continuation, output idempotency, and a regression assertion that resolving review does not duplicate prior outputs in the parent report. Scans use the runner's explicit database path. `tests/test_batch_v2.py` and `tests/test_scan_v2.py` pass.
- T017/T018: wired the default app to the v2 library UI, one-folder settings, review actions, job status/progress, cancellation, and explicit errors. The legacy app remains available only through explicit dependency injection. `tests/test_web_v2.py` and `tests/test_app.py` pass.
- T019: updated `readme.md`, the project overview and architecture, and the MKVToolNix/FFmpeg guide and checker script. The required documentation contract check passes; `mkvmerge`, `ffprobe`, and `ffmpeg` are available locally.
- implementation clarification: the planner now receives `source_root` to resolve relative media identities safely; scanner jobs pass their runner database path to prevent a custom runner from splitting writes across databases. Recorded in the SDD decisions and updated plan interfaces.
- verification: `.venv/bin/python -m pytest -q` — 105 passed, 1 pre-existing Starlette/httpx deprecation warning; `git diff --check` passed. `npx --yes @ericrisco/rsc@3.7.1 doctor` — healthy (installed harness 3.7.4). Documentation contract and local tool checks passed.
- test iteration: the first full-suite run exposed tests importing the database factory through an incidental module re-export; the fixture now imports it from `dubber.db.session`, and the rerun passed.
- commit: deferred; project constitution assigns commit authorship to the responsible human. No commit was created.
