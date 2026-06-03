"""audio_timing — local beat/energy analysis (ARCHITECTURE §2.1, §5).

This package is the one **new** analyzer that runs locally (not a Modal provider).
PPC-002 implements the beat grid (beats / downbeats / BPM); PPC-003 will add the energy
curve + section/drop detection and the composing ``analyze(audio_path) -> (BeatGrid,
EnergyTimeline)`` entrypoint promised in CONTRACTS.md.

Timeline invariant: every timestamp returned is float seconds, absolute from t=0 of the
master audio (CONTRACTS.md).
"""

from engine.audio_timing.beats import (
    beat_grid_from_downbeat_array,
    detect_beat_grid,
)

__all__ = ["detect_beat_grid", "beat_grid_from_downbeat_array"]
