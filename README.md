# Premiere Pro Connector — DJ Multicam Auto-Editor

**Turn synced DJ-performance footage into a beat-cut multicam edit, driven by a prompt to Claude.**

You point the tool at several camera angles of a DJ set (already synced to a master
audio track) and ask, in plain language, for the edit you want — *"fast cuts through the
drop, hold on his face when he mouths the hook."* The tool analyses the music, the words,
and each camera angle, decides where to cut and which angle to show, and assembles a
multicam sequence inside Premiere Pro 2026.

> **Status:** **Phase 0 complete.** The engine (audio timing, fusion), the FCP7-XML
> round-trip importer/exporter, and a CLI all run on real footage — fully offline against
> fake providers (105 offline tests). Phase 1 (live Modal `clip`/transcriber + MCP server)
> and Phase 2 (UXP panel) are next. Start with [`AGENTS.md`](AGENTS.md); see
> [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) for the running record and
> [`ROADMAP.md`](ROADMAP.md) for what's done vs. pending.

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
5. **Lands in Premiere** — exports a **Final Cut Pro 7 XML** (`<xmeml>`) timeline that
   Premiere Pro 2026 imports natively (note: PP 2026 does *not* import `.fcpxml`), preserving
   the grade/crop, overlays, and fade; later it will drive an open project live via a UXP panel.

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

## Setup

**Requirements:** Python **3.11+**, **ffmpeg** on `PATH`, and a **C compiler** (madmom
builds from source — MSVC Build Tools on Windows; `gcc`/`clang` on Linux/macOS).

```bash
git clone https://github.com/Shadwaan/premiere-pro-connector
cd premiere-pro-connector
python -m venv .venv
# activate:  Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
```

> ⚠️ **madmom is the one non-trivial dependency.** There is no working PyPI wheel for
> Python 3.11, so `requirements.txt` pins it from a git commit, and it must be built
> against the pinned NumPy/Cython **without pip build isolation**. A plain
> `pip install -r requirements.txt` will *not* work on its own — do the staged install:

```bash
# 1) build anchors first (must exist before madmom builds)
pip install "numpy==1.26.4" "scipy==1.13.1" "cython==0.29.37" "wheel" "setuptools<81"

# 2) build madmom against them, with build isolation OFF + a compiler on PATH.
#    Windows: run this from a "x64 Native Tools Command Prompt for VS" (vcvars64) so cl.exe is found.
pip install --no-build-isolation \
  "git+https://github.com/CPJKU/madmom.git@27f032e8947204902c675e5e341a3faf5dc86dae"

# 3) the rest (librosa, soundfile, pydantic, pytest); madmom is already satisfied.
pip install -r requirements.txt
```

**Verify the install:**

```bash
pytest -m "not audio"          # 105 fast, offline tests (no media needed)
```

The `audio`-marked tests additionally need a local `media/test_track.wav` (a beat-driven
track); they're skipped automatically when it's absent. The `.venv/` and `media/` folders
are git-ignored and never committed. Full madmom build notes are in
[`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) (PPC-002).

## Usage (Phase 0 CLI)

Input is a **synced multicam sequence exported from Premiere as FCP7 XML** (`File ▸ Export ▸
Final Cut Pro XML`): camera angles on video tracks (each angle may span multiple files),
overlays (PNG/graphics) on their own tracks, and the master music on an audio track.

```bash
python -m engine.cli "path/to/synced.xml" \
  --brief "fast cuts on the drop, hold on the hook" \
  --out  "path/to/autocut.xml"
```

This analyses the master audio, decides downbeat-snapped cuts between angles (Phase 0 uses
deterministic **fake** angle-scoring/transcription — no network), and writes a Premiere-
importable FCP7 XML: camera cuts on two tracks, overlays passed through on top, grade/crop/
distort and the closing fade preserved. Import it back into Premiere via `File ▸ Import`.

## Docs

- [`PRD.md`](PRD.md) — what we're building and why, with acceptance criteria.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system shape, components, phasing.
- [`CONTRACTS.md`](CONTRACTS.md) — the typed data shapes that cross every boundary.
- [`ROADMAP.md`](ROADMAP.md) — phased execution plan.
- [`AGENTS.md`](AGENTS.md) — build brief + the kickoff prompt for Claude Code.
- [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) — running record of work and findings.
