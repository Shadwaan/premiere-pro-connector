"""Fake providers (PPC-004) — deterministic, offline, no network, no media files.

These satisfy the protocols in ``base.py`` and let fusion (PPC-005) and the CLI (PPC-007)
run end-to-end without the hosted Modal services (AGENTS.md §2, golden rule 3: fakes
before networks). They are **test scaffolding**, not engine logic — the data is plausible
but synthetic, and intentionally generic (nothing here is tuned to a specific track).

Determinism: every output is a pure function of the constructor config + the input
arguments (angle id / requested hop). Seeds are derived from a stable hash of the angle id
so different angles get different — but reproducible — interest curves, giving fusion a
real choice to make. No randomness leaks in via Python's salted ``hash()``.
"""

from __future__ import annotations

import zlib

import numpy as np

from engine.contracts import (
    Angle,
    AngleScoreSample,
    AngleScoreTimeline,
    WordCue,
)

_DEFAULT_DURATION_S = 120.0


def _stable_seed(base_seed: int, key: str) -> int:
    """Reproducible 32-bit seed from a base seed + a string (CRC32, not salted hash)."""
    return (base_seed * 1_000_003 + zlib.crc32(key.encode("utf-8"))) % (2**32)


def _smooth_curve(n: int, rng: np.random.RandomState, n_components: int = 5) -> np.ndarray:
    """A smooth, deterministic 0..1 curve: sum of random sinusoids, min-max normalized."""
    if n <= 0:
        return np.zeros(0)
    if n == 1:
        return np.array([float(rng.uniform(0.0, 1.0))])
    t = np.linspace(0.0, 1.0, n)
    curve = np.zeros(n)
    for _ in range(n_components):
        freq = rng.uniform(0.5, 6.0)
        phase = rng.uniform(0.0, 2 * np.pi)
        amp = rng.uniform(0.3, 1.0)
        curve += amp * np.sin(2 * np.pi * freq * t + phase)
    span = float(curve.max() - curve.min())
    if span <= 1e-12:
        return np.full(n, 0.5)
    return (curve - curve.min()) / span


class FakeTranscriber:
    """A ``TranscriberProvider`` that returns a fixed, deterministic set of word cues.

    By default it places a few generic cues (an intro to-camera line, two repeated lyric
    hooks, a closing to-camera line) at fractions of ``duration_s`` so they land inside any
    track. Pass ``cues=`` to inject an explicit list instead.
    """

    def __init__(
        self,
        *,
        duration_s: float | None = None,
        cues: list[WordCue] | None = None,
    ) -> None:
        self._duration_s = duration_s
        self._cues = list(cues) if cues is not None else None

    def transcribe(self, audio_path: str) -> list[WordCue]:  # noqa: ARG002 - path unused by design
        if self._cues is not None:
            return [c.model_copy(deep=True) for c in self._cues]
        return self._default_cues(self._duration_s or _DEFAULT_DURATION_S)

    @staticmethod
    def _default_cues(d: float) -> list[WordCue]:
        def cue(frac: float, dur: float, text: str, kind: str, **kw) -> WordCue:
            start = frac * d
            end = min(start + dur, d)
            return WordCue(start=start, end=end, text=text, kind=kind, **kw)

        return [
            cue(0.06, 2.0, "yo what is up everybody", "speech", speaker="DJ", to_camera=True),
            cue(0.30, 1.5, "feel the rhythm", "lyric", is_hook=True),
            cue(0.60, 1.5, "feel the rhythm", "lyric", is_hook=True),
            cue(0.85, 2.0, "let's go", "speech", speaker="DJ", to_camera=True),
        ]


class FakeAngleScorer:
    """An ``AngleScoringProvider`` that synthesizes a deterministic interest timeline.

    The protocol's ``score(angle, hop_s)`` carries no duration, so the duration is provided
    at construction (the CLI/test knows the master timeline length). Each angle gets its own
    seeded smooth curves for interest / face_visible / motion, so different angles differ
    but every run is reproducible.
    """

    def __init__(self, *, duration_s: float, seed: int = 0) -> None:
        if duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        self._duration_s = float(duration_s)
        self._seed = seed

    def score(self, angle: Angle, hop_s: float) -> AngleScoreTimeline:
        if hop_s <= 0:
            raise ValueError("hop_s must be > 0")
        n = int(self._duration_s // hop_s) + 1  # samples at 0, hop, 2*hop, ... <= duration
        rng = np.random.RandomState(_stable_seed(self._seed, angle.angle_id))
        interest = _smooth_curve(n, rng)
        face = _smooth_curve(n, rng)
        motion = _smooth_curve(n, rng)
        samples = [
            AngleScoreSample(
                t=round(k * hop_s, 6),
                interest=float(interest[k]),
                face_visible=float(face[k]),
                motion=float(motion[k]),
                note=f"fake[{angle.angle_id}] t={k * hop_s:.1f}s",
            )
            for k in range(n)
        ]
        return AngleScoreTimeline(angle_id=angle.angle_id, hop_s=hop_s, samples=samples)
