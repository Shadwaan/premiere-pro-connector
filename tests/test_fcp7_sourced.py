"""PPC-007 tests: source-resolved FCP7 export (multi-file split, filters, audio, markers)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from engine.contracts import (
    EditDecision,
    EditDecisionList,
    EditParams,
    EnergyTimeline,
    Section,
)
from engine.export.fcp7xml import edit_decision_list_to_fcp7xml_sourced
from engine.timeline_model import AngleTrack, ImportedSequence, SourceSegment


def _seg(file_id, tl0, tl1, src_in, filters=None) -> SourceSegment:
    return SourceSegment(
        file_id=file_id,
        file_name=f"{file_id}.mov",
        pathurl=f"file://localhost/x/{file_id}.mov",
        file_path=f"/x/{file_id}.mov",
        file_xml=f"<file id='{file_id}'><name>{file_id}.mov</name><duration>500</duration></file>",
        tl_start_f=tl0,
        tl_end_f=tl1,
        src_in_f=src_in,
        filters_xml=filters or [],
    )


def _imported() -> ImportedSequence:
    # fps 10 -> frame_duration (1,10): seconds*10 = frames (easy math).
    distort = "<filter><effect><name>Distort</name></effect></filter>"
    return ImportedSequence(
        name="demo",
        fps=10.0,
        timebase=10,
        ntsc=False,
        duration_f=200,
        width=1920,
        height=1080,
        angles=[
            AngleTrack("A", "A", [_seg("file-1", 0, 100, 10), _seg("file-2", 100, 200, 0, [distort])]),
        ],
        audio_files=[],
        audio_xml="<audio><track><clipitem id='ca'><file id='file-5'><name>m.wav</name></file></clipitem></track></audio>",
    )


def _edl() -> EditDecisionList:
    # One decision spanning 5..15 s -> frames 50..150 -> straddles the file boundary at 100.
    return EditDecisionList(
        project_id="demo",
        params=EditParams(),
        decisions=[EditDecision(index=0, t_start=5.0, t_end=15.0, angle_id="A", reason="x")],
    )


def _energy() -> EnergyTimeline:
    return EnergyTimeline(
        hop_s=1.0,
        energy=[0.5] * 20,
        sections=[
            Section(start=0.0, end=10.0, kind="intro", energy=0.3),
            Section(start=10.0, end=20.0, kind="drop", energy=0.9),
        ],
        drops=[10.0],
    )


def test_decision_splits_across_file_boundary():
    imp = _imported()
    xml, n_unres = edit_decision_list_to_fcp7xml_sourced(
        _edl(), imp, {"A": imp.angles[0]}, duration_s=20.0, energy=_energy()
    )
    assert n_unres == 0
    root = ET.fromstring(xml)
    clips = root.findall("sequence/media/video/track/clipitem")
    assert len(clips) == 2  # one decision -> two clips (file boundary at frame 100)

    c0, c1 = clips
    assert c0.find("file").get("id") == "file-1"
    assert (c0.findtext("start"), c0.findtext("end")) == ("50", "100")
    assert (c0.findtext("in"), c0.findtext("out")) == ("60", "110")  # 10 + (50-0)
    assert c1.find("file").get("id") == "file-2"
    assert (c1.findtext("start"), c1.findtext("end")) == ("100", "150")
    assert (c1.findtext("in"), c1.findtext("out")) == ("0", "50")


def test_filter_preserved_on_dslr_segment():
    imp = _imported()
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl(), imp, {"A": imp.angles[0]}, duration_s=20.0
    )
    root = ET.fromstring(xml)
    clips = root.findall("sequence/media/video/track/clipitem")
    # file-2 segment carried a Distort filter; file-1 did not.
    assert clips[0].find("filter") is None
    assert clips[1].find("filter/effect/name").text == "Distort"


def test_master_audio_reemitted_and_well_formed():
    imp = _imported()
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl(), imp, {"A": imp.angles[0]}, duration_s=20.0
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    root = ET.fromstring(xml)
    assert root.find("sequence/media/audio/track/clipitem/file") is not None  # audio preserved
    assert root.findtext("sequence/duration") == "200"  # 20 s * 10 fps


def test_clipitems_have_masterclipid_and_ppro_ticks():
    """Regression: video clipitems must carry masterclipid (+ ppro ticks / standard fields),
    or Premiere imports the media but drops the sequence."""
    imp = _imported()
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl(), imp, {"A": imp.angles[0]}, duration_s=20.0
    )
    root = ET.fromstring(xml)
    clips = root.findall("sequence/media/video/track/clipitem")
    assert clips
    for c in clips:
        fid = c.find("file").get("id")
        assert c.findtext("masterclipid") == f"masterclip-{fid}"  # one master clip per file
        assert c.find("pproTicksIn") is not None
        assert c.find("pproTicksOut") is not None
        assert c.findtext("alphatype") == "none"
        assert c.findtext("anamorphic") == "FALSE"
    # ppro ticks are exact: frame * 254_016_000_000 / fps (fps=10 here).
    c0 = clips[0]  # file-1, src in=60 out=110
    assert c0.findtext("pproTicksIn") == str(round(60 * 254_016_000_000 / 10))
    assert c0.findtext("pproTicksOut") == str(round(110 * 254_016_000_000 / 10))


def test_markers_emitted_from_energy():
    imp = _imported()
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl(), imp, {"A": imp.angles[0]}, duration_s=20.0, energy=_energy()
    )
    root = ET.fromstring(xml)
    markers = root.findall("sequence/marker")
    labels = [m.findtext("name") for m in markers]
    assert "intro" in labels and "drop section" in labels
    assert any(l.startswith("DROP") for l in labels)
