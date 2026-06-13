"""Reusable auto-cut pipeline (PPC-007 refactor) — the single entrypoint both the CLI and the
local web UI call, so their output is byte-identical for the same inputs.

`run_autocut` runs exactly the Phase-0 flow the CLI used to inline:
  parse_fcp7xml -> choose_master_audio -> analyze + _shift_analysis (onto the sequence
  timeline) -> Fake transcriber/angle-scorer (offline) -> propose_cuts(availability) ->
  write_fcp7xml_sourced (multi-file resolve, overlays, fade, masterclipid/ppro, downbeat snap).

It is a thin orchestration layer: no engine logic is reimplemented here, and with default
``AutocutParams`` the call into ``propose_cuts`` is identical to the old CLI's. No network,
no LLM — only local madmom/librosa analysis + deterministic fakes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from engine.audio_timing import analyze
from engine.contracts import Angle, BeatGrid, EnergyTimeline, Project, Section
from engine.export.fcp7xml import write_fcp7xml_sourced
from engine.fcp7_import import choose_master_audio, parse_fcp7xml
from engine.fusion import map_brief_to_params, propose_cuts
from engine.providers import FakeAngleScorer, FakeTranscriber

DEFAULT_BRIEF = "fast cuts on the drop, hold on the hook"


class MasterAudioNotFound(FileNotFoundError):
    """Raised when the master-audio path (from the XML or the override) isn't on disk."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"master audio not found on this machine: {path}")


@dataclass
class AutocutParams:
    """Tunable knobs. Every override defaults to ``None`` -> the brief/engine default, so the
    CLI (which sets only ``brief``/``seed``) reproduces the previous behavior exactly."""

    brief: str | None = DEFAULT_BRIEF
    snap: str | None = None  # None -> derived from brief (baseline "downbeat"); else beat/downbeat/phrase
    min_shot_len_s: float | None = None  # None -> brief/engine default
    max_shot_len_s: float | None = None  # None -> engine HOLD_MAX_S
    phrase_downbeats: int | None = None  # None -> fuse default (2)
    seed: int = 1
    score_hop_s: float = 1.0
    master_audio_path: str | None = None  # override when the XML's path doesn't resolve


def _shift_analysis(
    bg: BeatGrid, el: EnergyTimeline, offset_s: float, duration_s: float
) -> tuple[BeatGrid, EnergyTimeline]:
    """Shift wav-relative analysis onto the sequence timeline (the master clip sits at a small
    offset) and clamp to the edit span [0, duration_s]. (Unchanged from the original CLI.)"""

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


def run_autocut(input_xml: str, out_xml: str, *, params: AutocutParams | None = None) -> dict:
    """Run the full auto-cut pipeline and write ``out_xml``; return a summary dict.

    Raises ``MasterAudioNotFound`` if the master audio can't be located on disk.
    """
    p = params or AutocutParams()
    imported = parse_fcp7xml(input_xml)
    master = choose_master_audio(imported)
    master_path = p.master_audio_path or master.file_path
    if not Path(master_path).exists():
        raise MasterAudioNotFound(master_path)

    fps = imported.fps
    offset_s = (master.tl_start_f - master.src_in_f) / fps
    duration_s = master.tl_end_f / fps  # edit spans the music: [0, music end]

    bg_raw, el_raw = analyze(master_path)
    bg, el = _shift_analysis(bg_raw, el_raw, offset_s, duration_s)

    project = Project(
        project_id=Path(input_xml).stem,
        master_audio_path=master_path,
        angles=[
            Angle(angle_id=a.angle_id, media_path=a.segments[0].file_path, label=a.label)
            for a in imported.angles
        ],
        fps=fps,
        duration_s=duration_s,
    )
    availability = {a.angle_id: a.availability_s(fps) for a in imported.angles}
    words = FakeTranscriber(duration_s=duration_s).transcribe(master_path)
    scores = [
        FakeAngleScorer(duration_s=duration_s, seed=p.seed + i).score(a, hop_s=p.score_hop_s)
        for i, a in enumerate(project.angles)
    ]

    # Brief -> EditParams, then apply explicit overrides (None leaves the brief/engine value).
    edit_params = map_brief_to_params(p.brief)
    if p.min_shot_len_s is not None:
        edit_params = edit_params.model_copy(update={"min_shot_len_s": p.min_shot_len_s})

    edl = propose_cuts(
        project, bg, el, words, scores,
        params=edit_params,
        switch_quant=p.snap,  # None -> derives from edit_params.snap (brief baseline "downbeat")
        phrase_downbeats=2 if p.phrase_downbeats is None else p.phrase_downbeats,
        hold_max_s=p.max_shot_len_s,  # None -> engine HOLD_MAX_S
        availability=availability,
    )

    angle_tracks = {a.angle_id: a for a in imported.angles}
    _, n_unresolved = write_fcp7xml_sourced(
        edl, imported, angle_tracks, out_xml, duration_s=duration_s, energy=el
    )
    return _summarize(edl, el, imported, master_path, offset_s, duration_s, out_xml, n_unresolved)


def _summarize(edl, el, imported, master_path, offset_s, duration_s, out_path, n_unresolved) -> dict:
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
        "master_audio": master_path,
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
