"""PPC-005 tests: fusion logic and EditDecisionList invariants.

All offline (no audio, no network). Beat grid + energy are built synthetically so each
behaviour (hysteresis, drop aggression, semantic override, staleness cap) can be isolated;
one test runs the real fake providers end-to-end (closing the PPC-004 gate).
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.contracts import (
    AngleScoreSample,
    AngleScoreTimeline,
    Angle,
    BeatGrid,
    EditParams,
    EnergyTimeline,
    Project,
    Section,
    WordCue,
)
from engine.fusion import fuse, map_brief_to_params, propose_cuts
from engine.providers import FakeAngleScorer, FakeTranscriber


# --------------------------------------------------------------------------- #
# Synthetic builders
# --------------------------------------------------------------------------- #


def make_project(duration=20.0, angle_ids=("A", "B")) -> Project:
    return Project(
        project_id="t",
        master_audio_path="/fake.wav",
        angles=[Angle(angle_id=a, media_path=f"/fake_{a}.mov") for a in angle_ids],
        duration_s=duration,
    )


def make_beatgrid(duration=20.0, bar=2.0) -> BeatGrid:
    downbeats = list(np.arange(0.0, duration, bar))
    beats = list(np.arange(0.0, duration, bar / 4))
    return BeatGrid(bpm=120.0, beats=beats, downbeats=downbeats)


def make_energy(duration=20.0, hop=0.5, level=0.9, sections=None, drops=None) -> EnergyTimeline:
    n = int(duration / hop) + 1
    if sections is None:
        sections = [Section(start=0.0, end=duration, kind="other", energy=level)]
    return EnergyTimeline(hop_s=hop, energy=[level] * n, sections=sections, drops=drops or [])


def make_scores(angle_ids, duration, interest_fn, face_fn=None, hop=0.5):
    out = []
    n = int(duration / hop) + 1
    for aid in angle_ids:
        samples = [
            AngleScoreSample(
                t=k * hop,
                interest=float(interest_fn(aid, k * hop)),
                face_visible=float((face_fn or (lambda a, t: 0.0))(aid, k * hop)),
            )
            for k in range(n)
        ]
        out.append(AngleScoreTimeline(angle_id=aid, hop_s=hop, samples=samples))
    return out


def count_switches(edl) -> int:
    d = edl.decisions
    return sum(1 for i in range(1, len(d)) if d[i].angle_id != d[i - 1].angle_id)


# --------------------------------------------------------------------------- #
# Invariants (incl. end-to-end on the real fakes -> closes PPC-004 gate)
# --------------------------------------------------------------------------- #


def assert_invariants(edl, project):
    d = edl.decisions
    assert d
    assert d[0].t_start == 0.0
    assert d[-1].t_end == pytest.approx(project.duration_s)
    real = {a.angle_id for a in project.angles}
    for i, dec in enumerate(d):
        assert dec.index == i
        assert dec.t_end > dec.t_start
        assert dec.angle_id in real
        assert dec.reason
        if i + 1 < len(d):
            assert dec.t_end == pytest.approx(d[i + 1].t_start)


def test_end_to_end_on_fakes_offline_is_valid():
    project = make_project(duration=60.0)
    bg = make_beatgrid(duration=60.0)
    energy = make_energy(
        duration=60.0,
        sections=[
            Section(start=0.0, end=20.0, kind="intro", energy=0.3),
            Section(start=20.0, end=45.0, kind="drop", energy=0.9),
            Section(start=45.0, end=60.0, kind="breakdown", energy=0.4),
        ],
        drops=[20.0],
    )
    words = FakeTranscriber(duration_s=60.0).transcribe(project.master_audio_path)
    scores = [FakeAngleScorer(duration_s=60.0).score(a, hop_s=1.0) for a in project.angles]

    edl = fuse(project, bg, energy, words, scores, EditParams())
    assert_invariants(edl, project)
    assert edl.contract_version == "0.1"
    assert len(edl.decisions) > 1


def test_single_angle_still_tiles_timeline():
    project = make_project(duration=20.0, angle_ids=("A",))
    edl = fuse(
        project,
        make_beatgrid(),
        make_energy(),
        [],
        make_scores(("A",), 20.0, lambda a, t: 0.5),
        EditParams(),
    )
    assert_invariants(edl, project)
    assert all(d.angle_id == "A" for d in edl.decisions)


# --------------------------------------------------------------------------- #
# Hysteresis (switch_penalty)
# --------------------------------------------------------------------------- #


def test_switch_penalty_reduces_jitter():
    project, bg, energy = make_project(), make_beatgrid(), make_energy()
    # A and B swap which is hotter every 2 s bin -> argmax alternates without hysteresis.
    def interest(a, t):
        hot = int(t // 2) % 2 == 0
        return 0.6 if (a == "A") == hot else 0.4

    scores = make_scores(("A", "B"), 20.0, interest)
    loose = fuse(project, bg, energy, [], scores, EditParams(switch_penalty=0.0, cut_density=1.0))
    sticky = fuse(project, bg, energy, [], scores, EditParams(switch_penalty=0.5, cut_density=1.0))
    assert count_switches(sticky) < count_switches(loose)


# --------------------------------------------------------------------------- #
# Drop aggression / energy-scaled density
# --------------------------------------------------------------------------- #


def _cuts_in(edl, t0, t1):
    return sum(1 for d in edl.decisions if t0 - 1e-6 <= d.t_start < t1 - 1e-6)


def test_higher_drop_aggression_makes_more_cuts():
    project = make_project(duration=60.0)
    bg = make_beatgrid(duration=60.0, bar=1.0)
    energy = make_energy(
        duration=60.0, level=0.5,
        sections=[Section(start=0.0, end=60.0, kind="drop", energy=0.5)],
        drops=[0.0, 30.0],
    )
    scores = make_scores(("A", "B"), 60.0, lambda a, t: 0.5)
    calm = fuse(project, bg, energy, [], scores, EditParams(drop_aggression=0.1, cut_density=0.5))
    hard = fuse(project, bg, energy, [], scores, EditParams(drop_aggression=0.9, cut_density=0.5))
    assert len(hard.decisions) > len(calm.decisions)


def test_drop_section_cuts_faster_than_non_drop_at_same_energy():
    project = make_project(duration=60.0)
    bg = make_beatgrid(duration=60.0, bar=1.0)
    energy = make_energy(
        duration=60.0, level=0.5,
        sections=[
            Section(start=0.0, end=30.0, kind="other", energy=0.5),
            Section(start=30.0, end=60.0, kind="drop", energy=0.5),
        ],
        drops=[30.0],
    )
    scores = make_scores(("A", "B"), 60.0, lambda a, t: 0.5)
    edl = fuse(project, bg, energy, [], scores, EditParams())
    assert _cuts_in(edl, 30.0, 60.0) > _cuts_in(edl, 0.0, 30.0)


# --------------------------------------------------------------------------- #
# Semantic override (hooks / to-camera -> best-face angle)
# --------------------------------------------------------------------------- #


def test_vocal_cue_biases_to_best_face_angle():
    project, bg, energy = make_project(), make_beatgrid(), make_energy()
    # A wins on interest everywhere; B is the best-face angle.
    scores = make_scores(
        ("A", "B"), 20.0,
        interest_fn=lambda a, t: 0.8 if a == "A" else 0.4,
        face_fn=lambda a, t: 0.1 if a == "A" else 0.9,
    )
    hook = [WordCue(start=10.0, end=12.0, text="feel it", kind="lyric", is_hook=True)]
    edl = fuse(
        project, bg, energy, hook, scores,
        EditParams(switch_penalty=0.0, face_bias_on_vocals=0.7, cut_density=1.0),
    )
    seg_with_cue = next(d for d in edl.decisions if d.t_start <= 10.0 < d.t_end)
    seg_no_cue = next(d for d in edl.decisions if d.t_start <= 2.0 < d.t_end)
    assert seg_with_cue.angle_id == "B"  # face bias overrides interest during the hook
    assert seg_no_cue.angle_id == "A"  # default to the higher-interest angle


# --------------------------------------------------------------------------- #
# Staleness cap (max_consecutive_s)
# --------------------------------------------------------------------------- #


def test_max_consecutive_forces_a_switch():
    project, bg, energy = make_project(), make_beatgrid(), make_energy()
    scores = make_scores(("A", "B"), 20.0, lambda a, t: 1.0 if a == "A" else 0.0)
    common = dict(switch_penalty=0.5, cut_density=1.0)
    no_cap = fuse(project, bg, energy, [], scores, EditParams(max_consecutive_s=100.0, **common))
    capped = fuse(project, bg, energy, [], scores, EditParams(max_consecutive_s=4.0, **common))
    assert all(d.angle_id == "A" for d in no_cap.decisions)  # A dominates uninterrupted
    assert any(d.angle_id == "B" for d in capped.decisions)  # cap forces B in periodically


# --------------------------------------------------------------------------- #
# NL brief -> EditParams
# --------------------------------------------------------------------------- #


def test_brief_fast_drop_raises_density_and_aggression():
    p = map_brief_to_params("fast cuts on the drop")
    assert p.cut_density == pytest.approx(0.8)
    assert p.drop_aggression == pytest.approx(1.0)


def test_brief_slow_lowers_density():
    assert map_brief_to_params("slow chill edit").cut_density < 0.5


def test_brief_face_and_snap():
    p = map_brief_to_params("favor the face on the hook, cut on the downbeat")
    assert p.face_bias_on_vocals > 0.7
    assert p.snap == "downbeat"


def test_availability_forces_only_available_angle():
    """When an angle has no footage in a window, fusion must not choose it there."""
    project, bg, energy = make_project(duration=20.0), make_beatgrid(20.0), make_energy(20.0)
    # B is the higher-interest angle everywhere, but only available for the first 10 s.
    scores = make_scores(("A", "B"), 20.0, lambda a, t: 0.9 if a == "B" else 0.4)
    availability = {"A": [(0.0, 20.0)], "B": [(0.0, 10.0)]}
    edl = fuse(
        project, bg, energy, [], scores,
        EditParams(switch_penalty=0.0, cut_density=1.0), availability=availability,
    )
    after = [d for d in edl.decisions if d.t_start >= 10.0 - 1e-6]
    before = [d for d in edl.decisions if d.t_end <= 10.0 + 1e-6]
    assert after and all(d.angle_id == "A" for d in after)  # only A after B disappears
    assert any(d.angle_id == "B" for d in before)  # B used while available
    # A forced cut lands on the availability edge so no segment straddles it.
    assert any(abs(d.t_start - 10.0) < 0.5 for d in edl.decisions)


def test_brief_changes_cut_count_end_to_end():
    project = make_project(duration=60.0)
    bg = make_beatgrid(duration=60.0, bar=1.0)
    energy = make_energy(duration=60.0, level=0.6)
    scores = make_scores(("A", "B"), 60.0, lambda a, t: 0.5)
    fast = propose_cuts(project, bg, energy, [], scores, brief="fast frantic cuts")
    slow = propose_cuts(project, bg, energy, [], scores, brief="slow chill hold")
    assert len(fast.decisions) > len(slow.decisions)
