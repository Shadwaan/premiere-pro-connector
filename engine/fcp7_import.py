"""FCP7 XML importer (PPC-007): parse a synced Premiere sequence into an ImportedSequence.

Reads the user's exported `<xmeml>` (the round-trip *in* side): sequence fps/duration, each
video TRACK as a multi-file ``AngleTrack`` (preserving source in-points + filters), and the
audio tracks (preserved verbatim for re-export, plus parsed refs for master-audio selection).

Depends only on the timeline model + stdlib XML — no engine/contract coupling.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

from engine.timeline_model import AngleTrack, AudioRef, ImportedSequence, SourceSegment


def _fps(rate_el: ET.Element) -> tuple[float, int, bool]:
    tb = int(rate_el.findtext("timebase"))
    ntsc = (rate_el.findtext("ntsc") or "FALSE").strip().upper() == "TRUE"
    return (tb * 1000.0 / 1001.0 if ntsc else float(tb), tb, ntsc)


def _url_to_path(pathurl: str | None) -> str:
    if not pathurl:
        return ""
    p = unquote(urlparse(pathurl).path)
    # "/D:/foo" -> "D:/foo" on Windows-style drive paths.
    if len(p) >= 3 and p[0] == "/" and p[2] == ":":
        p = p[1:]
    return p


def _angle_name(file_names: list[str], idx: int) -> str:
    joined = " ".join(n.upper() for n in file_names)
    if "GX0" in joined or "GOPRO" in joined:
        return "GoPro"
    if "MVI" in joined or ".MOV" in joined:
        return "DSLR"
    return f"V{idx}"


_VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".avi", ".m4v", ".mts", ".mpg", ".mpeg", ".mkv"}


def _ext(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def _is_camera_track(file_names: list[str]) -> bool:
    """A camera-angle track holds only camera VIDEO files (.mp4/.mov/…). Anything else —
    images (PNG overlays), graphics, captions — is an overlay/pass-through track."""
    exts = {_ext(n) for n in file_names if n}
    return bool(exts) and exts.issubset(_VIDEO_EXTS)


def parse_fcp7xml(path: str) -> ImportedSequence:
    root = ET.parse(path).getroot()
    seq = root.find("sequence")
    if seq is None:
        raise ValueError("no <sequence> in FCP7 XML")

    fps, tb, ntsc = _fps(seq.find("rate"))
    duration_f = int(seq.findtext("duration") or "0")
    name = seq.findtext("name") or "sequence"
    media = seq.find("media")

    width, height = 1920, 1080
    vfmt = media.find("video/format/samplecharacteristics") if media is not None else None
    if vfmt is not None:
        width = int(vfmt.findtext("width") or width)
        height = int(vfmt.findtext("height") or height)

    angles: list[AngleTrack] = []
    overlay_tracks_xml: list[str] = []
    closing_fade_xml: str | None = None
    closing_fade_dur_f = 0
    _closing_fade_end = -1
    if media is not None and media.find("video") is not None:
        for ti, track in enumerate(media.find("video").findall("track"), start=1):
            clipitems = track.findall("clipitem")
            if not clipitems:
                continue
            names = [
                (c.find("file").findtext("name") if c.find("file") is not None else None)
                or c.findtext("name")
                or ""
                for c in clipitems
            ]
            if not _is_camera_track(names):
                # Overlay / pass-through track (PNG, captions, …): keep verbatim, don't cut.
                overlay_tracks_xml.append(ET.tostring(track, encoding="unicode"))
                continue

            segments: list[SourceSegment] = []
            for clip in clipitems:
                file_el = clip.find("file")
                if file_el is None:
                    continue
                pathurl = file_el.findtext("pathurl")
                fname = file_el.findtext("name") or clip.findtext("name") or ""
                start = int(clip.findtext("start"))
                end = int(clip.findtext("end"))
                src_in = int(clip.findtext("in"))
                src_out = int(clip.findtext("out"))
                if end < 0:  # FCP7 uses -1 when a transition defines the boundary
                    end = start + (src_out - src_in)
                segments.append(
                    SourceSegment(
                        file_id=file_el.get("id", f"file-v{ti}-{len(segments)}"),
                        file_name=fname,
                        pathurl=pathurl or "",
                        file_path=_url_to_path(pathurl),
                        file_xml=ET.tostring(file_el, encoding="unicode"),
                        tl_start_f=start,
                        tl_end_f=end,
                        src_in_f=src_in,
                        filters_xml=[ET.tostring(f, encoding="unicode") for f in clip.findall("filter")],
                    )
                )
            if segments:
                aid = _angle_name(names, ti)
                angles.append(AngleTrack(angle_id=aid, label=aid, segments=segments))

            # Capture a closing fade-to-black on this camera track (latest end-aligned one).
            for t in track.findall("transitionitem"):
                if (t.findtext("alignment") or "").startswith("end"):
                    e = int(t.findtext("end"))
                    if e > _closing_fade_end:
                        _closing_fade_end = e
                        closing_fade_xml = ET.tostring(t, encoding="unicode")
                        closing_fade_dur_f = e - int(t.findtext("start"))

    audio_files: list[AudioRef] = []
    audio_xml: str | None = None
    if media is not None and media.find("audio") is not None:
        audio_el = media.find("audio")
        audio_xml = ET.tostring(audio_el, encoding="unicode")
        for track in audio_el.findall("track"):
            for clip in track.findall("clipitem"):
                file_el = clip.find("file")
                if file_el is None:
                    continue
                pathurl = file_el.findtext("pathurl")
                audio_files.append(
                    AudioRef(
                        file_id=file_el.get("id", "file-audio"),
                        file_name=file_el.findtext("name") or clip.findtext("name") or "",
                        pathurl=pathurl or "",
                        file_path=_url_to_path(pathurl),
                        tl_start_f=int(clip.findtext("start")),
                        tl_end_f=int(clip.findtext("end")),
                        src_in_f=int(clip.findtext("in")),
                    )
                )

    return ImportedSequence(
        name=name,
        fps=fps,
        timebase=tb,
        ntsc=ntsc,
        duration_f=duration_f,
        width=width,
        height=height,
        angles=angles,
        audio_files=audio_files,
        audio_xml=audio_xml,
        overlay_tracks_xml=overlay_tracks_xml,
        closing_fade_xml=closing_fade_xml,
        closing_fade_dur_f=closing_fade_dur_f,
    )


def choose_master_audio(seq: ImportedSequence) -> AudioRef:
    """Pick the master-music audio: the distinct audio file spanning the most timeline."""
    if not seq.audio_files:
        raise ValueError("sequence has no audio tracks; cannot pick master audio")
    by_file: dict[str, AudioRef] = {}
    for a in seq.audio_files:
        cur = by_file.get(a.file_path)
        if cur is None or (a.tl_end_f - a.tl_start_f) > (cur.tl_end_f - cur.tl_start_f):
            by_file[a.file_path] = a
    return max(by_file.values(), key=lambda a: a.tl_end_f - a.tl_start_f)
