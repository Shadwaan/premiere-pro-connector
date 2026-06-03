"""PPC-002 tests: beat grid detection.

Two layers:
- **Offline / fast** — the pure reduction logic (madmom array -> BeatGrid) and the BPM
  helper, on synthetic data. No audio, no neural net; always runs.
- **Real-audio** (`@pytest.mark.audio`) — runs the actual madmom and librosa engines on
  ``media/test_track.wav`` and checks the PPC-002 gate. Skipped if the track is absent
  (it is git-ignored), so these only run on a machine that has it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engine.audio_timing import beat_grid_from_downbeat_array, detect_beat_grid
from engine.audio_timing.beats import _bpm_from_beats
from engine.contracts import BeatGrid

TRACK = Path(__file__).resolve().parent.parent / "media" / "test_track.wav"
PROJECT_FPS = 30.0
ONE_FRAME_S = 1.0 / PROJECT_FPS


# --------------------------------------------------------------------------- #
# Offline: pure reduction logic
# --------------------------------------------------------------------------- #


def _synthetic_downbeat_array(bpm: float, n_beats: int) -> np.ndarray:
    """A perfect 4/4 grid as madmom would emit it: (N, 2) of [time, bar_position]."""
    ibi = 60.0 / bpm
    times = np.arange(n_beats) * ibi
    positions = (np.arange(n_beats) % 4) + 1  # 1,2,3,4,1,2,3,4,...
    return np.column_stack([times, positions])


def test_bpm_from_beats_exact():
    beats = [i * 0.5 for i in range(10)]  # 0.5 s IBI -> 120 BPM
    assert _bpm_from_beats(beats) == pytest.approx(120.0)


def test_bpm_from_beats_degenerate():
    assert _bpm_from_beats([]) == 0.0
    assert _bpm_from_beats([1.23]) == 0.0


def test_reduction_extracts_beats_and_downbeats():
    raw = _synthetic_downbeat_array(bpm=128.0, n_beats=16)
    grid = beat_grid_from_downbeat_array(raw)
    assert isinstance(grid, BeatGrid)
    assert len(grid.beats) == 16
    # downbeats are positions == 1 -> every 4th beat -> 4 of them
    assert len(grid.downbeats) == 4
    assert grid.downbeats == pytest.approx([0.0, 4 * (60 / 128), 8 * (60 / 128), 12 * (60 / 128)])
    assert grid.bpm == pytest.approx(128.0)
    # downbeats must be a subset of beats
    assert set(grid.downbeats).issubset(set(grid.beats))


def test_reduction_rejects_bad_shape():
    with pytest.raises(ValueError):
        beat_grid_from_downbeat_array(np.zeros((5,)))  # 1-D, not (N, 2)
    with pytest.raises(ValueError):
        beat_grid_from_downbeat_array(np.zeros((5, 3)))  # wrong width


# --------------------------------------------------------------------------- #
# Real audio: the PPC-002 gate
# --------------------------------------------------------------------------- #

requires_track = pytest.mark.skipif(
    not TRACK.exists(), reason=f"test track not present at {TRACK} (git-ignored)"
)


@pytest.fixture(scope="session")
def madmom_grid() -> BeatGrid:
    """Run the real madmom pipeline once and share it across the audio tests."""
    if not TRACK.exists():
        pytest.skip(f"test track not present at {TRACK}")
    return detect_beat_grid(str(TRACK), engine="madmom")


@pytest.mark.audio
@requires_track
def test_madmom_grid_is_well_formed(madmom_grid: BeatGrid):
    g = madmom_grid
    assert len(g.beats) > 100  # a 5.5-min track has hundreds of beats
    assert g.beats == sorted(g.beats)  # monotonic, ordered times
    assert set(g.downbeats).issubset(set(g.beats))  # downbeats are real beats
    assert 60.0 < g.bpm < 200.0  # plausible musical tempo


@pytest.mark.audio
@requires_track
def test_madmom_bpm_matches_house_track(madmom_grid: BeatGrid):
    # "Biscits - Voodoo" is a ~128 BPM house track.
    assert madmom_grid.bpm == pytest.approx(128.0, abs=2.0)


@pytest.mark.audio
@requires_track
def test_grid_is_frame_stable(madmom_grid: BeatGrid):
    """Gate proxy for '±1 frame of manual taps': the grid must be frame-accurate.

    A steady 4/4 track has a near-constant inter-beat interval. We require >=95% of
    inter-beat intervals to fall within +-1 frame (1/30 s) of the median IBI — the same
    95% / +-1-frame bar PRD §8 sets for cut accuracy. Literal manual-tap comparison
    needs user-tapped ground truth; see BUILD_LOG (PPC-002).
    """
    ibis = np.diff(np.asarray(madmom_grid.beats))
    median = np.median(ibis)
    within = np.abs(ibis - median) <= ONE_FRAME_S
    frac = within.mean()
    assert frac >= 0.95, f"only {frac:.1%} of inter-beat intervals within +-1 frame"


@pytest.mark.audio
@requires_track
def test_downbeats_every_four_beats(madmom_grid: BeatGrid):
    """4/4: downbeat spacing should be ~4x the beat interval."""
    beat_ibi = np.median(np.diff(np.asarray(madmom_grid.beats)))
    db_spacing = np.median(np.diff(np.asarray(madmom_grid.downbeats)))
    assert db_spacing == pytest.approx(4 * beat_ibi, rel=0.05)


@pytest.mark.audio
@requires_track
def test_librosa_fallback_agrees_on_tempo(madmom_grid: BeatGrid):
    """The librosa fallback should produce a valid grid whose tempo agrees with madmom
    after octave normalization (librosa sometimes locks to half/double tempo)."""
    g = detect_beat_grid(str(TRACK), engine="librosa")
    assert isinstance(g, BeatGrid)
    assert len(g.beats) > 100
    assert g.bpm > 0

    def octave_norm(bpm: float) -> float:
        while bpm < 90:
            bpm *= 2
        while bpm > 180:
            bpm /= 2
        return bpm

    assert octave_norm(g.bpm) == pytest.approx(octave_norm(madmom_grid.bpm), abs=3.0)
