# BUILD LOG — Premiere Pro Connector

Running record of work, findings, decisions, and gotchas. Newest entry on top. Any agent
joining mid-stream: read this first, then `AGENTS.md`.

Format per entry: date · `PPC-###` (if applicable) · what changed · what was learned / what's
still open.

---

## 2026-06-03 · `PPC-002` · beat grid (madmom) + librosa fallback

**Changed**
- `engine/audio_timing/` package: `beats.py` (madmom `RNNDownBeatProcessor` →
  `DBNDownBeatTrackingProcessor`, librosa fallback, and a pure reduction helper
  `beat_grid_from_downbeat_array`) + `__init__.py` exposing `detect_beat_grid`.
- `tests/test_audio_timing.py`: offline reduction/BPM tests (always run) + real-audio
  gate tests marked `@pytest.mark.audio` (skip if `media/test_track.wav` absent).
- `requirements.txt`: pinned the full audio stack. `pyproject.toml`: registered the
  `audio` marker.
- **35 tests pass** (26 contracts + 9 audio) in ~78 s.

**Test track:** "Biscits – Voodoo" downloaded via yt-dlp → `media/test_track.wav`
(PCM s16le, 48 kHz stereo, 334.87 s). Git-ignored.

**Gate (PPC-002: "Beats within ±1 frame of manual taps")** — met by proxy. On the real
track: BPM 127.66 (~128 expected ✓), 712 beats / 178 downbeats, inter-beat-interval
std 0.0066 s (≈⅕ of a 30 fps frame), and **≥95 % of inter-beat intervals within ±1
frame** of the median — the same 95 %/±1-frame bar PRD §8 sets. ⚠️ *Literal* manual-tap
comparison still needs user-tapped ground truth or a hand-labelled reference; the
frame-stability + cross-engine (madmom vs librosa) tempo agreement is the automatic
stand-in. Offer open: tap along / supply a reference if you want the literal check.

**madmom install (the finicky bit — verified in the clean venv):**
- **No working PyPI release for Python 3.11.** Built from git master, commit
  `27f032e8947204902c675e5e341a3faf5dc86dae` (reports as `madmom 0.17.dev0`).
- NumPy **1.26.4** is the stack anchor: newest NumPy that madmom builds against *and*
  that librosa/numba/scipy accept on 3.11. Cython pinned to **0.29.37** (madmom's `.pyx`
  use 0.29 idioms; Cython 3 not used). scipy 1.13.1.
- Windows build recipe (MSVC Build Tools 2026 present; not on PATH by default):
  1. `pip install numpy==1.26.4 scipy==1.13.1 cython==0.29.37 "wheel" "setuptools<81"`
  2. from a `vcvars64.bat`-initialised shell:
     `pip install --no-build-isolation git+https://github.com/CPJKU/madmom.git@27f032e…`
  Plain `pip install -r requirements.txt` will **not** replicate this (needs vcvars +
  `--no-build-isolation`); follow the two steps above on a fresh machine.
- Beats-per-bar defaulted to `(4,)` — DJ/EDM is 4/4; restricting the meter improves
  downbeat accuracy vs also allowing 3/4. RNN/DBN fps = 100 (madmom activation rate).
- Full madmom pass on the 5.5-min track ≈ 46 s (single-threaded). Fine for v1.

### Next up
- `PPC-003`: energy curve (librosa RMS/spectral flux) + section/drop detection, then the
  composing `analyze(audio_path) -> (BeatGrid, EnergyTimeline)`. Gate: drop detected
  within ±0.3 s. (Awaiting your go-ahead.)

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
