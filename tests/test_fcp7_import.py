"""PPC-007 tests: FCP7 XML import (synthetic always; real Koshto set guarded)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.fcp7_import import choose_master_audio, parse_fcp7xml

SYNTHETIC = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
  <sequence id="sequence-1">
    <duration>300</duration>
    <rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>
    <name>demo</name>
    <media>
      <video>
        <format><samplecharacteristics><width>1920</width><height>1080</height></samplecharacteristics></format>
        <track>
          <clipitem id="clipitem-1">
            <name>GX010001.MP4</name><start>0</start><end>100</end><in>5</in><out>105</out>
            <file id="file-1"><name>GX010001.MP4</name>
              <pathurl>file://localhost/D%3a/foot/GX010001.MP4</pathurl><duration>500</duration></file>
            <filter><effect><name>Distort</name></effect></filter>
          </clipitem>
          <clipitem id="clipitem-2">
            <name>GX020001.MP4</name><start>100</start><end>200</end><in>0</in><out>100</out>
            <file id="file-2"><name>GX020001.MP4</name>
              <pathurl>file://localhost/D%3a/foot/GX020001.MP4</pathurl><duration>500</duration></file>
          </clipitem>
        </track>
        <track>
          <clipitem id="clipitem-3">
            <name>MVI_0001.MOV</name><start>0</start><end>120</end><in>9</in><out>129</out>
            <file id="file-3"><name>MVI_0001.MOV</name>
              <pathurl>file://localhost/D%3a/foot/MVI_0001.MOV</pathurl><duration>500</duration></file>
          </clipitem>
        </track>
      </video>
      <audio>
        <track>
          <clipitem id="clipitem-5"><name>Master.wav</name><start>6</start><end>290</end><in>1</in><out>285</out>
            <file id="file-5"><name>Master.wav</name>
              <pathurl>file://localhost/D%3a/mus/Master.wav</pathurl><duration>285</duration></file>
          </clipitem>
        </track>
      </audio>
    </media>
  </sequence>
</xmeml>
"""


def test_parse_synthetic(tmp_path: Path):
    f = tmp_path / "demo.xml"
    f.write_text(SYNTHETIC, encoding="utf-8")
    seq = parse_fcp7xml(str(f))

    assert abs(seq.fps - 30000 / 1001) < 0.01  # 29.97
    assert (seq.timebase, seq.ntsc) == (30, True)
    assert seq.duration_f == 300
    assert (seq.width, seq.height) == (1920, 1080)

    # Two non-empty video tracks -> two angles; first is GoPro (2 files), second DSLR.
    assert [a.angle_id for a in seq.angles] == ["GoPro", "DSLR"]
    gopro = seq.angles[0]
    assert len(gopro.segments) == 2
    assert gopro.segments[0].src_in_f == 5  # source in-point preserved
    assert gopro.segments[0].file_path == "D:/foot/GX010001.MP4"
    assert gopro.segments[0].filters_xml  # Distort captured
    assert seq.angles[1].segments[0].src_in_f == 9

    master = choose_master_audio(seq)
    assert master.file_name == "Master.wav"
    assert master.tl_start_f == 6 and master.src_in_f == 1


def test_availability_from_synthetic(tmp_path: Path):
    f = tmp_path / "demo.xml"
    f.write_text(SYNTHETIC, encoding="utf-8")
    seq = parse_fcp7xml(str(f))
    fps = seq.fps
    gopro, dslr = seq.angles
    assert gopro.availability_s(fps) == [(0.0, 200 / fps)]  # contiguous 2 files
    assert dslr.availability_s(fps) == [(0.0, 120 / fps)]  # ends earlier (the real gap)


# --------------------------------------------------------------------------- #
# Real Koshto set (guarded)
# --------------------------------------------------------------------------- #

KOSHTO = Path(r"D:/All Video Content/Koshto/koshtoset.xml")


@pytest.mark.skipif(not KOSHTO.exists(), reason="real Koshto FCP7 XML not present")
def test_parse_real_koshto():
    seq = parse_fcp7xml(str(KOSHTO))
    assert abs(seq.fps - 30000 / 1001) < 0.01
    assert seq.duration_f == 52840
    assert [a.angle_id for a in seq.angles] == ["GoPro", "DSLR"]
    gopro, dslr = seq.angles
    assert [s.file_name for s in gopro.segments] == ["GX010465.MP4", "GX020465.MP4"]
    assert [s.file_name for s in dslr.segments] == ["MVI_4017.MOV", "MVI_4018.MOV"]
    assert all(s.filters_xml for s in dslr.segments)  # DSLR Distort on both files
    assert gopro.segments[0].src_in_f == 1034
    assert dslr.segments[0].src_in_f == 899
    # DSLR ends before GoPro (the availability gap).
    assert dslr.coverage_f()[1] < gopro.coverage_f()[1]
    master = choose_master_audio(seq)
    assert "Master.wav" in master.file_name
    assert master.file_path.endswith("Balcony Sessions Ep 4 Koshto Master.wav")
