"""Phase-0 CLI (PPC-007): synced FCP7 XML -> beat-cut multicam FCP7 XML.

Pipeline:
  parse koshtoset.xml -> ImportedSequence (multi-file angles + availability)
  -> analyze the master .wav (beats / energy / sections / drops), shifted onto the
     sequence timeline -> FakeAngleScorer + FakeTranscriber (Phase 0, offline)
  -> propose_cuts(brief, availability) -> source-resolved FCP7 XML (each cut mapped to the
     correct underlying file + source frame, sync offsets + DSLR filter preserved).

Run:  python -m engine.cli "D:/All Video Content/Koshto/koshtoset.xml" [--brief "..."] [--out out.xml]
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from engine.audio_timing import analyze
from engine.contracts import Angle, BeatGrid, EnergyTimeline, Project, Section
from engine.export.fcp7xml import write_fcp7xml_sourced
from engine.fcp7_import import choose_master_audio, parse_fcp7xml
from engine.fusion import propose_cuts
from engine.providers import FakeAngleScorer, FakeTranscriber

DEFAULT_BRIEF = "fast cuts on the drop, hold on the hook"


def _mmss(t: float) -> str:
    m = int(t // 60)
    return f"{m:d}:{t - 60 * m:05.2f}"


def _shift_analysis(
    bg: BeatGrid, el: EnergyTimeline, offset_s: float, duration_s: float
) -> tuple[BeatGrid, EnergyTimeline]:
    """Shift wav-relative analysis onto the sequence timeline (the master clip sits at a small
    offset) and clamp to the edit span [0, duration_s]."""
    def within(t: float) -> bool:
        return 0.0 - 1e-6 <= t <= duration_s + 1e-6

    beats = [b + offset_s for b in bg.beats if within(b + offset_s)]
    downbeats = [d + offset_s for d in bg.downbeats if within(d + offset_s)]
    shifted_bg = BeatGrid(bpm=bg.bpm, beats=beats, downbeats=downbeats)

    n_pad = max(0, round(offset_s / el.hop_s))
    energy = [0.0] * n_pad + list(el.energy)

    sections: list[Section] = []
    for s in el.sections:
        a, b = s.start + offset_s, s.end + offset_s
        if b <= 0.0 or a >= duration_s:
            continue
        sections.append(Section(start=max(0.0, a), end=min(duration_s, b), kind=s.kind, energy=s.energy))
    if sections:
        sections[0] = sections[0].model_copy(update={"start": 0.0})
        sections[-1] = sections[-1].model_copy(update={"end": duration_s})
    else:
        sections = [Section(start=0.0, end=duration_s, kind="other", energy=0.5)]

    drops = [d + offset_s for d in el.drops if 0.0 < d + offset_s < duration_s]
    shifted_el = EnergyTimeline(hop_s=el.hop_s, energy=energy, sections=sections, drops=drops)
    return shifted_bg, shifted_el


def run(
    xmeml_path: str,
    *,
    brief: str = DEFAULT_BRIEF,
    out_path: str | None = None,
    seed: int = 1,
    score_hop_s: float = 1.0,
) -> dict:
    """Run the full Phase-0 pipeline; returns a summary dict (and writes the output XML)."""
    imported = parse_fcp7xml(xmeml_path)
    master = choose_master_audio(imported)
    fps = imported.fps

    offset_s = (master.tl_start_f - master.src_in_f) / fps
    duration_s = master.tl_end_f / fps  # edit spans the music: [0, music end]

    bg_raw, el_raw = analyze(master.file_path)
    bg, el = _shift_analysis(bg_raw, el_raw, offset_s, duration_s)

    project = Project(
        project_id=Path(xmeml_path).stem,
        master_audio_path=master.file_path,
        angles=[
            Angle(angle_id=a.angle_id, media_path=a.segments[0].file_path, label=a.label)
            for a in imported.angles
        ],
        fps=fps,
        duration_s=duration_s,
    )
    availability = {a.angle_id: a.availability_s(fps) for a in imported.angles}
    words = FakeTranscriber(duration_s=duration_s).transcribe(master.file_path)
    scores = [
        FakeAngleScorer(duration_s=duration_s, seed=seed + i).score(a, hop_s=score_hop_s)
        for i, a in enumerate(project.angles)
    ]

    edl = propose_cuts(project, bg, el, words, scores, brief=brief, availability=availability)

    angle_tracks = {a.angle_id: a for a in imported.angles}
    if out_path is None:
        out_path = str(Path(xmeml_path).with_name(Path(xmeml_path).stem + "_autocut.xml"))
    _, n_unresolved = write_fcp7xml_sourced(
        edl, imported, angle_tracks, out_path, duration_s=duration_s, energy=el
    )

    return _summarize(edl, el, imported, master, offset_s, duration_s, out_path, n_unresolved)


def _summarize(edl, el, imported, master, offset_s, duration_s, out_path, n_unresolved) -> dict:
    d = edl.decisions
    switches = sum(1 for i in range(1, len(d)) if d[i].angle_id != d[i - 1].angle_id)
    by_angle = Counter(x.angle_id for x in d)
    by_section: Counter = Counter()
    for x in d:
        for s in el.sections:
            if s.start - 1e-6 <= x.t_start < s.end - 1e-6:
                by_section[s.kind] += 1
                break
    lens = [x.t_end - x.t_start for x in d]
    return {
        "fps": imported.fps,
        "master_audio": master.file_path,
        "offset_s": offset_s,
        "duration_s": duration_s,
        "n_decisions": len(d),
        "switches": switches,
        "by_angle": dict(by_angle),
        "by_section": dict(by_section),
        "shot_len": (min(lens), sum(lens) / len(lens), max(lens)) if lens else (0, 0, 0),
        "n_unresolved": n_unresolved,
        "out_path": out_path,
        "n_sections": len(el.sections),
        "n_drops": len(el.drops),
        "params": edl.params.model_dump(),
    }


def _print_summary(s: dict) -> None:
    print(f"master audio : {s['master_audio']}")
    print(f"fps          : {s['fps']:.4f}   timeline offset {s['offset_s']:.3f}s")
    print(f"edit span    : 0:00 -> {_mmss(s['duration_s'])}  ({s['duration_s']:.1f}s)")
    print(f"sections     : {s['n_sections']}   hard drops: {s['n_drops']}")
    print(f"brief params : {s['params']}")
    print(f"DECISIONS    : {s['n_decisions']}   switches: {s['switches']}")
    print(f"by angle     : {s['by_angle']}")
    print(f"by section   : {s['by_section']}")
    mn, mean, mx = s["shot_len"]
    print(f"shot length  : min {mn:.2f}s  mean {mean:.2f}s  max {mx:.2f}s")
    if s["n_unresolved"]:
        print(f"WARNING      : {s['n_unresolved']} decision(s) had no footage (unresolved)")
    print(f"OUTPUT       : {s['out_path']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DJ multicam auto-editor (Phase 0, FCP7 XML).")
    ap.add_argument("xmeml", help="path to the synced Premiere FCP7 .xml")
    ap.add_argument("--brief", default=DEFAULT_BRIEF, help="natural-language edit brief")
    ap.add_argument("--out", default=None, help="output .xml path")
    ap.add_argument("--seed", type=int, default=1, help="fake angle-scorer seed")
    args = ap.parse_args(argv)
    summary = run(args.xmeml, brief=args.brief, out_path=args.out, seed=args.seed)
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
