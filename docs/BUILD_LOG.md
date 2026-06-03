# BUILD LOG — Premiere Pro Connector

Running record of work, findings, decisions, and gotchas. Newest entry on top. Any agent
joining mid-stream: read this first, then `AGENTS.md`.

Format per entry: date · `PPC-###` (if applicable) · what changed · what was learned / what's
still open.

---

## 2026-06-03 · `PPC-006` · FCPXML exporter

**Changed**
- `engine/export/fcpxml.py`: `edit_decision_list_to_fcpxml(...)` + `write_fcpxml(...)`, plus
  frame-snapping helpers (`frame_duration`, `frames_at`, `rational_time`).
- `engine/export/__init__.py`. `tests/test_fcpxml.py`: 11 tests (frame-snapping incl. NTSC,
  well-formedness, one-asset-per-angle + file URIs, decision→clip 1:1, gapless frame-accurate
  mapping, reason `<note>`, marker placement/labels/time, no-energy→no-markers, bad angle
  raises). **70 offline tests pass.**

**Surface form chosen (PRD §9 Q4): single sequence, angle clips cut onto one video track**
— NOT a true `<mc-clip>`/`<multicam>` container. Reason: FCPXML multicam import into Premiere
is known-fragile; a cut sequence gives the identical visual result (angle switches = cuts),
imports far more reliably, and is fully refinable. Live angle re-picking is the Phase-2 UXP
panel's job, so nothing is lost by deferring the multicam container.

**Decisions / details**
- **Frame-snapping lives only here** (timeline invariant honored): float seconds →
  `frames*num/den s` using `project.fps`. Integer fps → `1/fps`; NTSC (23.976/29.97/59.94)
  → 1001-based frameDuration. Clip durations computed as `end_frame − start_frame` so
  adjacent clips stay **gapless and frame-accurate** after snapping.
- **Video-only** by design: assets declare `hasVideo` only. The user keeps/places the master
  audio in Premiere (angles are pre-synced to it) — matches "straight cuts, no A/V re-sync"
  and keeps the import clean. `include master audio` can be added later if wanted.
- **Markers**: one per section boundary (labelled by kind, e.g. `intro`, `drop section`,
  `breakdown`) + one per hard onset-drop (`DROP 0:29.60`). Attached to the asset-clip
  containing each (frame-snapped) time; source==timeline so marker source-frame == absolute
  frame. Markers need the optional `energy: EnergyTimeline` arg (a contract type — export
  still depends only on contracts).
- Each clip carries its fusion `reason` as a `<note>` (Premiere shows it as clip Notes).
- FCPXML `version="1.9"` (broadly Premiere-compatible; confirm against PP 2026 on import).

**EDL fallback**: NOT built (per instruction — stub only if FCPXML import fights us). CMX3600
remains the documented fallback.

**Sample artifact**: `media/voodoo_sample.fcpxml` (git-ignored) from the real "Voodoo" EDL,
2 placeholder angles (GoPro `D:/footage/voodoo/gopro.mp4`, DSLR `dslr.mov`), fps 30, brief
"fast cuts on the drop, hold on the hook": **135 clips, 22 markers, 29 KB, well-formed**;
duration 10046/30s = 334.87 s; drop markers at 888/30s (29.60 s) etc. — frame-exact.

**Premiere import caveats to verify on first real import (PP 2026):**
- Placeholder media paths will come in **offline** → relink to the real GoPro/DSLR files.
- Confirm `version="1.9"` is accepted; if not, try a newer FCPXML version.
- Confirm clip `<note>` and `<marker>` import as expected; markers may land as clip markers
  rather than sequence markers (FCPXML has no sequence-level marker).
- If 1.9 / structure is rejected, fall back to EDL (then build `export/edl.py`).

**Gate (PPC-006: "file imports into PP 2026 as a multicam sequence")** — file generated &
well-formed; **actual Premiere import is the user's validation step (deferred to PPC-007 /
first real import).**

**SURFACE DECISION (recorded per instruction):** validate the connector via *one* FCPXML
import, then prioritize the **Phase-2 live UXP panel** as the real workflow. Real acceptance
set = a **30-min, 2-angle (GoPro + DSLR) DJ set** synced in Premiere by the user.

### Next up
- `PPC-007`: `cli.py` — run the whole pipeline (analyze → score(fake) → transcribe(fake) →
  propose_cuts → export) on a project folder → one FCPXML. **Pausing for user sanity-check of
  the sample FCPXML + import dry-run first.**

---

## 2026-06-03 · `PPC-005` · fusion (deterministic edit-decision logic)

**Changed**
- `engine/fusion.py`: `fuse(...)`, `propose_cuts(...)`, `map_brief_to_params(...)` per
  ARCHITECTURE §4 + the FUSION DECISION (PPC-003 entry).
- `tests/test_fusion.py`: 11 tests — invariants, hysteresis, drop-aggression,
  drop-section-vs-non-drop, semantic override, max-consecutive cap, brief mapping, and an
  **end-to-end run on the real fake providers** (offline). **59 offline tests pass.**

**How it works**
- *Candidate cuts*: grid per `EditParams.snap` (beat / downbeat / phrase, `phrase_downbeats`
  configurable, default 4) ∪ section boundaries (forced cuts, snapped to grid). Section
  transitions are the structural cuts.
- *Density*: target shot length = `HOLD_MAX(8s) → HOLD_MIN(max(min_shot_len,1s))` scaled by
  `intensity = 0.4·cut_density + 0.6·energy(t)`, `+0.25·drop_aggression` in a `"drop"`
  section, `+0.45·drop_aggression` within [−1s,+8s] of a hard onset-drop. Full section map
  drives density; drops are the confidence-ranked overlay (nothing discarded).
- *Angle choice*: per segment, mean interest (interpolated from the score timeline) +
  hysteresis (reward staying = `switch_penalty`) + staleness cap (`max_consecutive_s` forces
  a switch). Deterministic argmax (tie-break by angle id).
- *Semantic override*: a segment overlapping an `is_hook`/`to_camera` cue adds
  `face_bias_on_vocals · mean_face` → pulls to the best-face angle.
- *Invariants enforced* by `_validate()` before returning: `t_start[0]==0`,
  `t_end[-1]==duration`, contiguous, sequential indices, real angle ids, every reason set.

**Gate (PPC-005: "emits a valid EditDecisionList, all invariants hold")** — ✅ met
(`test_end_to_end_on_fakes_offline_is_valid` + `_validate`).
**Gate (PPC-004: "fusion runs end-to-end on fakes, no network")** — ✅ now closed by the
same end-to-end test (synthetic beat grid/energy + FakeTranscriber + FakeAngleScorer →
valid EDL, zero I/O).

**Sample on the real track** ("Voodoo", brief "fast cuts on the drop, hold on the hook",
3 fake angles): 135 decisions, 53 switches, shot length 1.87–6.34 s (mean 2.48).
Cuts-by-kind: intro 8, drop 76, breakdown 21, other 24, outro 6 — drops cut at 1 bar
(1.87 s), intro holds 3–6 s. Reason strings are ASCII (`hook->B`) for Windows-console
safety. Shown to user for sanity check before PPC-006.

### Next up
- `PPC-006`: `export/fcpxml.py` — `EditDecisionList` → Premiere-importable multicam FCPXML +
  markers. **Pausing for user sanity-check of the sample EDL first.**

---

## 2026-06-03 · `PPC-004` · provider protocols + fake providers

**Changed**
- `engine/providers/base.py`: `TranscriberProvider` / `AngleScoringProvider` Protocols
  (`@runtime_checkable`), exact CONTRACTS.md shapes. Engine depends on these, never on
  Modal/HTTP — real adapters slot behind them in Phase 1.
- `engine/providers/fakes.py`: `FakeTranscriber` + `FakeAngleScorer` — deterministic,
  **no network, no media files**. Seeds derive from a CRC32 of the angle id (not Python's
  salted `hash()`), so different angles get different-but-reproducible interest curves and
  fusion has a real choice to make. Generic data — nothing tuned to any track.
- `engine/providers/__init__.py`: re-exports protocols + fakes.
- `tests/test_providers.py`: protocol conformance, determinism, unit-range fields,
  angle distinctness, arg validation, and an offline data-flow test that assembles exactly
  the inputs fusion will consume. **11 new tests; 48 offline tests pass (57 incl. audio).**

**Design notes**
- The protocol `score(angle, hop_s)` carries no duration, so `FakeAngleScorer` takes
  `duration_s` at construction (the CLI/test knows the master timeline length). The real
  Phase-1 adapter will probe the media instead.
- `FakeTranscriber` places generic cues (intro to-camera line, two repeated lyric hooks,
  closing to-camera line) at fractions of duration, or accepts injected cues. Gives
  fusion's semantic-override path (`is_hook` / `to_camera`) something to act on.

**Gate (PPC-004: "Fusion runs end-to-end on fakes, no network")** — provider half done:
the fakes produce every input fusion needs with zero I/O (verified by
`test_provider_layer_produces_fusion_inputs_offline`). The *literal* end-to-end run
through fusion is closed at PPC-005, when `fusion.py` exists.

### Next up
- `PPC-005`: `fusion.py` per ARCHITECTURE §4 and the FUSION DECISION recorded in the
  PPC-003 entry above. **Pausing for user go-ahead before starting (per instruction).**

---

## 2026-06-03 · `PPC-003` · energy curve + section/drop detection

**Changed**
- `engine/audio_timing/energy.py`: energy curve (librosa) + pure
  `detect_sections_from_energy` / `detect_drops_from_energy` + audio I/O
  `compute_energy_timeline`. Pure logic split from I/O, same pattern as `beats.py`.
- `engine/audio_timing/analyze.py`: composing `analyze(audio_path) -> (BeatGrid,
  EnergyTimeline)` (the CONTRACTS.md entrypoint). `__init__.py` re-exports it.
- `tests/test_energy.py`: offline synthetic section/drop tests + `@audio` real-track
  tests (curve normalized, sections tile gap-free, drops non-empty, analyze returns both).
- **Full suite: 46 tests pass** (contracts 26, beats 9, energy 11).

**Energy curve design (the substantive decision).** First cut used full-band RMS(dB) —
on the real track every section came out 0.63–0.78 (flat) and only one drop was found.
Root cause: in EDM overall loudness barely dips in a breakdown (vocals/synths stay loud);
what drops out is the **kick/bass**. Rebuilt the curve as a weighted blend of
**low-band power (≤250 Hz, weight 0.55)** + full-band loudness (0.30) + spectral flux
(0.15), each log-compressed and normalized. Result: full 0..1 dynamic range and a
coherent intro→drop→breakdown→drop→…→outro map.

**Two bugs the synthetic tests caught (before any real-audio run):**
1. Section levels used strict `>` against the `hi` quantile, which equals the plateau
   value → nothing classified as high → zero "drop" sections. Fixed to `>=`.
2. Drop detection required the pre-dip to be ≤ an absolute `lo` quantile; a short dip
   smooths above `lo`, so the first drop was missed. Replaced with: large *rise* to a
   high post-level (the rise itself marks the dip). More robust.

**Detect-and-report on `media/test_track.wav` ("Voodoo"):**
- Drops: **0:29.60 (29.60 s), 1:30.10 (90.10 s), 4:03.30 (243.30 s)** — the three main
  breakdown→drop transitions.
- Sections (abbrev): intro 0:00–0:31 → drop 0:31–0:56 → breakdown 0:56–1:31 → drop
  1:31–1:56 → … → breakdown 3:31–4:02 → drop 4:02–4:56 → outro 5:13–end.

**Gate (PPC-003: "drop detected within ±0.3 s") — ✅ MET (by user confirmation,
2026-06-03).** The user verified by ear that the 3 hard onset-drops (0:29.6, 1:30.1,
4:03.3) are correct; they also align with section-map boundaries. This is *not* a
tapped-ground-truth measurement — no reference taps exist. **Final, objective validation
of drop timing is deferred to the first real edit (PPC-006/007)**, where cuts landing on
the drops can be judged against the footage. Recorded here rather than overclaiming an
automated check. `rise_min` left at 0.30 (highest precision; lowering it regressed the
confirmed 4:03 onset to 4:01 and added re-trigger false positives at 1:45/2:45 — see
sweep in conversation).

**Recall note (intentional):** the soft drops at ~2:31 and ~3:00 rise out of a
mid-energy passage, not a breakdown, so they are *not* in the hard-onset `drops` list.
They ARE captured as "drop"-kind sections in the section map. Nothing is discarded.

**FUSION DECISION (for PPC-005), agreed with user:**
- **Cut density** tracks the *full* ~11-section energy map + beat phrasing (downbeat /
  phrase grid) — not just the drops. Longer holds in low-energy sections, faster cuts in
  high-energy ones.
- **Aggression-boost zones** = the 4 `"drop"`-kind **sections** (≈0:31, 1:31, 2:31, 4:01)
  — cuts get faster across these whole regions.
- **Strongest boost** = the 3 **hard onset-drops** (0:29.6, 1:30.1, 4:03.3) — the
  highest-confidence subset, get the most aggressive cutting right at the onset.
- **Nothing in the section map is discarded** — every section informs cut density;
  drops are a confidence-ranked overlay on top, not a replacement.

### Next up
- `PPC-004`: provider protocols (`TranscriberProvider`, `AngleScoringProvider`) + **fake**
  implementations so fusion (PPC-005) runs fully offline, no network.

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
