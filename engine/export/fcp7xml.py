"""FCP7 XML exporter (PPC-006, pivot) — ``EditDecisionList`` -> Premiere-native ``.xml``.

Premiere Pro 2026 does **not** recognize ``.fcpxml`` (it doesn't even list it in Import),
so the primary exporter targets the legacy **Final Cut Pro 7 XML** interchange format
(``<xmeml>``) that Premiere natively imports. Same cut sequence + markers as ``fcpxml.py``,
different serialization.

Form: a single video track of ``<clipitem>`` cuts (angle switch = cut). All times are whole
**frames** under ``<rate><timebase>/<ntsc>``; this module is the only place float seconds are
frame-snapped (timeline invariant). Markers are true **sequence-level** ``<marker>`` elements
(an advantage of FCP7 XML over FCPXML clip markers).

Depends only on contract types (CONTRACTS.md is law).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from engine.contracts import EditDecisionList, EnergyTimeline, Project
from engine.export.fcpxml import frames_at  # shared float->frame snapping (contract-only)
from engine.timeline_model import AngleTrack, ImportedSequence

XMEML_VERSION = "4"  # the version Premiere itself reads/writes

# Fractional NTSC rates -> their integer FCP7 timebase (ntsc flag = TRUE).
_NTSC_BASES = (24, 30, 50, 60)

# Premiere's internal time unit: 254,016,000,000 ticks per second (fps-independent).
_PPRO_TICKS_PER_SECOND = 254_016_000_000


def _ppro_ticks(frame: int, fps: float) -> int:
    return round(frame * _PPRO_TICKS_PER_SECOND / fps)


def timebase_ntsc(fps: float) -> tuple[int, bool]:
    """Map fps to FCP7 ``(timebase, ntsc)``. e.g. 29.97 -> (30, True); 30 -> (30, False)."""
    for base in _NTSC_BASES:
        if abs(fps - base * 1000.0 / 1001.0) < 0.01:
            return base, True
    return int(round(fps)), False


def _basename(media_path: str) -> str:
    return str(media_path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _pathurl(media_path: str) -> str:
    """FCP7-style ``file://localhost/...`` URL for an absolute path (Windows or POSIX)."""
    p = str(media_path).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", p):  # Windows drive
        return "file://localhost/" + quote(p, safe="/:")
    if p.startswith("/"):
        return "file://localhost" + quote(p, safe="/:")
    return "file://localhost/" + quote(p, safe="/:")


def _mmss(t: float) -> str:
    m = int(t // 60)
    return f"{m:d}:{t - 60 * m:05.2f}"


def _rate(parent: ET.Element, timebase: int, ntsc: bool) -> None:
    r = ET.SubElement(parent, "rate")
    ET.SubElement(r, "timebase").text = str(timebase)
    ET.SubElement(r, "ntsc").text = "TRUE" if ntsc else "FALSE"


def _section_label(kind: str) -> str:
    return "drop section" if kind == "drop" else kind


def _markers(energy: EnergyTimeline | None) -> list[tuple[float, str]]:
    if energy is None:
        return []
    marks = [(s.start, _section_label(s.kind)) for s in energy.sections]
    marks += [(d, f"DROP {_mmss(d)}") for d in energy.drops]
    marks.sort(key=lambda m: m[0])
    return marks


def edit_decision_list_to_fcp7xml(
    edl: EditDecisionList,
    project: Project,
    *,
    energy: EnergyTimeline | None = None,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Render an ``EditDecisionList`` to an FCP7 XML (``xmeml``) document string."""
    fps = float(project.fps)
    timebase, ntsc = timebase_ntsc(fps)
    total_frames = frames_at(project.duration_s, fps)

    xmeml = ET.Element("xmeml", version=XMEML_VERSION)
    sequence = ET.SubElement(xmeml, "sequence", id=f"seq-{project.project_id}")
    ET.SubElement(sequence, "name").text = project.project_id
    ET.SubElement(sequence, "duration").text = str(total_frames)
    _rate(sequence, timebase, ntsc)

    tc = ET.SubElement(sequence, "timecode")
    _rate(tc, timebase, ntsc)
    ET.SubElement(tc, "string").text = "00:00:00:00"
    ET.SubElement(tc, "frame").text = "0"
    ET.SubElement(tc, "displayformat").text = "NDF"

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    vformat = ET.SubElement(video, "format")
    schar = ET.SubElement(vformat, "samplecharacteristics")
    _rate(schar, timebase, ntsc)
    ET.SubElement(schar, "width").text = str(width)
    ET.SubElement(schar, "height").text = str(height)
    track = ET.SubElement(video, "track")

    real_angles = {a.angle_id: a for a in project.angles}
    file_defined: set[str] = set()  # FCP7: define <file> fully once, then reference by id

    for i, dec in enumerate(edl.decisions, start=1):
        angle = real_angles.get(dec.angle_id)
        if angle is None:
            raise ValueError(f"decision angle_id {dec.angle_id!r} not in project angles")
        f0, f1 = frames_at(dec.t_start, fps), frames_at(dec.t_end, fps)
        if f1 <= f0:  # guard against a sub-frame segment after snapping
            f1 = f0 + 1

        clip = ET.SubElement(track, "clipitem", id=f"clipitem-{i}")
        ET.SubElement(clip, "name").text = angle.label or angle.angle_id
        ET.SubElement(clip, "enabled").text = "TRUE"
        ET.SubElement(clip, "duration").text = str(total_frames)
        _rate(clip, timebase, ntsc)
        # Timeline position (start/end) and source in/out — equal, since angles are pre-synced.
        ET.SubElement(clip, "start").text = str(f0)
        ET.SubElement(clip, "end").text = str(f1)
        ET.SubElement(clip, "in").text = str(f0)
        ET.SubElement(clip, "out").text = str(f1)
        ET.SubElement(clip, "comment").text = dec.reason  # explainability

        file_id = f"file-{dec.angle_id}"
        if file_id not in file_defined:
            fobj = ET.SubElement(clip, "file", id=file_id)
            ET.SubElement(fobj, "name").text = _basename(angle.media_path)
            ET.SubElement(fobj, "pathurl").text = _pathurl(angle.media_path)
            _rate(fobj, timebase, ntsc)
            ET.SubElement(fobj, "duration").text = str(total_frames)
            fmedia = ET.SubElement(fobj, "media")
            fvideo = ET.SubElement(fmedia, "video")
            fschar = ET.SubElement(fvideo, "samplecharacteristics")
            _rate(fschar, timebase, ntsc)
            ET.SubElement(fschar, "width").text = str(width)
            ET.SubElement(fschar, "height").text = str(height)
            file_defined.add(file_id)
        else:
            ET.SubElement(clip, "file", id=file_id)  # reference-only

    # Sequence-level (timeline) markers, after the media block.
    for t, label in _markers(energy):
        if t < 0 or t >= project.duration_s:
            continue
        marker = ET.SubElement(sequence, "marker")
        ET.SubElement(marker, "name").text = label
        ET.SubElement(marker, "comment").text = ""
        ET.SubElement(marker, "in").text = str(frames_at(t, fps))
        ET.SubElement(marker, "out").text = "-1"  # point marker

    ET.indent(xmeml, space="  ")
    body = ET.tostring(xmeml, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n{body}\n'


def write_fcp7xml(
    edl: EditDecisionList,
    project: Project,
    out_path: str | Path,
    *,
    energy: EnergyTimeline | None = None,
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """Render and write an FCP7 ``.xml`` file; returns its path."""
    xml = edit_decision_list_to_fcp7xml(edl, project, energy=energy, width=width, height=height)
    path = Path(out_path)
    path.write_text(xml, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Source-resolved export: multi-file angles, preserved sync/filters, real media
# --------------------------------------------------------------------------- #


def edit_decision_list_to_fcp7xml_sourced(
    edl: EditDecisionList,
    imported: ImportedSequence,
    angle_tracks: dict[str, AngleTrack],
    *,
    duration_s: float,
    energy: EnergyTimeline | None = None,
) -> tuple[str, int]:
    """Render an EDL against the parsed multicam timeline, resolving each cut to the correct
    underlying file + source frames.

    - Adjacent same-angle decisions are coalesced (FIX 1) so identical footage is not razored
      into redundant back-to-back clips; real angle switches are preserved.
    - Emits one ``<video><track>`` per angle (FIX 2, DSLR=V1 / GoPro=V2 by angle_id order);
      tracks never overlap in time and their union gaplessly covers the timeline.
    - Each clip is split at source-file boundaries (multi-file angles stay synced), keeps its
      source in-point, and re-emits ALL ``<filter>`` blocks verbatim (Lumetri grade, Basic
      Motion reframe, DSLR Distort, …). The master audio block is re-emitted verbatim.
    - Overlay tracks (PNG, captions if present) are copied verbatim ABOVE the cameras; a
      captured closing fade-to-black is re-applied to the end of the final segment.

    Returns ``(xml, n_unresolved)`` — ``n_unresolved`` is the count of runs with no footage
    (should be 0 when availability is honored).
    """
    fps = imported.fps
    timebase, ntsc = imported.timebase, imported.ntsc
    total_frames = frames_at(duration_s, fps)
    width, height = imported.width, imported.height

    xmeml = ET.Element("xmeml", version=XMEML_VERSION)
    sequence = ET.SubElement(xmeml, "sequence", id=f"seq-{edl.project_id}")
    ET.SubElement(sequence, "name").text = edl.project_id
    ET.SubElement(sequence, "duration").text = str(total_frames)
    _rate(sequence, timebase, ntsc)
    tc = ET.SubElement(sequence, "timecode")
    _rate(tc, timebase, ntsc)
    ET.SubElement(tc, "string").text = "00:00:00:00"
    ET.SubElement(tc, "frame").text = "0"
    ET.SubElement(tc, "displayformat").text = "NDF"

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    vfmt = ET.SubElement(video, "format")
    schar = ET.SubElement(vfmt, "samplecharacteristics")
    _rate(schar, timebase, ntsc)
    ET.SubElement(schar, "width").text = str(width)
    ET.SubElement(schar, "height").text = str(height)

    emitted_files: set[str] = set()
    n_unresolved = 0
    clip_n = 0

    # FIX 1 — coalesce consecutive same-angle decisions so identical footage is not razored
    # into back-to-back clips. Run boundaries are exactly the real angle switches, which are
    # all preserved; only redundant same-angle cut points disappear. File-boundary splits
    # still happen inside AngleTrack.resolve().
    runs = _coalesce_decisions(edl.decisions)
    runs_by_angle: dict[str, list[tuple[float, float]]] = {}
    for aid, t0, t1 in runs:
        runs_by_angle.setdefault(aid, []).append((t0, t1))

    # FIX 2 — one <video><track> per angle, deterministic order by angle_id (alphabetical;
    # for this set DSLR=V1, GoPro=V2). Only one angle is active at any instant, so the tracks
    # never overlap in time and their union gaplessly covers [0, total_frames].
    angle_track_el: dict[str, ET.Element] = {}
    for aid in sorted(runs_by_angle):
        at = angle_tracks.get(aid)
        if at is None:
            raise ValueError(f"decision angle_id {aid!r} has no parsed track")
        atrack = ET.SubElement(video, "track")
        angle_track_el[aid] = atrack
        for t0, t1 in runs_by_angle[aid]:
            resolved = at.resolve(frames_at(t0, fps), frames_at(t1, fps))
            if not resolved:
                n_unresolved += 1
                continue
            for rc in resolved:
                clip_n += 1
                _emit_clipitem(atrack, clip_n, rc, fps, timebase, ntsc, emitted_files)
        ET.SubElement(atrack, "enabled").text = "TRUE"
        ET.SubElement(atrack, "locked").text = "FALSE"

    # FADE: re-apply the captured closing fade-to-black to the END of the final on-screen
    # segment (the last decision's angle), matching the source fade's type + duration.
    if imported.closing_fade_xml and edl.decisions:
        target = angle_track_el.get(edl.decisions[-1].angle_id)
        if target is not None:
            fade = ET.fromstring(imported.closing_fade_xml)
            dur = imported.closing_fade_dur_f or 1
            fade.find("start").text = str(total_frames - dur)
            fade.find("end").text = str(total_frames)
            enabled_el = target.find("enabled")
            idx = list(target).index(enabled_el) if enabled_el is not None else len(target)
            target.insert(idx, fade)  # transitionitem goes before <enabled>/<locked>

    # OVERLAY pass-through: copy overlay tracks (PNG, captions if any) VERBATIM, ABOVE the
    # camera tracks so they composite on top; relative stacking preserved. NOT cut.
    for overlay_xml in imported.overlay_tracks_xml:
        video.append(ET.fromstring(overlay_xml))

    # Master audio: re-emit verbatim so the cut video stays synced to the music.
    if imported.audio_xml:
        media.append(ET.fromstring(imported.audio_xml))

    for t, label in _markers(energy):
        if t < 0 or t >= duration_s:
            continue
        marker = ET.SubElement(sequence, "marker")
        ET.SubElement(marker, "name").text = label
        ET.SubElement(marker, "comment").text = ""
        ET.SubElement(marker, "in").text = str(frames_at(t, fps))
        ET.SubElement(marker, "out").text = "-1"

    ET.indent(xmeml, space="  ")
    body = ET.tostring(xmeml, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n{body}\n', n_unresolved


def _file_duration_frames(file_xml: str) -> int | None:
    try:
        d = ET.fromstring(file_xml).findtext("duration")
        return int(d) if d is not None else None
    except (ET.ParseError, ValueError):
        return None


def _coalesce_decisions(decisions) -> list[tuple[str, float, float]]:
    """Merge consecutive decisions with the same angle_id into (angle_id, t_start, t_end)
    runs. Contiguity (next t_start == prev t_end) is required to merge — a real angle switch
    always starts a new run, so every switch is preserved."""
    runs: list[list] = []
    for d in decisions:
        if runs and runs[-1][0] == d.angle_id and abs(runs[-1][2] - d.t_start) < 1e-6:
            runs[-1][2] = d.t_end
        else:
            runs.append([d.angle_id, d.t_start, d.t_end])
    return [(a, b, c) for a, b, c in runs]


def _emit_clipitem(track, clip_id, rc, fps, timebase, ntsc, emitted_files) -> None:
    """Emit one resolved clip as a Premiere-shaped <clipitem> (masterclipid + ppro ticks +
    standard metadata + verbatim source-file def/ref + ALL preserved <filter> blocks)."""
    seg = rc.segment
    clip = ET.SubElement(track, "clipitem", id=f"clipitem-{clip_id}")
    # masterclipid links every instance of a source file to ONE bin master clip. Without it
    # Premiere imports the media but silently drops the sequence (the earlier import bug).
    ET.SubElement(clip, "masterclipid").text = f"masterclip-{seg.file_id}"
    ET.SubElement(clip, "name").text = seg.file_name
    ET.SubElement(clip, "enabled").text = "TRUE"
    file_dur = _file_duration_frames(seg.file_xml) or rc.src_out_f
    ET.SubElement(clip, "duration").text = str(file_dur)
    _rate(clip, timebase, ntsc)
    ET.SubElement(clip, "start").text = str(rc.tl_start_f)
    ET.SubElement(clip, "end").text = str(rc.tl_end_f)
    ET.SubElement(clip, "in").text = str(rc.src_in_f)
    ET.SubElement(clip, "out").text = str(rc.src_out_f)
    ET.SubElement(clip, "pproTicksIn").text = str(_ppro_ticks(rc.src_in_f, fps))
    ET.SubElement(clip, "pproTicksOut").text = str(_ppro_ticks(rc.src_out_f, fps))
    ET.SubElement(clip, "alphatype").text = "none"
    ET.SubElement(clip, "pixelaspectratio").text = "square"
    ET.SubElement(clip, "anamorphic").text = "FALSE"
    if seg.file_id not in emitted_files:
        clip.append(ET.fromstring(seg.file_xml))  # define-once, verbatim metadata
        emitted_files.add(seg.file_id)
    else:
        ET.SubElement(clip, "file", id=seg.file_id)  # reference
    # Preserve EVERY <filter> on the source clip verbatim — Lumetri (grade), Basic Motion
    # (reframe), Distort (DSLR aspect), etc. Generic: not specific to any one effect.
    for fx in seg.filters_xml:
        clip.append(ET.fromstring(fx))


def write_fcp7xml_sourced(
    edl: EditDecisionList,
    imported: ImportedSequence,
    angle_tracks: dict[str, AngleTrack],
    out_path: str | Path,
    *,
    duration_s: float,
    energy: EnergyTimeline | None = None,
) -> tuple[Path, int]:
    """Render and write a source-resolved FCP7 ``.xml``; returns ``(path, n_unresolved)``."""
    xml, n_unresolved = edit_decision_list_to_fcp7xml_sourced(
        edl, imported, angle_tracks, duration_s=duration_s, energy=energy
    )
    path = Path(out_path)
    path.write_text(xml, encoding="utf-8")
    return path, n_unresolved
