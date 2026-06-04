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


# --------------------------------------------------------------------------- #
# FIX 1 (coalesce same-angle) + FIX 2 (per-angle tracks) — two angles
# --------------------------------------------------------------------------- #


def _imported_2angle() -> ImportedSequence:
    return ImportedSequence(
        name="demo2",
        fps=10.0,
        timebase=10,
        ntsc=False,
        duration_f=80,
        width=1920,
        height=1080,
        angles=[
            AngleTrack("GoPro", "GoPro", [_seg("file-g", 0, 80, 0)]),
            AngleTrack("DSLR", "DSLR", [_seg("file-d", 0, 80, 0)]),
        ],
        audio_files=[],
        audio_xml="<audio><track><clipitem id='ca'><file id='file-5'><name>m.wav</name></file></clipitem></track></audio>",
    )


def _edl_2angle() -> EditDecisionList:
    # 4 decisions; the first two are the SAME angle (GoPro) and must coalesce; then a real
    # switch to DSLR, then back to GoPro. fps 10 -> seconds*10 = frames.
    d = [
        EditDecision(index=0, t_start=0.0, t_end=2.0, angle_id="GoPro", reason="x"),
        EditDecision(index=1, t_start=2.0, t_end=4.0, angle_id="GoPro", reason="x"),  # redundant
        EditDecision(index=2, t_start=4.0, t_end=6.0, angle_id="DSLR", reason="x"),   # switch
        EditDecision(index=3, t_start=6.0, t_end=8.0, angle_id="GoPro", reason="x"),  # switch
    ]
    return EditDecisionList(project_id="demo2", params=EditParams(), decisions=d)


def _angle_tracks(imp):
    return {a.angle_id: a for a in imp.angles}


def test_fix1_coalesces_adjacent_same_angle():
    imp = _imported_2angle()
    xml, n = edit_decision_list_to_fcp7xml_sourced(
        _edl_2angle(), imp, _angle_tracks(imp), duration_s=8.0
    )
    assert n == 0
    root = ET.fromstring(xml)
    clips = root.findall("sequence/media/video/track/clipitem")
    assert len(clips) == 3  # 4 decisions -> 3 clips (the two GoPro decisions merged)
    # The merged GoPro [0,4] becomes ONE clip spanning frames 0..40.
    gopro = [c for c in clips if c.findtext("name") == "file-g.mov"]
    assert any(c.findtext("start") == "0" and c.findtext("end") == "40" for c in gopro)


def test_fix2_one_track_per_angle_dslr_v1_gopro_v2():
    imp = _imported_2angle()
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl_2angle(), imp, _angle_tracks(imp), duration_s=8.0
    )
    root = ET.fromstring(xml)
    tracks = root.findall("sequence/media/video/track")
    assert len(tracks) == 2
    # alphabetical angle order -> DSLR on V1 (first), GoPro on V2 (second).
    v1_files = {c.findtext("name") for c in tracks[0].findall("clipitem")}
    v2_files = {c.findtext("name") for c in tracks[1].findall("clipitem")}
    assert v1_files == {"file-d.mov"}  # DSLR only
    assert v2_files == {"file-g.mov"}  # GoPro only


def test_fix2_tracks_no_overlap_and_union_gapless():
    imp = _imported_2angle()
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl_2angle(), imp, _angle_tracks(imp), duration_s=8.0
    )
    root = ET.fromstring(xml)
    tracks = root.findall("sequence/media/video/track")
    total = int(root.findtext("sequence/duration"))
    spans = []
    for tr in tracks:
        clips = [(int(c.findtext("start")), int(c.findtext("end"))) for c in tr.findall("clipitem")]
        for a, b in zip(clips, clips[1:]):
            assert a[1] <= b[0], "overlap within a track"  # no overlap within track
        spans.extend(clips)
    spans.sort()
    assert spans[0][0] == 0 and spans[-1][1] == total  # covers [0, total]
    for a, b in zip(spans, spans[1:]):
        assert a[1] == b[0], "gap in union of tracks"  # gapless union


_OVERLAY_TRACK = (
    "<track><clipitem id='ov1'><name>logo.png</name><start>10</start><end>30</end>"
    "<in>0</in><out>20</out><file id='file-png'><name>logo.png</name>"
    "<pathurl>file://localhost/x/logo.png</pathurl></file></clipitem>"
    "<enabled>TRUE</enabled><locked>FALSE</locked></track>"
)
_FADE = (
    "<transitionitem><start>0</start><end>0</end><alignment>end-black</alignment>"
    "<effect><name>Cross Dissolve</name><effectid>Cross Dissolve</effectid>"
    "<effecttype>transition</effecttype></effect></transitionitem>"
)


def test_overlay_track_passthrough_above_cameras():
    imp = _imported_2angle()
    imp.overlay_tracks_xml = [_OVERLAY_TRACK]
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl_2angle(), imp, _angle_tracks(imp), duration_s=8.0
    )
    root = ET.fromstring(xml)
    tracks = root.findall("sequence/media/video/track")
    assert len(tracks) == 3  # 2 cameras + 1 overlay
    overlay = tracks[-1]  # appended last => composites on top
    clip = overlay.find("clipitem")
    assert clip.findtext("name") == "logo.png"
    # NOT cut: still one clip at its original position.
    assert (clip.findtext("start"), clip.findtext("end")) == ("10", "30")
    assert len(overlay.findall("clipitem")) == 1


def test_closing_fade_reapplied_to_last_segment():
    imp = _imported_2angle()
    imp.closing_fade_xml = _FADE
    imp.closing_fade_dur_f = 2  # frames (fps 10)
    edl = _edl_2angle()  # last decision is GoPro
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        edl, imp, _angle_tracks(imp), duration_s=8.0
    )
    root = ET.fromstring(xml)
    total = int(root.findtext("sequence/duration"))  # 80
    # GoPro is V2 (second track, alphabetical DSLR<GoPro).
    gopro_track = root.findall("sequence/media/video/track")[1]
    fade = gopro_track.find("transitionitem")
    assert fade is not None
    assert (fade.findtext("start"), fade.findtext("end")) == (str(total - 2), str(total))
    assert fade.find("effect/name").text == "Cross Dissolve"
    assert fade.findtext("alignment") == "end-black"


def test_no_fade_when_source_had_none():
    imp = _imported_2angle()  # closing_fade_xml defaults None
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl_2angle(), imp, _angle_tracks(imp), duration_s=8.0
    )
    root = ET.fromstring(xml)
    assert root.findall("sequence/media/video/track/transitionitem") == []


def test_real_switches_preserved():
    imp = _imported_2angle()
    xml, _ = edit_decision_list_to_fcp7xml_sourced(
        _edl_2angle(), imp, _angle_tracks(imp), duration_s=8.0
    )
    root = ET.fromstring(xml)
    clips = root.findall("sequence/media/video/track/clipitem")
    names = {c.findtext("name") for c in clips}
    assert names == {"file-g.mov", "file-d.mov"}  # both angles present (switches kept)
