# BUILD LOG — Premiere Pro Connector

Running record of work, findings, decisions, and gotchas. Newest entry on top. Any agent
joining mid-stream: read this first, then `AGENTS.md`.

Format per entry: date · `PPC-###` (if applicable) · what changed · what was learned / what's
still open.

---

## 2026-06-03 · `PPC-001` · contracts frozen + round-trip test

**Changed**
- Scaffolded the repo per ARCHITECTURE §8: `engine/`, `tests/`, `requirements.txt`,
  `pyproject.toml`, `.gitignore`, plus a dedicated `.venv` (Python 3.11.1).
- `engine/contracts.py` — faithful Pydantic v2 translation of every model in
  CONTRACTS.md: `Angle`, `Project`, `BeatGrid`, `Section`, `EnergyTimeline`, `WordCue`,
  `AngleScoreSample`, `AngleScoreTimeline`, `EditParams`, `EditDecision`,
  `EditDecisionList`. `CONTRACT_VERSION = "0.1"`.
- `tests/test_contracts.py` — builds a non-default fake of every model and round-trips
  it through dict (`model_dump`→`model_validate`) and JSON; plus a completeness guard
  that fails if any contract model lacks a fake. **26 tests pass.**

**Gate (PPC-001: "Models import; fakes round-trip in a test")** — met.

**Decisions / what was learned**
- All contract models inherit a private `_Contract` base with
  `model_config = ConfigDict(extra="forbid")`. Rationale: "contracts are law" — unknown
  fields should surface drift loudly, not be silently dropped. Adapters map raw Modal
  responses *into* these models (they don't parse directly), so strictness is safe.
- **No numeric-range or cross-field invariant validators added yet.** The 0..1 ranges and
  the `EditDecisionList` coverage/contiguity invariants are documented in CONTRACTS.md as
  comments and are the *fusion* step's responsibility (PPC-005). Enforcing them at model
  construction would over-extend the contract for PPC-001; revisit when fusion lands.
- **Provider protocols deferred to PPC-004.** CONTRACTS.md lists `TranscriberProvider` /
  `AngleScoringProvider`, but they are `Protocol`s (not round-trippable) and ROADMAP
  assigns "provider protocols + fakes" to PPC-004. PPC-001 is the data shapes only.
- Env: `pydantic==2.12.5`, `pytest==8.4.2` pinned. Audio deps intentionally *not* added
  yet — they go in at PPC-002 only after madmom is verified in this clean venv.
- `pyproject.toml` sets `pythonpath = ["."]` so `import engine` works without an install.

### Next up
- `PPC-002`: verify madmom installs cleanly in the venv, pin versions, then implement
  beat grid + downbeats. **Awaiting the user's test track.**

---

## 2026-06-03 · scoping & docs · (no code yet)

- Project created. This repo is **spec + docs only**; scaffolding will be built by Claude Code
  from `AGENTS.md`.
- **Decisions locked:**
  - Surface = **MCP connector** (Claude chat is the UI). Phase 0 ships a CLI first to validate
    edit quality; the connector wraps the same engine in Phase 1.
  - Premiere integration = **UXP** (PP 2026), not CEP/ExtendScript (sunset Sept 2026).
  - `clip` and the transcriber are **hosted on Modal** → reached via provider adapters; engine
    never depends on Modal specifics. Fakes first, real adapters in Phase 1.
  - New code = the **audio timing analyzer** (madmom/librosa) + fusion + FCPXML export.
  - Timeline invariant = **float seconds, absolute**; frame-snap only at export.
- **Open questions** tracked in `PRD.md §9` (audio-analyzer location, rules-vs-LLM fusion,
  angle-scoring cost/sampling, FCPXML multicam fidelity, angle count).
- **First target shoot:** balcony studio set, no crowd, energy shifts, DJ talks + mimics
  lyrics → all three signals (music / words / visuals) contribute.

### Next up
- `PPC-001`: freeze `contracts.py`. Then `PPC-002/003` audio timing on a real test track.
- Before Phase 1 adapters: **probe the live Modal endpoints** and record observed shapes here.
