#!/usr/bin/env python3
"""Turns sign-off deck violations into routing blockages.

The ones left on the top no longer share a cause: they are isolated spots where
the router leaves a wire hundredths away from a macro's metal. Raising global
margins -- blockage growth, techlef spacing -- closed the ones that did have a
pattern, but below that it only reshuffles: each run moves them around without
ever dropping below ten.

So the router is told exactly where it may not put metal again.
It is a DRC-driven loop, entirely inside OpenROAD:

    route -> GDS -> sign-off DRC -> this script -> blockages -> route

The file is cumulative on purpose: what was forbidden on one pass stays
forbidden on the next, which is what makes the loop converge instead of ring.

    python3 scripts/drc_blockages.py        # add the latest DRC run
    python3 scripts/drc_blockages.py --reset   # start from scratch
"""

from __future__ import annotations

import glob
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "out" / "drc_GRADIENT_NAV"
OUT = ROOT / "out" / "drc_blockages.txt"

#: Margin around the marked spot. The gap the deck measures is tenths of a
#: micron; with any less the router slips back through the same place, one
#: track over.
_HALO = 0.10

#: Which rule maps to which layer. Signal layers only: power is placed by
#: `pdngen` and never routed by the router.
_LAYER = {"M2": "Metal2", "M3": "Metal3", "M4": "Metal4"}


def boxes():
    for f in glob.glob(str(RUN / "*.lyrdb")):
        for item in ET.parse(f).getroot().iter("item"):
            cat = (item.findtext("category") or "").strip("'")
            layer = _LAYER.get(cat.split(".")[0])
            if layer is None:
                continue
            for v in item.iter("value"):
                n = [float(z) for z in re.findall(r"-?\d+\.?\d*", v.text or "")]
                if len(n) < 4:
                    continue
                xs, ys = n[0::2], n[1::2]
                yield (layer, min(xs) - _HALO, min(ys) - _HALO,
                       max(xs) + _HALO, max(ys) + _HALO)
                break


def main() -> int:
    if "--reset" in sys.argv:
        OUT.write_text("")
        print(f"{OUT} vaciado")
        return 0
    old = OUT.read_text().splitlines() if OUT.exists() else []
    seen = set(old)
    new = [f"{l} {a:.4f} {b:.4f} {c:.4f} {d:.4f}" for l, a, b, c, d in boxes()]
    add = [s for s in new if s not in seen]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(old + add) + ("\n" if old + add else ""))
    print(f"{OUT}: {len(add)} nuevas, {len(old) + len(add)} en total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
