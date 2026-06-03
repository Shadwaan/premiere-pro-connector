# ARCHITECTURE — Premiere Pro Connector

**Last updated:** 2026-06-03. Design constraints for any agent building this. If your plan
contradicts this doc or [`CONTRACTS.md`](CONTRACTS.md), STOP and flag it.

---

## 1. One-paragraph shape

A local **engine** (Python) ingests synced angles + master audio, runs three analyzers —
two of which are **remote calls to existing Modal services** (`clip`, transcriber) and one
**new local module** (audio timing) — then a **fusion** step produces an `EditDecisionList`
(see CONTRACTS). An **exporter** turns that into an FCPXML multicam sequence. An **MCP server**
wraps the engine as tools so **Claude** can drive it from chat. Later, a **UXP panel** applies
the decision list to an open Premiere Pro 2026 project live.

```
                         ┌─────────── analyzers ───────────┐
 synced angles  ──┐      │  audio_timing   (LOCAL, new)     │
 + master audio   ├────► │  transcriber    (MODAL, exists)  │ ──► fusion ──► EditDecisionList
                  │      │  angle_scoring  (MODAL, clip)    │                     │
 NL brief ────────┘      └──────────────────────────────────┘                     ▼
                                                                    ┌──────────────┴───────────────┐
                                                                    │ exporter → FCPXML + markers   │ (Phase 1)
                                                                    │ uxp_bridge → live project     │ (Phase 2)
                                                                    └───────────────────────────────┘
        Claude  ⇄  MCP server (wraps engine tools)  ⇄  user, in chat
```

---

## 2. Components

### 2.1 Engine (`engine/`, Python) — new
The brain. Pure functions over the typed contracts; no UI, no MCP, no Premiere knowledge.
Sub-modules:

- `audio_timing` — beat grid, downbeats, BPM, energy curve, section/drop detection. **New code.**
- `angle_scoring` — adapter that calls the hosted `clip` service and reduces its
  `/describe`/`/find` output into a per-angle interest timeline.
- `transcription` — adapter that calls the hosted transcriber and maps its segments into
  timestamped speech/lyric cues.
- `fusion` — deterministic decision logic that combines the three timelines + NL parameters
  into an `EditDecisionList`. Accepts optional **angle-availability** windows so an angle is
  never chosen where it has no footage.
- `fcp7_import` + `timeline_model` — read the user's synced **FCP7 XML** into an internal
  multi-file-angle timeline (see §3). *Not* contract types: they map `angle_id` + a timeline
  range back to the correct underlying file + source frame; the engine still works on the
  contract `Angle`/`EditDecisionList`.
- `export` — `EditDecisionList` → **FCP7 XML** (`<xmeml>`, primary — Premiere 2026 does not
  import `.fcpxml`) / FCPXML (secondary) / EDL (fallback). Frame-snapping happens only here.
- `cli` — Phase-0 entrypoint: FCP7 XML in → analyze → fakes → fusion → FCP7 XML out.

### 2.2 Provider adapters (`engine/providers/`) — new, pattern borrowed from multimodal-transcriber
`clip` and the transcriber live on **Modal**. They are reached over HTTP behind a swappable
adapter protocol — engine code depends on the **adapter interface**, never on Modal specifics.
Mirror the `app.providers` protocol pattern from the multimodal-transcriber repo. This keeps
the engine testable with fakes and lets the hosted endpoints change without touching fusion.

### 2.3 MCP server (`mcp/`) — new
Exposes the engine as MCP tools so Claude (in this chat app / Claude Desktop) can call them.
This is **the connector** and the primary UI. Tools (see CONTRACTS for I/O shapes):

| Tool | Purpose |
|---|---|
| `register_project` | Point at a folder of synced angles + master audio; returns a `project_id`. |
| `analyze_audio` | Run `audio_timing`; returns `BeatGrid` + `EnergyTimeline`. |
| `transcribe` | Run hosted transcriber; returns timestamped `WordCue[]`. |
| `score_angles` | Run hosted `clip` per angle; returns `AngleScoreTimeline[]`. |
| `propose_cuts` | Run fusion with NL/params; returns `EditDecisionList`. |
| `export_sequence` | `EditDecisionList` → FCPXML file path. |
| `apply_to_premiere` | *(Phase 2)* push decisions to the open project via the UXP bridge. |

Claude orchestrates these in response to a prompt. A typical turn:
`register_project → analyze_audio → score_angles → transcribe → propose_cuts → export_sequence`.

### 2.4 UXP panel + bridge (`uxp/`) — new, Phase 2
A Premiere Pro **UXP** plugin (target PP 25.6+/2026; `@adobe/premierepro` typed APIs). It
builds the multicam source sequence, places the cuts/markers, and lets Claude apply/adjust
edits live. UXP — **not** CEP/ExtendScript (sunset Sept 2026). The MCP server talks to the
panel over a local WebSocket (panel runs inside Premiere; MCP server runs as a normal process).

---

## 3. Data flow & the timeline invariant

**All timestamps are float seconds, absolute from the start of the master audio timeline.**
Every analyzer emits times in this frame; fusion and export depend on it. Because the user
pre-syncs the angles, every angle shares this clock — that is what makes fusion trivial. Keep
this invariant everywhere (same rule the multimodal-transcriber repo uses).

Frame-snapping to the project FPS happens **only** at export time, never inside the engine.

### 3.1 Multi-file angles, availability, and the FCP7 XML round-trip (added PPC-007)

Real synced footage is messier than "one file per angle":

- **An angle is a TRACK, not a file.** In the first real set each camera is split across
  multiple media files (GoPro = `GX010465` + `GX020465`; DSLR = `MVI_4017` + `MVI_4018`).
  `timeline_model.AngleTrack` models an angle as an ordered list of source-file segments,
  each with its own timeline range and **source in-point** (the sync trim). When fusion picks
  an angle for a cut, the exporter `resolve()`s that timeline range against the track,
  **splitting at file boundaries** so a cut that crosses `GX010465`→`GX020465` becomes two
  `clipitem`s with correct source frames. Per-clip **filters are preserved** (e.g. the DSLR
  aspect Distort).
- **Availability windows.** A track need not cover the whole timeline (the DSLR ends at
  ~24:30 while the GoPro and music continue). `AngleTrack.availability_s()` yields the covered
  intervals; fusion takes these as an optional input, forces cuts at the edges, and never
  selects an angle outside its windows (so the DSLR-less tail is solo GoPro).
- **Sync offset.** The master-audio clip may sit at a small timeline offset (here +5 frames).
  The CLI shifts the wav-relative analysis onto the sequence timeline so cuts land where the
  music actually is.
- **Round-trip surface = FCP7 XML.** Input and output are both `<xmeml>` (Premiere-native).
  These richer shapes live in `timeline_model` / `fcp7_import`, *outside* `CONTRACTS.md` — the
  contract `EditDecisionList` (angle_id per cut) remains the one handoff between fusion and
  export; the source map only resolves angle_id → file/frame at export.

---

## 4. Fusion logic (v1, deterministic)

Inputs: `BeatGrid`, `EnergyTimeline`, `WordCue[]`, `AngleScoreTimeline[]`, `EditParams`.

Sketch:
1. **Candidate cut points** = phrase boundaries (every 4/8/16 downbeats, configurable), plus
   section transitions (build→drop etc.). Cut density scales with energy: longer holds in
   intros/breakdowns, faster cuts approaching/at the drop.
2. **Angle choice** per segment = the angle with the highest mean interest score over that
   segment, with hysteresis (a switching penalty) to avoid jitter and a max-consecutive-segment
   cap to avoid staleness.
3. **Semantic overrides** = when a `WordCue` marks a lyric hook or direct-to-camera talk,
   bias toward the angle whose score timeline indicates the DJ's face is best framed.
4. **Output** = ordered `EditDecision[]`, each `{ t_start, t_end, angle_id, reason }`.

`EditParams` is what the NL brief maps to: `cut_density`, `drop_aggression`,
`face_bias_on_vocals`, `min_shot_len`, `switch_penalty`, etc. v1 maps brief→params with a small
rules layer; an optional Claude pass can set params or resolve ambiguous windows (PRD §9 Q2).

---

## 5. The new piece: audio timing

- **Beats / downbeats / tempo:** `madmom` (`DBNDownBeatTrackingProcessor`) is the accuracy
  pick for offline analysis; `librosa.beat` is the easy fallback.
- **Energy / sections / drops:** `librosa` RMS + spectral flux to build an energy curve;
  detect builds (rising energy) and drops (sharp rise after a dip). Optionally label sections
  later with **CLAP** (audio↔text) — *not* required for v1.
- **Install gotcha:** madmom needs Cython and is picky about NumPy versions; pin in
  `requirements.txt` and verify in a clean env early. If it fights the rest of the stack,
  isolate it (own venv or a Modal function — PRD §9 Q1).

---

## 6. Hosted services (Modal)

`clip` and the transcriber are already deployed on Modal. The engine treats them as remote
HTTP APIs:

- **clip** — `POST /v1/videos` (upload) → `POST /v1/videos/{id}/describe` and `/find`
  (async jobs) → poll `GET /v1/jobs/{id}`. `angle_scoring` reduces describe/find output into a
  numeric interest timeline per angle. Confirm exact request/response against the live deploy
  before wiring (it returns job envelopes; see clip repo `schemas.py`).
- **transcriber** — produces timestamped, optionally speaker-labelled segments. `transcription`
  maps these to `WordCue[]`.

**Probe before building parsers.** Call each endpoint once against the live Modal deploy and
build the adapter around the *observed* response shape, not assumptions.

---

## 7. Phasing (see ROADMAP for detail)

- **Phase 0 — Engine + FCPXML, CLI only.** No MCP, no Premiere plugin. Prove the cuts feel
  right on the first shoot. Fastest path to real edited footage.
- **Phase 1 — MCP connector.** Wrap the engine as MCP tools; drive it from Claude chat. This
  is the connector the user wants; the FCPXML export remains the hand-off into Premiere.
- **Phase 2 — UXP panel.** Live apply/adjust inside an open Premiere 2026 project.

The engine is identical across all three phases; only the surface changes.

---

## 8. Repo layout (proposed)

```
premiere-pro-connector/
  engine/
    contracts.py          # Pydantic models (CONTRACTS.md is law)
    audio_timing/         # madmom/librosa — NEW
    providers/            # clip + transcriber adapters (Modal) + fakes
    timeline_model.py     # multi-file angle + availability model (NOT a contract) — PPC-007
    fcp7_import.py        # parse synced FCP7 XML -> ImportedSequence — PPC-007
    angle_scoring.py
    transcription.py
    fusion.py             # + optional angle-availability
    export/               # fcp7xml.py (primary), fcpxml.py (secondary), edl.py (fallback)
    cli.py                # Phase 0 entrypoint (FCP7 XML in -> FCP7 XML out)
  mcp/                    # Phase 1 MCP server
  uxp/                    # Phase 2 Premiere UXP panel
  tests/                  # unit + a golden-clip eval
  requirements.txt
  PRD.md ARCHITECTURE.md CONTRACTS.md ROADMAP.md AGENTS.md
  docs/BUILD_LOG.md
```
