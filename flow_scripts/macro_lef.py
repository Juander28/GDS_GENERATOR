#!/usr/bin/env python3
"""An abstract LEF of the TOP, for placing it inside the padring's user area.

    env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/macro_lef.py

Not the same job as `build_collateral.py`, which abstracts the small blocks, and
one thing had to be done differently.

MAGIC CANNOT BE TRUSTED FOR THESE PINS. `port makeall` promotes the GDS labels
to ports and then takes the WHOLE GEOMETRY OF THE NET with them. In a block that
is harmless -- its pins are small. In the top, `S3N` reaches from the die edge
through an ESD cell into the core, so the abstract came out with the pin at
(152.4, 382.9), deep inside, and the router said `DRT-0073 No access point`.

So the pins are taken from the ROUTED DEF, where each one is exactly the box
`place_pins` put on the die edge, and only the outline and the obstructions come
from magic. And the pins are then carved back out of the obstructions: the
growth in `_OBS_GROW` is sized for a block whose pins sit on a landing pad in
the middle, and on an edge pin it simply buries it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import klayout.db as kdb
import build_collateral as bc

ROOT = Path(__file__).resolve().parent.parent
BLOCK = "GRADIENT_NAV2"
_OUT = ROOT / "out_v2_GRADIENT_NAV2"

#: DE DONDE SALE LA GEOMETRIA, en orden de preferencia.
#:
#: El relleno de densidad ya NO se hace dos veces. Se hace UNA, al final, sobre
#: el area integrada; el bloque llega hasta el decap y nada mas. Asi que aqui
#: hay que coger el fichero mas avanzado que EXISTA, y no `_filled.gds` a secas:
#: cogiendolo a secas se lee el relleno de la tanda ANTERIOR, y con el su
#: contorno. Medido: el bloque pasaba a 460.90 x 386.99 um y este LEF seguia
#: diciendo `SIZE 418.240 BY 442.190`, la de hace dos dias, asi que
#: `integrate_top.tcl` colocaba una caja del tamano equivocado y `MPL-0041`
#: cantaba un solape con un clamp que en realidad no existia.
GDS = next((g for g in (_OUT / f"{BLOCK}_filled.gds",
                        _OUT / f"{BLOCK}_decap.gds",
                        _OUT / f"{BLOCK}.gds") if g.exists()),
           _OUT / f"{BLOCK}_filled.gds")
DEF = _OUT / f"{BLOCK}_routed.def"
NET = ROOT.parent / "XSCHEM/simulation" / f"{BLOCK}.sch" / f"{BLOCK}.spice"
OUT = ROOT / "lef" / f"{BLOCK}.lef"
#: How far the obstructions are pulled back from a pin, so the router has
#: somewhere to land rather than just an edge.
CLEAR = 0.20


def def_pins(path: Path):
    """{name: (layer, x0, y0, x1, y1)} in um, absolute, from the routed DEF."""
    txt = path.read_text()
    dbu = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))
    out, cur, rel = {}, None, None
    for line in txt.splitlines():
        m = re.match(r"\s*- (\S+) \+ NET", line)
        if m:
            cur, rel = m.group(1), None
            continue
        m = re.match(r"\s*\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)", line)
        if m and cur:
            rel = (m.group(1),) + tuple(int(v) for v in m.groups()[1:])
            continue
        m = re.match(r"\s*\+ (?:PLACED|FIXED) \( (-?\d+) (-?\d+) \)", line)
        if m and cur and rel:
            x, y = int(m.group(1)), int(m.group(2))
            out[cur] = (rel[0], (x + rel[1]) / dbu, (y + rel[2]) / dbu,
                        (x + rel[3]) / dbu, (y + rel[4]) / dbu)
            cur, rel = None, None
    return out


def main() -> int:
    dirs = bc.read_directions(NET, BLOCK)
    pins = def_pins(DEF)
    falta = [p for p in dirs if p not in pins]
    if falta:
        sys.exit(f"  in the netlist and not in {DEF.name}: {falta}")

    raw = bc.write_lef(BLOCK, GDS.resolve(), ROOT / "work_lef_top").read_text()
    cabecera = raw[:raw.index("  PIN ")]
    obs = raw[raw.index("  OBS"):] if "  OBS" in raw else ""

    #  THE OBSTRUCTIONS ARE THE WHOLE OUTLINE, minus the pins. Magic's own OBS on
    #  a block this size and this full is not enough: the router laid Metal2 and
    #  Metal3 INSIDE the macro and brushed its density fill at 0.175 um -- 300
    #  violations of M2.2a and M3.2a, all of them at x 424 and y 1001, inside the
    #  block, where nothing may go.
    #
    #  And that is the honest abstract anyway. GRADIENT_NAV2 ships FILLED: every
    #  layer is solid across it bar the pins, so "everything is blocked except
    #  where a pin is" is not conservative, it is what the block actually is.
    m = re.search(r"SIZE ([\d.]+) BY ([\d.]+)", raw)
    W, H = float(m.group(1)), float(m.group(2))
    porlayer = {}
    for name, (l, *b) in pins.items():
        porlayer.setdefault(l, []).append(b)
    cuerpo, tocados = ["  OBS"], 0
    for l in ("Metal1", "Metal2", "Metal3", "Metal4", "Metal5"):
        reg = kdb.Region()
        reg.insert(kdb.Box(0, 0, round(W * 1000), round(H * 1000)))
        if l in porlayer:
            cut = kdb.Region()
            for b in porlayer[l]:
                cut.insert(kdb.Box(round(b[0] * 1000), round(b[1] * 1000),
                                   round(b[2] * 1000), round(b[3] * 1000)))
            reg -= cut.sized(round(CLEAR * 1000))
            tocados += 1
        cuerpo.append(f"      LAYER {l} ;")
        for poly in reg.merged().each():
            bb = poly.bbox()
            cuerpo.append(f"        RECT {bb.left/1000:.3f} {bb.bottom/1000:.3f} "
                          f"{bb.right/1000:.3f} {bb.top/1000:.3f} ;")
    cuerpo.append("  END")

    #  the pins, straight from the DEF
    pin_txt = []
    for name, d in dirs.items():
        l, x0, y0, x1, y1 = pins[name]
        use = ("POWER" if name in bc.POWER else
               "GROUND" if name in bc.GROUND else "SIGNAL")
        pin_txt += [f"  PIN {name}", f"    DIRECTION {d} ;", f"    USE {use} ;",
                    "    PORT", f"      LAYER {l} ;",
                    f"        RECT {x0:.3f} {y0:.3f} {x1:.3f} {y1:.3f} ;",
                    "    END", f"  END {name}"]

    OUT.write_text(cabecera + "\n".join(pin_txt) + "\n"
                   + "\n".join(cuerpo) + f"\nEND {BLOCK}\n")
    print(f"  {len(pins)} pins taken from {DEF.name}, not from magic's ports")
    print(f"  obstructions: the whole outline on 5 layers, pins carved out on {tocados}")
    print(f"  -> {OUT}   {re.search(r'SIZE .*', cabecera).group(0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
