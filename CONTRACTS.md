# CONTRACTS — Premiere Pro Connector

These are **normative**. They live in `engine/contracts.py` (Pydantic v2) and are the single
source of truth shared by every analyzer, the fusion step, the exporter, the MCP tools, and the
UXP bridge. Changing a contract is a breaking change: bump `CONTRACT_VERSION` and update all
implementers + tests in the same change.

`CONTRACT_VERSION = "0.1"`

**Timeline invariant:** every timestamp below is **float seconds, absolute from the start of
the master audio timeline.** No exceptions. Frame-snapping to project FPS happens only at
export. (Same invariant the multimodal-transcriber repo uses — it makes fusion trivial.)

---

## Project & inputs

```python
class Angle(BaseModel):
    angle_id: str                      # stable id, e.g. "A", "B", "cam_balcony"
    media_path: str                    # absolute path to the angle's video file
    label: str | None = None           # human name, e.g. "wide balcony"
    # Angles are assumed pre-synced: t=0 in this contract == t=0 in every angle.

class Project(BaseModel):
    project_id: str
    master_audio_path: str             # the track the edit is cut to
    angles: list[Angle]                # >= 1; v1 targets 2-3
    fps: float = 30.0                  # project frame rate, used ONLY at export
    duration_s: float                  # length of the master timeline
```

---

## Audio timing (from `audio_timing`, local)

```python
class BeatGrid(BaseModel):
    bpm: float
    beats: list[float]                 # every beat, seconds
    downbeats: list[float]             # bar starts, seconds
    # phrase boundaries are derived (every N downbeats) at fusion time, not stored here.

class Section(BaseModel):
    start: float
    end: float
    kind: Literal["intro", "build", "drop", "breakdown", "outro", "other"]
    energy: float                      # 0..1 mean normalized energy in the section

class EnergyTimeline(BaseModel):
    hop_s: float                       # sampling interval of the energy curve
    energy: list[float]                # 0..1 normalized, one value per hop
    sections: list[Section]            # contiguous, ordered, cover [0, duration_s]
    drops: list[float]                 # seconds of detected drop onsets
```

---

## Words (from `transcription`, hosted Modal)

```python
class WordCue(BaseModel):
    start: float
    end: float
    text: str
    kind: Literal["speech", "lyric", "unknown"] = "unknown"
    speaker: str | None = None         # if diarization available; else None
    is_hook: bool = False              # flagged when text looks like a repeated/sung hook
    to_camera: bool = False            # heuristic: DJ addressing the camera
```

`transcription` maps the hosted transcriber's raw segments into `WordCue[]`. `is_hook` /
`to_camera` are heuristics computed here, not from the transcriber.

---

## Angle scores (from `angle_scoring` → hosted `clip`)

```python
class AngleScoreSample(BaseModel):
    t: float                           # sample time, seconds
    interest: float                    # 0..1 overall "worth showing" score
    face_visible: float = 0.0          # 0..1, is the DJ's face well framed
    motion: float = 0.0                # 0..1, movement/energy in the shot
    note: str | None = None            # short caption snippet from clip, for debugging

class AngleScoreTimeline(BaseModel):
    angle_id: str
    hop_s: float                       # scoring grid interval (sampled, not per-frame)
    samples: list[AngleScoreSample]
```

`angle_scoring` calls `clip`'s `/describe`/`/find`, reduces the captions/timestamps into the
numeric fields above on a coarse grid (PRD §9 Q3), and interpolates between samples at fusion
time.

---

## Edit parameters (NL brief → params)

```python
class EditParams(BaseModel):
    cut_density: float = 0.5           # 0 slow .. 1 frantic; baseline cut rate
    drop_aggression: float = 0.8       # 0..1 how much faster cuts get at/after a drop
    face_bias_on_vocals: float = 0.7   # 0..1 pull toward best-face angle on hooks/to-camera
    min_shot_len_s: float = 0.5        # never hold an angle shorter than this
    switch_penalty: float = 0.3        # hysteresis; discourages rapid back-and-forth
    max_consecutive_s: float = 8.0     # force a switch if one angle held this long
    snap: Literal["beat", "downbeat", "phrase"] = "beat"
```

The MCP `propose_cuts` tool accepts either an explicit `EditParams` or a natural-language
`brief` that a small rules layer (optionally Claude) maps onto these fields.

---

## Output: the edit decision list

```python
class EditDecision(BaseModel):
    index: int
    t_start: float                     # seconds, snapped to grid per EditParams.snap
    t_end: float
    angle_id: str                      # which angle to show for this segment
    reason: str                        # one line: why this cut + this angle (explainability)

class EditDecisionList(BaseModel):
    contract_version: str = CONTRACT_VERSION
    project_id: str
    params: EditParams
    decisions: list[EditDecision]      # contiguous, ordered, cover [0, duration_s]
    # Invariants: decisions[0].t_start == 0; decisions[-1].t_end == project.duration_s;
    # each t_end == next t_start; each angle_id exists in project.angles.
```

This is the **handoff object**. The FCPXML exporter and the Phase-2 UXP bridge both consume
exactly this — nothing else. Two surfaces, one contract.

---

## Export targets

- **FCPXML** (primary): an `EditDecisionList` → a Premiere-importable multicam sequence +
  markers at section/drop boundaries. Validate the element shape against PP 2026 on first run
  (PRD §9 Q4).
- **EDL** (fallback): CMX3600 cut list, if FCPXML multicam import proves too fragile.

---

## Provider protocols (adapters)

Engine code depends only on these interfaces, never on Modal/HTTP specifics (borrowed from
multimodal-transcriber's `app.providers` pattern). Each has a **fake** implementation for tests.

```python
class TranscriberProvider(Protocol):
    def transcribe(self, audio_path: str) -> list[WordCue]: ...

class AngleScoringProvider(Protocol):
    def score(self, angle: Angle, hop_s: float) -> AngleScoreTimeline: ...
```

`audio_timing` is local (not a provider) but exposes `analyze(audio_path) -> tuple[BeatGrid,
EnergyTimeline]`.
