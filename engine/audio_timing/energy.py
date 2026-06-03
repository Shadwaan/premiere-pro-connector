"""Energy curve, section detection, and drop detection (PPC-003).

Pipeline (ARCHITECTURE §5):
- **Energy curve** — librosa RMS (in dB) + spectral flux (onset strength), each
  normalized 0..1 and blended, sampled at a fixed hop. Populates ``EnergyTimeline.energy``.
- **Sections** — contiguous, gap-free ``Section[]`` covering ``[0, duration_s]``, labelled
  intro / build / drop / breakdown / outro / other, each carrying mean 0..1 energy.
- **Drops** — seconds of sharp energy rises that follow a dip/breakdown.

As with ``beats.py``, the pure array logic (``detect_sections_from_energy`` /
``detect_drops_from_energy``) is split from the audio I/O (``compute_energy_timeline``) so
it can be unit-tested offline with synthetic arrays. All times are float seconds, absolute
from t=0 (CONTRACTS.md timeline invariant).
"""

from __future__ import annotations

import warnings

import numpy as np

from engine.contracts import EnergyTimeline, Section

# Default analysis grid. 0.1 s hop gives ~0.1 s drop-time resolution (well under the
# ±0.3 s gate) while keeping the stored curve a manageable size.
DEFAULT_HOP_S = 0.1
DEFAULT_SR = 22050
# Blend weights for the energy curve. In EDM the overall loudness barely dips during a
# breakdown (vocals/synths stay loud) — what drops out is the kick/bass. So low-band
# energy is the strongest structural signal and gets the most weight, full-band loudness
# adds overall intensity, and spectral flux sharpens onsets/builds (ARCHITECTURE §5).
_LOW_WEIGHT = 0.55
_FULL_WEIGHT = 0.30
_FLUX_WEIGHT = 0.15
# Upper edge of the "low band" (kick + bass fundamentals), Hz.
_LOW_BAND_HZ = 250.0


# --------------------------------------------------------------------------- #
# Small pure helpers
# --------------------------------------------------------------------------- #


def _normalize_01(x: np.ndarray) -> np.ndarray:
    """Min-max normalize to 0..1; a constant array maps to all-zeros."""
    arr = np.asarray(x, dtype=float)
    lo = float(arr.min())
    hi = float(arr.max())
    if hi - lo <= 1e-12:
        return np.zeros_like(arr)
    return (arr - lo) / (hi - lo)


def _moving_average(x: np.ndarray, win: int) -> np.ndarray:
    """Centered moving average with edge padding; output length matches input."""
    arr = np.asarray(x, dtype=float)
    win = int(max(1, win))
    if win <= 1 or arr.size == 0:
        return arr
    pad = win // 2
    padded = np.pad(arr, pad, mode="edge")
    kernel = np.ones(win) / win
    return np.convolve(padded, kernel, mode="valid")[: arr.size]


def _contiguous_true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return [start, end) index ranges where ``mask`` is True."""
    runs: list[tuple[int, int]] = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


# --------------------------------------------------------------------------- #
# Drop detection (pure)
# --------------------------------------------------------------------------- #


def detect_drops_from_energy(
    energy: np.ndarray,
    hop_s: float,
    *,
    smooth_s: float = 0.6,
    pre_window_s: float = 4.0,
    post_window_s: float = 3.0,
    hi_q: float = 0.75,
    rise_min: float = 0.30,
    min_gap_s: float = 6.0,
) -> list[float]:
    """Detect drop onsets: a sharp rise to high energy that follows a dip.

    A frame is in a *drop region* when the highest upcoming energy (``post_window_s``
    forward) is at/above the ``hi_q`` quantile **and** the rise from the lowest recent
    energy (``pre_window_s`` back) to that peak is at least ``rise_min``. The large rise is
    itself what marks the preceding dip — requiring an absolute low threshold is brittle
    because a brief dip gets smoothed away. Within each region the drop time is the frame
    of steepest ascent (the transition itself). Regions closer than ``min_gap_s`` merge.
    """
    e = _moving_average(np.asarray(energy, dtype=float), round(smooth_s / hop_s))
    n = e.size
    if n < 3:
        return []

    hi = float(np.quantile(e, hi_q))

    pre_n = max(1, round(pre_window_s / hop_s))
    post_n = max(1, round(post_window_s / hop_s))
    e_pre_min = np.array([e[max(0, i - pre_n) : i + 1].min() for i in range(n)])
    e_post_max = np.array([e[i : min(n, i + post_n + 1)].max() for i in range(n)])

    is_drop = (e_post_max >= hi) & ((e_post_max - e_pre_min) >= rise_min)
    de = np.gradient(e)

    times: list[float] = []
    for start, end in _contiguous_true_runs(is_drop):
        idx = start + int(np.argmax(de[start:end]))
        times.append(idx * hop_s)

    # Merge near-duplicate detections.
    times.sort()
    merged: list[float] = []
    for t in times:
        if not merged or (t - merged[-1]) >= min_gap_s:
            merged.append(t)
    return merged


# --------------------------------------------------------------------------- #
# Section detection (pure)
# --------------------------------------------------------------------------- #


def detect_sections_from_energy(
    energy: np.ndarray,
    hop_s: float,
    duration_s: float,
    *,
    smooth_s: float = 3.0,
    lo_q: float = 0.33,
    hi_q: float = 0.66,
    min_section_s: float = 6.0,
    rise_eps: float = 0.05,
) -> list[Section]:
    """Segment the energy curve into contiguous, labelled sections covering
    ``[0, duration_s]`` with no gaps.

    The smoothed curve is quantized into low/mid/high levels; equal-level runs become
    sections, short runs are merged away, and each run is labelled from its level, its
    position (first→intro, last→outro), its neighbours (low after high→breakdown), and its
    trend (rising mid→build).
    """
    arr = np.asarray(energy, dtype=float)
    n = arr.size
    if n == 0:
        return [Section(start=0.0, end=float(duration_s), kind="other", energy=0.0)]

    e_s = _moving_average(arr, round(smooth_s / hop_s))
    lo = float(np.quantile(e_s, lo_q))
    hi = float(np.quantile(e_s, hi_q))
    # `>=` for the high level so a flat plateau at the curve's max still counts as high
    # (a strict `>` would exclude it when `hi` equals the plateau value).
    level = np.where(e_s >= hi, 2, np.where(e_s <= lo, 0, 1))

    min_frames = max(1, round(min_section_s / hop_s))

    # Build equal-level runs, then iteratively merge runs shorter than min_frames into a
    # neighbour until all runs are long enough.
    def _build_runs(lvl: np.ndarray) -> list[list[int]]:
        out: list[list[int]] = []
        i = 0
        while i < n:
            j = i
            while j < n and lvl[j] == lvl[i]:
                j += 1
            out.append([i, j, int(lvl[i])])
            i = j
        return out

    runs = _build_runs(level)
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for k, (s, e, _lv) in enumerate(runs):
            if (e - s) < min_frames:
                # Merge into the longer adjacent run (prefer previous on a tie).
                prev_len = runs[k - 1][1] - runs[k - 1][0] if k > 0 else -1
                next_len = runs[k + 1][1] - runs[k + 1][0] if k < len(runs) - 1 else -1
                target = k - 1 if prev_len >= next_len else k + 1
                runs[target][0] = min(runs[target][0], s)
                runs[target][1] = max(runs[target][1], e)
                runs.pop(k)
                changed = True
                break

    # Convert runs to Sections with exact tiling over [0, duration_s].
    n_runs = len(runs)
    sections: list[Section] = []
    for k, (s, e, lv) in enumerate(runs):
        start = 0.0 if k == 0 else runs[k][0] * hop_s
        end = float(duration_s) if k == n_runs - 1 else runs[k + 1][0] * hop_s
        seg = arr[s:e]
        mean_energy = float(np.clip(seg.mean() if seg.size else 0.0, 0.0, 1.0))
        kind = _label_run(k, n_runs, lv, runs, e_s)
        sections.append(Section(start=start, end=end, kind=kind, energy=mean_energy))
    return sections


def _label_run(k: int, n_runs: int, level: int, runs: list[list[int]], e_s: np.ndarray) -> str:
    s, e, _ = runs[k]
    seg = e_s[s:e]
    rising = seg.size >= 2 and (seg[-1] - seg[0]) > 0.05
    prev_level = runs[k - 1][2] if k > 0 else None

    if level == 2:
        return "drop"
    if level == 0:
        if k == 0:
            return "intro"
        if k == n_runs - 1:
            return "outro"
        if prev_level == 2:
            return "breakdown"
        return "breakdown"
    # mid level
    if rising:
        return "build"
    if k == 0:
        return "intro"
    if k == n_runs - 1:
        return "outro"
    return "other"


# --------------------------------------------------------------------------- #
# Audio I/O entrypoint
# --------------------------------------------------------------------------- #


def _energy_curve(audio_path: str, hop_s: float, sr: int) -> tuple[np.ndarray, float, float]:
    """Load audio and build the normalized 0..1 energy curve.

    Returns ``(energy, hop_s_effective, duration_s)``. ``hop_s_effective`` is the actual
    grid (``hop_length / sr``) so stored times line up exactly with the samples.
    """
    import librosa

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
        duration_s = len(y) / sr
        hop_length = max(1, round(hop_s * sr))
        hop_s_eff = hop_length / sr

        n_fft = 2048
        power = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length)) ** 2
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

        # Low band (kick/bass) and full band, both log-compressed then normalized. The
        # low band collapses in breakdowns and returns at drops — the key discriminator.
        low_power = power[freqs <= _LOW_BAND_HZ].sum(axis=0)
        full_power = power.sum(axis=0)
        low_n = _normalize_01(librosa.power_to_db(low_power + 1e-12, ref=np.max))
        full_n = _normalize_01(librosa.power_to_db(full_power + 1e-12, ref=np.max))

        flux = librosa.onset.onset_strength(S=librosa.power_to_db(power), sr=sr)

    m = min(low_n.size, full_n.size, flux.size)
    energy = _normalize_01(
        _LOW_WEIGHT * low_n[:m]
        + _FULL_WEIGHT * full_n[:m]
        + _FLUX_WEIGHT * _normalize_01(flux[:m])
    )
    return energy, hop_s_eff, duration_s


def compute_energy_timeline(
    audio_path: str, *, hop_s: float = DEFAULT_HOP_S, sr: int = DEFAULT_SR
) -> EnergyTimeline:
    """Build the full ``EnergyTimeline`` (curve + sections + drops) from an audio file."""
    energy, hop_s_eff, duration_s = _energy_curve(audio_path, hop_s, sr)
    sections = detect_sections_from_energy(energy, hop_s_eff, duration_s)
    drops = detect_drops_from_energy(energy, hop_s_eff)
    return EnergyTimeline(
        hop_s=hop_s_eff,
        energy=[float(v) for v in energy],
        sections=sections,
        drops=drops,
    )
