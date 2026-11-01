---
type: feature-spec
title: Local media consolidation
tags: [sdd, spec, media, matching]
topic: sdd
status: approved
approved: 2026-11-01
created: 2026-11-01
---

# Spec — Local media consolidation

## Problem & why

Dubber currently asks the person to configure separate English and Spanish folders, inspect candidate pairs, and manually start merges. The goal is to point Dubber at one mixed media folder and let it identify duplicate films and episodes, then consolidate each confirmed group into one file: the best video, one audio track per wanted language, and available subtitles.

## Cost of not building it

The person must maintain language-specific folders, compare duplicate files, and initiate routine merges. This leaves most of the repetitive work manual and does not produce a unified media library.

## Strongest objection considered

Local matching cannot reliably recognize every differently named or translated film. A false match could combine unrelated media and lose track-selection intent. The user chose local-only matching for now; uncertain groups must therefore be recorded for review, not silently merged. This means some true duplicates may remain unconsolidated until reviewed.

## Goals

- Configure one folder containing mixed source files; write consolidated results under its `dub/` subfolder and exclude that output folder from scans.
- Detect likely duplicate films and episodes locally, without sending filenames or media metadata to online services.
- Automate confident groups without blocking prompts. Continue processing other groups when an exception occurs.
- For each confirmed group, produce one file with the selected best video, at most one audio track per selected language, and all available subtitle tracks from the source files.
- Preserve all source files. Never show an incomplete output as successful.
- Let the user resolve ambiguous groups without blocking the batch. Do not persist review decisions; later scans evaluate the files again.

## Out of scope

- TMDb or any other online metadata lookup; this can be considered as a separate future feature.
- Audio offset/synchronization correction.
- Manual confirmation for every group or modal prompts that block batch processing.
- Deleting or modifying source files.
- Migrating records from the existing `dubber.db`; the new workflow uses a fresh database and leaves the existing database untouched.

## Users & context

A single local user with a folder of downloaded films and series. Filenames vary and often lack IMDb IDs. Series commonly identify episodes as `S01E02` or `1x02`. A title may have several copies with different video quality and language tracks. Files may contain multiple audio and subtitle tracks. The user wants the app to do routine work without prompting, while retaining a way to resolve uncertain cases.

## Behaviour

1. Settings ask for one source folder and a selection of audio languages to keep. By default, all detected languages are selected. The output folder is `dub/` below the source folder. Recursive scans exclude `dub/`.
2. A batch scan reads local filenames and media metadata. It groups likely duplicate films by normalized title and available year/duration clues. It groups episodes by normalized series title and episode number, recognizing both `SxxEyy` and `NxNN` forms. It makes no network requests.
3. Confident duplicate groups are consolidated automatically. Groups with low confidence, conflicting metadata, or insufficient identification go to a review list. Review actions let the user mark the files as the same item or separate items for the current batch only. The decision is not persisted; later scans evaluate the files again and may present the same group for review. Review never blocks the rest of the batch.
4. For a confirmed group, the video source is chosen by this order: higher resolution; then positively identified HDR; then more efficient codec. If these are equal, a stable relative-path order breaks the tie. The output uses the chosen video's filename and relative folder path under `dub/`.
5. Audio output has at most one track per selected language. For duplicate tracks in one language, more channels wins; codec efficiency breaks a tie. If a source file has exactly one untagged audio track, it is treated as Spanish. If a file has multiple audio tracks and one or more are untagged, those untagged tracks create a review exception.
6. All available subtitle tracks from the group's source files are included. Each subtitle track retains enough source identity in its output metadata to distinguish where it came from.
7. A group with no duplicate source remains unchanged and produces no output. An unreadable file is recorded as an exception; other groups continue. The queue reports progress, completed groups, review groups, skipped groups, and errors.
8. A failed or cancelled consolidation leaves sources unchanged and does not replace a previously valid output with a partial file.

## Acceptance criteria

- Given one mixed source folder with two high-confidence copies of the same film, when a scan runs, then Dubber consolidates them without a prompt and writes one result under `dub/`.
- Given an existing `dub/` folder inside the source folder, when a recursive scan runs, then its outputs are not treated as source candidates.
- Given a folder with only unique files, when a scan completes, then sources remain untouched and no consolidated outputs are created.
- Given series copies using `S01E02` and `1x02`, when their normalized series title and episode identify the same item, then they appear in one candidate group.
- Given movie filenames without IMDb IDs, when local title/year/duration signals are insufficient for a confident match, then Dubber does not merge them automatically and adds them to review.
- Given an ambiguous group that the user marks as the same item, when the current batch continues, then the group is queued for consolidation without blocking other groups; a later scan evaluates it again and may present it for review.
- Given an ambiguous pair that the user marks as separate items, when the current batch continues, then the files are treated as separate for that batch; no decision is stored for later scans.
- Given candidates with different video resolutions, when Dubber selects the output video, then it chooses the highest-resolution candidate.
- Given equal-resolution videos, when one is positively identified as HDR, then it wins; if HDR status is equal, the more efficient codec wins; a remaining tie is resolved by stable relative-path order.
- Given multiple audio tracks in a selected language, when Dubber builds the output, then the track with the most channels wins and codec efficiency breaks a tie.
- Given a selected language list, when a group has other audio languages, then those unselected languages are absent and each selected language has at most one track.
- Given a source file with exactly one untagged audio track, when Dubber consolidates a confirmed group, then it treats the track as Spanish. If the file has multiple audio tracks and an untagged track, that group is added to review.
- Given subtitle tracks in multiple source files, when Dubber consolidates the group, then all available tracks are included with distinguishable source identity.
- Given a failed or cancelled job, when it exits, then no partial output is presented as complete and any previous valid output remains intact.
- Given an existing `dubber.db`, when the new workflow starts, then it uses a fresh database and does not modify or delete the old file.
- Given an unreadable source file, when the batch runs, then Dubber reports it as an exception and continues processing other groups.

## Points to clarify

- **assumption** — all detected audio languages are selected by default; the user may reduce this list in settings.
- **assumption** — video ranking is resolution, then positively detected HDR, then codec efficiency; a stable relative path breaks any remaining tie. HDR detection is only trusted when metadata positively identifies it.
- **assumption** — duplicate audio ranking is channel count, then codec efficiency.
- **assumption** — all subtitles are kept, including same-language subtitles from different sources, and their source remains distinguishable.
- **assumption** — supported source formats remain `.mkv`, `.mp4`, and `.avi`; scan remains recursive.
- **decision deferred to plan** — define the exact local-match confidence boundary. Prefer missing a match over a false automatic merge.
- **decision deferred to plan** — verify the codec-efficiency rankings and positive HDR metadata signals against representative files; codec/container support can vary by source format.
- **decision deferred to plan** — define deterministic output handling for filename/path collisions while preserving the chosen video's relative path where possible.
- **decision deferred to plan** — subtitle source identity and track selection mechanics must be validated against `mkvmerge` behavior for all supported source formats.

## Clarifications

- **2026-11-01 — Product direction changed:** the goal is no longer to find one English file and one Spanish file. It is to deduplicate all copies and consolidate them into one multilingual library file. Routine work should not use blocking prompts.
- **2026-11-01 — Inputs and privacy:** one mixed folder, local-only title matching, no TMDb for now. Series filenames commonly use `SxxEyy` or `NxNN`; many files do not contain IMDb IDs.
- **2026-11-01 — Video choice:** higher resolution wins, then HDR, then codec efficiency.
- **2026-11-01 — Audio choice:** one track per selected language; more channels wins, then codec efficiency.
- **2026-11-01 — Ambiguous groups:** user can resolve same-item or separate-item decisions for the current batch; decisions are not persisted, so later scans evaluate the files again.
- **2026-11-01 — Untagged audio:** a sole untagged audio track is assumed Spanish; untagged tracks in a file with multiple audio tracks cause a review exception.
- **2026-11-01 — Output and data:** output uses a `dub/` subfolder, is excluded from scans, and preserves the best-video source name/path. A new database is used; existing `dubber.db` is untouched.
- **2026-11-01 — Review decisions:** the user chose not to persist same-item/separate-item decisions; each scan reevaluates uncertain groups to keep the design simple and avoid extra media reads.
- **2026-11-01 — Approval:** user approved this revision: same/separate actions apply only to the current batch, are not persisted, and later scans reevaluate the files. No implementation is authorized yet.

## Revisions

| Date | Change | Why |
|---|---|---|
| 2026-11-01 | Initial draft based on user-approved scope and clarifications. | Define the desired automatic, local-only consolidation behaviour before design. |
| 2026-11-01 | Updated to reflect automatic multi-source consolidation, language selection, remembered review decisions, and the user's video/audio ranking choices. | The clarified goal superseded the earlier English/Spanish pair-merge specification. |
| 2026-11-01 | User approved the revised specification after clarification. | Contract was ready for technical planning. |
| 2026-11-01 | Replaced persistent SHA-256 review decisions with current-batch-only review actions; subsequent scans reevaluate uncertain groups. User approved the revision. | The user preferred a simpler design over preserving decisions across scans. |
