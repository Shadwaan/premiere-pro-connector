"""Timeline / source model for multi-file angles (PPC-007).

These dataclasses are an **engine-internal** representation of a synced multicam timeline as
read from an FCP7 XML, distinct from the frozen Pydantic contracts in ``contracts.py``:

- A real camera **angle is a TRACK**, not a single file — it's a sequence of source-file
  segments, each placed at a timeline range with its own source in-point and (optionally)
  filters (e.g. the DSLR aspect Distort the user applied).
- Angles have **availability windows** — a track may not cover the whole timeline (the DSLR
  ends before the GoPro), so fusion must not pick an angle where it has no footage.

The contracts are untouched: fusion still works on ``angle_id`` + score timelines and emits a
contract ``EditDecisionList``; this model is only used by the importer, the source-resolved
exporter, and the CLI to map ``angle_id`` + timeline range -> the correct underlying file and
source frames. Times here are integer **frames** (the FCP7 native unit); seconds are derived
via the sequence fps at the edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceSegment:
    """One source file occupying a timeline range within an angle/track."""

    file_id: str  # original FCP7 file id (for define-once/reference on export)
    file_name: str
    pathurl: str
    file_path: str  # decoded absolute path
    file_xml: str  # raw <file> element XML, re-emitted verbatim to preserve metadata
    tl_start_f: int  # timeline start frame
    tl_end_f: int  # timeline end frame
    src_in_f: int  # source in-point frame at tl_start_f
    filters_xml: list[str] = field(default_factory=list)  # <filter> elements to preserve


@dataclass
class ResolvedClip:
    """A timeline sub-range resolved to a concrete file + source frames."""

    segment: SourceSegment
    tl_start_f: int
    tl_end_f: int
    src_in_f: int
    src_out_f: int


@dataclass
class AngleTrack:
    angle_id: str
    label: str
    segments: list[SourceSegment]

    def coverage_f(self) -> tuple[int, int]:
        return min(s.tl_start_f for s in self.segments), max(s.tl_end_f for s in self.segments)

    def availability_s(self, fps: float) -> list[tuple[float, float]]:
        """Merged availability intervals (seconds). Adjacent segments coalesce."""
        segs = sorted(self.segments, key=lambda s: s.tl_start_f)
        merged: list[list[int]] = []
        for s in segs:
            if merged and s.tl_start_f <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], s.tl_end_f)
            else:
                merged.append([s.tl_start_f, s.tl_end_f])
        return [(a / fps, b / fps) for a, b in merged]

    def resolve(self, tl0_f: int, tl1_f: int) -> list[ResolvedClip]:
        """Map a timeline frame range to concrete clips, splitting at file boundaries.

        Returns one ``ResolvedClip`` per overlapping source segment (empty if the angle has
        no footage there). Source frames preserve the original sync in-points.
        """
        out: list[ResolvedClip] = []
        for seg in sorted(self.segments, key=lambda s: s.tl_start_f):
            a = max(tl0_f, seg.tl_start_f)
            b = min(tl1_f, seg.tl_end_f)
            if b <= a:
                continue
            src_in = seg.src_in_f + (a - seg.tl_start_f)
            out.append(ResolvedClip(seg, a, b, src_in, src_in + (b - a)))
        return out


@dataclass
class AudioRef:
    file_id: str
    file_name: str
    pathurl: str
    file_path: str
    tl_start_f: int
    tl_end_f: int
    src_in_f: int


@dataclass
class ImportedSequence:
    name: str
    fps: float
    timebase: int
    ntsc: bool
    duration_f: int
    width: int
    height: int
    angles: list[AngleTrack]
    audio_files: list[AudioRef]
    audio_xml: str | None = None  # raw <audio> media block, re-emitted verbatim
    # Overlay / pass-through video tracks (PNG, captions if present, …) — raw <track> XML,
    # re-emitted verbatim ABOVE the camera tracks. NOT cut. Source stacking order preserved.
    overlay_tracks_xml: list[str] = field(default_factory=list)
    # Closing fade captured from the last camera clip (re-applied to the final segment).
    closing_fade_xml: str | None = None
    closing_fade_dur_f: int = 0

    def duration_s(self) -> float:
        return self.duration_f / self.fps
