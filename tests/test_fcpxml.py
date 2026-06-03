"""PPC-006 tests: FCPXML export — well-formedness, frame-snapping, markers, mapping.

All offline. The real-track sample is generated separately (see BUILD_LOG); these tests use
small synthetic EditDecisionLists so each property is checked exactly.
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
from engine.export.fcpxml import (
    edit_decision_list_to_fcpxml,
    frame_duration,
    frames_at,
    rational_time,
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


# --------------------------------------------------------------------------- #
# Frame-snapping
# --------------------------------------------------------------------------- #


def test_frame_duration_integer_and_ntsc():
    assert frame_duration(30.0) == (1, 30)
    assert frame_duration(24.0) == (1, 24)
    assert frame_duration(23.976) == (1001, 24000)
    assert frame_duration(29.97) == (1001, 30000)


def test_rational_time_snaps_to_frames():
    assert rational_time(0.0, 30.0) == "0s"
    assert rational_time(3.0, 30.0) == "90/30s"  # 3 s == 90 frames
    assert rational_time(0.05, 30.0) == "2/30s"  # 1.5 frames -> rounds to 2
    assert frames_at(1.0, 30.0) == 30
    # NTSC: 1 s ~= 30 frames -> 30*1001/30000 s
    assert rational_time(1.0, 29.97) == f"{30 * 1001}/30000s"


# --------------------------------------------------------------------------- #
# Well-formedness & structure
# --------------------------------------------------------------------------- #


def test_output_is_well_formed_and_has_expected_shape():
    project = make_project()
    edl = make_edl(project, [(0.0, 6.0, "A"), (6.0, 12.0, "B")])
    xml = edit_decision_list_to_fcpxml(edl, project)

    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<!DOCTYPE fcpxml>" in xml

    root = ET.fromstring(xml)  # raises if malformed
    assert root.tag == "fcpxml"
    assert root.attrib["version"] == "1.9"
    assert root.find("resources/format") is not None
    assert root.find("library/event/project/sequence/spine") is not None


def test_one_asset_per_angle_with_file_uri():
    project = make_project(angle_ids=("A", "B", "C"))
    edl = make_edl(project, [(0.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcpxml(edl, project))
    assets = root.findall("resources/asset")
    assert len(assets) == 3
    srcs = [a.find("media-rep").attrib["src"] for a in assets]
    assert all(s.startswith("file://") for s in srcs)
    assert any(s.endswith("/media/A.mov") for s in srcs)


def test_decisions_map_one_to_one_to_clips():
    project = make_project()
    edl = make_edl(project, [(0.0, 4.0, "A"), (4.0, 8.0, "B"), (8.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcpxml(edl, project))
    clips = root.findall("library/event/project/sequence/spine/asset-clip")
    assert len(clips) == 3


def test_clip_mapping_frame_accurate_and_gapless():
    project = make_project(duration=10.0, fps=30.0)
    edl = make_edl(project, [(0.0, 4.0, "A"), (4.0, 10.0, "B")])
    root = ET.fromstring(edit_decision_list_to_fcpxml(edl, project))
    clips = root.findall("library/event/project/sequence/spine/asset-clip")

    c0, c1 = clips
    assert c0.attrib["ref"] == "asset_A"
    assert c0.attrib["offset"] == "0s"
    assert c0.attrib["start"] == "0s"
    assert c0.attrib["duration"] == "120/30s"  # 4 s
    assert c1.attrib["ref"] == "asset_B"
    assert c1.attrib["offset"] == "120/30s"  # gapless: c1 starts where c0 ends
    assert c1.attrib["duration"] == "180/30s"  # 6 s


def test_clip_carries_reason_note():
    project = make_project()
    edl = make_edl(project, [(0.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcpxml(edl, project))
    note = root.find("library/event/project/sequence/spine/asset-clip/note")
    assert note is not None and "-> A" in note.text


# --------------------------------------------------------------------------- #
# Markers
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


def _all_markers(root):
    return root.findall(".//marker")


def test_markers_placed_for_sections_and_drops():
    project = make_project(duration=12.0)
    edl = make_edl(project, [(0.0, 4.0, "A"), (4.0, 8.0, "B"), (8.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcpxml(edl, project, energy=_energy_for_markers()))
    labels = [m.attrib["value"] for m in _all_markers(root)]
    # 3 section boundaries + 1 hard drop
    assert "intro" in labels
    assert "drop section" in labels
    assert "breakdown" in labels
    assert any(l.startswith("DROP ") for l in labels)
    assert len(_all_markers(root)) == 4


def test_marker_time_is_frame_snapped_and_in_range():
    project = make_project(duration=12.0)
    edl = make_edl(project, [(0.0, 4.0, "A"), (4.0, 8.0, "B"), (8.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcpxml(edl, project, energy=_energy_for_markers()))
    drop = next(m for m in _all_markers(root) if m.attrib["value"].startswith("DROP"))
    # drop at 4.0 s, 30 fps -> 120 frames -> "120/30s"
    assert drop.attrib["start"] == "120/30s"


def test_no_markers_without_energy():
    project = make_project()
    edl = make_edl(project, [(0.0, 12.0, "A")])
    root = ET.fromstring(edit_decision_list_to_fcpxml(edl, project))
    assert _all_markers(root) == []


def test_unknown_angle_raises():
    project = make_project(angle_ids=("A",))
    edl = make_edl(project, [(0.0, 12.0, "B")])  # B not in project
    with pytest.raises(ValueError):
        edit_decision_list_to_fcpxml(edl, project)
