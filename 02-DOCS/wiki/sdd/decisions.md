# Approved decisions for local media consolidation (2026-11-01)

The user approved the technical plan and its two-PR delivery split on 2026-11-01.

- Keep one local source root and derive `dub/` below it; exclude that exact subtree from scans.
- Run a scan-and-consolidate batch in the existing single-thread job runner; confident groups run without prompts, while review exceptions never block other groups.
- Use conservative, deterministic local matching; no online metadata calls. Fuzzy review candidates use Jaccard similarity over normalized, unique token sets at a threshold of 0.78; uncertain candidates are reviewed rather than auto-merged.
- Do not persist review decisions. Same/separate actions resolve the current batch only; later scans evaluate the files again. This avoids rereading large media files to preserve a decision across scans.
- Start with a separate `dubber-v2.db`; never migrate or modify legacy `dubber.db` automatically.
- Select tracks with a manifest and `mkvmerge`; write a same-directory `.partial.mkv` then atomically publish after success.

## HDR probing dependency (2026-11-01)

- **Decision:** Require the local `ffprobe` executable alongside `mkvmerge` for media probing. Use `ffprobe`'s video-stream `color_transfer` to identify PQ/ST 2084 and HLG; pair tracks by video-stream ordinal. If `ffprobe` is missing/fails or its video-stream count does not match `mkvmerge`, surface a probe error rather than guessing.
- **Reason:** A generated 10-bit HEVC MKV tagged with ST 2084 was reported by `ffprobe` as `smpte2084`, while `mkvmerge -J` omitted the transfer metadata. Without `ffprobe`, the approved HDR tie-break would not work reliably.
- **Alternatives considered:** Treat absent `mkvmerge` color metadata as non-HDR (loses the approved positive HDR tie-break); infer HDR from BT.2020 primaries (not reliable); add a Python probing dependency (unnecessary when the user approved a local executable).
- **Approval:** The user approved adding `ffprobe` on 2026-11-01.

## Explicit library and database roots (2026-11-01)

- **Decision:** Pass `source_root` to the consolidation planner and carry the resolved root in its manifest. Let the scanner accept an optional explicit database path, and have batch jobs pass their runner's database path.
- **Reason:** Persisted media identities contain library-relative paths, so the planner needs the selected library root to resolve source files safely. A batch runner may also be created with a database handle that differs from `DUBBER_DB`; its scan must write to the same database instead of opening the environment default.
- **Alternatives considered:** Resolve paths against the current working directory (not stable or safe); let the scanner re-read `DUBBER_DB` (can split one batch across two databases); or store absolute media paths in each persisted identity (unnecessary duplication).
- **Effect:** This clarifies internal API contracts without changing the user workflow or the rule that review choices are batch-scoped.
