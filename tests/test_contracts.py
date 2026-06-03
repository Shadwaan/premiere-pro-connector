"""PPC-001 gate: every contract model imports and round-trips.

Builds a fake instance of every Pydantic model in ``engine.contracts`` and asserts it
survives a dict round-trip (``model_dump`` -> ``model_validate``) and a JSON round-trip
(``model_dump_json`` -> ``model_validate_json``) unchanged. A completeness guard ensures
no model can be added to the contract without a corresponding fake here.
"""

from __future__ import annotations

import inspect

import pytest

from engine import contracts
from engine.contracts import (
    Angle,
    AngleScoreSample,
    AngleScoreTimeline,
    BeatGrid,
    EditDecision,
    EditDecisionList,
    EditParams,
    EnergyTimeline,
    Project,
    Section,
    WordCue,
)


def make_fakes() -> dict[type, object]:
    """One representative, non-default fake per contract model.

    Non-default field values are used deliberately so the round-trip would catch a field
    that is dropped, renamed, or silently defaulted.
    """
    angle_a = Angle(angle_id="A", media_path="/abs/cam_a.mov", label="wide balcony")
    angle_b = Angle(angle_id="B", media_path="/abs/cam_b.mov")  # label defaults to None

    project = Project(
        project_id="proj_001",
        master_audio_path="/abs/master.wav",
        angles=[angle_a, angle_b],
        fps=23.976,
        duration_s=212.5,
    )

    beat_grid = BeatGrid(
        bpm=128.0,
        beats=[0.0, 0.469, 0.938, 1.406],
        downbeats=[0.0, 1.875],
    )

    section = Section(start=0.0, end=16.0, kind="build", energy=0.62)

    energy_timeline = EnergyTimeline(
        hop_s=0.1,
        energy=[0.0, 0.25, 0.5, 0.75, 1.0],
        sections=[
            Section(start=0.0, end=16.0, kind="intro", energy=0.2),
            Section(start=16.0, end=32.0, kind="drop", energy=0.95),
        ],
        drops=[16.0],
    )

    word_cue = WordCue(
        start=12.0,
        end=12.8,
        text="here we go",
        kind="speech",
        speaker="DJ",
        is_hook=True,
        to_camera=True,
    )

    angle_score_sample = AngleScoreSample(
        t=4.0,
        interest=0.8,
        face_visible=0.9,
        motion=0.3,
        note="DJ centered, good light",
    )

    angle_score_timeline = AngleScoreTimeline(
        angle_id="A",
        hop_s=1.0,
        samples=[
            AngleScoreSample(t=0.0, interest=0.4),
            AngleScoreSample(t=1.0, interest=0.7, face_visible=0.5, motion=0.2, note="x"),
        ],
    )

    edit_params = EditParams(
        cut_density=0.7,
        drop_aggression=0.9,
        face_bias_on_vocals=0.6,
        min_shot_len_s=0.4,
        switch_penalty=0.25,
        max_consecutive_s=6.0,
        snap="downbeat",
    )

    edit_decision = EditDecision(
        index=0,
        t_start=0.0,
        t_end=1.875,
        angle_id="A",
        reason="phrase boundary; A highest mean interest",
    )

    edit_decision_list = EditDecisionList(
        project_id="proj_001",
        params=edit_params,
        decisions=[
            EditDecision(index=0, t_start=0.0, t_end=1.875, angle_id="A", reason="intro hold"),
            EditDecision(index=1, t_start=1.875, t_end=3.75, angle_id="B", reason="switch on downbeat"),
        ],
    )

    return {
        Angle: angle_a,
        Project: project,
        BeatGrid: beat_grid,
        Section: section,
        EnergyTimeline: energy_timeline,
        WordCue: word_cue,
        AngleScoreSample: angle_score_sample,
        AngleScoreTimeline: angle_score_timeline,
        EditParams: edit_params,
        EditDecision: edit_decision,
        EditDecisionList: edit_decision_list,
    }


FAKES = make_fakes()


def _all_contract_models() -> set[type]:
    """Every concrete Pydantic model exported by engine.contracts (excludes the base)."""
    models = set()
    for _name, obj in inspect.getmembers(contracts, inspect.isclass):
        if (
            issubclass(obj, contracts.BaseModel)
            and obj.__module__ == contracts.__name__
            and obj is not contracts._Contract
            and not obj.__name__.startswith("_")
        ):
            models.add(obj)
    return models


def test_every_model_has_a_fake():
    """Completeness guard: no contract model may be added without a fake here."""
    assert _all_contract_models() == set(FAKES), (
        "Models missing a fake: "
        f"{_all_contract_models() - set(FAKES)}; extra fakes: {set(FAKES) - _all_contract_models()}"
    )


@pytest.mark.parametrize("model", list(FAKES), ids=lambda m: m.__name__)
def test_dict_round_trip(model: type):
    inst = FAKES[model]
    restored = model.model_validate(inst.model_dump())
    assert restored == inst


@pytest.mark.parametrize("model", list(FAKES), ids=lambda m: m.__name__)
def test_json_round_trip(model: type):
    inst = FAKES[model]
    restored = model.model_validate_json(inst.model_dump_json())
    assert restored == inst


def test_contract_version_value():
    assert contracts.CONTRACT_VERSION == "0.1"


def test_edit_decision_list_defaults_contract_version():
    edl = FAKES[EditDecisionList]
    assert edl.contract_version == contracts.CONTRACT_VERSION


def test_extra_fields_are_rejected():
    """`extra="forbid"` keeps the contracts strict against drift."""
    with pytest.raises(Exception):
        Angle.model_validate(
            {"angle_id": "A", "media_path": "/x.mov", "unexpected_field": 1}
        )
