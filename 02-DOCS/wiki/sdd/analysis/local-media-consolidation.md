---
type: analysis
title: Analysis — Local media consolidation
slug: local-media-consolidation
topic: sdd
timestamp: 2026-11-01T15:17:06Z
status: complete
---

# Analysis — Local media consolidation

## Verdict

**GATE: PASS** — 0 CRITICAL, 0 HIGH, 0 MEDIUM findings. The revised plan covers all 16 approved acceptance criteria. The user re-approved the `ffprobe` revision, authorized PR1 T001-T010, and subsequently authorized PR2 T011-T020; both implementation slices are complete.

## Requirement coverage

| REQ-ID | Spec requirement | Plan section | Task(s) | Status |
|---|---|---|---|---|
| R1 | Consolidate confident film duplicates automatically from one folder | §2, §4 | T015-T016 | covered |
| R2 | Exclude `dub/` from source scans | §2, §3 | T007-T008 | covered |
| R3 | Leave unique source files untouched | §4-§5 | T015-T016 | covered |
| R4 | Normalize `SxxEyy` and `NxNN` episode identifiers | §2, §3 | T003-T004 | covered |
| R5 | Route low-confidence local film matches to review | §2, §3, §5 | T003-T004 | covered |
| R6 | Apply a same-item review choice to the current batch only | §3-§5 | T009-T010, T015-T016 | covered |
| R7 | Apply a separate-item review choice to the current batch only | §3-§5 | T009-T010, T015-T016 | covered |
| R8 | Select highest-resolution video | §2-§3 | T001-T002, T011-T012 | covered |
| R9 | Use positive HDR and codec-efficiency tie-breaks | §2-§3 | T001-T002, T011-T012 | covered |
| R10 | Rank duplicate audio by channels, then codec | §2-§3 | T011-T012 | covered |
| R11 | Keep at most one audio track per selected language | §0, §3 | T011-T012, T017-T018 | covered |
| R12 | Apply the untagged-audio rule | §3, §5 | T001-T002, T011-T012 | covered |
| R13 | Retain subtitles with source identity | §3, §5 | T011-T014 | covered |
| R14 | Preserve previous output on failure/cancel | §3-§5 | T013-T014 | covered |
| R15 | Preserve the old database and use a new one | §4-§5 | T005-T006 | covered |
| R16 | Report unreadable files and continue | §3, §5 | T007-T008 | covered |

## Findings

| # | Severity | Type | Artifact A (location) | Artifact B (location) | Conflict | Resolve in |
|---|---|---|---|---|---|---|
| — | — | — | — | — | No findings. | — |

## Scope and constitution checks

- The plan carries all eight ratified constitution rules verbatim in §0.
- Requiring local `ffprobe` is an implementation choice for the already-approved positive-HDR requirement, not a new product capability or network dependency. It is recorded in `02-DOCS/wiki/sdd/decisions.md`.
- The HDR contract identifies PQ/ST 2084 and HLG from `ffprobe` video-stream `color_transfer`; unknown transfer stays non-HDR. Missing/failing `ffprobe` and mismatched video-stream counts produce an explicit `ProbeError`.
- The two tools' video tracks are paired by their ordinal within the video tracks; the plan requires count validation and fixture tests for the mapping.
- The task table covers the revised metadata contract: T001 adds both tools' JSON fixtures and stream-mapping/error assertions; T002 implements and verifies them. T001/T002 are correctly reopened because their existing code/tests predate this contract.
- All 16 acceptance criteria map to plan sections and tasks. No acceptance criterion or user-facing behavior changed.
- Current-batch review decisions remain in-memory only; no decision or hash persists across scans.
- The 20-task dependency graph remains ordered and acyclic. Neighbor-dependent tasks carry `Consumes`/`Produces` interface contracts; T003 now follows T002 because its test fixtures consume `MediaMetadata`.
- T019's tool-documentation check includes `ffprobe`; the adjacent documentation review remains required.
- The review matcher remains limited to Review candidates and uses the specified Jaccard threshold and tokenization policy.
- Risks from a missing tool or uncertain stream mapping are surfaced as probe errors, which the scan contract records as per-file exceptions while continuing other groups.

## Recommended routing

1. The analysis gate passed and the user re-approved the revised plan before implementation resumed.
2. PR1 T001-T010 was completed and the user subsequently authorized PR2 T011-T020. PR2 implementation and verification are recorded in the progress artifact.

```json result-envelope
{
  "status": "complete",
  "executive_summary": "The revised spec/plan/task contracts pass analysis; the user re-approved ffprobe, PR1 T001-T010 completed, and PR2 T011-T020 was subsequently authorized.",
  "artifact": "02-DOCS/wiki/sdd/analysis/local-media-consolidation.md",
  "next_recommended": "use the verified PR2 implementation and progress artifact",
  "risk": "high",
  "skill_resolution": {
    "used": ["analyze"],
    "missing": [],
    "fallback": [],
    "compact_rules": ["Cross-read the artifacts, not implementation code.", "A finding without two artifact locations is not a finding."]
  },
  "evidence": ["16 acceptance criteria mapped to plan sections and tasks", "0 critical, 0 high, and 0 medium findings", "8 constitution rules carried verbatim", "20 task IDs and revised HDR interface checked", "ffprobe dependency approved; PR1 completed and PR2 subsequently authorized"]
}
```
