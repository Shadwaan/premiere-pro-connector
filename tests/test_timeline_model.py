"""PPC-007 tests: multi-file angle model (resolve splitting + availability)."""

from __future__ import annotations

from engine.timeline_model import AngleTrack, SourceSegment


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


def test_resolve_splits_across_file_boundary_preserving_source_in():
    track = AngleTrack("A", "A", [_seg("file-1", 0, 100, 10), _seg("file-2", 100, 180, 0)])
    clips = track.resolve(50, 150)
    assert len(clips) == 2
    c0, c1 = clips
    assert (c0.segment.file_id, c0.tl_start_f, c0.tl_end_f) == ("file-1", 50, 100)
    assert (c0.src_in_f, c0.src_out_f) == (60, 110)  # 10 + (50-0) .. +50
    assert (c1.segment.file_id, c1.tl_start_f, c1.tl_end_f) == ("file-2", 100, 150)
    assert (c1.src_in_f, c1.src_out_f) == (0, 50)


def test_resolve_within_single_segment():
    track = AngleTrack("A", "A", [_seg("file-1", 0, 100, 10), _seg("file-2", 100, 180, 0)])
    clips = track.resolve(120, 170)
    assert len(clips) == 1
    assert clips[0].segment.file_id == "file-2"
    assert (clips[0].src_in_f, clips[0].src_out_f) == (20, 70)


def test_resolve_outside_coverage_is_empty():
    track = AngleTrack("A", "A", [_seg("file-1", 0, 100, 0)])
    assert track.resolve(200, 250) == []


def test_availability_merges_contiguous_segments():
    track = AngleTrack("A", "A", [_seg("file-1", 0, 100, 0), _seg("file-2", 100, 180, 0)])
    assert track.availability_s(fps=10.0) == [(0.0, 18.0)]


def test_availability_reports_gap():
    track = AngleTrack("A", "A", [_seg("file-1", 0, 100, 0), _seg("file-3", 150, 200, 0)])
    assert track.availability_s(fps=10.0) == [(0.0, 10.0), (15.0, 20.0)]


def test_coverage_frames():
    track = AngleTrack("A", "A", [_seg("file-1", 0, 100, 0), _seg("file-2", 100, 180, 0)])
    assert track.coverage_f() == (0, 180)
