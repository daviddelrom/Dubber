---
type: plan
title: Plan — Local media consolidation
description: Technical plan to scan one local media library, group duplicate films/episodes and consolidate their tracks.
tags: [sdd, plan, media]
timestamp: 2026-11-01T14:09:00Z
topic: sdd
slug: local-media-consolidation
status: approved
approved: 2026-11-01
---

# Plan — Local media consolidation

> Spec: [../specs/local-media-consolidation.md](../specs/local-media-consolidation.md) · Constitution: [../constitution.md](../constitution.md) · Status: approved
> Last updated: 2026-11-01
> Approved with two-PR delivery. The user approved the `ffprobe` revision, completed PR1 T001-T010, and authorized PR2 T011-T020.

## 0. Global Constraints

The following constitution rules are copied verbatim; they apply to every task.

- **Constitution §1:** “Stack: Python 3.11+, FastAPI, SQLite/SQLModel y Jinja/HTMX son el stack actual. Sus dependencias y versión mínima están en `pyproject.toml`. Un cambio de framework web, motor de datos o lenguaje requiere una decisión documentada antes del merge.”
- **Constitution §2:** “Calidad: `.venv/bin/python -m pytest` debe pasar antes del merge. Los cambios de comportamiento incluyen pruebas del comportamiento afectado; las integraciones con `mkvmerge` se validan con archivos MKV reales cuando sea viable. No se fija cobertura mínima ni linter mientras el proyecto no los configure.”
- **Constitution §3:** “Límites de arquitectura: la lógica de `dubber/core/` permanece independiente de la web y de la base de datos. El acceso a datos, trabajos y HTTP se mantiene en `db/`, `jobs/` y `web/`, respectivamente; un cambio que cruce estos límites debe justificarlo en revisión. Detalle: `02-DOCS/wiki/project/architecture.md`.”
- **Constitution §4:** “Ramas y autoría: todo cambio de código se desarrolla en una rama y se integra mediante pull request; no se trabaja directamente en la rama predeterminada. Los commits y el PR pertenecen a la persona responsable, no se atribuyen a una IA.”
- **Constitution §5:** “Seguridad local: el servidor solo escucha en `127.0.0.1`; los procesos externos se invocan con argumentos separados, nunca mediante shell; no se guardan secretos en el repositorio. Estos puntos deben seguir cubiertos por pruebas o revisión.”
- **Constitution §6:** “Mezclas seguras: una coincidencia dudosa o con duración desconocida requiere aprobación explícita. Una salida temporal solo sustituye al resultado final cuando `mkvmerge` termina correctamente; cancelar o fallar no debe dejar un resultado parcial presentado como válido.”
- **Constitution §7:** “UX de trabajos largos: escaneos y mezclas muestran estado y progreso; errores y cancelaciones quedan visibles para la persona usuaria.”
- **Constitution §8:** “Decisiones: cada decisión técnica significativa se registra con fecha, opciones consideradas y motivo en `02-DOCS/wiki/project/decisions.md` o, si afecta el proceso SDD, en `02-DOCS/wiki/sdd/decisions.md`.”

Additional feature constraints from the approved spec:

- Confident groups consolidate without blocking prompts; ambiguous groups remain in Review.
- Matching is local only; TMDb and other online metadata services are out of scope.
- One output MKV is written per confirmed group under `<source>/dub/`; that subtree is excluded from scans.
- Keep one selected video, at most one audio track per selected language, all available subtitles, and all source files.
- Default selected languages: all detected languages; users may choose an explicit set.
- Same/separate review actions apply to the current batch only; do not persist them.
- `mkvmerge` and `ffprobe` are required local executables; `ffprobe` supplies color-transfer metadata that `mkvmerge -J` omits.
- Video priority: pixel resolution, positively identified HDR, codec-efficiency rank, stable relative path.
- Audio priority: channel count, codec-efficiency rank, stable source-relative path and track number.
- Do not migrate or modify legacy `dubber.db`; use a separate v2 database.

## 1. Context & constraints

- Spec acceptance criteria: §Acceptance #1-#16. The most consequential are automatic consolidation (#1), no output re-scan (#2), current-batch review resolution (#6-#7), video/audio ranking (#8-#12), subtitle provenance (#13), and no partial result (#14).
- The user explicitly changed the goal from merging one English/Spanish pair to consolidating all copies into one multilingual library file. Do not preserve the old `esp`/`eng` roles in the new domain model.
- Existing architecture: FastAPI/Jinja/HTMX UI, SQLite/SQLModel, one-thread `JobRunner`, `mkvmerge -J` probing and `mkvmerge` output. Existing `MediaFile`/`Track` metadata is too sparse for quality ranking and consolidation across arbitrary group members.
- Current database uses `create_all` and has no migrations. This feature intentionally starts a new DB file; no automatic migration or destructive reset.
- Out of scope: online title lookup, audio offset correction, deleting sources, login, and automatic perceptual-quality analysis.

## 2. Architecture

```text
[Settings + Library UI] --scan request--> [Single-folder Scan Job]
                                               |
                  [Filesystem Walker] --> [Media Probe: mkvmerge -J + ffprobe]
                                               |
                                      [Local Candidate Grouper]
                                               |
                              [Current-batch Review + Confidence Gate]
                                  | high confidence       | ambiguous
                                  v                       v
                         [Consolidation Planner]    [Review UI]
                                  |                       |
                                  |                  same/separate decision
                                  |                       |
                                  +<----------------------+
                                  |
                         [mkvmerge Executor]
                                  |
                         [<source>/dub/*.mkv]

All components read/write [SQLite v2] through the DB service.
[Job Queue UI] <-- progress/log/status -- [Single-thread JobRunner]
```

- **Settings and library UI (internal):** configure the single source directory, selected audio languages, scan, and display library/groups.
- **Walker and media probe (internal + local executables):** recursively discover supported files, excluding the exact `dub/` output subtree; extract file and track metadata. `mkvmerge` and `ffprobe` are required external executables.
- **Local candidate grouper (internal):** normalize names, parse movie year and episode numbering, score candidate duplicates, and emit auto-merge groups or review candidates.
- **Review resolution (internal, in-memory):** apply the user's same/separate choice to the current batch and queue the resulting group(s); do not store the choice.
- **Consolidation planner (internal):** for each group, produce an immutable manifest of the winning video track, selected audio tracks, all subtitle tracks, and output path.
- **mkvmerge executor (internal + local executable):** execute a manifest, report progress, and atomically publish a complete file.
- **SQLite v2 (internal local store):** persist file/track metadata, groups, selected languages, jobs and output signatures; review choices are not persisted.
- **JobRunner (internal):** one worker serializes scan and merge work, preventing simultaneous writes to the same output.

**Top architectural decision:** one end-to-end scan/consolidation job with a single-thread worker, rather than a distributed queue or separate services. This fits one local user, the existing application lifecycle, and the no-prompt batch goal. The scan phase reports progress first; confident groups are then consolidated automatically; ambiguous groups remain visible in Review. A same/separate choice resolves only the current batch and is not retained for later scans.

### Candidate confidence rules (initial conservative policy)

- **Movie auto-group:** normalized titles are identical; if both years exist they agree; both durations are known and differ by no more than `max(120 seconds, 2% of the longer duration)`. If year or duration is missing, keep the candidate for review rather than auto-merge.
- **Episode auto-group:** normalized series titles are identical; normalized season/episode numbers agree (`SxxEyy` and `NxNN` map to the same pair); durations are known and differ by no more than `max(120 seconds, 5% of the longer duration)`.
- **Review candidate:** exact normalized title/episode identity with missing or conflicting year/duration is reviewed, never auto-merged. For fuzzy candidates, first remove any year or episode marker parsed by the filename parser; then apply Unicode NFKD and case-folding, discard combining marks, replace punctuation with spaces, collapse whitespace, split into unique tokens, and remove only these release tokens: `480p`, `576p`, `720p`, `1080p`, `1440p`, `2160p`, `4k`, `8k`, `bluray`, `brrip`, `bdrip`, `web`, `webrip`, `webdl`, `hdtv`, `dvdrip`, `remux`, `x264`, `h264`, `avc`, `x265`, `h265`, `hevc`, `av1`, `aac`, `ac3`, `eac3`, `dts`, `truehd`, `atmos`, `flac`, `mp3`, and `opus`. Compare the resulting unique token sets using Jaccard similarity `|A ∩ B| / |A ∪ B|`. A candidate enters Review at `>=0.78` only when both sides contain at least two normalized tokens and available year/duration clues are compatible. Conflicting explicit years never auto-merge. Candidates below the threshold are not grouped. Arbitrary release-group names are not removed.
- **Ambiguous graph:** candidate links that would place one file in incompatible groups are never auto-merged; the affected component goes to Review.
- These are starting thresholds, not claims of universal identity. Acceptance fixtures must prove both safe auto-match and near-match-to-review behavior. Thresholds may be changed only via a documented decision, not ad hoc during implementation.

### Track ranking contracts

- **Resolution:** compare pixel area (`width × height`), then height, then width.
- **HDR:** use `ffprobe` stream color-transfer metadata to positively identify PQ/ST 2084 or HLG; BT.2020 primaries alone are insufficient. Missing/unknown metadata is not HDR. If `ffprobe` fails or video-track counts differ between tools, return a probe error rather than guessing.
- **Video codec efficiency:** explicit family rank: AV1 > HEVC/H.265 > VP9 > AVC/H.264 > MPEG-4 Part 2 > MPEG-2 > unknown. Unknown formats remain eligible by resolution/HDR but rank below known codecs. This is a deterministic proxy, not a perceptual quality measurement.
- **Audio codec efficiency:** explicit tested family rank: Opus > E-AC-3 > AAC > AC-3 > DTS > MP3 > PCM > unknown. Higher channel count is always the primary criterion.
- **Track source:** all media inputs are passed as separate input entries with explicit selected track IDs. The manifest prevents `mkvmerge` defaults from accidentally importing extra video/audio tracks.

## 3. Interfaces & contracts

```text
scan_library(config: LibraryConfig, *, database_path: Path | None = None)
  -> ScanReport | ScanError
  - recursively indexes supported files; never descends into output_root
  - reports unreadable files and continues
  - idempotent for unchanged size + mtime
  - uses the supplied database path rather than the environment default when provided
  - returns the indexed `MediaMetadata` needed by grouping
  - `ScanReport = {files: list[MediaMetadata], indexed: int, changed: int, unreadable: list[FileIdentity]}`

probe_media(file: MediaFileRef)
  -> MediaMetadata | ProbeError
  - `FileIdentity = {file_id: str, relative_path: str, size: int, mtime_ns: int}`; `MediaFileRef = {file_id: str, path: Path, identity: FileIdentity}`
  - use `mkvmerge -J` for container, track, codec, dimension, and channel metadata; use `ffprobe` video-stream order and `color_transfer` for HDR signals
  - pair video streams by their ordinal within the video tracks from each tool, not by global stream index; if video-track counts differ, return `ProbeError`
  - returns `MediaMetadata = {identity: FileIdentity, duration_s: float | None, tracks: list[TrackMetadata]}`; each `TrackMetadata = {track_no: int, type: str, language: str, codec_id: str, channels: int | None, width: int | None, height: int | None, hdr_signals: list[str]}`

build_candidate_groups(files: list[MediaMetadata])
  -> GroupingResult
  - movie/episode rules above; no network calls
  - no source file appears in two automatic groups
  - `ConfirmedGroup = AutoGroup = {group_id: str, members: list[MediaMetadata]}`; `ReviewGroup = {group_id: str, members: list[MediaMetadata], reason: str}`
  - returns `GroupingResult = {auto_groups: list[AutoGroup], review_groups: list[ReviewGroup], unique_files: list[FileIdentity]}`

resolve_review_group(group: ReviewGroup, partition: list[list[str]])
  -> list[ConfirmedGroup] | ReviewError
  - applies the same/separate choice to the current batch only; does not persist it
  - `partition` contains each `group.members[].identity.file_id` exactly once; reject unknown, duplicate, or missing IDs with `ReviewError`
  - the next scan creates fresh groups from current filenames and metadata

plan_consolidation(
  group: ConfirmedGroup,
  selected_languages: set[Language],
  source_root: Path
)
  -> ConsolidationManifest | ReviewRequired
  - exactly one selected video track
  - zero or one selected audio track per configured language
  - all subtitle tracks, with source identity retained in track names
  - resolves member-relative paths beneath source_root and stores it in the manifest
  - output path follows the winning video's relative path under dub/, with .mkv extension

execute_consolidation(
  manifest: ConsolidationManifest,
  *,
  is_cancelled: Callable[[], bool],
  on_progress: Callable[[int], None],
  replace_existing: bool
)
  -> CompletedOutput | MergeError | Cancelled
  - writes a same-directory `.partial.mkv`, then atomically replaces output only on success
  - never modifies input files
  - if another group already owns the target path, refuses replacement and reports a collision
```

## 4. Data model & flow

### Entities

- **LibraryConfig** — one normalized source root, its reserved `dub/` output path, and selected-language mode (`all` or explicit set).
- **MediaFile** — stable row ID, relative path, size, mtime, normalized title, optional year/season/episode, duration, probe status.
- **Track** — file ID, track ID, media type, language (including `und`), codec ID/family, channels, pixel dimensions/HDR signals, track name.
- **CandidateGroup** — member file IDs, confidence class, review/confirmed/merged status, winning video file, output relative path, input signature.
- Group and job rows are batch history only; a historical `confirmed` or `separate` outcome is never loaded as an instruction in a later scan.
- **Job** — scan/consolidation status, progress, log, cancellation, completion; one job may report per-group outcomes.
- **OutputRecord** — group signature, output path, selected language settings signature, completed output file size/mtime. Used for idempotent re-scan and safe rebuild.

### Primary flow

1. User sets one source directory and audio language preferences; config stores `all` until the user chooses an explicit set. Output is derived as `<source>/dub`.
2. User starts **Scan & consolidate**. The walker excludes `<source>/dub`, detects supported files, and re-probes only new/changed files.
3. The grouper normalizes local titles, years and episode numbers and emits confident groups, review groups, unique files, and conflicts. No previous review choice is loaded.
4. For each confident group, the planner selects video/audio/subtitle tracks and calculates a deterministic output path. Previously completed groups with the same input and settings signature are skipped.
5. The executor writes `.partial.mkv` beside the output, validates successful `mkvmerge` completion, then atomically renames it. A failure is logged and processing continues with the next group.
6. Review actions resolve the selected partition for the current batch and queue the resulting group(s). The choice is discarded after the batch; later scans evaluate the files again and may present the group for review.
7. On next scan, unchanged sources and completed outputs are reused; the `dub` directory is never considered a source.

**Consistency boundaries:** one group output is atomic; the entire batch is not. Job status and each group outcome persist independently, so a failed group does not roll back completed groups. Persisted group outcomes are history only and do not retain review choices for later scans. Source files are read-only.

**Database impact:** start with a new default file `dubber-v2.db`; leave `dubber.db` untouched. Before creating tables, detect an existing legacy schema and refuse to mutate it if `DUBBER_DB` points there. No legacy migration is included. Add a schema version marker so later upgrades can be explicit.

## 5. Testing strategy

| Spec acceptance | Level | Asserts | Fakes / mocks |
| --- | --- | --- | --- |
| #1 automatic film consolidation | integration | two known same-title copies create one output without a prompt | filesystem temp dir; real `mkvmerge` |
| #2 exclude output subtree | integration | second scan never indexes files under `dub/` | temp files; real walker |
| #3 unique files untouched | integration | no output; source hashes unchanged | temp files |
| #4 episode numbering variants | unit | `S01E02` and `1x02` normalize identically with series name | none |
| #5 missing IMDb/low-confidence film | unit + integration | title/year/duration score routes weak or conflicting candidates to Review | fixed metadata fixtures |
| #6 same-item review resolution | integration | same-item action queues the group in this batch; a later scan reevaluates it and may show it in Review again | SQLite temp DB; real scan/job flow |
| #7 separate-item review resolution | integration | separate action splits the group for this batch only; no review decision is loaded or retained by a later scan | SQLite temp DB; real scan/job flow |
| #8 resolution winner | unit + integration | pixel area ranking chooses highest resolution and actual output has its video track | unit metadata; real mkvmerge fixture |
| #9 HDR and codec tie breaks | unit | positive PQ/HLG only, codec order and deterministic final tie | metadata JSON fixtures; no expensive HDR encode |
| #10 channel count/audio codec | unit + integration | more channels wins before codec; selected track IDs only | metadata fixtures; small MKV with multiple audio tracks |
| #11 selected audio languages | integration | only selected languages appear, at most one per language | real `mkvmerge -J` on output |
| #12 sole untagged audio | integration | sole untagged track is tagged/treated as Spanish; multi-track unknown produces Review | real MKVs with language tags omitted |
| #13 subtitles/provenance | integration | subtitle tracks from both inputs are present and names include source basename | real MKV fixtures with SRT tracks |
| #14 failure/cancel atomicity | integration | partial removed; prior output byte hash unchanged; sources unchanged | fake process for failure/cancel, real `os.replace` |
| #15 legacy DB preservation | integration | old DB hash/schema unchanged; v2 DB is distinct; legacy override fails safely | temp SQLite files |
| #16 unreadable file continues | integration | unreadable file appears as exception while another group completes | corrupt fixture + real valid MKV |

- **E2E boundary:** FastAPI `TestClient` drives settings → scan-and-consolidate → review → output; jobs may poll until terminal status. Real filesystem, SQLite, `mkvmerge`, and small MKVs are required for confidence. No external metadata APIs are used.
- **Always-real dependencies:** `mkvmerge` for track-selection and container behavior; SQLite for persisted library/job state; filesystem renames for output atomicity. Mock only process failure/cancellation and malformed probe responses.

## 6. Sequencing & dependencies

1. **Probe contract and fixtures** — expand media metadata to include dimensions, HDR signals, channels and codec identifiers; use `mkvmerge -J` for track metadata and `ffprobe` for video color-transfer metadata. Verify the ordinal mapping against representative files; a missing/failing `ffprobe` or a stream-count mismatch is an explicit `ProbeError`. — depends on: none — serial.
2. **Local naming and candidate grouping** — normalize movie/series names, parse years and both episode forms, implement conservative confidence rules and test collision/near-match fixtures. — depends on: #1 interface definition — parallelizable with #3 after interfaces are agreed.
3. **V2 data model and DB guard** — singleton source config, richer tracks, candidate groups, output records, jobs, schema version. Default to `dubber-v2.db`; preserve/refuse legacy DB. — depends on: shared metadata/group contracts from #1/#2.
4. **Single-folder scan and language settings** — one source root, derived `dub/`, recursive scan with exact output exclusion, persistent all-vs-selected language setting, incremental probe. — depends on: #1, #3.
5. **Current-batch review resolution** — review page with confirm-same / separate partition actions; apply the resolution to the running batch only and retain no decision for later scans. — depends on: #2, #3, #4.
6. **Consolidation manifest and executor** — choose video/audio/subtitles; build per-input track-selection manifest; output naming/collision guard; atomic temporary output; continue batch after per-group errors. — depends on: #1, #3.
7. **Automatic end-to-end job and UI** — Scan & consolidate triggers confident groups; review confirmation queues a group; jobs show per-group progress/outcomes; remove old esp/eng/dub flows. — depends on: #4, #5, #6.
8. **Database/data safety, E2E, docs** — prove old DB untouched, source preservation, idempotency, edge cases; update user and tool docs. — depends on: #7.

- **Parallel candidates:** #2 and #3 can proceed in parallel once their data/interface contracts are agreed; #5 and #6 can proceed in parallel after #3/#4, with disjoint module ownership.
- **Hard ordering:** probe metadata and identity/group contracts precede the consolidation planner; no code before task breakdown and analyze pass.

## 7. Risks & open decisions

| Risk | Trigger | Impact | Mitigation / spike to retire it |
| --- | --- | --- | --- |
| False-positive local match | Common/translated title, remake, conflicting releases | Unrelated files consolidated | Auto-merge only exact normalized title + compatible year + duration threshold; exact episode identity for series; fuzzy/uncertain cases only Review; test remakes/common names. |
| HDR/codec metadata unavailable or inconsistent | `ffprobe` is missing/fails, or tool stream order/count cannot be aligned | Wrong video tie-break | Require local `ffprobe`; map video tracks by video ordinal, treat unknown transfer as non-HDR, and return a visible probe error on tool failure or count mismatch. |
| Audio language tags are absent/wrong | User files have untagged or mis-tagged audio | Wrong language retained or omitted | Keep sole-track Spanish rule; multi-track unknowns go to Review; expose selected track metadata in review. |
| Subtitle compatibility/provenance | Source format or subtitle codec not supported by Matroska | Missing subtitle or failed group | Real integration fixtures per supported format; if one track cannot be muxed, mark group failed/review and preserve sources/output. |
| Same ambiguous group reappears | A later scan finds the same uncertain files | User may repeat a same/separate choice | Keep choices scoped to one batch and show review as non-blocking; do not add persistent identity or hashing in v1. |
| Output collision/stale file | Chosen best source changes or two groups target same relative path | Overwrite unrelated or valid output | Group ownership uniqueness, output signature and collision refusal; only replace a matching prior group output after successful temp build. |
| Existing database opened as V2 | Default or `DUBBER_DB` points to old schema | Data corruption or startup failure | New default filename and schema-version preflight before `create_all`; integration test checks old DB hash remains unchanged. |
| Long scans / partial batch failures | Large folder, corrupt media, full disk, cancellation | Apparent hang or lost progress | One scan job with file/group progress, per-file errors, per-group atomicity, continue-after-error, cancellation checks. |

**Open decisions:** none. The user approved requiring the local `ffprobe` executable for reliable HDR transfer detection. Thresholds and codec rankings above are proposed for plan approval and must be implemented as explicit, tested policy tables.

## Tasks

Generated by `tasks` on 2026-11-01. Run behavioral tests red-first, then implement until green; commands below are the required done-checks, not code written in this phase.

| ID | [P] | Task | Done-check | Depends-on | Trace |
| --- | --- | --- | --- | --- | --- |
| T001 | [P] | Add media-probe tests | `.venv/bin/python -m pytest -q tests/test_metadata.py` fails only on expected dimension/HDR/channel/codec and stream-mapping assertions, not collection or import errors; fixtures cover both `mkvmerge -J` and `ffprobe` JSON. | — | Spec §Behaviour #4-#5; §Acceptance #8-#10, #12 |
| T002 |  | Extend media metadata probing | `.venv/bin/python -m pytest -q tests/test_metadata.py` passes with both tool-output fixtures; positive PQ/HLG and unknown HDR are distinguished, and missing/failing `ffprobe` or mismatched video-stream counts produce `ProbeError`. | T001 | Spec §Acceptance #8-#10, #12 |
| T003 |  | Add local matching tests | `.venv/bin/python -m pytest -q tests/test_local_matching.py` fails only on expected normalization, episode parsing, Jaccard threshold boundaries, confidence and ambiguity assertions. | T002 | Spec §Behaviour #2-#3; §Acceptance #4-#5 |
| T004 |  | Implement local candidate grouping | `.venv/bin/python -m pytest -q tests/test_local_matching.py` passes for exact high-confidence groups, explicit Jaccard boundary values, fuzzy review candidates, conflicting years and non-matches. | T002, T003 | Spec §Behaviour #2-#3; §Acceptance #4-#5 |
| T005 |  | Add v2 database safety tests | `.venv/bin/python -m pytest -q tests/test_db_v2.py` fails only on expected new-schema, separate-default-file and legacy-DB refusal assertions. | T002, T004 | Spec §Out of scope; §Acceptance #15 |
| T006 |  | Create v2 data model and database guard | `.venv/bin/python -m pytest -q tests/test_db_v2.py` passes; a legacy schema is rejected before any table or row changes. | T005 | Spec §Goals; §Acceptance #15 |
| T007 |  | Add single-folder scan tests | `.venv/bin/python -m pytest -q tests/test_scan_v2.py` fails only on expected one-root settings, recursive discovery, `dub/` exclusion, unchanged-file and corrupt-file assertions. | T006 | Spec §Behaviour #1, #7; §Acceptance #1-#3, #16 |
| T008 |  | Implement single-folder incremental scanning | `.venv/bin/python -m pytest -q tests/test_scan_v2.py` passes; rescans do not inspect the output tree and report unreadable files without stopping. | T007 | Spec §Behaviour #1, #7; §Acceptance #1-#3, #16 |
| T009 | [P] | Add current-batch review-resolution tests | `.venv/bin/python -m pytest -q tests/test_review_resolution.py` fails only on same-item queueing, separate partitioning, non-blocking batch continuation, and reevaluation on the next scan. | T004, T008 | Spec §Behaviour #3; §Acceptance #6-#7 |
| T010 |  | Implement current-batch review resolution | `.venv/bin/python -m pytest -q tests/test_review_resolution.py` passes; same/separate choices affect the current batch only and are not persisted or loaded by later scans. | T009 | Spec §Behaviour #3; §Acceptance #6-#7 |
| T011 | [P] | Add track-selection planner tests | `.venv/bin/python -m pytest -q tests/test_consolidation_plan.py` fails only on expected video/audio/subtitle selection, language-filter, source-label and collision assertions. | T002, T004, T006 | Spec §Behaviour #4-#6; §Acceptance #8-#13 |
| T012 |  | Implement consolidation manifest planner | `.venv/bin/python -m pytest -q tests/test_consolidation_plan.py` passes; every manifest has one video, at most one audio track per selected language, and all available subtitle tracks. | T011 | Spec §Behaviour #4-#6; §Acceptance #8-#13 |
| T013 |  | Add real muxer execution tests | `.venv/bin/python -m pytest -q tests/test_consolidation_executor.py` fails only on expected real-MKV track layout, subtitle provenance, atomic output, cancellation and source-preservation assertions. | T012 | Spec §Behaviour #6, #8; §Acceptance #13-#14 |
| T014 |  | Implement atomic consolidation executor | `.venv/bin/python -m pytest -q tests/test_consolidation_executor.py` passes with real `mkvmerge` for successful muxes and injected failures/cancellation for error paths. | T013 | Spec §Behaviour #6, #8; §Acceptance #13-#14 |
| T015 |  | Add end-to-end batch job tests | `.venv/bin/python -m pytest -q tests/test_batch_v2.py` fails only on expected scan → group → auto-consolidate flow, review isolation, per-group continuation and idempotency assertions. | T008, T010, T014 | Spec §Goals; §Behaviour #1-#8; §Acceptance #1-#16 |
| T016 |  | Implement automatic scan-and-consolidate jobs | `.venv/bin/python -m pytest -q tests/test_batch_v2.py` passes; high-confidence groups run without prompts, while review groups and failures do not block other groups. | T015 | Spec §Goals; §Behaviour #1-#8; §Acceptance #1-#16 |
| T017 |  | Add UI contract tests | `.venv/bin/python -m pytest -q tests/test_web_v2.py` fails only on expected one-folder settings, selected languages, review actions, job status and no-prompt behavior. | T008, T010, T016 | Spec §Behaviour #1, #3, #7; §Acceptance #1, #6-#7, #11 |
| T018 |  | Wire simplified library and review UI | `.venv/bin/python -m pytest -q tests/test_web_v2.py` passes; old separate English/Spanish folder controls are absent, review actions are non-blocking/current-batch only, and the next scan does not reuse them. | T017 | Spec §Goals; §Behaviour #1, #3, #7 |
| T019 |  | Update user and tool documentation | `.venv/bin/python -c "from pathlib import Path; c={'readme.md':['Escanear y consolidar','dubber-v2.db','TMDb','no se guardan las decisiones de revisión'],'02-DOCS/wiki/project/overview.md':['un solo directorio','revisión','cada escaneo vuelve a evaluar','TMDb'],'01-TOOLS/mkvtoolnix/README.md':['mkvmerge','ffmpeg','ffprobe']}; missing=[f'{p}: {x}' for p,xs in c.items() for x in xs if x not in Path(p).read_text()]; assert not missing, missing"` passes with every required term present in its specific file; review verifies the adjacent text describes the approved behavior and actual tool requirements. | T018 | Constitution §8; Spec §Goals and §Out of scope |
| T020 |  | Run full verification and health checks | `.venv/bin/python -m pytest -q` passes and `npx --yes @ericrisco/rsc@3.7.1 doctor` reports healthy; record exact outputs in the verify artifact. | T019 | Constitution §2, §6; Spec §Acceptance #1-#16 |


### Per-task Interfaces

**T001 — Interfaces**
- Consumes: `mkvmerge_json: dict` and `ffprobe_json: dict` fixtures representative of both external tools.
- Produces: assertions for `probe_media(file: MediaFileRef) -> MediaMetadata | ProbeError` and the `MediaMetadata`/`TrackMetadata` shapes specified in T002.

**T002 — Interfaces**
- Consumes: `mkvmerge_json: dict` returned by `mkvmerge -J` and `ffprobe_json: dict` returned by `ffprobe`; video tracks are paired by ordinal and unequal video-stream counts return `ProbeError`.
- Produces: `probe_media(file: MediaFileRef) -> MediaMetadata | ProbeError`, where `MediaMetadata = {identity: FileIdentity, duration_s: float | None, tracks: list[TrackMetadata]}` and `TrackMetadata = {track_no: int, type: str, language: str, codec_id: str, channels: int | None, width: int | None, height: int | None, hdr_signals: list[str]}`. The implementation runs both tools; a missing/nonzero `ffprobe` result returns `ProbeError`.

**T003 — Interfaces**
- Consumes: `MediaMetadata` and `FileIdentity` from T002.
- Produces: assertions for `build_candidate_groups(files: list[MediaMetadata]) -> GroupingResult`, including the exact normalization, confidence, Jaccard, and ambiguity rules in §2.

**T004 — Interfaces**
- Consumes: `files: list[MediaMetadata]` from T002.
- Produces: `build_candidate_groups(files) -> GroupingResult`, where `GroupingResult = {auto_groups: list[AutoGroup], review_groups: list[ReviewGroup], unique_files: list[FileIdentity]}`; no file belongs to two `AutoGroup` values.

**T005 — Interfaces**
- Consumes: `open_v2_database(path: Path) -> DatabaseHandle | LegacyDatabaseError` and `default_database_path() -> Path` from T006.
- Produces: tests proving the default path differs from `dubber.db` and a legacy database remains unchanged when rejected.

**T006 — Interfaces**
- Consumes: the entity list in plan §4 and `FileIdentity` from T002.
- Produces: `open_v2_database(path: Path) -> DatabaseHandle | LegacyDatabaseError`, `default_database_path() -> Path`, `LibraryConfig = {source_root: Path, output_root: Path, language_mode: "all" | set[str]}`, and `MediaFile`, `Track`, `CandidateGroup`, `Job`, and `OutputRecord` tables in `dubber-v2.db`; legacy schema detection occurs before schema creation.

**T007 — Interfaces**
- Consumes: `LibraryConfig` and `scan_library(config) -> ScanReport | ScanError` from T008.
- Produces: tests for recursive discovery, output exclusion, unchanged-file reuse, and per-file scan errors.

**T008 — Interfaces**
- Consumes: `LibraryConfig = {source_root: Path, output_root: Path, language_mode: "all" | set[str]}` from T006 and `probe_media(file: MediaFileRef) -> MediaMetadata | ProbeError` from T002.
- Produces: `scan_library(config: LibraryConfig, *, database_path: Path | None = None) -> ScanReport | ScanError`, where `ScanReport = {files: list[MediaMetadata], indexed: int, changed: int, unreadable: list[FileIdentity]}`. An explicit path keeps the scanner on the same database as its batch runner rather than re-reading `DUBBER_DB`.

**T009 — Interfaces**
- Consumes: `ReviewGroup` from T004 and `resolve_review_group(group, partition) -> list[ConfirmedGroup] | ReviewError` from T010.
- Produces: tests proving same/separate resolution affects only the current batch and later scans do not load a saved choice.

**T010 — Interfaces**
- Consumes: `ReviewGroup = {group_id: str, members: list[MediaMetadata], reason: str}` from T004 and a user-selected `partition: list[list[str]]` of each member's `identity.file_id`.
- Produces: `resolve_review_group(group, partition) -> list[ConfirmedGroup] | ReviewError`; the result is in-memory and scoped to the current batch.

**T011 — Interfaces**
- Consumes: `ConfirmedGroup`, `selected_languages: set[str]`, and configured `source_root: Path` from T004/T006.
- Produces: assertions for `plan_consolidation(group, selected_languages, source_root) -> ConsolidationManifest | ReviewRequired` and the manifest shape in T012.

**T012 — Interfaces**
- Consumes: `ConfirmedGroup = {group_id: str, members: list[MediaMetadata]}`, `selected_languages: set[str]`, and `source_root: Path`.
- Produces: `plan_consolidation(group, selected_languages, source_root) -> ConsolidationManifest | ReviewRequired`; `ConsolidationManifest = {group_id: str, source_root: Path, video: TrackRef, audio: list[TrackRef], subtitles: list[TrackRef], output_relpath: str, input_signature: str, settings_signature: str}`; audio has at most one entry per selected language. `source_root` resolves persisted relative file identities safely at execution time.

**T013 — Interfaces**
- Consumes: `ConsolidationManifest` from T012 and the cancellable/progress-reporting `execute_consolidation` API from T014.
- Produces: tests for real-MKV track layout, subtitle provenance, atomic publication, cancellation, and source preservation.

**T014 — Interfaces**
- Consumes: `ConsolidationManifest` from T012.
- Produces: `execute_consolidation(manifest, *, is_cancelled, on_progress, replace_existing) -> CompletedOutput | MergeError | Cancelled`; success is reported only after atomic publication, progress is reported through the callback, and replacement is permitted only for an output owned by the same group.

**T015 — Interfaces**
- Consumes: `submit_scan_and_consolidate(config: LibraryConfig) -> JobRef`, `submit_review_resolution(job_id: str, group_id: str, partition: list[list[str]]) -> JobRef`, and `get_job_report(job_id: str) -> BatchReport` from T016.
- Produces: end-to-end assertions for automatic groups, non-blocking review, per-group continuation, and idempotency.

**T016 — Interfaces**
- Consumes: `scan_library(config, database_path=...) -> ScanReport` from T008, `build_candidate_groups(files) -> GroupingResult` from T004, `resolve_review_group(group, partition) -> list[ConfirmedGroup] | ReviewError` from T010, `plan_consolidation(group, selected_languages, source_root) -> ConsolidationManifest | ReviewRequired` from T012, and cancellable/progress-reporting `execute_consolidation` from T014.
- Produces: `submit_scan_and_consolidate(config: LibraryConfig) -> JobRef`, `submit_review_resolution(job_id: str, group_id: str, partition: list[list[str]]) -> JobRef`, and `get_job_report(job_id: str) -> BatchReport`, where `JobRef = {job_id: str}` and `BatchReport = {job_id: str, status: "queued" | "running" | "completed" | "failed" | "cancelled", progress: {phase: str, completed: float, total: int}, log: list[str], scanned: int, consolidated: list[CompletedOutput], review: list[ReviewGroup], skipped: list[dict], errors: list[dict]}`; persist job progress/log.

**T017 — Interfaces**
- Consumes: `LibraryConfig`, `ReviewGroup`, and `BatchReport` shapes from T006/T004/T016.
- Produces: expected route contracts for T018: `GET / -> 200 settings_page`, `POST /settings -> 303 /`, `POST /jobs/scan -> 202 {job_id: str}`, `POST /jobs/{job_id}/reviews/{group_id}` with `{partition: list[list[str]]}` of member `file_id` values `-> 202 {job_id: str}`, and `GET /jobs/{job_id} -> 200 BatchReport`.

**T018 — Interfaces**
- Consumes: settings form `{source_root: str, selected_languages: list[str] | ["all"]}`, `ReviewGroup`, `BatchReport`, and the route contract from T017.
- Produces: one-folder settings page, non-blocking review actions (`same` with a partition or `separate`), and queue cards reflecting each group outcome. The action submits current-batch resolution; no later scan loads it.


### Review workload forecast

| Dimension | Forecast | Why |
| --- | --- | --- |
| Estimated changed lines | 800–1,200 | New scanner/matcher/data model, selection manifest, error handling, UI, and real-MKV tests. |
| Files / areas | 20–30 files across `dubber/core`, `db`, `jobs`, `web`, `tests`, `readme.md` and `02-DOCS`. | The feature changes the data model and the complete user flow, not one isolated endpoint. |
| Review risk | High | Local matching can merge unrelated media; track metadata and database replacement have data-safety consequences. |
| Suggested delivery | Two reviewable PRs (approved by user). | Estimate exceeds the configured 400-line / 12-file review budget and spans multiple contracts. |

**Approved PR slices:** PR 1 adds v2 probing, local matching, database safety, one-folder scan and current-batch review resolution while leaving the old workflow available. PR 2 adds automatic track consolidation, simplified UI, batch orchestration and end-to-end verification. Do not remove the old workflow or switch the default DB until PR 2 is complete and verified.

## Task handoff

The revised plan passed `analyze` and the user re-approved it on 2026-11-01. PR1 T001-T010 and user-authorized PR2 T011-T020 are complete; verification is recorded in [the progress artifact](../progress/local-media-consolidation.md).
