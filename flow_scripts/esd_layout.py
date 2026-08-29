#!/usr/bin/env python3
"""Draws ESD_CDM, the secondary (CDM) ESD cell, device by device.

    env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/esd_layout.py

WHY THIS IS NOT BUILT LIKE EVERY OTHER BLOCK. `coil_layout` knows three kinds of
device -- MOSFET, poly resistor and MIM capacitor -- and this cell is made of
diodes. Hand it a diode line and its parser reads it as a transistor. Adding a
diode family to the generator means a parser, a placement module and routing
hooks; this cell is five devices in two rows, so it is drawn here instead and
the generator is left alone.

WHAT IT DRAWS (see XSCHEM_v2/ESD_CDM.sch, which is the circuit):

    PAD --[ R1: 5 x (1 x 10 um) unsilicided poly, in parallel ]-- CORE
     |
     +-- D1, D2  diode_nd2ps_06v0  anode VSS (substrate) -> cathode PAD
     +-- D3, D4  diode_pd2nw_06v0  anode PAD -> cathode VDD (n-well)

Each diode is 10 x 5 um, so pj = 2*(10+5) = 30 um where the PDK asks for more
than 25, and there are two per direction.

THE INTERFACE IS THE ONE EVERY OTHER BLOCK EXPORTS, because the top flow reads
blocks through it and nothing else:

  * VSS and VDD as metal1 rails across the full width, RAIL_WIDTH tall;
  * a metal3 BAR over each rail with a via1+via2 stack every _PITCH um. That bar
    is the landing pad for the top's vertical Metal4 straps -- without it pdngen
    reports `PDN-0232 grid does not contain any shapes or vias` and aborts;
  * PAD and CORE as metal3 pads ON THE ROUTING TRACK GRID (0.28 + k*0.56), so
    the top router lands centred instead of clipping the edge;
  * a text label per port on metal1, on BOTH 34/0 and 34/10. magic reads the
    GDS text, `build_collateral.py` runs `port makeall` to promote them, and
    without a label a pin simply does not appear in the LEF -- with no error.

The PCells bring their own comp, implants, well and contacts, but NO METAL1:
every contact has to be covered here, or CO.6 fires on the bare ones.
"""

from __future__ import annotations

import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import klayout.db as kdb

import sys
sys.path.insert(0, "/foss/designs/zotnetic_layout")
from coil_layout.pdk_manager import get_pdk_module          # noqa: E402

import gdsfactory as gf                                     # noqa: E402

OUT = Path("/foss/designs/a_zonetic2026/layouts/ESD_CDM")
CELL = "ESD_CDM"

GRID = 0.005
RAIL_W = 0.9              # same as coil_layout.placement.RAIL_WIDTH
TRACK_PITCH, TRACK_OFF = 0.56, 0.28

#: Diode geometry. `wa` runs along x and `la` along y, so this is 10 wide by
#: 5 tall and pj = 2*(10+5) = 30 um.
D_WA, D_LA = 10.0, 5.0
#: Column pitch of the two diodes in a row. The two pd2nw bring an n-well each
#: and NW.2 wants 0.6 um between wells at the same potential; at a pitch of 12
#: the gap came to 0.44. 13 leaves 1.44.
D_PITCH_X = 13.0

#: Resistor: five 1 x 2 um bodies of high-sheet poly, in parallel.
#: `ppolyf_u_high_Rs_res` and not `ppolyf_res(ppolyf_u)`: measured on the PCells
#: alone, the first has no violation of its own and the second brings SB.4,
#: PP.2 and PRES.7 with it.
R_W, R_L, R_N = 1.0, 2.0, 5
#: Row pitch. The PCell's salicide block runs from -0.28 to w+0.28, so at a
#: pitch of 2.6 two neighbouring blocks stay 1.04 um apart.
R_PITCH_Y = 2.6
#: Where the high-Rs PCell puts its contacts, MEASURED on it and not assumed:
#: the substrate tap at -1.66..-1.44, the left poly head at -0.57..-0.35 and the
#: right one at l+0.35..l+0.57. The plain ppolyf_res puts them somewhere else
#: entirely, and reusing those numbers left thirty bare contacts (CO.6).
TAP_X0, TAP_X1 = -1.79, -1.31
HEAD_L0, HEAD_L1 = -0.63, -0.29
HEAD_R0, HEAD_R1 = 0.29, 0.63

#: --- patches to the diode PCells --------------------------------------------
#: The PDK PCells are not clean on their own at these dimensions. Measured with
#: nothing else in the cell:
#:
#:   diode_nd2ps : CO.4 x24, DF.1a_MV x6
#:   diode_pd2nw : the same, plus NP.5b, NP.5di, DF.4c_MV, DF.4d_MV and DV.6
#:
#: All of it is in the TAP STRIP the PCell hangs off the left of the diode, and
#: in the n-well enclosure. The strip comes out 0.34 um wide with 0.22 um
#: contacts in it, so the comp overlaps the contact by 0.06 where CO.4 asks for
#: 0.07, and the well overlaps the p+ comp by 0.43 where DF.4c_MV asks for 0.6.
#: `pcmpgr=True` changes nothing -- checked.
#:
#: So the geometry is grown here. The numbers are the rule minima plus a
#: little, and they are applied on top of the PCell, which merges with it.
#: The tap strip as the PCell draws it, and how far it is grown on each side.
#: Its contacts sit at -0.64..-0.42 in a comp of -0.70..-0.36, so the comp
#: overlaps them by 0.06 where CO.4 asks for 0.07 -- on BOTH sides. And the
#: strip cannot simply be widened: the inner side already sits 0.36 um from the
#: diode's own comp, which is exactly DF.3a_MV's minimum, so growing inwards
#: trades CO.4 for DF.3a. What works is to grow the OUTER side and MOVE THE
#: CONTACTS out with it, which `_fix_strip_contacts` does on the written GDS.
STRIP_X0, STRIP_X1 = -0.70, -0.36
STRIP_GROW_OUT = 0.06
#: Where the replacement contacts go, relative to the diode origin, and how big.
#: 0.22 is CO.1's minimum size; at -0.66..-0.44 inside a comp of -0.76..-0.36
#: the overlap is 0.10 on the outside and 0.08 on the inside.
CONTACT = 0.22
STRIP_CO_X = -0.55                    # centre
IMPLANT_ENC = 0.20                    # NP.5/PP.5 beyond the widened comp
NWELL_PCOMP = 0.65                    # DF.4c_MV asks 0.6
DUALGATE_ENC = 0.30                   # DV.6 asks 0.24
#: And an LVPWELL under each nd2ps. This one is not about DRC at all: the LVS
#: deck extracts that diode as
#:     extract_devices(diode('diode_nd2ps_06v0'),
#:                     { 'N' => ..., 'P' => lvpwell_con })
#: so its ANODE is a LOW-VOLTAGE P WELL, not the bare substrate. Without a
#: 204/0 under it the device is simply not derived -- the extracted netlist came
#: back with the two pd2nw and no nd2ps at all, and no warning. The well holds
#: the diode's own p+ strip, which is what ties it to VSS.
LVPWELL_ENC = 0.60

#: Via stack of a rail drop, and of a port pad.
VIA, PAD_SZ = 0.26, 0.44
#: How often a drop goes on the rail bar.
DROP_PITCH = 2.0


def snap(v: float) -> float:
    return round(v / GRID) * GRID


def on_track(x: float) -> float:
    return snap(TRACK_OFF + round((x - TRACK_OFF) / TRACK_PITCH) * TRACK_PITCH)


def box(c, layer, x0, y0, x1, y1):
    """A rectangle, snapped to the manufacturing grid.

    Inserted straight instead of through `gf.components.rectangle`: that one
    caches cells by size and ends up reusing one cell for heights that differ by
    less than a nanometre, which drops OFFGRID vertices.
    """
    if x1 <= x0 or y1 <= y0:
        return
    c.shapes(c.kcl.layout.layer(*layer)).insert(
        kdb.DBox(snap(x0), snap(y0), snap(x1), snap(y1)))


def via_stack(c, gf180, L, x, y, layers=("via1", "via2")):
    """A via1+via2 stack centred on (x, y), with its metal1/2/3 pads."""
    for lay in ("metal1", "metal2", "metal3"):
        box(c, L[lay], x - PAD_SZ / 2, y - PAD_SZ / 2, x + PAD_SZ / 2, y + PAD_SZ / 2)
    for v in layers:
        c.add_ref(gf180.via_generator(
            x_range=(x - VIA / 2, x + VIA / 2), y_range=(y - VIA / 2, y + VIA / 2),
            via_layer=L[v], via_size=(VIA, VIA),
            via_enclosure=((PAD_SZ - VIA) / 2, (PAD_SZ - VIA) / 2),
            via_spacing=(VIA, VIA)))


def label(c, L, name, x, y):
    """The port label, on metal1 drawing AND on the metal1 label layer.

    Both, because magic reads one and KLayout's LVS deck the other, and a port
    that only carries one of them matches in one tool and not the other.
    """
    for layer in (L["metal1"], (34, 10)):
        c.shapes(c.kcl.layout.layer(*layer)).insert(
            kdb.DText(name, kdb.DTrans(kdb.DVector(x, y))))


# --------------------------------------------------------------------------- #
#  the floorplan
# --------------------------------------------------------------------------- #
#  Everything below is derived from three anchors and the PCell geometry, so
#  changing a device size moves the wiring with it.
MARGIN = 1.0
DX = 1.0                  # left edge of the first diode's main comp
Y_ND = 1.7                # the nd2ps row (clamps below VSS)
Y_PD = 8.6                # the pd2nw row (clamps above VDD)
Y_LINK = 7.5              # the horizontal PAD bar between the two rows
Y_VDD = 15.0              # bottom of the VDD rail
RX = 27.5                 # left edge of the resistor bodies
RY = 1.7


def build():
    gf180 = get_pdk_module("gf180")
    L = gf180.layer
    c = gf.Component(CELL)

    #  --- the four diodes ---------------------------------------------------
    #  The PCell puts the main comp at (0,0)-(wa,la) and the tap strip of the
    #  opposite implant just to its left, at x -0.70..-0.36. Which of the two is
    #  the anode depends on the type:
    #     nd2ps : main comp is n+   -> CATHODE (PAD); strip is p+ -> substrate (VSS)
    #     pd2nw : main comp is p+   -> ANODE   (PAD); strip is n+ -> n-well  (VDD)
    #  (the strip offsets live in STRIP_X0 / STRIP_X1 at the top)
    pad_m1, strips = [], []
    for kind, y, rail_y, tag in (("nd2ps", Y_ND, RAIL_W, "VSS"),
                                 ("pd2nw", Y_PD, Y_VDD, "VDD")):
        for k in range(2):
            x = DX + k * D_PITCH_X
            d = c.add_ref(getattr(gf180, f"diode_{kind}")(
                la=D_LA, wa=D_WA, volt="5/6V"))
            d.dmove((x, y))
            #  metal1 over the main comp: the PAD terminal. It starts 0.04 um
            #  inside the comp, which is enough to cover the outermost contact
            #  and keeps 0.40 um from the strip riser next door.
            box(c, L["metal1"], x + 0.04, y + 0.04, x + D_WA - 0.04, y + D_LA - 0.04)
            pad_m1.append((x + 0.04, y + 0.04, x + D_WA - 0.04, y + D_LA - 0.04))
            #  Widen the tap strip and its implant (see the constants above),
            #  then cover it with metal1 and carry that on to its rail.
            gx0 = x + STRIP_X0 - STRIP_GROW_OUT
            imp = L["pplus"] if kind == "nd2ps" else L["nplus"]
            gx1 = x + STRIP_X1
            box(c, L["comp"], gx0, y, gx1, y + D_LA)
            box(c, imp, gx0 - IMPLANT_ENC, y - IMPLANT_ENC,
                gx1 + 0.16, y + D_LA + IMPLANT_ENC)
            #  The n-well of a pd2nw has to overlap its p+ comp by 0.6 and its
            #  n+ tap by 0.16; the PCell gives 0.43 and 0.
            if kind == "pd2nw":
                box(c, L["nwell"], gx0 - 0.16 - 0.10, y - NWELL_PCOMP,
                    x + D_WA + NWELL_PCOMP, y + D_LA + NWELL_PCOMP)
            else:
                box(c, (204, 0), gx0 - LVPWELL_ENC, y - LVPWELL_ENC,
                    x + D_WA + LVPWELL_ENC, y + D_LA + LVPWELL_ENC)
            #  And the dualgate has to enclose every comp, tap included, by 0.24.
            box(c, L["dualgate"], gx0 - DUALGATE_ENC, y - DUALGATE_ENC,
                x + D_WA + DUALGATE_ENC, y + D_LA + DUALGATE_ENC)
            sx0, sx1 = gx0 + 0.02, gx1 - 0.02
            strips.append((x, y))
            box(c, L["metal1"], sx0, min(y, rail_y), sx1, max(y + D_LA, rail_y + RAIL_W))

    #  The bar that ties the four main comps together. It runs in the gap
    #  between the rows, clear of the n+ implant below (which stops at
    #  Y_ND + D_LA + 0.16) and of the n-well above (which starts at Y_PD - 0.43).
    x_pad_hi = DX + D_PITCH_X + D_WA - 0.04
    box(c, L["metal1"], DX + 0.04, Y_LINK - 0.5, x_pad_hi, Y_LINK + 0.5)
    for k in range(2):
        x = DX + k * D_PITCH_X
        box(c, L["metal1"], x + 0.5, Y_ND + D_LA - 0.04, x + 2.0, Y_LINK + 0.5)
        box(c, L["metal1"], x + 0.5, Y_LINK - 0.5, x + 2.0, Y_PD + 0.04)

    #  --- the resistor: five fingers in parallel ----------------------------
    #  The PCell hangs a SUBSTRATE TAP off the left of each body, at
    #  x -1.52..-1.16, and its contact sits between the tap and the left head.
    #  Covering both with one piece of metal is what once tied a resistor end to
    #  ground with a clean DRC, so the two get separate covers.
    r_top = RY + (R_N - 1) * R_PITCH_Y + R_W
    for i in range(R_N):
        y = RY + i * R_PITCH_Y
        r = c.add_ref(gf180.ppolyf_u_high_Rs_res(l_res=R_L, w_res=R_W, volt="5V"))
        r.dmove((RX, y))
        box(c, L["metal1"], RX + HEAD_L0, y + 0.05, RX + HEAD_L1, y + R_W - 0.05)
        box(c, L["metal1"], RX + R_L + HEAD_R0, y + 0.05,
            RX + R_L + HEAD_R1, y + R_W - 0.05)
        box(c, L["metal1"], RX + TAP_X0, y + 0.05, RX + TAP_X1, y + R_W - 0.05)
    #  the three vertical bars: PAD, CORE, and the taps down to VSS
    box(c, L["metal1"], RX + HEAD_L0, RY, RX + HEAD_L1, r_top)
    box(c, L["metal1"], RX + R_L + HEAD_R0, RY, RX + R_L + HEAD_R1, r_top)
    box(c, L["metal1"], RX + TAP_X0, RAIL_W - 0.1, RX + TAP_X1, r_top)

    #  --- PAD, from the diodes to the resistor ------------------------------
    #  Over the tap bar, so it goes in metal2 with a via at each end. Metal1
    #  cannot cross it, and going round would be longer than the cell.
    x_a, x_b = x_pad_hi - 1.0, RX - 0.1
    box(c, L["metal2"], x_a - PAD_SZ / 2, Y_LINK - PAD_SZ / 2,
        x_b + PAD_SZ / 2, Y_LINK + PAD_SZ / 2)
    for x in (x_a, x_b):
        box(c, L["metal1"], x - PAD_SZ / 2, Y_LINK - PAD_SZ / 2,
            x + PAD_SZ / 2, Y_LINK + PAD_SZ / 2)
        c.add_ref(gf180.via_generator(
            x_range=(x - VIA / 2, x + VIA / 2),
            y_range=(Y_LINK - VIA / 2, Y_LINK + VIA / 2),
            via_layer=L["via1"], via_size=(VIA, VIA),
            via_enclosure=((PAD_SZ - VIA) / 2, (PAD_SZ - VIA) / 2),
            via_spacing=(VIA, VIA)))

    #  --- rails, their metal3 bars and the drops ----------------------------
    W = RX + R_L + HEAD_R1 + MARGIN
    H = Y_VDD + RAIL_W
    for y0, name in ((0.0, "VSS"), (Y_VDD, "VDD")):
        box(c, L["metal1"], 0.0, y0, W, y0 + RAIL_W)
        box(c, L["metal3"], 0.0, y0, W, y0 + RAIL_W)
        x = MARGIN
        while x <= W - MARGIN:
            via_stack(c, gf180, L, snap(x), y0 + RAIL_W / 2)
            x += DROP_PITCH

    #  --- the two signal ports, on metal3 and on the routing grid -----------
    for name, x, y in (("PAD", on_track(DX + 3.0), Y_LINK),
                       ("CORE", on_track(RX + R_L + 0.46), Y_LINK)):
        via_stack(c, gf180, L, x, y)

    #  --- labels ------------------------------------------------------------
    label(c, L, "PAD", on_track(DX + 3.0), Y_LINK)
    label(c, L, "CORE", on_track(RX + R_L + 0.46), Y_LINK)
    label(c, L, "VSS", W / 2, RAIL_W / 2)
    label(c, L, "VDD", W / 2, Y_VDD + RAIL_W / 2)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{CELL}_flat_gf180.gds"
    c.write_gds(path)
    _fix_strip_contacts(path, strips)
    b = c.dbbox()
    print(f"  {CELL}: {b.width():.2f} x {b.height():.2f} um -> {path}")
    return path




def _fix_strip_contacts(path, strips):
    """Move the tap-strip contacts outwards, on the written GDS.

    The PCell centres them in a strip that is 0.02 um too narrow for CO.4, and
    the strip cannot grow inwards (DF.3a_MV). So the comp is grown outwards in
    `build` and the contacts follow here: the originals are deleted and redrawn
    at the same heights, 0.03 um further out.

    It is done on the GDS and not on the Component because the contacts belong
    to the PCell, and reaching inside a gdsfactory reference to delete a shape
    is a good deal more fragile than reading the flat layout back.
    """
    ly = kdb.Layout()
    ly.read(str(path))
    top = ly.top_cell()
    top.flatten(-1, True)
    co = ly.layer(33, 0)
    dbu = ly.dbu
    moved = 0
    for (x, y) in strips:
        lo, hi = (x - 0.80) / dbu, (x - 0.34) / dbu
        ys = []
        todo = []
        for s in top.each_shape(co):
            b = s.box if s.is_box() else s.polygon.bbox()
            if lo <= (b.left + b.right) / 2 <= hi and y / dbu - 1 <= b.bottom:
                if b.top <= (y + D_LA) / dbu + 1:
                    ys.append((b.bottom + b.top) / 2 * dbu)
                    todo.append(s)
        for s in todo:
            s.delete()
        cx = x + STRIP_CO_X
        for cy in ys:
            top.shapes(co).insert(kdb.DBox(snap(cx - CONTACT / 2), snap(cy - CONTACT / 2),
                                           snap(cx + CONTACT / 2), snap(cy + CONTACT / 2)))
        moved += len(ys)
    ly.write(str(path))
    print(f"  tap-strip contacts moved out: {moved}")




#: The LVS reference netlist. It is written HERE, next to the layout it has to
#: match, for the same reason `decap_fill.py` writes its devices into the
#: schematic: the two have to be produced from one source or they drift.
#: Five resistor bodies and four diodes, one line each, because that is what
#: both extractors see -- one device per drawn body.
LVS_TEMPLATE = """* ESD_CDM: the secondary (CDM) ESD network.
* Written by openroad/scripts/esd_layout.py, together with the GDS it matches.
* The circuit is XSCHEM_v2/ESD_CDM.sch; see it for why the diodes are these two
* types and no others.
.subckt ESD_CDM PAD CORE VDD VSS
{diodes}
{resistors}
.ends
"""


def write_lvs(path=None):
    dio = "\n".join(
        [f"D{i} VSS PAD diode_nd2ps_06v0 AREA={D_WA * D_LA:.0f}p PJ={2 * (D_WA + D_LA):.0f}u"
         for i in (1, 2)] +
        [f"D{i} PAD VDD diode_pd2nw_06v0 AREA={D_WA * D_LA:.0f}p PJ={2 * (D_WA + D_LA):.0f}u"
         for i in (3, 4)])
    #  1000 ohm/square is the sheet the KLayout deck uses for ppolyf_u_1k, and
    #  netgen is given the same number through gf180mcuD_setup_polyres.tcl.
    #  It is the implant this shuttle runs; the GEOMETRY is the same for 1k, 2k
    #  and 3k, so nothing above this line changes with it.
    res = "\n".join(
        f"R{i} CORE PAD VSS ppolyf_u_1k W={R_W}e-06 L={R_L}e-06 R={R_L / R_W * 1000:.0f}"
        for i in range(1, R_N + 1))
    p = path or (OUT / f"{CELL}_lvs.spice")
    p.write_text(LVS_TEMPLATE.format(diodes=dio, resistors=res))
    print(f"  LVS reference -> {p}")
    return p


if __name__ == "__main__":
    build()
    write_lvs()
