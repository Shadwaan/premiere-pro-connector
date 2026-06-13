"""Phase-0 CLI (PPC-007): synced FCP7 XML -> beat-cut multicam FCP7 XML.

Thin wrapper over ``engine.pipeline.run_autocut`` (the same function the local web UI calls,
so output is byte-identical). The pipeline itself is documented in ``engine/pipeline.py``.

Run:  python -m engine.cli "D:/All Video Content/Koshto/koshtoset.xml" [--brief "..."] [--out out.xml]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from engine.pipeline import DEFAULT_BRIEF, AutocutParams, MasterAudioNotFound, run_autocut


def _mmss(t: float) -> str:
    m = int(t // 60)
    return f"{m:d}:{t - 60 * m:05.2f}"


def _print_summary(s: dict) -> None:
    print(f"master audio : {s['master_audio']}")
    print(f"fps          : {s['fps']:.4f}   timeline offset {s['offset_s']:.3f}s")
    print(f"edit span    : 0:00 -> {_mmss(s['duration_s'])}  ({s['duration_s']:.1f}s)")
    print(f"sections     : {s['n_sections']}   hard drops: {s['n_drops']}")
    print(f"brief params : {s['params']}")
    print(f"DECISIONS    : {s['n_decisions']}   switches: {s['switches']}")
    print(f"by angle     : {s['by_angle']}")
    print(f"by section   : {s['by_section']}")
    mn, mean, mx = s["shot_len"]
    print(f"shot length  : min {mn:.2f}s  mean {mean:.2f}s  max {mx:.2f}s")
    if s["n_unresolved"]:
        print(f"WARNING      : {s['n_unresolved']} decision(s) had no footage (unresolved)")
    print(f"OUTPUT       : {s['out_path']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DJ multicam auto-editor (Phase 0, FCP7 XML).")
    ap.add_argument("xmeml", help="path to the synced Premiere FCP7 .xml")
    ap.add_argument("--brief", default=DEFAULT_BRIEF, help="natural-language edit brief")
    ap.add_argument("--out", default=None, help="output .xml path")
    ap.add_argument("--seed", type=int, default=1, help="fake angle-scorer seed")
    args = ap.parse_args(argv)

    out_path = args.out or str(Path(args.xmeml).with_name(Path(args.xmeml).stem + "_autocut.xml"))
    try:
        summary = run_autocut(args.xmeml, out_path, params=AutocutParams(brief=args.brief, seed=args.seed))
    except MasterAudioNotFound as e:
        print(f"ERROR: {e}")
        return 2
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
