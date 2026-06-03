"""Composing entrypoint: ``analyze(audio_path) -> (BeatGrid, EnergyTimeline)``.

This is the public surface CONTRACTS.md promises for the local ``audio_timing`` analyzer.
It runs the PPC-002 beat grid and the PPC-003 energy timeline together over the same
master-audio file, both on the shared absolute-seconds timeline.
"""

from __future__ import annotations

from engine.audio_timing.beats import Engine, detect_beat_grid
from engine.audio_timing.energy import DEFAULT_HOP_S, DEFAULT_SR, compute_energy_timeline
from engine.contracts import BeatGrid, EnergyTimeline


def analyze(
    audio_path: str,
    *,
    beat_engine: Engine = "auto",
    energy_hop_s: float = DEFAULT_HOP_S,
    sr: int = DEFAULT_SR,
) -> tuple[BeatGrid, EnergyTimeline]:
    """Analyze the master audio into a ``(BeatGrid, EnergyTimeline)`` pair."""
    beat_grid = detect_beat_grid(audio_path, engine=beat_engine)
    energy_timeline = compute_energy_timeline(audio_path, hop_s=energy_hop_s, sr=sr)
    return beat_grid, energy_timeline
