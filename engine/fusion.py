"""Fusion (PPC-005) — deterministic edit-decision logic (ARCHITECTURE §4).

Combines the three signal timelines + ``EditParams`` into an ``EditDecisionList``:

1. **Candidate cut points** from the beat/phrase grid (configurable phrase length) plus
   every section-map boundary.
2. **Cut density scales with section energy** — longer holds in low-energy sections, faster
   cuts in high-energy ones. The ``"drop"``-kind sections are aggression-boost zones; the
   hard onset-drops (``EnergyTimeline.drops``) get the strongest boost. Nothing in the
   section map is discarded (FUSION DECISION, BUILD_LOG PPC-003 entry).
3. **Angle choice** = highest mean interest per segment, with hysteresis (``switch_penalty``)
   and a ``max_consecutive_s`` staleness cap.
4. **Semantic overrides** — on a ``WordCue`` ``is_hook`` / ``to_camera``, bias toward the
   best-face angle per ``face_bias_on_vocals``.

Every timestamp is float seconds, absolute from t=0 (timeline invariant); frame-snapping is
the exporter's job, not fusion's. Every ``EditDecision`` carries a one-line ``reason``.
"""

from __future__ import annotations

import numpy as np

from engine.contracts import (
    BeatGrid,
    EditDecision,
    EditDecisionList,
    EditParams,
    EnergyTimeline,
    Project,
    Section,
    WordCue,
)

# Shot-length bounds (seconds). HOLD_MAX ≈ 4 bars at ~128 BPM (slow, low energy);
# HOLD_MIN ≈ 1 bar (fast, at the drop). These bound the energy-scaled target shot length.
HOLD_MAX_S = 8.0
HOLD_MIN_FLOOR_S = 1.0
# Drop emphasis: extra cut intensity in a "drop" section, and near a hard onset-drop.
_DROP_SECTION_BOOST = 0.25
_HARD_DROP_BOOST = 0.45
_HARD_DROP_WINDOW = (-1.0, 8.0)  # a shot starting from 1 s before to 8 s after an onset
_EPS = 1e-6


# --------------------------------------------------------------------------- #
# Grid / interpolation helpers
# --------------------------------------------------------------------------- #


def _grid(beat_grid: BeatGrid, snap: str, phrase_downbeats: int) -> np.ndarray:
    if snap == "beat":
        pts = beat_grid.beats
    elif snap == "downbeat":
        pts = beat_grid.downbeats
    else:  # "phrase"
        pts = beat_grid.downbeats[:: max(1, phrase_downbeats)]
    return np.array(sorted(float(p) for p in pts), dtype=float)


def _first_ge(sorted_arr: np.ndarray, x: float) -> float:
    i = int(np.searchsorted(sorted_arr, x, side="left"))
    return float(sorted_arr[i]) if i < sorted_arr.size else float("inf")


def _nearest_grid(grid: np.ndarray, desired: float, lo_bound: float, last: float) -> float:
    """Grid point NEAREST to ``desired`` that is >= ``lo_bound`` and strictly after ``last``.

    Snapping to the nearest (vs always rounding forward) removes the systematic "late"
    bias — a switch lands on the closest downbeat to its musical target, not the next one.
    Falls back to the first grid point >= lo_bound if neither neighbour qualifies.
    """
    if grid.size == 0:
        return float("inf")
    i = int(np.searchsorted(grid, desired))
    cands = []
    if i < grid.size:
        cands.append(float(grid[i]))  # ceil
    if i > 0:
        cands.append(float(grid[i - 1]))  # floor
    cands = [g for g in cands if g >= lo_bound - _EPS and g > last + _EPS]
    if cands:
        return min(cands, key=lambda g: abs(g - desired))
    return _first_ge(grid, lo_bound)


def _snap_to_grid(x: float, grid: np.ndarray) -> float:
    if grid.size == 0:
        return x
    i = int(np.searchsorted(grid, x, side="left"))
    cands = []
    if i < grid.size:
        cands.append(grid[i])
    if i > 0:
        cands.append(grid[i - 1])
    return float(min(cands, key=lambda g: abs(g - x)))


def _section_at(sections: list[Section], t: float) -> Section | None:
    for s in sections:
        if s.start - _EPS <= t < s.end + _EPS:
            return s
    return sections[-1] if sections else None


def _segment_mean(times: np.ndarray, values: np.ndarray, t0: float, t1: float, n: int = 8) -> float:
    """Mean of an angle-score field over [t0, t1], by interpolating the sampled timeline."""
    if times.size == 0:
        return 0.0
    if times.size == 1:
        return float(values[0])
    q = np.linspace(t0, t1, max(2, n))
    return float(np.interp(q, times, values).mean())


# --------------------------------------------------------------------------- #
# Step 1+2: candidate cut points with energy-scaled density
# --------------------------------------------------------------------------- #


def _near_hard_drop(t: float, drops: list[float]) -> bool:
    lo, hi = _HARD_DROP_WINDOW
    return any(lo <= (t - d) <= hi for d in drops)


def _target_shot_len(
    t: float,
    sections: list[Section],
    e_times: np.ndarray,
    e_vals: np.ndarray,
    drops: list[float],
    params: EditParams,
    hold_max_s: float = HOLD_MAX_S,
) -> float:
    e = float(np.interp(t, e_times, e_vals)) if e_times.size else 0.5
    intensity = 0.4 * params.cut_density + 0.6 * e
    sec = _section_at(sections, t)
    if sec is not None and sec.kind == "drop":
        intensity += _DROP_SECTION_BOOST * params.drop_aggression
    if _near_hard_drop(t, drops):
        intensity += _HARD_DROP_BOOST * params.drop_aggression
    intensity = float(np.clip(intensity, 0.0, 1.0))
    hold_min = max(params.min_shot_len_s, HOLD_MIN_FLOOR_S)
    hold_max = max(hold_max_s, hold_min)
    return hold_max - intensity * (hold_max - hold_min)


def _candidate_cuts(
    project: Project,
    beat_grid: BeatGrid,
    energy: EnergyTimeline,
    params: EditParams,
    phrase_downbeats: int,
    switch_quant: str,
    hold_max_s: float,
    availability: dict[str, list[tuple[float, float]]] | None = None,
) -> list[float]:
    duration = float(project.duration_s)
    grid = _grid(beat_grid, switch_quant, phrase_downbeats)
    grid = grid[(grid > _EPS) & (grid < duration - _EPS)]
    if grid.size == 0:  # no beat grid available — fall back to a uniform 2 s grid
        grid = np.arange(2.0, duration, 2.0)

    # Forced cuts (snapped onto the grid so cuts stay on the beat):
    #  - section boundaries — the musically important structural transitions;
    #  - angle availability edges — so no segment straddles an angle appearing/disappearing
    #    (e.g. the DSLR ending at 24:30), which would make angle choice ambiguous.
    boundaries = {s.start for s in energy.sections}
    for intervals in (availability or {}).values():
        for a, b in intervals:
            boundaries.update((a, b))
    forced = sorted(
        {_snap_to_grid(t, grid) for t in boundaries if _EPS < t < duration - _EPS}
    )
    forced_arr = np.array(forced, dtype=float)

    e_times = np.arange(len(energy.energy)) * energy.hop_s
    e_vals = np.array(energy.energy, dtype=float)

    cuts = [0.0]
    last = 0.0
    while last < duration - _EPS:
        L = _target_shot_len(last, energy.sections, e_times, e_vals, energy.drops, params, hold_max_s)
        ng = _nearest_grid(grid, last + L, last + params.min_shot_len_s, last)
        nf = _first_ge(forced_arr, last + _EPS) if forced_arr.size else float("inf")
        nxt = min(ng, nf, duration)
        if nxt - last < params.min_shot_len_s:  # never below the floor
            nxt = min(_first_ge(grid, last + params.min_shot_len_s), duration)
        if nxt >= duration - _EPS or nxt <= last + _EPS:
            break
        cuts.append(float(nxt))
        last = nxt
    cuts.append(duration)

    # Dedupe and drop a too-short final tail by merging it into the previous segment.
    cuts = _dedupe(cuts)
    if len(cuts) >= 3 and (cuts[-1] - cuts[-2]) < params.min_shot_len_s:
        cuts.pop(-2)
    return cuts


def _dedupe(cuts: list[float]) -> list[float]:
    out: list[float] = []
    for c in cuts:
        if not out or c - out[-1] > _EPS:
            out.append(c)
    return out


# --------------------------------------------------------------------------- #
# Step 3+4: angle assignment (hysteresis, staleness cap, semantic override)
# --------------------------------------------------------------------------- #


def _vocal_cue_in(words: list[WordCue], t0: float, t1: float) -> WordCue | None:
    for w in words:
        if (w.is_hook or w.to_camera) and w.start < t1 and w.end > t0:
            return w
    return None


def _available(intervals: list[tuple[float, float]] | None, t0: float, t1: float) -> bool:
    """True if some availability interval fully covers [t0, t1] (None = always available)."""
    if intervals is None:
        return True
    return any(a - _EPS <= t0 and t1 <= b + _EPS for a, b in intervals)


def _assign_angles(
    cuts: list[float],
    project: Project,
    words: list[WordCue],
    angle_scores,
    sections: list[Section],
    params: EditParams,
    availability: dict[str, list[tuple[float, float]]] | None = None,
) -> list[EditDecision]:
    score_map = {tl.angle_id: tl for tl in angle_scores}
    angle_ids = [a.angle_id for a in project.angles if a.angle_id in score_map]
    if not angle_ids:
        raise ValueError("no angle has a score timeline; cannot assign angles")
    avail = availability or {}

    arr: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for aid in angle_ids:
        tl = score_map[aid]
        ts = np.array([s.t for s in tl.samples], dtype=float)
        interest = np.array([s.interest for s in tl.samples], dtype=float)
        face = np.array([s.face_visible for s in tl.samples], dtype=float)
        arr[aid] = (ts, interest, face)

    decisions: list[EditDecision] = []
    prev: str | None = None
    held = 0.0  # consecutive seconds the current angle has been on screen

    for i in range(len(cuts) - 1):
        t0, t1 = cuts[i], cuts[i + 1]
        seg_len = t1 - t0
        cue = _vocal_cue_in(words, t0, t1)

        mi = {a: _segment_mean(arr[a][0], arr[a][1], t0, t1) for a in angle_ids}
        mf = {a: _segment_mean(arr[a][0], arr[a][2], t0, t1) for a in angle_ids}

        eff: dict[str, float] = {}
        for a in angle_ids:
            s = mi[a]
            if cue is not None:
                s += params.face_bias_on_vocals * mf[a]  # bias toward best-face angle
            if a == prev:
                s += params.switch_penalty  # hysteresis: reward staying
            eff[a] = s

        # Availability gate first: only angles with footage across this whole segment.
        available = [a for a in angle_ids if _available(avail.get(a), t0, t1)]
        if not available:
            available = list(angle_ids)  # safety: should not happen (one angle covers all)

        allowed = available
        forced_switch = False
        if prev is not None and len(available) > 1 and (held + seg_len) > params.max_consecutive_s:
            others = [a for a in available if a != prev]  # staleness cap: force a switch
            if others:
                allowed = others
                forced_switch = True

        # Deterministic argmax (tie-break by angle id).
        choice = max(allowed, key=lambda a: (eff[a], a))
        stayed = choice == prev
        held = held + seg_len if stayed else seg_len

        reason = _reason(_section_at(sections, t0), cue, choice, mi[choice], mf[choice],
                         stayed=stayed, forced_switch=forced_switch, vocal=cue is not None)
        decisions.append(
            EditDecision(index=i, t_start=t0, t_end=t1, angle_id=choice, reason=reason)
        )
        prev = choice
    return decisions


def _reason(
    section: Section | None,
    cue: WordCue | None,
    angle_id: str,
    interest: float,
    face: float,
    *,
    stayed: bool,
    forced_switch: bool,
    vocal: bool,
) -> str:
    parts = [section.kind if section else "other"]
    if forced_switch:
        parts.append("max-hold switch")
    elif stayed:
        parts.append("hold")
    if vocal and cue is not None:
        tag = "hook" if cue.is_hook else "to-camera"
        parts.append(f"{tag}->{angle_id} face={face:.2f}")
    else:
        parts.append(f"{angle_id} interest={interest:.2f}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# Invariant guard + public API
# --------------------------------------------------------------------------- #


def _validate(edl: EditDecisionList, project: Project) -> None:
    d = edl.decisions
    assert d, "EditDecisionList must have at least one decision"
    assert abs(d[0].t_start) < _EPS, f"first t_start must be 0, got {d[0].t_start}"
    assert abs(d[-1].t_end - project.duration_s) < 1e-3, (
        f"last t_end {d[-1].t_end} must equal duration {project.duration_s}"
    )
    real = {a.angle_id for a in project.angles}
    for k, dec in enumerate(d):
        assert dec.index == k, f"decision {k} has index {dec.index}"
        assert dec.t_end > dec.t_start, f"decision {k} not forward: {dec.t_start}..{dec.t_end}"
        assert dec.angle_id in real, f"decision {k} angle {dec.angle_id} not in project"
        assert dec.reason, f"decision {k} missing reason"
        if k + 1 < len(d):
            assert abs(dec.t_end - d[k + 1].t_start) < _EPS, f"gap after decision {k}"


def fuse(
    project: Project,
    beat_grid: BeatGrid,
    energy: EnergyTimeline,
    words: list[WordCue],
    angle_scores,
    params: EditParams,
    *,
    phrase_downbeats: int = 2,
    switch_quant: str = "downbeat",
    hold_max_s: float | None = None,
    availability: dict[str, list[tuple[float, float]]] | None = None,
) -> EditDecisionList:
    """Core fusion: signals + params -> validated ``EditDecisionList``.

    ``switch_quant`` is the grid that cuts/angle-switches quantize to: ``"downbeat"``
    (default — switches land on the bar's "1"), ``"beat"`` (finer), or ``"phrase"`` (every
    ``phrase_downbeats`` downbeats, e.g. 2 = every 2 bars / 8 beats). Snapping is to the
    NEAREST grid point, not forward. ``hold_max_s`` is the longest hold (max shot length);
    ``None`` keeps the engine default (``HOLD_MAX_S``). ``availability`` (optional) maps
    angle_id -> available [start, end] intervals; an angle is only chosen where it has
    footage, and availability edges become forced cut points.
    """
    cuts = _candidate_cuts(
        project, beat_grid, energy, params, phrase_downbeats, switch_quant,
        HOLD_MAX_S if hold_max_s is None else hold_max_s, availability,
    )
    decisions = _assign_angles(
        cuts, project, words, angle_scores, energy.sections, params, availability
    )
    edl = EditDecisionList(project_id=project.project_id, params=params, decisions=decisions)
    _validate(edl, project)
    return edl


def propose_cuts(
    project: Project,
    beat_grid: BeatGrid,
    energy: EnergyTimeline,
    words: list[WordCue],
    angle_scores,
    *,
    params: EditParams | None = None,
    brief: str | None = None,
    phrase_downbeats: int = 2,
    switch_quant: str | None = None,
    hold_max_s: float | None = None,
    availability: dict[str, list[tuple[float, float]]] | None = None,
) -> EditDecisionList:
    """Fusion entrypoint accepting either explicit ``params`` or a natural-language ``brief``.

    ``switch_quant`` defaults to the resolved ``params.snap`` (which the brief sets, baseline
    ``"downbeat"``), so switches land on the bar by default; pass it explicitly to override.
    ``hold_max_s`` (max shot length) defaults to the engine constant when ``None``.
    """
    p = params if params is not None else map_brief_to_params(brief)
    sq = switch_quant if switch_quant is not None else p.snap
    return fuse(
        project, beat_grid, energy, words, angle_scores, p,
        phrase_downbeats=phrase_downbeats, switch_quant=sq, hold_max_s=hold_max_s,
        availability=availability,
    )


# --------------------------------------------------------------------------- #
# NL brief -> EditParams (v1 rules layer; optional Claude pass later — PRD §9 Q2)
# --------------------------------------------------------------------------- #

_FAST = ("fast", "frantic", "energetic", "quick", "snappy", "rapid", "punchy")
_SLOW = ("slow", "chill", "relaxed", "mellow", "calm", "laid back", "laid-back")
_HARD = ("hard", "aggressive", "intense", "heavy", "hit", "punch", "slam")
_SOFT = ("gentle", "soft", "easy", "smooth")
_FACE = ("face", "vocal", "hook", "lyric", "sing", "talk", "camera", "lip")


def map_brief_to_params(brief: str | None, base: EditParams | None = None) -> EditParams:
    """Map a natural-language brief onto ``EditParams`` with a small keyword rules layer."""
    p = (base or EditParams()).model_copy(deep=True)
    if base is None:
        # Brief-layer default: quantize switches to the bar's "1" (the EditParams contract
        # default stays "beat"; we don't change CONTRACTS.md). PPC-007 downbeat fix.
        p.snap = "downbeat"
    if not brief:
        return p
    b = brief.lower()

    def has(words: tuple[str, ...]) -> bool:
        return any(w in b for w in words)

    if has(_FAST):
        p.cut_density = min(1.0, p.cut_density + 0.3)
    if has(_SLOW):
        p.cut_density = max(0.0, p.cut_density - 0.3)
    if "drop" in b and (has(_FAST) or has(_HARD)):
        p.drop_aggression = min(1.0, p.drop_aggression + 0.2)
    if "drop" in b and has(_SOFT):
        p.drop_aggression = max(0.0, p.drop_aggression - 0.2)
    if has(_FACE):
        p.face_bias_on_vocals = min(1.0, p.face_bias_on_vocals + 0.2)
    if "hold" in b and ("hook" in b or "vocal" in b):
        p.min_shot_len_s = max(p.min_shot_len_s, 1.5)
    if "downbeat" in b or "bar" in b:
        p.snap = "downbeat"
    elif "phrase" in b:
        p.snap = "phrase"
    elif "beat" in b:
        p.snap = "beat"
    return p
