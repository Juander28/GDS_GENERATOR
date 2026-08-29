#!/usr/bin/env python3
"""Checks, net by net, that the top GDS connects what the DEF says it should.

Two questions, both invisible to DRC:

* **Opens.** netgen LVS on the top reported ~110 extra nets, all fragments
  named after a macro pin (`COMP_3.INN`, `OPAM_1.OUT`). An open breaks no rule:
  neither DRC tool sees it, only LVS does, and there it turns up mixed in with
  everything else. Here we check that ALL the terminals of each DEF net land on
  the same extracted net.
* **Shorts.** The opposite case and even more slippery: two shapes on the same
  layer that overlap **merge into one polygon**, so there is no spacing
  violation to see. Neither KLayout, nor magic, nor the router's own report say
  a word. Here the DEF nets are grouped by extracted net: two nets landing on
  the same one are shorted. That is how the last one on the top turned up --
  `S2P`, `VDD` and `VSS` fused by a Metal2 wire crossing the power pads of two
  macros -- in one second, instead of the two hours magic takes to extract the
  top so netgen can report it as a 2442-terminal node.

It extracts connectivity from the GDS with KLayout: metals and vias only, no
devices, which is what makes it fast.

    python3 scripts/check_connectivity.py [DEF]
"""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path

import klayout.db as kdb

from def_to_gds import lef_origin

ROOT = Path(__file__).resolve().parent.parent

#: (layer, via below) of the routing stack, bottom to top.
STACK = [("Metal1", (34, 0)), ("Via1", (35, 0)), ("Metal2", (36, 0)),
         ("Via2", (38, 0)), ("Metal3", (42, 0)), ("Via3", (40, 0)),
         ("Metal4", (46, 0)), ("Via4", (41, 0)), ("Metal5", (81, 0))]

_ORIENT = {"N": (1, 1, 0), "S": (-1, -1, 1), "FN": (-1, 1, 0), "FS": (1, -1, 1)}


def lef_pins(path: Path) -> dict[str, list[tuple[float, float, float, float]]]:
    """Pin -> Metal3 rectangles declared in the LEF."""
    out: dict[str, list] = {}
    pin = layer = None
    for line in path.read_text().splitlines():
        m = re.match(r"\s*PIN\s+(\S+)\s*$", line)
        if m:
            pin, layer = m.group(1), None
            continue
        if pin and re.match(rf"\s*END\s+{re.escape(pin)}\s*$", line):
            pin = None
            continue
        m = re.match(r"\s*LAYER\s+(\S+)\s*;", line)
        if m:
            layer = m.group(1)
            continue
        m = re.match(r"\s*RECT ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ;", line)
        if m and pin and layer == "Metal3":
            out.setdefault(pin, []).append(tuple(float(v) for v in m.groups()))
    return out


def read_def(path: Path):
    """(instances, nets) from the DEF: placement and (inst, pin) list per net."""
    text = path.read_text()
    comp = text[text.index("COMPONENTS "):text.index("END COMPONENTS")]
    inst = {}
    for m in re.finditer(r"-\s+(\S+)\s+(\S+)\s*\+\s+\S+\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)",
                         comp):
        inst[m.group(1)] = (m.group(2), int(m.group(3)), int(m.group(4)), m.group(5))
    #  This flow's DEF runs at 2000 units per micron, not the usual 1000: it has
    #  to be read, not assumed.
    units = float(re.search(r"UNITS DISTANCE MICRONS (\d+)", text).group(1))
    body = text[text.index("\nNETS "):text.index("END NETS")]
    nets = {}
    for blk in body.split("\n    - ")[1:]:
        name = blk.split()[0]
        #  The net HEADER only: past the first `+` come the routing coordinates,
        #  and `( 50960 * )` also matches the terminal pattern.
        #  un par (instancia, pin).
        head = blk.split("+")[0]
        pins = [(a, b) for a, b in re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", head)
                if a != "PIN"]
        nets[name] = pins
    return inst, nets, units


def read_def_ports(path: Path):
    """net -> [(layer, x, y)] for the top's own pins.

    These are NOT macro terminals and have to be checked separately. They were
    left out of the original check and that is where the top's last bug hid: the
    `VDD` and `VSS` ports were **floating**. `place_pins` leaves them on the die
    edge like any other signal, on a pad that never touches the power grid, and
    the router does not close them because it skips POWER/GROUND nets. DRC does
    not see it -- an open breaks no rule -- and this check did not look: LVS was
    the only one that flagged it, disguised as a pin matching failure.
    """
    text = path.read_text()
    body = text[text.index("\nPINS "):text.index("END PINS")]
    units = float(re.search(r"UNITS DISTANCE MICRONS (\d+)", text).group(1))
    declarados = int(re.search(r"\nPINS (\d+)", text).group(1))
    out: dict[str, list] = {}
    for blk in body.split("\n    - ")[1:]:
        m = re.search(r"NET\s+(\S+)", blk)
        layer = re.search(r"LAYER\s+(\S+)\s*\(", blk)
        #  `FIXED` too, not just `PLACED`: the two power ones are placed by hand
        #  with `place_pin` and OpenROAD writes them as FIXED. Looking only at
        #  PLACED silently skipped the only two worth watching.
        loc = re.search(r"(?:PLACED|FIXED|COVER)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", blk)
        if not (m and layer and loc):
            continue
        out.setdefault(m.group(1), []).append(
            (layer.group(1), int(loc.group(1)) / units, int(loc.group(2)) / units))
    #  That ALL the ones the DEF declares were read. A port the regex does not
    #  understand raises no error: it vanishes, and with it the check that it is
    #  connected. That is how `VDD` and `VSS` slipped through -- OpenROAD writes
    #  them `FIXED` and not `PLACED` because `place_pin` sets them by hand: 17
    #  55 nets salian «conectadas».
    leidos = sum(len(v) for v in out.values())
    if leidos != declarados:
        sys.exit(f"the DEF declares {declarados} pins and only {leidos} were read"
                 f" -- fix read_def_ports before trusting the result")
    return out


def place(rect, x, y, orient, size, origin=(0.0, 0.0)):
    """LEF rectangle -> absolute coordinates, according to the orientation.

    `ORIGIN` is ADDED, which is OpenROAD's convention: it normalises the master
    so that the lower-left corner of its box lands on (0, 0), and the DEF point
    is that corner. Here the blocks declare `ORIGIN 1.26 0` and such because
    their geometry starts at -1.26 -- the substrate taps stick out to the left
    of the origin -- so without adding it you probe 1.26 um left of the pin.
    See `def_to_gds.normalizar_origen`, which is where the GDS gets fixed.

    And the mirror comes AFTER normalising, not before: it reflects about the
    `[0, SIZE]` box, which is only the macro's box once ORIGIN has been added.
    """
    ox, oy = origin
    x0, y0, x1, y1 = rect[0] + ox, rect[1] + oy, rect[2] + ox, rect[3] + oy
    w, h = size
    if orient in ("S", "FS"):
        y0, y1 = h - y1, h - y0
    if orient in ("FN", "S"):
        x0, x1 = w - x1, w - x0
    return (x + x0, y + y0, x + x1, y + y1)


def macro_size(path: Path) -> tuple[float, float]:
    m = re.search(r"\s*SIZE ([\d.]+) BY ([\d.]+) ;", path.read_text())
    return (float(m.group(1)), float(m.group(2)))


def main() -> int:
    #  The GDS can be overridden from the command line so a DELIBERATELY BROKEN
    #  file can be fed in and the check seen to fail: see
    #  `scripts/probar_verificacion.py`. A check nobody has ever seen fail is
    #  fallar no ha demostrado nada.
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gds = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--gds=")]
    out = ROOT / os.environ.get("TOP_OUT", "out")
    top = os.environ.get("TOP_CELL", "GRADIENT_NAV")
    dpath = Path(args[0]) if args else out / f"{top}_routed.def"
    gpath = Path(gds[0]) if gds else out / f"{top}.gds"
    inst, nets, units = read_def(dpath)

    ly = kdb.Layout()
    ly.read(str(gpath))
    top = ly.top_cell()
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, []))
    regions = {}
    for name, (gl, dt) in STACK:
        regions[name] = l2n.make_polygon_layer(ly.layer(gl, dt), name)
    for i in range(0, len(STACK) - 1, 2):
        metal, via, up = STACK[i][0], STACK[i + 1][0], STACK[i + 2][0]
        l2n.connect(regions[metal])
        l2n.connect(regions[metal], regions[via])
        l2n.connect(regions[via], regions[up])
    l2n.connect(regions["Metal5"])
    l2n.extract_netlist()

    lefs, sizes, origenes = {}, {}, {}
    for p in (ROOT / "lef").glob("*.lef"):
        if p.name in ("vias.lef", "techlef_patched.tlef"):
            continue
        lefs[p.stem] = lef_pins(p)
        sizes[p.stem] = macro_size(p)
        origenes[p.stem] = lef_origin(p)

    #  `name` is empty on every net without a label, i.e. on almost all of them:
    #  using it as identity threw two different nets into the same bucket. The
    #  one that really identifies is `expanded_name()`, which gives `$1143`.
    abiertas = 0
    donde = {}                       # extracted net -> {DEF nets touching it}
    puertos = read_def_ports(dpath)
    huerfanos = sorted(set(puertos) - set(nets))
    print(f"  {sum(len(v) for v in puertos.values())} top ports read from the DEF"
          + (f"   CAREFUL, no net in the DEF: {huerfanos}" if huerfanos else ""))
    for net, pins in sorted(nets.items()):
        seen, missing = set(), []
        #  The top's own pin goes in the same bag as the macro ones: if it lands
        #  on a different extracted net, the port is floating.
        for layer, px, py in puertos.get(net, []):
            n = l2n.probe_net(regions.get(layer, regions["Metal3"]),
                              kdb.DPoint(px, py))
            if not n:
                missing.append(f"PIN {net} ({layer})")
                continue
            seen.add(n.expanded_name())
            donde.setdefault(n.expanded_name(), set()).add(net)
        for iname, pin in pins:
            if iname not in inst:
                continue
            cell, x, y, orient = inst[iname]
            x, y = x / units, y / units
            for r in lefs.get(cell, {}).get(pin, []):
                a = place(r, x, y, orient, sizes[cell], origenes[cell])
                pt = kdb.DPoint((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
                n = l2n.probe_net(regions["Metal3"], pt)
                if not n:
                    missing.append(f"{iname}.{pin}")
                    continue
                seen.add(n.expanded_name())
                donde.setdefault(n.expanded_name(), set()).add(net)
        if len(seen) > 1 or missing:
            abiertas += 1
            print(f"  OPEN     {net:14s} {len(pins)} terminals -> {len(seen)} nets"
                  + (f", sin metal: {', '.join(missing)}" if missing else ""))

    cortos = sorted((v for v in donde.values() if len(v) > 1), key=len, reverse=True)
    for v in cortos:
        print(f"  SHORT    {len(v)} DEF nets on the same extracted net: "
              f"{', '.join(sorted(v))}")

    print(f"\n{len(nets) - abiertas}/{len(nets)} DEF nets connected in the GDS"
          f"   |   {len(cortos)} corto(s)")
    return 1 if abiertas or cortos else 0


if __name__ == "__main__":
    sys.exit(main())
