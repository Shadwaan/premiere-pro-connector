"""PPC-006 (pivot) tests: FCP7 XML export — well-formedness, frame-snapping, markers, mapping.

FCP7 XML (`<xmeml>`) is the Premiere-native interchange (Premiere 2026 rejects `.fcpxml`).
All offline; small synthetic EditDecisionLists so each property is checked exactly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from engine.contracts import (
    Angle,
    EditDecision,
    EditDecisionList,
    EditParams,
    EnergyTimeline,
    Project,
    Section,
)
from engine.export.fcp7xml import (
    edit_decision_list_to_fcp7xml,
    timebase_ntsc,
)


def make_project(duration=12.0, fps=30.0, angle_ids=("A", "B")) -> Project:
    return Project(
        project_id="proj",
        master_audio_path="/m.wav",
        angles=[Angle(angle_id=a, media_path=f"/media/{a}.mov", label=f"cam {a}") for a in angle_ids],
        fps=fps,
        duration_s=duration,
    )


def make_edl(project, cuts_and_angles) -> EditDecisionList:
    decisions = [
        EditDecision(index=i, t_start=t0, t_end=t1, angle_id=a, reason=f"seg {i} -> {a}")
        for i, (t0, t1, a) in enumerate(cuts_and_angles)
    ]
    return EditDecisionList(project_id=project.project_id, params=EditParams(), decisions=decisions)


def _seq(root):
    return root.find("sequence")


def _clipitems(root):
    return root.findall("sequence/media/video/track/clipitem")


# --------------------------------------------------------------------------- #
# Rate / frame-snapping
# --------------------------------------------------------------------------- #


def test_timebase_ntsc_mapping():
    assert timebase_ntsc(30.0) == (30, False)
    assert timebase_ntsc(24.0) == (24, False)
    assert timebase_ntsc(29.97) == (30, True)
    assert timebase_ntsc(23.976) == (24, True)


# --------------------------------------------------------------------------- #
# Well-formedness & structure
# --------------------------------------------------------------------------- #


def test_output_is_well_formed_xmeml():
    project = make_project()
    edl = make_edl(project, [(0.0, 6.0, "A"), (6.0, 12.0, "B")])
    xml = edit_decision_list_to_fcp7xml(edl, project)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<!DOCTYPE xmeml>" in xml
    root = ET.fromstring(xml)
    assert root.tag == "xmeml"
    assert root.attrib["version"] == "4"
    seq = _seq(root)
    assert seq is not None
    assert seq.find("rate/timebase").text == "30"
    assert seq.find("rate/ntsc").text == "FALSE"
    assert seq.find("duration").text == str(360)  # 12 s * 30 fps


def test_decisions_map_one_to_one_to_clipitems():
    project = make_project()
    edl = make_edl(project, [(0.0, 4.0, "A"), (4.0, 8.0, "B"), (8.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcp7xml(edl, project))
    assert len(_clipitems(root)) == 3


def test_clip_frames_accurate_and_gapless():
    project = make_project(duration=10.0, fps=30.0)
    edl = make_edl(project, [(0.0, 4.0, "A"), (4.0, 10.0, "B")])
    root = ET.fromstring(edit_decision_list_to_fcp7xml(edl, project))
    c0, c1 = _clipitems(root)
    # timeline + source frames; angles pre-synced so in==start, out==end
    assert (c0.find("start").text, c0.find("end").text) == ("0", "120")
    assert (c0.find("in").text, c0.find("out").text) == ("0", "120")
    assert c1.find("start").text == "120"  # gapless
    assert c1.find("end").text == "300"  # 10 s


def test_file_defined_once_then_referenced():
    project = make_project(angle_ids=("A", "B"))
    edl = make_edl(project, [(0.0, 3.0, "A"), (3.0, 6.0, "A"), (6.0, 12.0, "B")])
    root = ET.fromstring(edit_decision_list_to_fcp7xml(edl, project))
    files = root.findall(".//clipitem/file")
    assert len(files) == 3  # one per clipitem
    # Only the first occurrence of each file id carries a definition (has children).
    defined = [f for f in files if list(f)]
    ref_only = [f for f in files if not list(f)]
    assert len(defined) == 2  # A and B defined once each
    assert len(ref_only) == 1  # the 2nd A clip references by id
    a_def = next(f for f in defined if f.attrib["id"] == "file-A")
    assert a_def.find("pathurl").text.startswith("file://localhost/")
    assert a_def.find("name").text == "A.mov"


def test_clip_carries_reason_comment():
    project = make_project()
    edl = make_edl(project, [(0.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcp7xml(edl, project))
    assert "-> A" in _clipitems(root)[0].find("comment").text


# --------------------------------------------------------------------------- #
# Markers (sequence-level)
# --------------------------------------------------------------------------- #


def _energy_for_markers() -> EnergyTimeline:
    return EnergyTimeline(
        hop_s=0.5,
        energy=[0.5] * 25,
        sections=[
            Section(start=0.0, end=4.0, kind="intro", energy=0.3),
            Section(start=4.0, end=8.0, kind="drop", energy=0.9),
            Section(start=8.0, end=12.0, kind="breakdown", energy=0.4),
        ],
        drops=[4.0],
    )


def test_markers_are_sequence_level_with_labels_and_frames():
    project = make_project(duration=12.0)
    edl = make_edl(project, [(0.0, 4.0, "A"), (4.0, 8.0, "B"), (8.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcp7xml(edl, project, energy=_energy_for_markers()))
    markers = _seq(root).findall("marker")  # direct children of <sequence>
    labels = [m.find("name").text for m in markers]
    assert len(markers) == 4  # 3 sections + 1 drop
    assert {"intro", "drop section", "breakdown"} <= set(labels)
    drop = next(m for m in markers if m.find("name").text.startswith("DROP"))
    assert drop.find("in").text == "120"  # 4 s * 30 fps
    assert drop.find("out").text == "-1"  # point marker


def test_no_markers_without_energy():
    project = make_project()
    edl = make_edl(project, [(0.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcp7xml(edl, project))
    assert _seq(root).findall("marker") == []


def test_unknown_angle_raises():
    project = make_project(angle_ids=("A",))
    edl = make_edl(project, [(0.0, 12.0, "B")])
    with pytest.raises(ValueError):
        edit_decision_list_to_fcp7xml(edl, project)
