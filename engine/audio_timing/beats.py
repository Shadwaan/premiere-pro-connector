"""Beat grid detection (PPC-002).

Primary engine: **madmom** ``RNNDownBeatProcessor`` -> ``DBNDownBeatTrackingProcessor``,
the accuracy pick for offline analysis (ARCHITECTURE §5). Fallback: **librosa**
``beat.beat_track`` (no downbeat model — downbeats are inferred as every 4th beat).

The pure reduction step (madmom result array -> ``BeatGrid``) is split out as
``beat_grid_from_downbeat_array`` so it can be unit-tested offline without running the
neural net or touching audio.

All times are float seconds, absolute from t=0 (CONTRACTS.md timeline invariant).
"""

from __future__ import annotations

import warnings
from typing import Literal, Sequence

import numpy as np

from engine.contracts import BeatGrid

# madmom's RNN activations are sampled at 100 fps; the DBN tracker must match.
DEFAULT_ACT_FPS = 100
# DJ/EDM material is 4/4. Restricting the meter to 4 beats per bar makes downbeat
# tracking markedly more reliable than letting madmom also consider 3/4.
DEFAULT_BEATS_PER_BAR: tuple[int, ...] = (4,)

Engine = Literal["auto", "madmom", "librosa"]


def _bpm_from_beats(beats: Sequence[float]) -> float:
    """Tempo from the median inter-beat interval — robust to a few outlier beats."""
    arr = np.asarray(beats, dtype=float)
    if arr.size < 2:
        return 0.0
    ibis = np.diff(arr)
    ibis = ibis[ibis > 0]
    if ibis.size == 0:
        return 0.0
    return float(60.0 / np.median(ibis))


def beat_grid_from_downbeat_array(raw: np.ndarray) -> BeatGrid:
    """Reduce a ``DBNDownBeatTrackingProcessor`` result into a ``BeatGrid``.

    ``raw`` has shape ``(N, 2)``: column 0 is the beat time in seconds, column 1 is the
    1-based beat position within the bar (position ``1`` == downbeat / bar start).
    """
    arr = np.asarray(raw, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(
            f"expected a (N, 2) [time, bar_position] array, got shape {arr.shape}"
        )
    times = arr[:, 0]
    positions = arr[:, 1]
    beats = [float(t) for t in times]
    downbeats = [float(t) for t in times[np.isclose(positions, 1.0)]]
    return BeatGrid(bpm=_bpm_from_beats(beats), beats=beats, downbeats=downbeats)


def detect_beat_grid(
    audio_path: str,
    *,
    engine: Engine = "auto",
    beats_per_bar: Sequence[int] = DEFAULT_BEATS_PER_BAR,
    fps: int = DEFAULT_ACT_FPS,
) -> BeatGrid:
    """Detect beats, downbeats and BPM for ``audio_path``.

    ``engine="auto"`` (default) uses madmom and falls back to librosa if madmom is
    unavailable or errors. ``"madmom"`` / ``"librosa"`` force one engine.
    """
    if engine in ("auto", "madmom"):
        try:
            return _madmom_beat_grid(audio_path, beats_per_bar=beats_per_bar, fps=fps)
        except Exception:
            if engine == "madmom":
                raise
            # auto: degrade to librosa rather than failing the whole pipeline.
    return _librosa_beat_grid(audio_path)


def _madmom_beat_grid(
    audio_path: str, *, beats_per_bar: Sequence[int], fps: int
) -> BeatGrid:
    from madmom.features.downbeats import (
        DBNDownBeatTrackingProcessor,
        RNNDownBeatProcessor,
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        activations = RNNDownBeatProcessor()(str(audio_path))
        tracker = DBNDownBeatTrackingProcessor(
            beats_per_bar=list(beats_per_bar), fps=fps
        )
        raw = tracker(activations)
    return beat_grid_from_downbeat_array(raw)


def _librosa_beat_grid(audio_path: str) -> BeatGrid:
    """Fallback beat grid. librosa has no downbeat model, so downbeats are inferred as
    every 4th beat (assumes 4/4) — coarser than madmom, but keeps the engine running."""
    import librosa

    y, sr = librosa.load(str(audio_path), mono=True)
    _tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beats = [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
    downbeats = beats[::4]  # assume 4/4 bar starts
    return BeatGrid(bpm=_bpm_from_beats(beats), beats=beats, downbeats=downbeats)
