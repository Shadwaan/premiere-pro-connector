"""Provider protocols (PPC-004).

The engine depends on these interfaces, never on Modal/HTTP specifics (AGENTS.md §2,
ARCHITECTURE §2.2 — the `app.providers` pattern from multimodal-transcriber). The hosted
`clip` and transcriber services get real adapters in Phase 1; in Phase 0 the fakes in
``fakes.py`` stand in so the whole engine runs offline.

These are the exact shapes from CONTRACTS.md ("Provider protocols (adapters)"). All times
the providers emit are float seconds, absolute from t=0 (timeline invariant).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from engine.contracts import Angle, AngleScoreTimeline, WordCue


@runtime_checkable
class TranscriberProvider(Protocol):
    """Maps an audio file to timestamped word cues (speech / mimicked lyrics)."""

    def transcribe(self, audio_path: str) -> list[WordCue]: ...


@runtime_checkable
class AngleScoringProvider(Protocol):
    """Scores one camera angle over time on a coarse grid (sampled, not per-frame)."""

    def score(self, angle: Angle, hop_s: float) -> AngleScoreTimeline: ...
