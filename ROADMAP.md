# ROADMAP — Premiere Pro Connector

Phased execution plan. The **engine is identical across all phases**; each phase only adds a
new surface around it. Build strictly in order — don't start a phase until the prior one's
"done when" is met. Task IDs `PPC-###` are referenced from [`AGENTS.md`](AGENTS.md) and the
build log.

---

## Phase 0 — Engine + FCPXML (CLI only)

**Goal:** prove the cuts feel right on the first balcony shoot, with zero MCP/Premiere plumbing.

| ID | Task | Done when |
|---|---|---|
| PPC-001 | Freeze `contracts.py` from CONTRACTS.md (Pydantic v2) | Models import; fakes round-trip in a test |
| PPC-002 | `audio_timing`: beat grid + downbeats (madmom, librosa fallback) | Beats on a test track within ±1 frame of manual taps |
| PPC-003 | `audio_timing`: energy curve + section/drop detection | Drop in test track detected within ±0.3 s |
| PPC-004 | Provider protocols + **fakes** for transcriber & angle scoring | Fusion runs end-to-end on fakes, no network |
| PPC-005 | `fusion`: candidate cuts, angle choice w/ hysteresis, semantic overrides | Emits a valid `EditDecisionList` (all invariants hold) |
| PPC-006 | `export/fcpxml.py`: `EditDecisionList` → FCPXML multicam + markers | File imports into PP 2026 as a multicam sequence |
| PPC-007 | `cli.py`: run the whole pipeline on a project folder | One command → FCPXML on the first real shoot |
| PPC-008 | Golden-clip eval: cut-on-beat accuracy + keep-rate check | Metrics printed; ≥95% cuts within ±1 frame |

**Phase 0 done when:** the first shoot produces an imported multicam edit a human would mostly
keep (PRD §6 acceptance).

---

## Phase 1 — Live `clip` + transcriber + MCP connector

**Goal:** swap fakes for the real hosted services and let Claude drive the engine from chat.

| ID | Task | Done when |
|---|---|---|
| PPC-101 | Probe live Modal endpoints; document observed shapes in BUILD_LOG | Real request/response captured for clip + transcriber |
| PPC-102 | Real `transcription` adapter (Modal transcriber → `WordCue[]`) | Matches fake's interface; integration test passes |
| PPC-103 | Real `angle_scoring` adapter (clip describe/find → timeline, sampled) | Per-angle timeline returned; cost/latency noted |
| PPC-104 | MCP server exposing the 6 core tools (CONTRACTS/ARCHITECTURE §2.3) | Tools callable from Claude; full run from a prompt |
| PPC-105 | NL brief → `EditParams` mapping (rules; optional Claude pass) | "fast cuts on the drop" changes the cut list sensibly |

**Phase 1 done when:** a single natural-language prompt to Claude yields an exported FCPXML for
a real project, using the live hosted services.

---

## Phase 2 — UXP panel (live in Premiere)

**Goal:** apply and adjust the edit inside an open Premiere Pro 2026 project — the full connector.

| ID | Task | Done when |
|---|---|---|
| PPC-201 | UXP plugin scaffold (PP 25.6+, `@adobe/premierepro`, UXP Dev Tool) | Panel loads in Premiere |
| PPC-202 | Build multicam source sequence from the project's angles | Synced multicam clip created in the open project |
| PPC-203 | Apply `EditDecisionList` (cuts + angle switches + markers) | Decision list rendered onto the timeline |
| PPC-204 | MCP ↔ panel WebSocket bridge; `apply_to_premiere` tool | Claude applies/adjusts edits live from chat |
| PPC-205 | Iterative edit ("make the bridge cut slower") round-trips | Re-proposed cuts update the live timeline |

**Phase 2 done when:** the user prompts Claude and watches the multicam edit assemble in their
open Premiere project, then refines it conversationally.

---

## Explicitly later (not scheduled)

- CLAP-based section labelling for richer fusion cues.
- Transitions, colour, audio ducking — anything beyond straight cuts.
- Packaging for other users; any SaaS/billing.
- Pushing `audio_timing` to Modal if local install proves painful.
