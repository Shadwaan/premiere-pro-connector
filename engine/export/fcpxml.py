"""FCPXML exporter (PPC-006): ``EditDecisionList`` -> Premiere Pro 2026-importable timeline.

Surface form chosen: **a single sequence with the angle clips cut onto one video track**
(each ``EditDecision`` becomes an ``asset-clip`` referencing the chosen angle's media). This
is the angle-switch-as-cut edit the user wants and imports reliably. A *true* FCPXML
multicam container (`<mc-clip>` / `<media><multicam>`) is known-fragile in Premiere
(PRD §9 Q4); the cut sequence gives the same visual result and is far more robust. Live
angle re-picking is the Phase-2 UXP panel's job, not the FCPXML's.

**Timeline invariant boundary:** the engine is float seconds everywhere; this module is the
ONLY place float seconds are frame-snapped to Premiere's rational `frames*num/den s` time,
using the project fps.

Depends only on contract types (`EditDecisionList`, `Project`, `EnergyTimeline`, `Section`).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from engine.contracts import EditDecisionList, EnergyTimeline, Project

FCPXML_VERSION = "1.9"  # broadly Premiere-compatible; confirm against PP 2026 on first import

# NTSC fractional rates -> (frameDuration numerator, denominator).
_NTSC = [
    (24000 / 1001, (1001, 24000)),
    (30000 / 1001, (1001, 30000)),
    (48000 / 1001, (1001, 48000)),
    (60000 / 1001, (1001, 60000)),
]


# --------------------------------------------------------------------------- #
# Frame-snapping / rational time  (the ONLY float->frame conversion in the codebase)
# --------------------------------------------------------------------------- #


def frame_duration(fps: float) -> tuple[int, int]:
    """Return ``(num, den)`` so that one frame == ``num/den`` seconds."""
    for val, nd in _NTSC:
        if abs(fps - val) < 0.01:
            return nd
    return (1, int(round(fps)))


def frames_at(seconds: float, fps: float) -> int:
    """Nearest whole frame index for a time in seconds."""
    num, den = frame_duration(fps)
    return int(round(seconds * den / num))


def rational_time(seconds: float, fps: float) -> str:
    """Frame-snapped FCPXML time string, e.g. ``"90/30s"`` or ``"0s"``."""
    num, den = frame_duration(fps)
    f = frames_at(seconds, fps)
    if f == 0:
        return "0s"
    return f"{f * num}/{den}s"


def _file_uri(media_path: str) -> str:
    """Best-effort ``file://`` URI for an absolute path (Windows or POSIX)."""
    p = str(media_path).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", p):  # Windows drive path -> file:///C:/...
        return "file:///" + quote(p, safe="/:")
    if p.startswith("/"):
        return "file://" + quote(p, safe="/:")
    return "file://" + quote("/" + p, safe="/:")


def _mmss(t: float) -> str:
    m = int(t // 60)
    return f"{m:d}:{t - 60 * m:05.2f}"


# --------------------------------------------------------------------------- #
# Markers (from the optional EnergyTimeline)
# --------------------------------------------------------------------------- #


def _section_label(kind: str) -> str:
    return "drop section" if kind == "drop" else kind


def _markers(energy: EnergyTimeline | None) -> list[tuple[float, str]]:
    """(time, label) markers: one per section boundary + one per hard onset-drop."""
    if energy is None:
        return []
    marks: list[tuple[float, str]] = []
    for s in energy.sections:
        marks.append((s.start, _section_label(s.kind)))
    for d in energy.drops:
        marks.append((d, f"DROP {_mmss(d)}"))
    marks.sort(key=lambda m: m[0])
    return marks


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def edit_decision_list_to_fcpxml(
    edl: EditDecisionList,
    project: Project,
    *,
    energy: EnergyTimeline | None = None,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Render an ``EditDecisionList`` to an FCPXML document string.

    ``energy`` (optional) supplies section boundaries + hard drops for timeline markers.
    Video-only by design: angles are placed as cuts on one track; the user keeps/places the
    master audio in Premiere (the angles are already synced to it).
    """
    fps = float(project.fps)
    num, den = frame_duration(fps)
    dur = rational_time(project.duration_s, fps)

    root = ET.Element("fcpxml", version=FCPXML_VERSION)
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r1",
        name=f"FFVideoFormat_{int(round(fps))}p",
        frameDuration=f"{num}/{den}s",
        width=str(width),
        height=str(height),
    )

    # One asset per angle, id keyed by angle_id.
    asset_id: dict[str, str] = {}
    for i, angle in enumerate(project.angles, start=1):
        aid = f"asset_{angle.angle_id}"
        asset_id[angle.angle_id] = aid
        asset = ET.SubElement(
            resources,
            "asset",
            id=aid,
            name=angle.label or angle.angle_id,
            start="0s",
            duration=dur,
            hasVideo="1",
            videoSources="1",
            format="r1",
        )
        ET.SubElement(asset, "media-rep", kind="original-media", src=_file_uri(angle.media_path))

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Premiere Pro Connector")
    proj = ET.SubElement(event, "project", name=project.project_id)
    sequence = ET.SubElement(
        proj,
        "sequence",
        format="r1",
        duration=dur,
        tcStart="0s",
        tcFormat="NDF",
    )
    spine = ET.SubElement(sequence, "spine")

    # One asset-clip per decision; angles are pre-synced so source-in == timeline time.
    clip_els = []
    for dec in edl.decisions:
        ref = asset_id.get(dec.angle_id)
        if ref is None:
            raise ValueError(f"decision angle_id {dec.angle_id!r} not in project angles")
        seg = rational_time(dec.t_end, fps)  # snap end, then derive duration from snapped ends
        start = rational_time(dec.t_start, fps)
        # duration in frames = end_frame - start_frame, so adjacent clips stay gap-free.
        f0, f1 = frames_at(dec.t_start, fps), frames_at(dec.t_end, fps)
        clip_dur = f"{(f1 - f0) * num}/{den}s" if (f1 - f0) else f"{num}/{den}s"
        clip = ET.SubElement(
            spine,
            "asset-clip",
            ref=ref,
            offset=start,
            name=dec.angle_id,
            start=start,
            duration=clip_dur,
        )
        # Carry the explainability reason as a valid <note> child (Premiere shows it as the
        # clip's Notes; schema order is note before any markers).
        ET.SubElement(clip, "note").text = dec.reason
        clip_els.append((dec, clip))

    _attach_markers(clip_els, _markers(energy), fps, num, den, project.duration_s)

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n{body}\n'


def _attach_markers(clip_els, marks, fps, num, den, duration_s) -> None:
    """Attach each marker to the asset-clip whose time range contains it (source==timeline)."""
    for t, label in marks:
        if t < 0 or t >= duration_s:
            continue
        ft = frames_at(t, fps)
        target = None
        for dec, clip in clip_els:
            if frames_at(dec.t_start, fps) <= ft < frames_at(dec.t_end, fps):
                target = clip
                break
        if target is None and clip_els:
            target = clip_els[-1][1]  # fallback: last clip (e.g., t == last boundary)
        if target is None:
            continue
        # Source time == timeline time here (start == offset), so the marker's source-frame
        # equals its absolute frame ft; it lands at absolute time t on the sequence.
        ET.SubElement(
            target, "marker", start=f"{ft * num}/{den}s", duration=f"{num}/{den}s", value=label
        )


def write_fcpxml(
    edl: EditDecisionList,
    project: Project,
    out_path: str | Path,
    *,
    energy: EnergyTimeline | None = None,
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """Render and write an ``.fcpxml`` file; returns its path."""
    xml = edit_decision_list_to_fcpxml(edl, project, energy=energy, width=width, height=height)
    path = Path(out_path)
    path.write_text(xml, encoding="utf-8")
    return path
