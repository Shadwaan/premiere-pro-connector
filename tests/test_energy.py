"""PPC-003 tests: energy curve, section detection, drop detection.

- **Offline / fast** — section & drop logic on a synthetic energy profile with known
  structure (intro/build/dip/drop/breakdown/drop/outro). No audio; always runs.
- **Real-audio** (`@pytest.mark.audio`) — runs the full pipeline on
  ``media/test_track.wav``: asserts the curve is normalized, sections tile the timeline
  with no gaps, and drops is non-empty. Skipped if the track is absent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engine.audio_timing import (
    analyze,
    compute_energy_timeline,
    detect_drops_from_energy,
    detect_sections_from_energy,
)
from engine.audio_timing.energy import _moving_average, _normalize_01
from engine.contracts import BeatGrid, EnergyTimeline, Section

TRACK = Path(__file__).resolve().parent.parent / "media" / "test_track.wav"
HOP_S = 0.1

# (duration_s, start_value, end_value); jumps between segments are sharp (endpoint=False).
SYNTH_SEGMENTS = [
    (10, 0.10, 0.10),  # intro    [0, 10)
    (12, 0.10, 0.55),  # build    [10, 22)
    (2, 0.55, 0.12),   # dip      [22, 24)
    (20, 0.90, 0.90),  # drop 1   [24, 44)   <- sharp rise at t=24
    (14, 0.15, 0.15),  # breakdown[44, 58)
    (20, 0.90, 0.90),  # drop 2   [58, 78)   <- sharp rise at t=58
    (10, 0.10, 0.10),  # outro    [78, 88)
]
EXPECTED_DROPS = [24.0, 58.0]
SYNTH_DURATION = 88.0


def _build_profile(segments, hop_s=HOP_S) -> np.ndarray:
    parts = []
    for dur, v0, v1 in segments:
        k = max(1, round(dur / hop_s))
        parts.append(np.linspace(v0, v1, k, endpoint=False))
    return np.concatenate(parts)


# --------------------------------------------------------------------------- #
# Offline: pure helpers
# --------------------------------------------------------------------------- #


def test_normalize_01_range_and_constant():
    out = _normalize_01(np.array([2.0, 4.0, 6.0]))
    assert out.min() == 0.0 and out.max() == 1.0
    assert np.allclose(_normalize_01(np.array([5.0, 5.0, 5.0])), 0.0)


def test_moving_average_preserves_length_and_smooths():
    x = np.array([0.0, 10.0, 0.0, 10.0, 0.0])
    sm = _moving_average(x, 3)
    assert sm.shape == x.shape
    assert sm.max() < x.max()  # peaks are attenuated


# --------------------------------------------------------------------------- #
# Offline: drop detection
# --------------------------------------------------------------------------- #


def test_drop_detection_finds_both_sharp_rises():
    energy = _build_profile(SYNTH_SEGMENTS)
    drops = detect_drops_from_energy(energy, HOP_S)
    assert len(drops) == 2, f"expected 2 drops, got {drops}"
    for got, expected in zip(drops, EXPECTED_DROPS):
        assert abs(got - expected) <= 0.8, f"drop {got:.2f}s far from {expected:.2f}s"


def test_drop_detection_quiet_signal_has_no_drops():
    energy = _build_profile([(60, 0.3, 0.3)])  # flat, no rise
    assert detect_drops_from_energy(energy, HOP_S) == []


# --------------------------------------------------------------------------- #
# Offline: section detection
# --------------------------------------------------------------------------- #


def _assert_tiles(sections: list[Section], duration_s: float):
    assert sections, "no sections produced"
    assert sections[0].start == 0.0
    assert sections[-1].end == pytest.approx(duration_s)
    for a, b in zip(sections, sections[1:]):
        assert a.end == pytest.approx(b.start), "gap/overlap between sections"
    for s in sections:
        assert s.end > s.start
        assert 0.0 <= s.energy <= 1.0


def test_sections_tile_timeline_with_no_gaps():
    energy = _build_profile(SYNTH_SEGMENTS)
    sections = detect_sections_from_energy(energy, HOP_S, SYNTH_DURATION)
    _assert_tiles(sections, SYNTH_DURATION)


def test_sections_label_high_energy_as_drop():
    energy = _build_profile(SYNTH_SEGMENTS)
    sections = detect_sections_from_energy(energy, HOP_S, SYNTH_DURATION)
    kinds = [s.kind for s in sections]
    assert "drop" in kinds, f"no drop section in {kinds}"
    # The highest-energy section should be a drop.
    hottest = max(sections, key=lambda s: s.energy)
    assert hottest.kind == "drop"


def test_sections_empty_energy_covers_timeline():
    sections = detect_sections_from_energy(np.array([]), HOP_S, 30.0)
    _assert_tiles(sections, 30.0)


# --------------------------------------------------------------------------- #
# Real audio: the PPC-003 pipeline
# --------------------------------------------------------------------------- #

requires_track = pytest.mark.skipif(
    not TRACK.exists(), reason=f"test track not present at {TRACK} (git-ignored)"
)


@pytest.fixture(scope="session")
def energy_timeline() -> EnergyTimeline:
    if not TRACK.exists():
        pytest.skip(f"test track not present at {TRACK}")
    return compute_energy_timeline(str(TRACK))


@pytest.mark.audio
@requires_track
def test_energy_curve_is_normalized(energy_timeline: EnergyTimeline):
    e = np.asarray(energy_timeline.energy)
    assert e.size > 100
    assert e.min() >= 0.0 and e.max() <= 1.0
    assert energy_timeline.hop_s > 0


@pytest.mark.audio
@requires_track
def test_sections_tile_real_timeline(energy_timeline: EnergyTimeline):
    secs = energy_timeline.sections
    assert secs[0].start == 0.0
    for a, b in zip(secs, secs[1:]):
        assert a.end == pytest.approx(b.start)  # no gaps
    assert secs[-1].end > 300.0  # track is ~335 s
    for s in secs:
        assert 0.0 <= s.energy <= 1.0


@pytest.mark.audio
@requires_track
def test_drops_detected_on_real_track(energy_timeline: EnergyTimeline):
    assert len(energy_timeline.drops) >= 1
    assert all(d >= 0.0 for d in energy_timeline.drops)


@pytest.mark.audio
@requires_track
def test_analyze_returns_beatgrid_and_energy():
    bg, el = analyze(str(TRACK))
    assert isinstance(bg, BeatGrid)
    assert isinstance(el, EnergyTimeline)
    assert len(bg.beats) > 100
    assert len(el.energy) > 100
