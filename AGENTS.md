# AGENTS.md — Premiere Pro Connector build brief

Canonical instruction set for the coding agent building this (primarily **Claude Code**). Read
it fully before writing code. This file is the entry point for every build session.

> This repo was scoped in a Claude (Cowork) session and handed off to Claude Code for the
> actual build. The docs are authoritative; the code does not exist yet.

---

## 0. Read before any work

- [`PRD.md`](PRD.md) — requirements, first-shoot acceptance scenario, success metrics, open questions.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system shape, components, the timeline invariant, fusion sketch.
- [`CONTRACTS.md`](CONTRACTS.md) — the typed shapes that cross every boundary. **This is law.**
- [`ROADMAP.md`](ROADMAP.md) — phased plan with task IDs `PPC-###` and "done when" gates.
- [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) — decisions, findings, what's next. Update it as you go.

## 1. Workflow (mandatory)

1. Open `ROADMAP.md`, pick the **lowest-numbered unfinished `PPC-###`** in the current phase.
2. Check its "done when" gate and the relevant `PRD.md` criteria.
3. If your plan contradicts `ARCHITECTURE.md` or `CONTRACTS.md`, **STOP and flag it** — do not
   silently diverge. Contracts change only by bumping `CONTRACT_VERSION` and updating all
   implementers + tests together.
4. Implement **one `PPC-###` at a time.** Verify against its gate. Commit. Then append a
   `BUILD_LOG.md` entry (what changed, what you learned, what's still open).
5. Don't start a later phase until the current phase's "done when" is met.

## 2. Golden rules

1. **`CONTRACTS.md` is law.** Engine code depends only on `engine.contracts` and the provider
   protocols — never on adapter internals or Modal/HTTP specifics.
2. **Timeline invariant:** float seconds, absolute from master-audio t=0, everywhere. Frame-snap
   only in the exporter.
3. **Fakes before networks.** Build Phase 0 entirely against fake providers; no Modal calls
   until Phase 1. The whole engine must be testable offline.
4. **Probe before parsing.** Before writing the real `clip`/transcriber adapters (Phase 1),
   call each live Modal endpoint once and build the parser around the *observed* response, not
   assumptions. Record the shapes in `BUILD_LOG.md`.
5. **UXP, not CEP.** All Premiere integration targets UXP (PP 25.6+/2026). Do not write
   ExtendScript/CEP — it sunsets September 2026.
6. **Straight cuts only (v1).** No transitions, colour, audio mixing, or effects. The tool cuts
   and stitches; it never re-syncs A/V.
7. **Explainability:** every `EditDecision` carries a one-line `reason`.

## 3. Reused assets (hosted on Modal)

- **`clip`** — video understanding (Marlin-2B / Qwen3-VL). Used by `angle_scoring`. Endpoints:
  upload `POST /v1/videos`, then `POST /v1/videos/{id}/describe` / `/find` (async job
  envelopes), poll `GET /v1/jobs/{id}`. See the `clip` repo's `schemas.py` for response models —
  but **confirm against the live deploy**.
- **Transcriber** (Banglish/Whisper, WhisperX + diarization + LLM cleanup) — used by
  `transcription`. Produces timestamped, optionally speaker-labelled segments.
- Treat both as remote HTTP behind the provider protocols in `CONTRACTS.md`. The user will
  supply live URLs / credentials when Phase 1 starts.

## 4. Stack

- Python 3.11+, Pydantic v2 for contracts.
- `madmom` (beats/downbeats) + `librosa` (energy/sections); ffmpeg required. Pin versions —
  madmom is finicky with NumPy/Cython; verify in a clean env at `PPC-002`.
- MCP server: standard MCP Python server exposing the tools in `ARCHITECTURE.md §2.3`.
- UXP (Phase 2): `@adobe/premierepro` typed APIs, UXP Developer Tool v2.2+, PP 25.6+.
- Tests: `pytest`, with a golden-clip eval for cut accuracy / keep-rate.

## 5. Definition of done (per task)

- Code matches `CONTRACTS.md` shapes exactly.
- Unit tests pass; the relevant `ROADMAP.md` "done when" gate is demonstrably met.
- `BUILD_LOG.md` updated.
- No network calls in Phase 0; no CEP anywhere; no scope creep beyond straight cuts.

---

## 6. Kickoff prompt for Claude Code

Paste this into Claude Code, run from the repo root:

```
You are building the Premiere Pro Connector — a DJ multicam auto-editor driven by Claude.
This repo currently contains only specs: read AGENTS.md, PRD.md, ARCHITECTURE.md,
CONTRACTS.md, and ROADMAP.md in full before writing anything. Do not write code that
contradicts CONTRACTS.md or ARCHITECTURE.md — if you think it should change, stop and tell me.

Start Phase 0. Work one PPC-### task at a time in ROADMAP order, lowest first:

1. PPC-001 — implement engine/contracts.py from CONTRACTS.md (Pydantic v2), with a test that
   round-trips fake instances of every model.
2. PPC-002/003 — implement engine/audio_timing on madmom (beats/downbeats) + librosa (energy,
   sections, drops). Pin versions in requirements.txt and verify madmom installs cleanly first.
   I will provide a test track.
3. PPC-004 — provider protocols + FAKE transcriber and angle-scoring providers so the rest of
   the engine runs offline.
4. PPC-005 — fusion.py per ARCHITECTURE §4: candidate cuts from phrase/section boundaries,
   energy-scaled cut density, angle choice with hysteresis, semantic overrides from word cues.
5. PPC-006 — export/fcpxml.py: EditDecisionList → Premiere-importable multicam FCPXML + markers.
6. PPC-007 — cli.py tying it together on a project folder.
7. PPC-008 — a golden-clip eval for cut-on-beat accuracy and keep-rate.

After each task: verify its ROADMAP "done when" gate, run tests, commit, and append a
BUILD_LOG.md entry. Then ask me before moving to the next task. Stop at the end of Phase 0 —
do NOT touch Modal services or any Premiere/UXP code until I say Phase 1.

Honour the golden rules in AGENTS.md §2: contracts are law, timeline is float seconds absolute,
fakes before networks, straight cuts only, every decision carries a reason.
```
