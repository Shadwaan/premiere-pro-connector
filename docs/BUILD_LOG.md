# BUILD LOG — Premiere Pro Connector

Running record of work, findings, decisions, and gotchas. Newest entry on top. Any agent
joining mid-stream: read this first, then `AGENTS.md`.

Format per entry: date · `PPC-###` (if applicable) · what changed · what was learned / what's
still open.

---

## 2026-06-04 · `PPC-007` (fusion fix) · switches land on downbeats, not late beats

**Symptom.** Angle switches felt 1–2 beats late — landing on beat 2/3 of the bar instead of
the "1".

**Diagnosis (data, on the koshtonewset run).**
1. madmom DOES give downbeats (703 downbeats / 2809 beats), but fusion wasn't using them:
   `EditParams.snap` defaulted to `"beat"`, so `_grid` returned the plain beat grid. All 248
   switches landed exactly on a beat (mean |dt nearest beat| = 0.000 s) but only **23.4 % on
   a downbeat**; the rest on beat #2 (+0.49 s) or beat #3 (+0.94 s). Mean |dt downbeat| 0.652 s.
2. The +5-frame / 0.167 s master offset is correct-signed and applied once (`_shift_analysis`);
   switches sat dead-on beats, so it wasn't the cause.
3. The walk used `_first_ge` (round FORWARD to next grid point) → consistently late.

**Fix (fusion only; no CONTRACTS/shape change).**
- New `switch_quant` param on `fuse`/`propose_cuts` (`"downbeat"` default, also `"beat"` /
  `"phrase"`), selecting the cut/switch grid — backward-compatible. `propose_cuts` derives it
  from the resolved `params.snap` when not passed.
- `map_brief_to_params` baseline `snap` flipped to `"downbeat"` (brief-layer default; the
  `EditParams` contract default stays `"beat"`, so CONTRACTS.md is untouched).
- New `_nearest_grid` snaps the shot end to the NEAREST grid point (≥ min-shot, forward of
  last), replacing the forward `_first_ge` bias.
- `phrase` mode = every `phrase_downbeats` downbeats (default 2 = every 2 bars / 8 beats) for
  an optional coarser switch cadence.

**Before / after (cached analysis, koshtonewset):**
| | switches | mean &#124;dt downbeat&#124; | on-downbeat |
|---|---|---|---|
| BEFORE (beat grid, forward) | 254 | 0.762 s | 16.5 % |
| AFTER (downbeat, nearest — default) | 242 | **0.000 s** | **100 %** |

**Re-exported `koshtonewset_autocut.xml`** (snap=downbeat): 630 decisions, 242 switches.
Output audit: **242/242 switches on a downbeat (max offset 0 frames)**; the one non-downbeat
clip start is the GoPro file-boundary split at 45316 (same-angle, exempt). FIX 1/FIX 2 still
hold (2 tracks, 244 clipitems, 0 missing masterclipid/ppro, union gapless [0, 51731]).

**Tests:** `test_switches_land_on_downbeats_by_default`, `test_beat_quant_can_land_off_downbeats`,
`test_switch_quant_phrase_uses_coarser_grid`. **101 offline tests pass.**

### Next up
- `PPC-008`: golden-clip eval (cut-on-beat accuracy + keep-rate) — last Phase-0 task.

---

## 2026-06-04 · `PPC-007` (export polish) · coalesce cuts, per-angle tracks, filter audit

Two export-only fixes (no CONTRACTS/fusion change) + a grade/framing-preservation audit on a
newly graded source `KoshtoNewSet.xml` → `koshtonewset_autocut.xml`.

**FIX 1 — coalesce redundant same-angle cuts.** `edit_decision_list_to_fcp7xml_sourced` now
merges consecutive decisions with the same `angle_id` into one continuous range *before*
resolving (`_coalesce_decisions`), then still splits at real source-file boundaries via
`AngleTrack.resolve`. Every GoPro↔DSLR switch is preserved (a switch starts a new run); only
back-to-back razor cuts on identical footage disappear. **Clip count 697 → 251.** (695
decisions → 249 runs + 2 file-boundary splits = 251.)

**FIX 2 — one `<video><track>` per angle.** Deterministic order by `angle_id`
(alphabetical → **DSLR = V1, GoPro = V2**). Each track carries only its angle's clips at their
timeline positions (implicit gaps elsewhere). Verified: **no overlap within a track**, and the
**union of both tracks gaplessly covers [0, 51731]**. Audio re-emitted verbatim as before.

**FILTER AUDIT (the main ask).**
- (a) `KoshtoNewSet.xml` per-source-clip filters Premiere actually wrote:
  - GoPro `GX010465`/`GX020465`: **Basic Motion** (scale/rotation/center/crop = the reframe) +
    **Lumetri** (the grade; `<effectid>Lumetri</effectid><effecttype>filter</effecttype>`).
  - DSLR `MVI_4017`/`MVI_4018`: Basic Motion + Lumetri + **Distort** (aspect).
  - Audio: none.
  - **Lumetri SURVIVED Premiere's FCP7-XML export** — it is NOT dropped (format is fine). The
    reframe is carried as **Basic Motion** (not Distort). No standalone opacity filter was
    present (none applied).
- (b) Our code never dropped any filter type: `fcp7_import` captures `clip.findall("filter")`
  (ALL `<filter>`s) and the exporter re-emits each verbatim — generic, not Distort-specific.
- (c) In `koshtonewset_autocut.xml`: **0 clips whose filter set differs from their source
  clip.** All 126 GoPro clips carry `[Basic Motion, Lumetri]`; all 125 DSLR clips carry
  `[Basic Motion, Lumetri, Distort]`. Grade + reframe + aspect all preserved on every cut.

**Also intact:** masterclipid/pproTicks on all 251 clips (0 missing); `n_unresolved = 0`
(implied by gapless full coverage); duration 51731.

**Tests:** added `test_fix1_coalesces_adjacent_same_angle`,
`test_fix2_one_track_per_angle_dslr_v1_gopro_v2`,
`test_fix2_tracks_no_overlap_and_union_gapless`, `test_real_switches_preserved`.
**98 offline tests pass.**

### Next up
- `PPC-008`: golden-clip eval (cut-on-beat accuracy + keep-rate) — last Phase-0 task.

---

## 2026-06-03 · `PPC-007` (fix) · sequence dropped on import — missing `<masterclipid>`

**Symptom.** Premiere Pro 2026 imported the MEDIA (files landed in the bin) but the
sequence/timeline never appeared; re-import threw "File Import Failure" with an empty
message.

**Diagnosis (data, not guesses).** Ran all five suspect checks against
`koshtoset_autocut.xml` — **all passed**: in/out ≤ file `<duration>` (0/697 violations),
rate uniform `(30, TRUE)`, file ids define-once with no dangling refs, video track gapless
with no overlaps, audio block in/out valid. Then diffed our video `<clipitem>` against the
Premiere-authored clips in `koshtoset.xml`. Our video clips were **missing**
`masterclipid, pproTicksIn, pproTicksOut, alphatype, pixelaspectratio, anamorphic`. The
**re-emitted audio clip (verbatim) HAD `masterclipid`; our generated video clips did not.**
That asymmetry is the bug: without `<masterclipid>` Premiere can import the file (so media
reaches the bin) but cannot instantiate the clip in the sequence → the whole sequence is
dropped with an empty error.

**Fix (`engine/export/fcp7xml.py`, sourced path).** Emit on every video clipitem, in
Premiere's field order: `<masterclipid>` = `masterclip-<file_id>` (one master clip per
source file — all instances of a file share it), `<pproTicksIn/Out>` (=
`frame × 254_016_000_000 / fps`, verified byte-exact vs the source: in 1034 →
8763839884800), and `<alphatype>/<pixelaspectratio>/<anamorphic>`. No CONTRACTS change.

**Verified.** Regression test `test_clipitems_have_masterclipid_and_ppro_ticks` added;
**94 offline tests pass.** Re-exported `koshtoset_autocut.xml`: 697 video clipitems, **0
missing masterclipid / pproTicks**, 4 master clips (file-1..4), audio masterclip-5 intact,
well-formed, duration 51731. Awaiting the user's re-import to confirm the sequence loads.

---

## 2026-06-03 · `PPC-007` · CLI + FCP7 XML round-trip on the real Koshto set

**Changed**
- `engine/timeline_model.py` (NEW, dataclasses — *not* contracts): `SourceSegment` /
  `AngleTrack` / `ResolvedClip` / `AudioRef` / `ImportedSequence`. Models a real **angle as a
  track of multiple source files**, each with its own source in-point + filters; `resolve()`
  splits a timeline range at file boundaries; `availability_s()` gives covered intervals.
- `engine/fcp7_import.py` (NEW): parse a synced FCP7 `<xmeml>` → `ImportedSequence`
  (fps/duration, multi-file video angles, audio block verbatim, master-audio picker).
- `engine/fusion.py`: optional `availability` arg — forces cuts at availability edges and
  never picks an angle outside its windows (backward-compatible; default None).
- `engine/export/fcp7xml.py`: `edit_decision_list_to_fcp7xml_sourced(...)` — resolves each
  cut to the correct file + source frames, splits multi-file angles, preserves the DSLR
  Distort filter (verbatim `<filter>`), re-emits the master audio block verbatim, frame-snaps.
- `engine/cli.py` (NEW): full Phase-0 pipeline + a `_shift_analysis` that moves the
  wav-relative beats/energy onto the sequence timeline (the master clip's +5-frame offset).
- Tests: `test_timeline_model.py` (6), `test_fcp7_import.py` (3, +real-guarded),
  `test_fcp7_sourced.py` (4), fusion availability (1). **93 offline tests pass.**

**Docs:** ARCHITECTURE §2.1/§3.1/§8 + PRD §4.6/§9 Q4 updated for the FCP7-XML round-trip,
multi-file angle model, and availability windows. CONTRACTS.md untouched — the multi-file
model is engine-internal; the contract `EditDecisionList` (angle_id per cut) is still the only
fusion↔export handoff; the source map only resolves angle_id → file/frame at export.

**Real run — `koshtoset.xml` → `koshtoset_autocut.xml`** (brief "fast cuts on the drop, hold
on the hook", ~5 min madmom on the 28-min master):
- fps 29.97; edit span 0:00 → **28:46** (music end); offset 0.167 s; 56 sections, 10 drops.
- **695 decisions, 248 switches**; GoPro 395 / DSLR 300; shot length 1.62–6.40 s (mean 2.48).
- Output verified: well-formed, **697 clipitems** (2 extra = multi-file splits), gapless,
  covers [0, 51731]. **0 DSLR clips after 24:30** (availability honored — solo GoPro tail);
  GoPro `GX010465`→`GX020465` handoff exactly at frame 45316 with source-in reset; **301/301
  DSLR clips keep the Distort filter, 0 GoPro filters**; audio re-emitted; 66 markers;
  source frames preserved (e.g. MVI_4018 start 43049 → in 21596). **n_unresolved = 0.**

**Gate (PPC-007: "one command → FCPXML on the first real shoot")** — met as **one command →
FCP7 XML** on the real set. **Import into Premiere Pro 2026 is the user's validation step.**

### Next up
- `PPC-008`: golden-clip eval (cut-on-beat accuracy + keep-rate). **Pausing for the user's
  import of `koshtoset_autocut.xml`.**

---

## 2026-06-03 · `PPC-006` (pivot) · FCP7 XML exporter — Premiere rejected .fcpxml

**Why the pivot.** User tested the FCPXML import: **Premiere Pro 2026 does not recognize
`.fcpxml`** — in File ▸ Import with "All Supported Media" the file doesn't even appear in
the list. Premiere's native interchange is **Final Cut Pro 7 XML** (`<xmeml>`, `.xml`), so
the exporter now targets that.

**Changed**
- `engine/export/fcp7xml.py`: `edit_decision_list_to_fcp7xml(...)` + `write_fcp7xml(...)`.
  Same cut sequence + markers as the FCPXML version, serialized as FCP7 XML:
  `<xmeml version="4"><sequence>` with `<rate><timebase>/<ntsc>`, a single `<video><track>`
  of `<clipitem>`s (`start/end` timeline frames, `in/out` source frames — equal, since
  angles are pre-synced), `<file>` defined once per angle then referenced by `id` with
  `<pathurl>file://localhost/…`, clip `<comment>` = fusion reason, and **true
  sequence-level `<marker>`s** (an FCP7-XML advantage over FCPXML clip markers).
- `engine/export/__init__.py`: **FCP7 XML is now the default** (`write_sequence` /
  `edit_decision_list_to_sequence` alias it). `fcpxml.py` kept as secondary/reference.
- `tests/test_fcp7xml.py`: 9 tests mirroring the FCPXML ones (timebase/ntsc mapping,
  well-formedness, 1:1 clip mapping, gapless frame-accurate start/end/in/out, file
  define-once-then-reference, reason comment, sequence-level markers + frames, no-energy →
  no-markers, bad angle raises). **79 offline tests pass.**

**Frame model.** Times are whole frames under `<rate>`: integer fps → `(timebase=fps,
ntsc=FALSE)`; NTSC 23.976/29.97/59.94 → `(24/30/60, ntsc=TRUE)`. Frame snapping reuses
`fcpxml.frames_at` (the single float→frame function). Clip end−start in frames keeps clips
gapless after snapping.

**Sample artifact**: `media/voodoo_sample.xml` (git-ignored), real "Voodoo" EDL, 2 placeholder
angles (GoPro `D:/footage/voodoo/gopro.mp4`, DSLR `dslr.mov`), fps 30, brief "fast cuts on
the drop, hold on the hook": **135 clipitems, 22 sequence markers, 72 KB, well-formed**;
duration 10046 frames (334.87 s); DROP markers at frame 888 (29.60 s) / 2703 (90.10 s) etc.

**Gate (PPC-006: "file imports into PP 2026 as a multicam/sequence")** — FCP7 `.xml`
generated & well-formed; **actual Premiere import is the user's next validation step.**
EDL (CMX3600) remains the last-resort fallback if FCP7 XML also fights us (not built).

### Next up (unchanged)
- `PPC-007`: `cli.py` — one command on a project folder → `.xml`. **Pausing for the user's
  FCP7-XML import sanity-check first.**

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
