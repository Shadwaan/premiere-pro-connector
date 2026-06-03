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

XMEML_VERSION = "4"  # the version Premiere itself reads/writes

# Fractional NTSC rates -> their integer FCP7 timebase (ntsc flag = TRUE).
_NTSC_BASES = (24, 30, 50, 60)


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
