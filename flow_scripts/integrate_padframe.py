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
#  EL ESD SECUNDARIO VIVE AQUI, no dentro del bloque. La red -- resistencia en
#  serie mas dos diodos -- tiene que estar JUNTO AL PAD, que es de donde viene el
#  evento: metida dentro del bloque, la pista del pad hasta el bloque queda por
#  delante de la sujecion y no la protege nada.
#
#  Es la celda de los organizadores, adoptada tal cual (ver
#  layouts_v2/io_secondary_5p0/README_ORIGEN.txt). Su `ASIG5V` mira al pad y su
#  `to_gate` al bloque, asi que la senal pasa POR la celda: el nucleo se conecta
#  a `<PIN>_I`, no al pin del die. Ese es tambien el nombre que usa
#  XSCHEM/B26_A.sch, y las dos cosas tienen que coincidir o el LVS no cuadra.
# --------------------------------------------------------------------------- #
#: La celda que se fabrica. Paso de ser la de los organizadores a la nuestra:
#: mismo circuito exacto -- 4+4 diodos de 10x10 y `ppolyf_u` W=16 L=4 con el bulk
#: en VDD, tal cual su esquematico -- pero 1.762 um2 en vez de 6.457, y sin la
#: `MSLOT.1` que arrastran las tres variantes suyas. Ver `esd_layout.py`.
ESD_CELL = "ESD_CDM"
ESD_W, ESD_H = 63.16, 27.90

#: Sufijo del lado del nucleo. Lo fija el esquematico, no este fichero.
ESD_SUF = "_I"

#: Donde puede empezar un clamp, contando desde el borde del die.
#:
#: NO basta con librar los anillos (`VDD_OFF + BUS_W` = 28 + 24 = 52). Por
#: delante de ellos corre el CANAL DE ESCAPE de los pines: `integrate_top.tcl`
#: le da a cada senal una tirada recta de metal2 desde su pad hasta
#: `ESCAPE_X = pista(VDD_OFF + BUS_W + 4)` = 55.72, y otro tanto por el norte
#: hasta `ESCAPE_Y` = 1054.20.
#:
#: Puestos en x = 54 los clamps caian DENTRO de ese canal, y el resultado no era
#: un DRC sino un cortocircuito: la placa de metal2 del escape se sienta encima
#: del clamp y toca su interior, puenteando la resistencia en serie. Las once
#: nets `<PIN>_I` se fundian con su pad -- 882 nets en el layout contra 894 en el
#: esquematico -- y el ESD quedaba anulado sin que el DRC dijese nada.
#:
#: 58 y 60 dejan 2.3 y 5.8 um de aire sobre el final del canal.
BUS_EDGE = 58.0

#: Aire entre el borde del die y el clamp por el lado del norte.
ESD_MARGEN = 60.0

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


def sitio_esd(pins, con_esd):
    """Donde va el clamp de cada pin: pegado a su pad, dentro de los anillos.

    Los once pads analogicos estan en el borde OESTE (cinco) y en el NORTE
    (seis), a 100 um entre si; la celda mide 75.65 x 85.35, asi que alineandola
    con su pad no se tocan entre ellas. Se pega a `BUS_EDGE`, que es donde acaba
    el anillo de VDD, para dejar la pista del pad al clamp lo mas corta posible:
    lo que hay por delante de la sujecion no esta protegido.
    """
    caja = {n: b[0] for n, _d, _u, b in pins if b}
    out, ocupado = {}, []
    for name in con_esd:
        if name not in caja:
            continue
        _l, x0, y0, x1, y1 = caja[name]
        cx, cy = (x0 + x1) / 2 / DBU, (y0 + y1) / 2 / DBU
        if cx < AREA / DBU / 2 and (x0 + x1) / 2 / DBU < BUS_EDGE:
            #  pad del oeste: el clamp a su derecha, centrado en su y
            x, y = BUS_EDGE, cy - ESD_H / 2
        else:
            #  pad del norte: el clamp debajo, centrado en su x
            x, y = cx - ESD_W / 2, AREA / DBU - ESD_MARGEN - ESD_H
        #  dentro del area util, pase lo que pase
        x = min(max(x, BUS_EDGE), AREA / DBU - ESD_MARGEN - ESD_W)
        y = min(max(y, BUS_EDGE), AREA / DBU - ESD_MARGEN - ESD_H)
        out[name] = (round(x, 3), round(y, 3))
        ocupado.append((x, y, x + ESD_W, y + ESD_H))
    return out, ocupado


def build():
    pins = read_def_pins(PADFRAME / f"{CELL}.def")
    terms = read_terminals(PADFRAME / f"{CELL}_interface.yaml")
    info = yaml.safe_load((PROJECT / "info.yaml").read_text())["pins"]
    senal = {p["name"]: p["io_type"] for p in info}
    #  DERIVADO del info.yaml, no listado a mano: quien lleve `secondary_esd`
    #  lleva clamp, y anadir un pin analogico alli basta para que aparezca aqui.
    con_esd = [p["name"] for p in info if p.get("secondary_esd")]

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
    #  Los clamps de ESD secundario, uno por pin analogico. La senal pasa POR
    #  ellos: el pad ataca `ASIG5V` y el nucleo cuelga de `to_gate`, que es el
    #  otro lado de la resistencia en serie.
    if con_esd:
        v.append("")
        v.append(f"  // Secondary ESD, one {ESD_CELL} per analogue pin.")
        v.append("  // Series resistor plus the two diodes, NEXT TO THE PAD:")
        v.append("  // anything between the pad and the clamp is unprotected.")
        for name in con_esd:
            v.append(f"  wire {name}{ESD_SUF};")
        for name in con_esd:
            v.append(f"  {ESD_CELL} x_esd_{name} ("
                     f".PAD({name}), .CORE({name}{ESD_SUF}), "
                     f".VDD(VDD), .VSS(VSS));")

    v += ["", f"  {MACRO} x_core ("]
    arg = []
    for p in macro_pins:
        if p in con_esd:                         # detras de su clamp
            arg.append(f".{p}({p}{ESD_SUF})")
        elif p in conexion and conexion[p][0] == "directo":
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
    #  LOS CLAMPS SON ZONA VEDADA para el macro. Van pegados a los pads, o sea
    #  en la franja oeste y en la norte, y el nucleo tiene que buscarse la vida
    #  en lo que queda -- que sobra: 460.9 x 387 dentro de unos 920 x 910.
    esd_pos, esd_cajas = sitio_esd(pins, con_esd)

    #  Con un halo: pegado no vale. Sin el, el optimizador dejaba el nucleo a
    #  0.35 um del clamp del oeste, donde no cabe ni una pista de las que tienen
    #  que salir del propio clamp hacia el bloque.
    ESD_HALO = 12.0

    def choca(x, y):
        ax0, ay0, ax1, ay1 = x, y, x + die["_w"], y + die["_h"]
        return any(ax0 < bx1 + ESD_HALO and ax1 > bx0 - ESD_HALO
                   and ay0 < by1 + ESD_HALO and ay1 > by0 - ESD_HALO
                   for bx0, by0, bx1, by1 in esd_cajas)

    best = None
    y = KEEPOUT
    while y <= AREA / DBU - die["_h"] - KEEPOUT:
        x = KEEPOUT
        while x <= AREA / DBU - die["_w"] - KEEPOUT:
            if choca(x, y):
                x += 5.0
                continue
            c = sum(abs((b[0][1] + b[0][3]) / 2 / DBU - (x + die[m][0]))
                    + abs((b[0][2] + b[0][4]) / 2 / DBU - (y + die[m][1]))
                    for m, b in real)
            if best is None or c < best[0]:
                best = (c, x, y)
            x += 5.0
        y += 5.0
    if best is None:
        sys.exit(f"  {die['_w']:.1f} x {die['_h']:.1f} um no cabe dejando sitio "
                 f"a los {len(esd_cajas)} clamps de ESD")
    t.append("")
    t.append(f"#  cost {best[0]:.0f} um over the {len(real)} signal and supply pins")
    t.append(f"set MACRO_ORIGIN {{{best[1]:.3f} {best[2]:.3f}}}")
    t.append(f"set MACRO_SIZE {{{die['_w']:.3f} {die['_h']:.3f}}}")
    t.append("")
    t.append("set PIN_ORDER {" + " ".join(n for n, *_ in pins) + "}")
    t.append("")
    t.append(f"#  Los {len(esd_pos)} clamps de ESD secundario, cada uno junto a su pad.")
    t.append(f"set ESD_CELL {ESD_CELL}")
    for name, (x, y) in esd_pos.items():
        t.append(f"set ESD({name}) {{{x:.3f} {y:.3f}}}")
    t.append("set ESD_PINS {" + " ".join(esd_pos) + "}")
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
