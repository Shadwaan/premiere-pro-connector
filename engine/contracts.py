"""Typed contracts — the single source of truth that crosses every boundary.

This module is the executable form of ``CONTRACTS.md`` (which is law, AGENTS.md §2).
Every analyzer, the fusion step, the exporter, the MCP tools, and the UXP bridge share
these shapes. Changing a contract is a breaking change: bump ``CONTRACT_VERSION`` and
update all implementers + tests in the same change.

Timeline invariant (ARCHITECTURE.md §3, CONTRACTS.md): every timestamp here is **float
seconds, absolute from the start of the master-audio timeline**. No exceptions.
Frame-snapping to project FPS happens only at export.

Note: the provider *protocols* (``TranscriberProvider`` / ``AngleScoringProvider``) from
CONTRACTS.md are introduced in PPC-004 alongside their fakes; they are not Pydantic models
and so are out of scope for the PPC-001 round-trip. The data shapes below are PPC-001.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "0.1"


class _Contract(BaseModel):
    """Shared base for all contract models.

    ``extra="forbid"`` makes the contracts strict: unknown fields are rejected rather
    than silently dropped, so drift between an implementer and the contract surfaces
    immediately instead of corrupting data downstream.
    """

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Project & inputs
# --------------------------------------------------------------------------- #


class Angle(_Contract):
    angle_id: str  # stable id, e.g. "A", "B", "cam_balcony"
    media_path: str  # absolute path to the angle's video file
    label: str | None = None  # human name, e.g. "wide balcony"
    # Angles are assumed pre-synced: t=0 in this contract == t=0 in every angle.


class Project(_Contract):
    project_id: str
    master_audio_path: str  # the track the edit is cut to
    angles: list[Angle]  # >= 1; v1 targets 2-3
    fps: float = 30.0  # project frame rate, used ONLY at export
    duration_s: float  # length of the master timeline


# --------------------------------------------------------------------------- #
# Audio timing (from `audio_timing`, local)
# --------------------------------------------------------------------------- #


class BeatGrid(_Contract):
    bpm: float
    beats: list[float]  # every beat, seconds
    downbeats: list[float]  # bar starts, seconds
    # phrase boundaries are derived (every N downbeats) at fusion time, not stored here.


class Section(_Contract):
    start: float
    end: float
    kind: Literal["intro", "build", "drop", "breakdown", "outro", "other"]
    energy: float  # 0..1 mean normalized energy in the section


class EnergyTimeline(_Contract):
    hop_s: float  # sampling interval of the energy curve
    energy: list[float]  # 0..1 normalized, one value per hop
    sections: list[Section]  # contiguous, ordered, cover [0, duration_s]
    drops: list[float]  # seconds of detected drop onsets


# --------------------------------------------------------------------------- #
# Words (from `transcription`, hosted Modal)
# --------------------------------------------------------------------------- #


class WordCue(_Contract):
    start: float
    end: float
    text: str
    kind: Literal["speech", "lyric", "unknown"] = "unknown"
    speaker: str | None = None  # if diarization available; else None
    is_hook: bool = False  # flagged when text looks like a repeated/sung hook
    to_camera: bool = False  # heuristic: DJ addressing the camera


# --------------------------------------------------------------------------- #
# Angle scores (from `angle_scoring` -> hosted `clip`)
# --------------------------------------------------------------------------- #


class AngleScoreSample(_Contract):
    t: float  # sample time, seconds
    interest: float  # 0..1 overall "worth showing" score
    face_visible: float = 0.0  # 0..1, is the DJ's face well framed
    motion: float = 0.0  # 0..1, movement/energy in the shot
    note: str | None = None  # short caption snippet from clip, for debugging


class AngleScoreTimeline(_Contract):
    angle_id: str
    hop_s: float  # scoring grid interval (sampled, not per-frame)
    samples: list[AngleScoreSample]


# --------------------------------------------------------------------------- #
# Edit parameters (NL brief -> params)
# --------------------------------------------------------------------------- #


class EditParams(_Contract):
    cut_density: float = 0.5  # 0 slow .. 1 frantic; baseline cut rate
    drop_aggression: float = 0.8  # 0..1 how much faster cuts get at/after a drop
    face_bias_on_vocals: float = 0.7  # 0..1 pull toward best-face angle on hooks/to-camera
    min_shot_len_s: float = 0.5  # never hold an angle shorter than this
    switch_penalty: float = 0.3  # hysteresis; discourages rapid back-and-forth
    max_consecutive_s: float = 8.0  # force a switch if one angle held this long
    snap: Literal["beat", "downbeat", "phrase"] = "beat"


# --------------------------------------------------------------------------- #
# Output: the edit decision list
# --------------------------------------------------------------------------- #


class EditDecision(_Contract):
    index: int
    t_start: float  # seconds, snapped to grid per EditParams.snap
    t_end: float
    angle_id: str  # which angle to show for this segment
    reason: str  # one line: why this cut + this angle (explainability)


class EditDecisionList(_Contract):
    contract_version: str = Field(default=CONTRACT_VERSION)
    project_id: str
    params: EditParams
    decisions: list[EditDecision]  # contiguous, ordered, cover [0, duration_s]
    # Invariants (enforced by fusion in PPC-005, not at construction here):
    #   decisions[0].t_start == 0; decisions[-1].t_end == project.duration_s;
    #   each t_end == next t_start; each angle_id exists in project.angles.


__all__ = [
    "CONTRACT_VERSION",
    "Angle",
    "Project",
    "BeatGrid",
    "Section",
    "EnergyTimeline",
    "WordCue",
    "AngleScoreSample",
    "AngleScoreTimeline",
    "EditParams",
    "EditDecision",
    "EditDecisionList",
]
