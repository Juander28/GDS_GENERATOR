#!/usr/bin/env python3
"""Builds the integration cell: our block inside the padring's user area.

    python3 scripts/integrate_padframe.py

WHAT THIS IS. `padframe/B26_A.def` is 1110 x 1110 um with 73 pins on its west
and north edges and NO COMPONENTS: an empty template. The padring does not
instantiate our block either (`B26_A_padring.v` has 552 pad and filler
instances and none of ours), so filling that area is our job -- placing the
macro, routing to the pins, and PROGRAMMING THE DIGITAL PADS.

WHY 73 PINS FOR 19 SIGNALS. Eleven analogue signals and two supplies are one
pin each. Each of the six digital ones is a `gf180mcu_fd_io__bi_t`, and that
pad brings its whole control interface into the user area. The padring ties
none of it: those pins are ours to drive.

CAREFUL WITH THE NAMES. `<sig>_OUT` is the pad's terminal `A`, which is its
data INPUT -- the opposite of what the name suggests -- and `<sig>_IN` is the
receiver output `Y`, which we do not use. The mapping is not guessed: it is
read from `B26_A_interface.yaml`, which gives `cell_terminal` for every pin.

This file writes the Verilog and the pin constraints; `integrate_top.tcl`
places and routes them.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
PADFRAME = ROOT / "padframe"
MACRO = "GRADIENT_NAV2"
CELL = "B26_A"

# --------------------------------------------------------------------------- #
#  HOW THE DIGITAL PADS ARE PROGRAMMED. This table is the whole configuration:
#  one line per control terminal, and nothing about it is repeated anywhere
#  else. Changing the drive strength or the slew for the next revision is one
#  edit here.
#
#  It comes straight from the truth table of gf180mcu_fd_io section 4.2:
#
#      OE PU PD  A  PAD                 IE PU PD PAD  Y
#       1  X  X  0   0                   0  X  X  X   0
#       1  X  X  1   1
#
#  With OE=1 the pad drives A out and PU/PD stop mattering; with IE=0 the
#  receiver is off. Everything else is set to the quietest option, which is what
#  an analogue chip wants: lowest drive and slow slew.
# --------------------------------------------------------------------------- #
PROGRAMMING = {
    "OE":    ("VDD", "output always enabled: these six are permanent outputs"),
    "IE":    ("VSS", "receiver off; we never read the pad back"),
    "PU":    ("VSS", "no pull-up (don't care with OE=1, but tie it somewhere)"),
    "PD":    ("VSS", "no pull-down"),
    "CS":    ("VSS", "plain CMOS input rather than Schmitt (moot with IE=0)"),
    "SL":    ("VSS", "slow slew: less noise injected into an analogue chip"),
    "PDRV0": ("VSS", "drive strength 4 mA, the lowest"),
    "PDRV1": ("VSS", "  ... the other half of the same code"),
}
#: The pad terminal that carries OUR data into the pad, and the one we ignore.
DATA_IN, DATA_OUT = "A", "Y"

DBU = 200            # the padring DEF's units
AREA = 222000        # dbu, both sides of the user area
#: How far the block keeps from the edges of the user area. Not cosmetic: the
#: west and north channels have to hold TWO power buses -- one per supply, since
#: the 48 control pins alternate between them -- plus the clearance the macro's
#: Metal4 obstructions demand (MIMTM.1 wants 1.2 um from a MIM plate to any
#: other Metal4, measured OUTSIDE the macro too). At 5 um the VDD bus landed
#: inside that halo. 12 costs nothing: the area is 1110 um and the block is 418.
KEEPOUT = 60.0


def read_die_pins(path: Path):
    """{name: (x, y)} of our own pins in um, plus '_w'/'_h' for the die."""
    txt = path.read_text()
    dbu = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))
    out, cur = {}, None
    for line in txt.splitlines():
        m = re.match(r"\s*- (\S+) \+ NET", line)
        if m:
            cur = m.group(1); continue
        m = re.match(r"\s*\+ (?:PLACED|FIXED) \( (-?\d+) (-?\d+) \)", line)
        if m and cur:
            out[cur] = (int(m.group(1)) / dbu, int(m.group(2)) / dbu); cur = None
    s = re.search(r"DIEAREA \( 0 0 \) \( (\d+) (\d+) \)", txt)
    out["_w"], out["_h"] = int(s.group(1)) / dbu, int(s.group(2)) / dbu
    return out


def read_def_pins(path: Path):
    """[(name, direction, use, [(layer, x0, y0, x1, y1), ...])] in file order."""
    out, cur, boxes = [], None, []
    for line in path.read_text().splitlines():
        m = re.match(r"^- (\S+) \+ NET \S+ \+ DIRECTION (\S+) \+ USE (\S+)", line)
        if m:
            if cur:
                out.append(cur + (boxes,))
            cur, boxes = m.groups(), []
            continue
        m = re.match(r"\s*\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)", line)
        if m and cur:
            boxes.append((m.group(1),) + tuple(int(v) for v in m.groups()[1:]))
    if cur:
        out.append(cur + (boxes,))
    return out


def read_terminals(path: Path):
    """{def pin name: cell terminal}, from the organisers' own interface file."""
    d = yaml.safe_load(path.read_text())
    out, seen = {}, {}
    for p in d["pins"]:
        base = p["user_pin_name"]
        term = p.get("cell_terminal")
        #  A signal with one entry keeps its bare name; one with many gets the
        #  `_TERM` suffix the DEF uses. The file lists them in the same order.
        seen.setdefault(base, []).append(term)
    for base, terms in seen.items():
        if len(terms) == 1:
            out[base] = terms[0]
        else:
            for t in terms:
                out[f"{base}_{'OUT' if t == DATA_IN else 'IN' if t == DATA_OUT else t}"] = t
    return out


def build():
    pins = read_def_pins(PADFRAME / f"{CELL}.def")
    terms = read_terminals(PADFRAME / f"{CELL}_interface.yaml")
    info = yaml.safe_load((PROJECT / "info.yaml").read_text())["pins"]
    senal = {p["name"]: p["io_type"] for p in info}

    #  Every DEF pin gets classified into exactly one of four kinds, and the
    #  classification is DERIVED, never listed by hand: add a pin to info.yaml
    #  and ask them for a new padring, and this follows.
    conexion, avisos = {}, []
    for name, direction, use, _boxes in pins:
        if name in senal:                       # analogue, or a supply
            conexion[name] = ("directo", name)
            continue
        base, _, suf = name.rpartition("_")
        term = terms.get(name)
        if term is None:
            avisos.append(f"{name}: no cell_terminal in the interface file")
            continue
        if term == DATA_IN:                     # the pad's data input: our signal
            conexion[name] = ("dato", base)
        elif term == DATA_OUT:                  # the receiver we do not use
            conexion[name] = ("suelto", base)
        elif term in PROGRAMMING:
            conexion[name] = ("rail", PROGRAMMING[term][0])
        else:
            avisos.append(f"{name}: terminal {term} is not in PROGRAMMING")
    if avisos:
        sys.exit("  the padring has pins this does not know what to do with:\n   "
                 + "\n   ".join(avisos))

    #  --- the Verilog -------------------------------------------------------
    macro_pins = [p["name"] for p in info]
    v = [f"// {CELL}: our block inside the padring's user area.",
         "// WRITTEN BY scripts/integrate_padframe.py -- do not edit by hand.",
         "//",
         "// The programming of the six digital pads lives in the PROGRAMMING",
         "// table of that script and nowhere else:"]
    for t, (rail, why) in PROGRAMMING.items():
        v.append(f"//   {t:6s} -> {rail}   {why}")
    v += ["", f"module {CELL} ("]
    v.append("    " + ",\n    ".join(n for n, *_ in pins) + ");")
    for name, direction, use, _b in pins:
        kind = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout"}[direction]
        v.append(f"  {kind} {name};")
    v.append("")
    for name, (que, quien) in conexion.items():
        if que == "rail":
            v.append(f"  assign {name} = {quien};")
    v += ["", f"  {MACRO} x_core ("]
    arg = []
    for p in macro_pins:
        if p in conexion and conexion[p][0] == "directo":
            arg.append(f".{p}({p})")
        else:                                    # a digital output: goes to _OUT
            arg.append(f".{p}({p}_OUT)")
    v.append("      " + ",\n      ".join(arg) + ");")
    v += ["", "endmodule"]
    (ROOT / "verilog" / f"{CELL}.v").write_text("\n".join(v) + "\n")

    #  --- the pin constraints ----------------------------------------------
    #  Fixed positions, straight from their DEF: the pads are where they are and
    #  nothing here gets to choose. One `place_pin` per pin, with the box of its
    #  FIRST rectangle -- the others are the same shape repeated down the slot.
    t = ["#  WRITTEN BY scripts/integrate_padframe.py -- do not edit by hand.",
         "#  Pin positions copied from padframe/B26_A.def: the pads are where the",
         "#  organisers put them and nothing here gets to choose.", ""]
    #  ALL the rectangles of each pin, not just the first. An analogue pad is a
    #  comb of eight, and creating the pin from one of them left the other seven
    #  as metal the router did not know about: one `Metal Spacing` on S4P, a
    #  0.07 um sliver at the edge of the second rectangle.
    for name, direction, use, boxes in pins:
        t.append(f"set PIN({name}) {{" + " ".join(
            "{" + f"{l} {a} {b} {c} {d}" + "}" for l, a, b, c, d in boxes) + "}")
    #  Which rail each tie-off goes to, and which pins carry a real signal.
    #  Written here so the tcl never repeats the PROGRAMMING table.
    t.append("")
    for name, (que, quien) in conexion.items():
        if que == "rail":
            t.append(f"set RAIL({name}) {quien}")
    t.append("set TIEOFFS {" + " ".join(n for n, (q, _) in conexion.items()
                                        if q == "rail") + "}")
    t.append("set SIGNALS {" + " ".join(n for n, (q, _) in conexion.items()
                                        if q in ("dato", "directo")) + "}")
    t.append("")

    #  WHERE THE MACRO GOES. Chosen by minimising the total Manhattan distance
    #  from each pad to the die pin of the same name, over a grid of candidate
    #  origins, with the block kept clear of the four edges. Only the SIGNAL and
    #  supply pins count: the 48 tie-offs go to a rail and their distance to the
    #  macro means nothing.
    die = read_die_pins(ROOT / "out_v2_GRADIENT_NAV2" / f"{MACRO}_routed.def")
    #  The six digital signals are called XP in the macro and XP_OUT in the
    #  padring, so they have to be mapped or they drop out of the cost and the
    #  placement is chosen from 13 pins instead of 19.
    real = []
    for n, _d, _u, boxes in pins:
        m = n if n in die else (conexion.get(n, ("", ""))[1]
                                if conexion.get(n, ("",))[0] == "dato" else None)
        if m in die:
            real.append((m, boxes))
    best = None
    y = KEEPOUT
    while y <= AREA / DBU - die["_h"] - KEEPOUT:
        x = KEEPOUT
        while x <= AREA / DBU - die["_w"] - KEEPOUT:
            c = sum(abs((b[0][1] + b[0][3]) / 2 / DBU - (x + die[m][0]))
                    + abs((b[0][2] + b[0][4]) / 2 / DBU - (y + die[m][1]))
                    for m, b in real)
            if best is None or c < best[0]:
                best = (c, x, y)
            x += 5.0
        y += 5.0
    t.append("")
    t.append(f"#  cost {best[0]:.0f} um over the {len(real)} signal and supply pins")
    t.append(f"set MACRO_ORIGIN {{{best[1]:.3f} {best[2]:.3f}}}")
    t.append(f"set MACRO_SIZE {{{die['_w']:.3f} {die['_h']:.3f}}}")
    t.append("")
    t.append("set PIN_ORDER {" + " ".join(n for n, *_ in pins) + "}")
    (ROOT / "constraints" / f"{CELL}_pins.tcl").write_text("\n".join(t) + "\n")

    cuenta = {}
    for _n, (q, _w) in conexion.items():
        cuenta[q] = cuenta.get(q, 0) + 1
    print(f"  {len(pins)} pins: " + ", ".join(f"{v} {k}" for k, v in sorted(cuenta.items())))
    print(f"  -> verilog/{CELL}.v")
    print(f"  -> constraints/{CELL}_pins.tcl")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
