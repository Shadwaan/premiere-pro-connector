# PRD — Premiere Pro Connector (DJ Multicam Auto-Editor)

**Status:** draft for build · **Owner:** Shadwaan · **Last updated:** 2026-06-03

> Companion docs: [`ARCHITECTURE.md`](ARCHITECTURE.md) for system design,
> [`CONTRACTS.md`](CONTRACTS.md) for the typed shapes, [`ROADMAP.md`](ROADMAP.md) for the
> phased plan, [`AGENTS.md`](AGENTS.md) for the coding-agent brief.

---

## 1. Vision

A tool that converts **synced multi-angle DJ-performance footage** into a **beat-cut
multicam edit**, controlled conversationally through Claude. The editing intelligence lives
in a reusable engine; Claude is the steering wheel (via an MCP connector); Premiere Pro 2026
is where the cut lands.

The long-term framing: the first real **Claude ↔ Premiere Pro connector**, with a DJ-video
editor as its first concrete application.

---

## 2. Users

| Phase | User | Use case |
|---|---|---|
| Now | Shadwaan personally | Edit own DJ-performance shoots: feed synced angles, get a beat-cut multicam edit to refine. |
| Near-term | Other DJs / creators | Same workflow, packaged so a non-developer can run it. |
| Long-term | Editors generally | A general Claude-driven Premiere connector; DJ editing is the flagship recipe. |

---

## 3. The problem

Editing a multi-angle DJ set by hand is slow and mechanical: you scrub each angle, find the
beat, and cut between cameras over and over for the length of a track. The decisions are
*rule-shaped* — cut on the beat, switch to the more interesting angle, hold through the
build, hit hard on the drop — which is exactly the kind of thing software can propose.

But the tooling gap is real:

- **No official Premiere connector for Claude.** Existing third-party AI panels are
  CEP/ExtendScript, which Adobe is **sunsetting in September 2026** — building new on it is a
  dead end.
- **No tool fuses music structure with multi-angle footage.** Beat-detection tools don't know
  about your cameras; multicam tools don't know about the music.
- For DJ sets specifically, the *audio* is the script. Off-the-shelf auto-editors key off
  speech or scene changes, not musical phrasing.

---

## 4. Core requirements

In priority order, the product must:

1. **Analyse the master audio** into a beat grid (beats, downbeats, BPM) and an energy/section
   timeline that marks builds, drops, and breakdowns.
2. **Ingest N synced camera angles** that share one timeline (sync is done by the user in
   Premiere; the tool assumes frame/sample alignment and does not re-sync).
3. **Score each angle over time** for visual interest using the hosted `clip` platform.
4. **Transcribe the audio** (DJ speech + mimicked vocal lyrics), timestamped, using the hosted
   transcriber, and surface those as semantic edit cues.
5. **Produce an Edit Decision List** — an ordered set of cuts, each with a timestamp (snapped
   to a beat/phrase) and a chosen angle — from a deterministic fusion of the three signals,
   steerable by natural-language instructions.
6. **Export a Premiere-importable multicam sequence** (FCPXML + markers) as the v1 deliverable.
7. **Be driven from Claude** via an MCP connector: the user prompts, Claude calls tools, the
   sequence is produced.
8. **(Phase 2) Apply edits to an open Premiere project live** via a UXP panel.

---

## 5. What the user provides vs. what the tool does

| User provides | Tool does |
|---|---|
| Synced angles + master audio (aligned in Premiere or as a folder of aligned clips) | Everything downstream: analyse, score, decide cuts, assemble |
| A natural-language brief ("fast cuts on the drop, hold on the hook") | Translates the brief into fusion parameters and a cut list |
| Final taste / manual refinement in Premiere | Produces a strong rough cut, not a locked final |

The tool **never** re-syncs audio/video and **never** moves money or touches anything outside
the project. It cuts and stitches.

---

## 6. First use case (acceptance scenario)

A balcony studio DJ set, 1 track, 2–3 synced angles, **no crowd**.

- The track has clear **energy shifts** (intro → build → drop → breakdown).
- The DJ **talks** at points (addresses camera) and **mimics vocal lyrics**.
- Expected behaviour: cuts land on the beat; the edit holds a wider/atmosphere shot through
  builds and cuts faster around the drop; when the DJ mouths a recognisable lyric or talks to
  camera, the edit favours the angle that best shows his face.

**Acceptance:** an imported FCPXML opens in Premiere Pro 2026 as a multicam sequence whose
cuts fall on detected beats (±1 frame) and whose angle choices are explainable from the
emitted decision list. A human editor would keep most cuts and only nudge a minority.

---

## 7. Non-goals (v1)

- **Audio/video sync.** User does it; tool assumes aligned input.
- **Colour, audio mixing, effects, titles, transitions** beyond straight cuts.
- **Real-time / live performance editing.**
- **Crowd-reaction-driven editing** (no crowd in the first shoot; visual scoring focuses on
  the DJ, motion, framing, and lighting).
- **Generating footage** or upscaling.
- **Multi-tenant SaaS / billing.**

---

## 8. Success metrics

- **Cut accuracy:** ≥95% of emitted cuts fall within ±1 frame of a detected beat.
- **Keep rate:** on the first shoot, a human keeps ≥60% of proposed cuts unchanged.
- **Time saved:** a rough multicam that would take ~1–2 hrs by hand is produced in minutes
  (plus hosted-inference time).
- **Explainability:** every cut in the decision list carries a one-line reason.

---

## 9. Open questions (resolve as we build)

1. **Audio analyzer location** — run madmom/librosa locally in the engine, or push it to a
   Modal function alongside clip/transcriber? (Leaning local for v1; madmom install is
   finicky — see ARCHITECTURE §5.)
2. **Fusion: rules vs LLM.** v1 is deterministic rules with NL-tunable parameters. Does Claude
   itself pick final angles for ambiguous windows, or only set parameters? (Leaning
   rules-first, with an optional Claude pass for taste.)
3. **Angle-scoring cost.** Scoring every angle across a full track on `clip` may be slow/pricey.
   Do we sample (score on a coarse grid, interpolate) or score densely? (Leaning sampled.)
4. **FCPXML multicam fidelity.** Premiere's FCPXML multicam import is fragile; confirm the
   exact element shape against PP 2026 on the first export. EDL is the fallback.
5. **Min/target angle count** for v1 (2 vs 3+).
