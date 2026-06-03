# Premiere Pro Connector — DJ Multicam Auto-Editor

**Turn synced DJ-performance footage into a beat-cut multicam edit, driven by a prompt to Claude.**

You point the tool at several camera angles of a DJ set (already synced to a master
audio track) and ask, in plain language, for the edit you want — *"fast cuts through the
drop, hold on his face when he mouths the hook."* The tool analyses the music, the words,
and each camera angle, decides where to cut and which angle to show, and assembles a
multicam sequence inside Premiere Pro 2026.

> **Status:** spec + docs only. No code yet. This repo is the brief handed to a coding
> agent (Claude Code) to build from. Start with [`AGENTS.md`](AGENTS.md).

---

## What it does

1. **Listens to the music** — beat grid, BPM, downbeats, energy curve, build/drop points
   (madmom / librosa). This decides *when* to cut.
2. **Reads the words** — the DJ's speech and the vocal lyrics he mimics, timestamped, via
   the existing Banglish/Whisper transcriber (hosted on Modal). This flags *semantic*
   moments worth favouring (a hook, a callout to camera).
3. **Watches each angle** — per-camera "how interesting is this shot right now" scoring via
   the existing `clip` video-understanding platform (hosted on Modal). This decides *which*
   angle to show.
4. **Fuses + cuts** — snaps cuts to musical phrase/beat boundaries, picks the best angle per
   section, holds through builds, cuts hard on drops, and emits an edit decision list.
5. **Lands in Premiere** — exports an FCPXML multicam sequence (v1), and later drives an
   open project live through a UXP panel.

## Why this exists

There is **no official Premiere Pro connector** for Claude — the third-party options are all
CEP/ExtendScript panels, a platform Adobe is sunsetting in **September 2026**. This project
builds the missing piece on **UXP**, Premiere's current extensibility platform, with the
editing intelligence as a reusable engine behind it.

## Reuses what already exists

| Asset | Role here | Where it lives |
|---|---|---|
| `clip` (Marlin-2B / Qwen3-VL video understanding) | Per-angle visual interest scoring | **Modal** (hosted) |
| Banglish/Whisper transcriber | DJ speech + lyric timing | **Modal** (hosted) |
| *(new)* audio timing analyzer | Beats, energy, drops | This repo |
| *(new)* fusion + FCPXML export | Cut decisions → Premiere | This repo |
| *(new)* MCP server + UXP panel | The Claude-driven connector | This repo |

## First target

A studio DJ set shot on a balcony: **no crowd**, but real **energy shifts** in the track, the
DJ **talks**, and there are **vocal lyrics he mimics**. Manual A/V sync (you align the angles
in Premiere); the tool only cuts and stitches.

## Docs

- [`PRD.md`](PRD.md) — what we're building and why, with acceptance criteria.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system shape, components, phasing.
- [`CONTRACTS.md`](CONTRACTS.md) — the typed data shapes that cross every boundary.
- [`ROADMAP.md`](ROADMAP.md) — phased execution plan.
- [`AGENTS.md`](AGENTS.md) — build brief + the kickoff prompt for Claude Code.
- [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) — running record of work and findings.
