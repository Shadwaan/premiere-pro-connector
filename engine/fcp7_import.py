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
    if media is not None and media.find("video") is not None:
        for ti, track in enumerate(media.find("video").findall("track"), start=1):
            clipitems = track.findall("clipitem")
            if not clipitems:
                continue
            segments: list[SourceSegment] = []
            names: list[str] = []
            for clip in clipitems:
                file_el = clip.find("file")
                if file_el is None:
                    continue
                pathurl = file_el.findtext("pathurl")
                fname = file_el.findtext("name") or clip.findtext("name") or ""
                names.append(fname)
                filters = [ET.tostring(f, encoding="unicode") for f in clip.findall("filter")]
                segments.append(
                    SourceSegment(
                        file_id=file_el.get("id", f"file-v{ti}-{len(segments)}"),
                        file_name=fname,
                        pathurl=pathurl or "",
                        file_path=_url_to_path(pathurl),
                        file_xml=ET.tostring(file_el, encoding="unicode"),
                        tl_start_f=int(clip.findtext("start")),
                        tl_end_f=int(clip.findtext("end")),
                        src_in_f=int(clip.findtext("in")),
                        filters_xml=filters,
                    )
                )
            if segments:
                aid = _angle_name(names, ti)
                angles.append(AngleTrack(angle_id=aid, label=aid, segments=segments))

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
