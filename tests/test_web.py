"""Smoke test for the local web UI (PRD §4 req 9). Skips if web deps aren't installed.

Generates a short click-track WAV + a minimal FCP7 XML referencing it, POSTs to /process with
default params, and asserts a 200 with a well-formed auto-cut XML (the expected camera tracks).
Self-contained: no external media needed.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # fastapi.testclient backend
import soundfile as sf  # noqa: E402  (after importorskip)
from fastapi.testclient import TestClient  # noqa: E402

from web.app import app  # noqa: E402

FPS = 30
SECONDS = 20  # long enough that the 8 s max-consecutive cap forces a switch -> both angles
FRAMES = FPS * SECONDS  # 600


def _click_wav(path: Path, sr: int = 22050, bpm: int = 120) -> None:
    """A simple click track so madmom has clear onsets to lock beats onto."""
    n = sr * SECONDS
    sig = np.zeros(n, dtype="float32")
    step = int(sr * 60 / bpm)  # samples per beat
    burst = (0.8 * np.sin(2 * np.pi * 1000 * np.arange(int(sr * 0.04)) / sr)).astype("float32")
    for start in range(0, n - burst.size, step):
        sig[start : start + burst.size] += burst
    sf.write(str(path), sig, sr)


def _fixture_xml(wav_uri: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4"><sequence id="seq-mini">
  <duration>{FRAMES}</duration>
  <rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>
  <name>mini</name>
  <media>
    <video>
      <format><samplecharacteristics><width>1920</width><height>1080</height></samplecharacteristics></format>
      <track><clipitem id="ci1"><name>GX010001.MP4</name><start>0</start><end>{FRAMES}</end><in>0</in><out>{FRAMES}</out>
        <file id="file-1"><name>GX010001.MP4</name><pathurl>file://localhost/x/GX010001.MP4</pathurl><duration>9000</duration></file></clipitem></track>
      <track><clipitem id="ci2"><name>MVI_0001.MOV</name><start>0</start><end>{FRAMES}</end><in>0</in><out>{FRAMES}</out>
        <file id="file-2"><name>MVI_0001.MOV</name><pathurl>file://localhost/x/MVI_0001.MOV</pathurl><duration>9000</duration></file></clipitem></track>
    </video>
    <audio><track><clipitem id="ci3"><name>master.wav</name><start>0</start><end>{FRAMES}</end><in>0</in><out>{FRAMES}</out>
      <file id="file-3"><name>master.wav</name><pathurl>{wav_uri}</pathurl><duration>{FRAMES}</duration></file></clipitem></track></audio>
  </media>
</sequence></xmeml>""".encode()


def test_process_returns_valid_autocut_xml(tmp_path: Path):
    wav = tmp_path / "master.wav"
    _click_wav(wav)
    xml_bytes = _fixture_xml(wav.as_uri())

    client = TestClient(app)
    res = client.post(
        "/process",
        files={"file": ("mini.xml", xml_bytes, "text/xml")},
        data={"snap": "downbeat", "seed": "1"},
    )

    assert res.status_code == 200, res.text
    assert "mini_autocut.xml" in res.headers.get("content-disposition", "")

    root = ET.fromstring(res.content)  # well-formed
    assert root.tag == "xmeml"
    vtracks = root.findall("sequence/media/video/track")
    assert len(vtracks) >= 2  # two camera angles -> two video tracks
    clips = root.findall("sequence/media/video/track/clipitem")
    assert clips and all(c.findtext("masterclipid") for c in clips)  # exporter intact
    assert root.find("sequence/media/audio/track/clipitem") is not None  # audio re-emitted


def test_index_page_served():
    res = TestClient(app).get("/")
    assert res.status_code == 200
    assert "auto-cut" in res.text.lower()


def test_missing_master_audio_returns_clear_error():
    """An XML whose master-audio path doesn't resolve -> 400 with a clear message."""
    xml_bytes = _fixture_xml("file://localhost/does/not/exist/master.wav")
    res = TestClient(app).post("/process", files={"file": ("mini.xml", xml_bytes, "text/xml")})
    assert res.status_code == 400
    assert "Master audio not found" in res.text
