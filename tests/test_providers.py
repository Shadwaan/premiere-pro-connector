"""PPC-004 tests: provider protocols + fakes run fully offline.

No network, no media files: the fakes are deterministic pure functions of their config.
The final test assembles exactly the inputs fusion (PPC-005) will consume, proving the
provider layer produces them with no I/O.
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.contracts import Angle, AngleScoreTimeline, Project, WordCue
from engine.providers import (
    AngleScoringProvider,
    FakeAngleScorer,
    FakeTranscriber,
    TranscriberProvider,
)

NONEXISTENT = "/does/not/exist/cam.mov"  # proves the fakes never touch the filesystem


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #


def test_fakes_satisfy_protocols():
    assert isinstance(FakeTranscriber(), TranscriberProvider)
    assert isinstance(FakeAngleScorer(duration_s=60.0), AngleScoringProvider)


# --------------------------------------------------------------------------- #
# FakeTranscriber
# --------------------------------------------------------------------------- #


def test_transcriber_returns_wordcues_within_duration():
    cues = FakeTranscriber(duration_s=200.0).transcribe(NONEXISTENT)
    assert cues and all(isinstance(c, WordCue) for c in cues)
    for c in cues:
        assert 0.0 <= c.start <= c.end <= 200.0


def test_transcriber_is_deterministic_and_path_independent():
    t = FakeTranscriber(duration_s=200.0)
    assert t.transcribe(NONEXISTENT) == t.transcribe("/some/other/path.wav")


def test_transcriber_surfaces_hooks_and_to_camera():
    cues = FakeTranscriber(duration_s=200.0).transcribe(NONEXISTENT)
    assert any(c.is_hook for c in cues), "fake should surface at least one hook"
    assert any(c.to_camera for c in cues), "fake should surface a to-camera cue"
    assert any(c.kind == "lyric" for c in cues)
    assert any(c.kind == "speech" for c in cues)


def test_transcriber_accepts_injected_cues():
    injected = [WordCue(start=1.0, end=2.0, text="hi", kind="speech")]
    out = FakeTranscriber(cues=injected).transcribe(NONEXISTENT)
    assert out == injected
    assert out is not injected  # returns copies, caller can't mutate internals


# --------------------------------------------------------------------------- #
# FakeAngleScorer
# --------------------------------------------------------------------------- #


def _interest(timeline: AngleScoreTimeline) -> np.ndarray:
    return np.array([s.interest for s in timeline.samples])


def test_scorer_timeline_shape_and_grid():
    scorer = FakeAngleScorer(duration_s=100.0)
    tl = scorer.score(Angle(angle_id="A", media_path=NONEXISTENT), hop_s=1.0)
    assert isinstance(tl, AngleScoreTimeline)
    assert tl.angle_id == "A"
    assert tl.hop_s == 1.0
    ts = [s.t for s in tl.samples]
    assert ts[0] == 0.0
    assert ts == sorted(ts)  # monotonic
    assert ts[-1] <= 100.0 and ts[-1] >= 100.0 - 1.0  # covers [0, duration]


def test_scorer_fields_in_unit_range():
    tl = FakeAngleScorer(duration_s=50.0).score(
        Angle(angle_id="A", media_path=NONEXISTENT), hop_s=0.5
    )
    for s in tl.samples:
        assert 0.0 <= s.interest <= 1.0
        assert 0.0 <= s.face_visible <= 1.0
        assert 0.0 <= s.motion <= 1.0


def test_scorer_is_deterministic():
    a = FakeAngleScorer(duration_s=50.0, seed=7)
    b = FakeAngleScorer(duration_s=50.0, seed=7)
    angle = Angle(angle_id="cam_balcony", media_path=NONEXISTENT)
    assert a.score(angle, 1.0) == b.score(angle, 1.0)


def test_scorer_distinguishes_angles():
    """Different angles must get different interest curves so fusion has a real choice."""
    scorer = FakeAngleScorer(duration_s=80.0)
    a = _interest(scorer.score(Angle(angle_id="A", media_path=NONEXISTENT), 1.0))
    b = _interest(scorer.score(Angle(angle_id="B", media_path=NONEXISTENT), 1.0))
    assert a.shape == b.shape
    assert not np.allclose(a, b)


def test_scorer_validates_args():
    with pytest.raises(ValueError):
        FakeAngleScorer(duration_s=0.0)
    with pytest.raises(ValueError):
        FakeAngleScorer(duration_s=10.0).score(
            Angle(angle_id="A", media_path=NONEXISTENT), hop_s=0.0
        )


# --------------------------------------------------------------------------- #
# Offline data flow: everything fusion (PPC-005) needs, no network/files
# --------------------------------------------------------------------------- #


def test_provider_layer_produces_fusion_inputs_offline():
    project = Project(
        project_id="p1",
        master_audio_path="/fake/master.wav",
        angles=[
            Angle(angle_id="A", media_path=NONEXISTENT, label="wide"),
            Angle(angle_id="B", media_path=NONEXISTENT, label="close"),
        ],
        duration_s=80.0,
    )
    transcriber: TranscriberProvider = FakeTranscriber(duration_s=project.duration_s)
    scorer: AngleScoringProvider = FakeAngleScorer(duration_s=project.duration_s)

    words = transcriber.transcribe(project.master_audio_path)
    timelines = [scorer.score(a, hop_s=1.0) for a in project.angles]

    assert all(isinstance(w, WordCue) for w in words)
    assert [tl.angle_id for tl in timelines] == ["A", "B"]
    assert all(tl.samples for tl in timelines)
