"""audio_timing — local beat/energy analysis (ARCHITECTURE §2.1, §5).

This package is the one **new** analyzer that runs locally (not a Modal provider). It
exposes the composing entrypoint CONTRACTS.md promises:

    analyze(audio_path) -> (BeatGrid, EnergyTimeline)

- PPC-002: beat grid (beats / downbeats / BPM) — ``beats.py``.
- PPC-003: energy curve + section/drop detection — ``energy.py``.

Timeline invariant: every timestamp returned is float seconds, absolute from t=0 of the
master audio (CONTRACTS.md).
"""

from engine.audio_timing.analyze import analyze
from engine.audio_timing.beats import (
    beat_grid_from_downbeat_array,
    detect_beat_grid,
)
from engine.audio_timing.energy import (
    compute_energy_timeline,
    detect_drops_from_energy,
    detect_sections_from_energy,
)

__all__ = [
    "analyze",
    "detect_beat_grid",
    "beat_grid_from_downbeat_array",
    "compute_energy_timeline",
    "detect_sections_from_energy",
    "detect_drops_from_energy",
]
