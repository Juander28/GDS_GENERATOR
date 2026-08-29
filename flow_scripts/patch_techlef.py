#!/usr/bin/env python3
"""Copy of the techlef with the via enclosure squared off.

The PDK `VIARULE Via*_GEN_*` give `ENCLOSURE 0.060 0.010`: around a 0.26 cut
that yields a **0.38 x 0.28** pad. That causes two problems when routing the
top, and both are geometry, not connectivity:

  * on its own the pad is 0.1064 um2 and `Mn.3` asks 0.1444  -> `M3.3`;
  * against a wire, the difference between 0.38 and 0.28 leaves a 0.05 step
    -> `M3.1`, plus hundredth-micron brushes in `M3.2a` / `M2.2a`.

With 0.060 on both axes the pad becomes 0.38 x 0.38 = 0.1444 exactly: it meets
the area on its own and makes no step against a 0.38 wire (see the non-standard
`ANCHO` rule in route_top.tcl). The PDK minimum is 0.010 on the short axis and
here it is raised to 0.060: more enclosure never breaks an enclosure rule.

    python3 scripts/patch_techlef.py   ->  lef/techlef_patched.tlef
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path("/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/techlef/"
           "gf180mcu_fd_sc_mcu9t5v0__nom.tlef")
DST = ROOT / "lef" / "techlef_patched.tlef"


#: The layers whose pad gets squared, with their minimum side. Metal5 is left
#: alone: its minimum area is 0.5625 and no via pad comes close, so growing it
#: would only crowd the MIM plates.
_SQUARE = {"Metal1": 0.19, "Metal2": 0.19, "Metal3": 0.19, "Metal4": 0.19}


#: Layers the router runs signal on in the top (see `route_top.tcl`).
_MARGEN = {"Metal2", "Metal3", "Metal4"}


def main() -> int:
    #  Careful: a ROUTING layer is declared `LAYER Metal3` (no `;`) and a layer
    #  inside a VIARULE is declared ` LAYER Metal3 ;` (with `;`). They are two
    #  different things and both are needed.
    out, in_rule, in_via, layer, rlayer, n = [], False, False, None, None, 0
    for line in SRC.read_text().splitlines():
        if re.match(r"\s*VIARULE (Via\d_GEN_\S+) GENERATE", line):
            in_rule = True
        elif re.match(r"\s*VIA (Via\d\S*)\s", line):
            in_via = True
        elif re.match(r"\s*END Via", line):
            in_rule = in_via = False
        m = re.match(r"\s*LAYER (\S+) ;", line)
        if m:
            layer = m.group(1)
        if in_rule:
            m = re.match(r"(\s*ENCLOSURE\s+)([\d.]+)\s+([\d.]+)\s*;", line)
            if m:
                a, b = float(m.group(2)), float(m.group(3))
                if a != b:
                    big = max(a, b)
                    line = f"{m.group(1)}{big:.3f} {big:.3f} ;"
                    n += 1
        elif in_via and layer in _SQUARE:
            # The fixed `VIA ... DEFAULT` are what the router actually uses; the
            # GENERATE rules only kick in when no fixed one fits.
            m = re.match(r"(\s*RECT\s+)([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)\s*;", line)
            if m:
                half = _SQUARE[layer]
                if abs(float(m.group(4)) - half) > 1e-9 or \
                   abs(float(m.group(5)) - half) > 1e-9:
                    line = (f"{m.group(1)}{-half:.3f} {-half:.3f} "
                            f"{half:.3f} {half:.3f} ;")
                    n += 1
        #  A hair of margin over the sign-off value on the layers the top routes
        #  on. The KLayout deck measures `Mn.2a` euclidean, corner to corner;
        #  the router measures by projection, so it left exactly 0.280
        #  orthogonally and at a diagonal corner the deck saw less.
        #  With 0.300 any euclidean spacing is >= 0.300 > 0.280 and the problem
        #  disappears by construction. It costs 7% of routing slack.
        #  routing slack, which we can spare.
        m = re.match(r"LAYER (\S+)\s*$", line)
        if m:
            rlayer = m.group(1)
        if rlayer in _MARGEN:
            m = re.match(r"(\s*SPACING\s+)0?\.280\s*;(.*)$", line)
            if m:
                line = f"{m.group(1)}0.300 ;{m.group(2)}"
                n += 1
        out.append(line)
    #  And a SPACING SAMENET section, which the PDK techlef does not carry.
    #
    #  Without it the router accepts two shapes of the SAME net separated by
    #  hundredths: to it they are connected elsewhere, so there is nothing to
    #  check. The sign-off deck disagrees -- `Mn.2a` measures the spacing
    #  between disjoint polygons whatever net they belong to -- and that is
    #  where the last `M3.2a`/`M2.2a` on the top came from, all 0.03 to 0.14 um
    #  between a wire and the pad of the port that very wire ends on.
    same = ["", "SPACING"]
    for layer, val in (("Metal1", 0.23), ("Metal2", 0.28), ("Metal3", 0.28),
                       ("Metal4", 0.28), ("Metal5", 0.30)):
        same.append(f"  SAMENET {layer} {layer} {val:.3f} ;")
    same += ["END SPACING", ""]
    tail = out.index("END LIBRARY") if "END LIBRARY" in out else len(out)
    out = out[:tail] + same + out[tail:]

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text("\n".join(out) + "\n")
    print(f"{DST}\n  {n} recuadros de via hechos cuadrados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
