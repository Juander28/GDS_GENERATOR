#!/usr/bin/env python3
"""Fills the gaps in the top with transistors wired as capacitors.

    python3 scripts/decap_fill.py --tile 16x47.85    # one loose tile, for DRC
    python3 scripts/decap_fill.py                    # el top entero

WHAT GETS DRAWN. In each gap, bands of NMOS and PMOS with their tap strips. The
NMOS has its gate on VDD and its channel, source, drain and bulk on VSS; the
PMOS the other way round. That way both sit in inversion and give the full gate
oxide capacitance, which is the whole point.

HOW THEY ARE POWERED, which is what decides where fill can go and where it
cannot. The top's power network is Metal4 strips (vertical, above the blocks)
and Metal5 ones (horizontal, along the channels): there is no low-metal power
in the gaps. But **within a shelf every macro is the same height** and each
block brings its VSS rail out on Metal1 at the bottom and VDD on Metal1 at the
top, at the same height. Fill dropped into a gap on that shelf connects to the
neighbour's rails **by abutment on Metal1**, without a single via and without
touching Metal2 or Metal3, where the routing that already closed at DRC 0 runs.

Corollary: only gaps with a macro beside them whose rails are at the same height
get filled. The rest -- the margin band and the channels between shelves --
stays empty and is reported, because reaching there would need a via stack up to
Metal5 and that stack crosses the routing.

**The rails do NOT reach both macro edges.** Measured on the top: the VSS rail
of the left neighbour ends exactly at its right edge (x = 96.830), but the one
on the right starts **0.26 um inside** (x = 112.820 for a macro whose edge is at
112.560). A tile drawing its rail edge to edge is **left open on that side**,
and 0.26 > 0.23 so DRC says nothing.
That is why the rails are stretched to OVERLAP the neighbour's, measuring it in
the GDS (`alcance`), and at the end real connectivity is checked (`comprobar`).

What got settled along the way, and is worth not stepping on again:

  * **The gate is `boxes[-1]` for BOTH types.** Both devices are built with
    `gate_con="top"`, so the gate plate is always the top one. Taking
    `boxes[0]` for the PMOS took a drain for a gate: the gate plate (2.0 um
    wide, the channel one) was stretched to the opposite rail, came within
    0.07 um of source and drain -- the four remaining `M1.2a` -- and on top of
    that the PMOS ended with its gate on VDD and a drain on VSS, i.e. **cut off
    and with no capacitance at all**.
  * **The PCell is not called raw.** `coil_layout`'s `map_device` already places
    the pad metal1 and applies `_fix_pcell_co7_gf180`; without it, 220 `CO.7`.
  * **No guard ring.** The PCell's comes out with `grw=0.22` and `DF.1a_MV` asks
    0.30: 768 `CO.4` + 348 `CO.7` + 184 `CO.6` on one tile. Bulk and well are
    tied by the `_tap` strips instead.
  * **The taps go IN the gaps between devices**, not at a fixed pitch from the
    edge, or they land 0.12 um from the neighbour's metal1. And the gap must
    measure at least `TAP_W + 2*CLR`: with 1.20 not one fitted and `DF.14_MV`
    fired, which asks for a bulk tap within 15 um of every NCOMP.
  * **The closing VSS bar started at `x0 - CLR`** and touched the VDD rail: it
    shorted the two supplies. DRC only hinted at it as four `M1.2a`; it was
    found by extracting the nets, not by reading the report.
  * **The well is kept 1.8 um from the tile edge.** Without `CONNECTIVITY_RULES`
    the deck applies `NW.2b_MV` and asks **1.7 um between wells even on the same
    net**; the right macro's well reaches right up to its edge.

ALTERNATING COLUMNS, not two rows. With a row of NMOS below and one of PMOS
above, each gate has to cross the whole height of the gap to the opposite rail,
and those two paths cross each other. Alternating the type by bands, each device
has its own bar below and the opposite one above, and its gate exits upwards.
Not one crossing.
"""

from __future__ import annotations

import os
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import klayout.db as kdb

sys.path.insert(0, "/foss/designs/zotnetic_layout")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from coil_layout.device_map import map_device               # noqa: E402
from coil_layout.spice_parser import Device                 # noqa: E402
from fill_density import colocacion                         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent

#: Top directory and cell, as everywhere else in the flow (`TOP_OUT` /
#: `TOP_CELL` are set by the Makefile).
OUT = ROOT / os.environ.get("TOP_OUT", "out")
TOP = os.environ.get("TOP_CELL", "GRADIENT_NAV")

GDS_IN = OUT / f"{TOP}.gds"
GDS_OUT = OUT / f"{TOP}_decap.gds"
DEF = OUT / f"{TOP}_routed.def"
DEV_TXT = OUT / "decap_devices.txt"
GAPS_TXT = OUT / "decap_gaps.txt"
SCH = PROJECT / "XSCHEM" / f"{TOP}.sch"

# --- capas de GF180 -----------------------------------------------------------
COMP, POLY, PPLUS, NPLUS, CONT, M1, NWELL = (22, 0), (30, 0), (31, 0), (32, 0), (33, 0), (34, 0), (21, 0)

# --- geometria ----------------------------------------------------------------
RAIL_W = 0.9        # block rail width; the fill continues them
CLR = 0.40          # metal1 clearance to another net's metal1 (M1.2a: 0.23)
L_CANAL = 2.0       # long channel: more oxide area per device
MIN_HEIGHT = 12.0     # below this no device fits between the two rails
MIN_WIDTH = 6.0
GRID = 0.005
TAP_W = 0.48        # DF.9 asks 0.2025 um2 of COMP; 0.45 is the minimum side
IMP_ENC = 0.18      # NP.5di/PP.5di piden 0.16
CO_S = 0.22
NWELL_ENC = 0.50    # nwell sobre la difusion p
NWELL_BORDE = 1.80  # nwell to tile edge: NW.2b_MV asks 1.7 um
TAP_PITCH = 6.0
BAR = 0.40          # height of the horizontal VDD/VSS bars
CARRIL = 0.60       # width of the vertical edge rails
RISER_W = 0.50      # width of the wire climbing from gate to its bar
W_MAX = 26.0        # `DF.13_MV` and `DF.14_MV` ask for a tap within 15 um of
                    # every PCOMP / NCOMP. With a tap **above and below** each
                    # row the worst point is the channel centre, W/2 + margins:
                    # 26 um leaves the centre at just over 14. With one tap the
                    # eran 11.
DEVICE_GAP = 1.44   # spacing between devices on the same row. It must fit a
                    # tap (0.48) with its metal1 clearance on each side: the
                    # taps go IN these gaps, not on top of the device. With
                    # 1.20 not ONE fitted and it fired
                    # `DF.14_MV`.
CLR_TAP = 0.60      # from a tap's COMP to the neighbouring device bbox
BORDE_DIE = 2.00    # guard margin against the die outline. A port DOES have to
                    # touch the edge -- that is the way in -- but fill does not:
                    # up against the outline, anything the integrator puts
                    # beside it (a seal ring, another project) ends at ZERO
                    # spacing. Before, the metal1 of the margin tiles reached
                    # 0.000 from the edge.
SOLAPE = 0.20       # how far the rail must ride onto the neighbour's
ALCANCE_MAX = 1.20  # and at most how far it is allowed in

#: x window of each row, measured from the tile edge. The PMOS one sits further
#: in because it drags the well, which needs `NWELL_BORDE`.
MARGEN_N = 2 * CLR + CARRIL
MARGEN_P = NWELL_BORDE + NWELL_ENC

#: Well margin on a side facing the DIE OUTLINE. There `NW.2b_MV` does not
#: apply -- there is no other well opposite -- and the `BORDE_DIE` guard margin
#: already leaves 2 um clear outside. Without this distinction, the eight tiles
#: on the die margins had no room for a single device (2.92 um of window against
#: the 3.66 it measures) and 0.77 pF were lost.
NWELL_BORDE_DIE = 0.20


def _reg(cell, layer) -> kdb.Region:
    ly = cell.kcl.layout
    return kdb.Region(cell.kdb_cell.begin_shapes_rec(ly.layer(*layer)))


_MADE: dict = {}


def device(kind: str, w_gate: float):
    """The device, wrapped by the SAME code the blocks use.

    The PCell is not called raw. `coil_layout.device_map.map_device` already puts
    metal1 over the source, drain and gate contacts, leaves named ports and
    applies `_fix_pcell_co7_gf180`, which fixes a
    separacion contacto-poly del PCell: llamandolo a pelo salian 220 `CO.7` en
    a single tile. Reusing it is also the guarantee that the fill is made of the
    same devices as the rest of the chip.

    `bulk` is not included: `map_device` always asks for them without a guard
    ring, and bulk and well are tied by `_tap`'s tap strips.
    """
    clave = (kind, round(w_gate, 3))
    if clave in _MADE:
        return _MADE[clave]
    dev = Device(name=f"{kind}{len(_MADE)}",
                 model=("nfet_06v0" if kind == "n" else "pfet_06v0"),
                 nodes={"drain": "d", "gate": "g", "source": "s", "bulk": "b"},
                 params={"L": f"{L_CANAL}u", "W": f"{w_gate}u", "nf": "1", "m": "1"})
    #  BOTH with the gate contact ON TOP. In this structure every device has its
    #  own bar below (its source one) and the opposite one above, so the gate
    #  always exits upwards. Bringing the PMOS one out at the bottom, its riser
    #  had to climb back up around the drain and
    #  pasaba a 0.07 um de el.
    wd = map_device(dev, "gf180", gate_con="top")
    _MADE[clave] = wd.component
    return wd.component


def copy_device(pc, destino, layout: kdb.Layout) -> None:
    """Vuelca la geometria de un PCell en `destino`, reescalando el dbu.

    The PCells live in a `coil_layout` layout with dbu 0.001 and the top's GDS
runs at 0.0005. `Cell.copy_tree` copies between layouts but **does not rescale**,
    and bringing the tiles in through a file is worse: `Layout.read` on a layout
    that already has cells **changes the destination dbu without touching what
    was already there**, so the whole top ends up at double coordinates. It was
    spotted because a tile's rail showed as 1.37 um tall instead of 0.9.

    `begin_shapes_rec` walks the tree and returns the shapes already transformed,
    so the device comes in flattened -- which is how the top ends up anyway.
    formas (`def_to_gds.py::flatten_all`).
    """
    origen = pc.kdb_cell.layout()
    escala = origen.dbu / layout.dbu
    for li in origen.layer_indexes():
        r = kdb.Region(pc.kdb_cell.begin_shapes_rec(li))
        if r.is_empty():
            continue
        if escala != 1.0:
            r.transform(kdb.ICplxTrans(escala))
        destino.shapes(layout.layer(origen.get_info(li))).insert(r)



def sn(v: float) -> float:
    return round(v / GRID) * GRID


def _tap(cell, layers, x, y, implant):
    """A tap: COMP + implant + contact + metal1, with the generator dimensions."""
    cell.shapes(layers[COMP]).insert(kdb.DBox(x, y, x + TAP_W, y + TAP_W))
    cell.shapes(layers[implant]).insert(
        kdb.DBox(x - IMP_ENC, y - IMP_ENC, x + TAP_W + IMP_ENC, y + TAP_W + IMP_ENC))
    cx = sn(x + (TAP_W - CO_S) / 2)
    cy = sn(y + (TAP_W - CO_S) / 2)
    cell.shapes(layers[CONT]).insert(kdb.DBox(cx, cy, cx + CO_S, cy + CO_S))


def _pcell_height(kind: str, w: float) -> float:
    return device(kind, w).kdb_cell.dbbox().height()


def _row_height(kind: str, w: float) -> float:
    """Height of a row: bar + bottom tap + device + top tap."""
    return (BAR + 0.10 + TAP_W + CLR_TAP + _pcell_height(kind, w)
            + CLR_TAP + TAP_W + 0.10)


def _band_height(w: float) -> float:
    """Exact height of the whole band: one NMOS row and one PMOS row."""
    return _row_height("n", w) + _row_height("p", w)


def _plan(usable: float) -> tuple[int, float]:
    """With what channel width, in **a single band**.

    One NMOS row and one PMOS row, nothing else. The height used to be split
across several stacked bands, choosing the combination that gave the most oxide
    area; now the whole height goes to **a single transistor per type**, as long
    as fits. Same capacitance with fewer devices, and without the ladder of bars
    and taps needed to interleave bands.

    The device's x width does not depend on W -- it is always 3.66 um, because W
    runs vertically -- so the number of devices per row is the same whatever is
    chosen, and the only thing being shared out is the height.
    """
    mejor, w = 0.0, 0.5
    while w <= W_MAX + 1e-9:
        if _band_height(w) + BAR <= usable:
            mejor = w
        else:
            break
        w = round(w + 0.25, 2)
    return (1, sn(mejor)) if mejor >= 0.5 else (0, 0.0)


def tile(layout: kdb.Layout, width: float, height: float, name: str,
            ext: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
            nw: tuple[float, float] = (NWELL_BORDE, NWELL_BORDE)):
    """A fill cell of `width` x `height`, with its rails on the edges.

    Estructura, de abajo arriba y repetida tantas veces como quepa:

        bar VSS / taps p+ / row NMOS (puerta arriba) / bar VDD
                  / taps n+ en el pozo / row PMOS (puerta arriba) / [bar VSS...]

    **Every metal crossing is within the SAME net**: the NMOS source and drain
    come down to their VSS bar crossing the p+ taps, which are VSS; the PMOS ones
    come down to the VDD bar crossing the n+ taps, which are VDD. Hence not one
    break in any strip and not a single via.

    The bars are tied to the rails by two vertical lanes, VDD on the left and VSS
    on the right. That is all the vertical distribution there is.

    `ext` are the four rail stretches measured against the neighbour, in the
    (VSS izquierda, VSS derecha, VDD izquierda, VDD derecha). `nw` es cuanto se
    keeps the well away from each tile edge: `NWELL_BORDE` against a macro and
    `NWELL_BORDE_DIE` contra el contorno del die.
    """
    top = layout.create_cell(name)
    L = {c: layout.layer(*c) for c in (COMP, POLY, PPLUS, NPLUS, CONT, M1, NWELL)}
    vss_i, vss_d, vdd_i, vdd_d = ext

    def m1(x0, y0, x1, y1):
        top.shapes(L[M1]).insert(kdb.DBox(sn(x0), sn(y0), sn(x1), sn(y1)))

    m1(-vss_i, 0, width + vss_d, RAIL_W)                     # VSS, abuts the neighbour
    m1(-vdd_i, height - RAIL_W, width + vdd_d, height)           # VDD, same

    margen_p = (nw[0] + NWELL_ENC, nw[1] + NWELL_ENC)
    usable = height - 2 * RAIL_W - 2 * CLR
    if usable <= 0 or width - margen_p[0] - margen_p[1] < 3.0:
        return top, []
    n_per, w_gate = _plan(usable)
    if n_per == 0:
        return top, []

    #  Vertical lanes: each starts above the opposite rail, and both are set
    #  `CLR` inwards. Flush with the edge, a tile's VSS lane came within **0.14
    #  um of the VDD rail of the DECODER next door** -- that macro belongs to
    #  another shelf and its rail starts 0.14 inside its edge.
    #  The only things allowed to stick out past the edge are the two horizontal
    #  rails, which is the whole point.
    m1(CLR, RAIL_W + CLR, CLR + CARRIL, height)
    m1(width - CLR - CARRIL, 0.0, width - CLR, height - RAIL_W - CLR)

    devices: list[tuple[str, float, float]] = []
    y = RAIL_W + CLR
    for k in range(n_per):
        y = _banda(layout, top, L, m1, y, w_gate, width, devices, name, k,
                   nw, margen_p)
    #  A final VSS bar: the gate of the last band's PMOS has to land on
    #  something, and what is above is the VDD rail.
    #  It starts at CARRIL + CLR like the others. Starting it at `x0 - CLR` it
    #  touched the VDD lane on its right edge and **shorted the two supplies**:
    #  extraction gave one single metal1 net across the whole tile, and DRC only
    #  hinted at it as four 0.07 um `M1.2a`.
    m1(2 * CLR + CARRIL, y, width - CLR, y + BAR)
    return top, devices


def _banda(layout, top, L, m1, y, w_gate, width, devices, name, idx,
           nw=(NWELL_BORDE, NWELL_BORDE), margen_p=(MARGEN_P, MARGEN_P)):
    """Dibuja una banda a partir de `y`. Devuelve la `y` de la barra de arriba."""
    izq, der = 2 * CLR + CARRIL, width - 2 * CLR - CARRIL
    h_n, h_p = _pcell_height("n", w_gate), _pcell_height("p", w_gate)

    #  All the dimensions BEFORE drawing: the NMOS gate has to know where its VDD
    #  bar is, and that bar runs above it.
    #
    #  Each row carries **two** tap strips, one below and one above. With one
    #  sola, el tap queda en un extremo del canal y `DF.13_MV` / `DF.14_MV` -- 15
    #  um at most from the tap to every PCOMP / NCOMP -- limit the device to
    #  about 11 um long. With both, the worst point is the channel centre and the
    #  same margin allows 26.
    y_vss = y
    y_ptap0 = y_vss + BAR + 0.10
    y_n0 = y_ptap0 + TAP_W + CLR_TAP
    y_ptap1 = y_n0 + h_n + CLR_TAP
    y_vdd = y_ptap1 + TAP_W + 0.10
    y_ntap0 = y_vdd + BAR + 0.10
    y_p0 = y_ntap0 + TAP_W + CLR_TAP
    y_ntap1 = y_p0 + h_p + CLR_TAP
    y_fin = y_ntap1 + TAP_W + 0.10

    def bar(y0, net):
        #  Each bar touches only ITS lane and keeps clear of the other.
        if net == "VDD":
            m1(CLR, y0, der, y0 + BAR)
        else:
            m1(izq, y0, width - CLR, y0 + BAR)

    def taps(y_tap, implant, y_bar, sites):
        """One tap per device, **between its source and drain pads**.

        There are 2.14 um free there -- the channel width minus the two pads --
        and that band is clear: the only things crossing it vertically are the
        pads themselves, which go to the bar below, and the gate riser, which
        arriba.

        They used to go in the gaps BETWEEN devices, and that left them out when
        the gap measured less than `TAP_W + 2*CLR`: on a narrow tile (the 9.52 um
        ones on the die margin) only one PMOS fits and the only remaining gap was
        1.26 um, two hundredths short. Result: **eleven `DF.13_MV`**, which asks
        for a well tap within 15 um of every PCOMP.

        A fixed pitch from the edge did not work either: they landed 0.12 um from
        a device's metal1. Since source and tap are the SAME net there is no
        short, but `M1.2a` is checked on geometry and fires anyway.
        """
        last = -1e9
        for a, b in sites:
            if b - a < TAP_W or (a + b) / 2 - last < TAP_PITCH:
                continue
            x = sn((a + b - TAP_W) / 2)
            _tap(top, L, x, sn(y_tap), implant)
            m1(x, min(y_tap, y_bar), x + TAP_W, max(y_tap + TAP_W, y_bar + BAR))
            last = (a + b) / 2

    def row(kind, y_base, y_sd, y_g):
        """A row of devices, with their metal1 stretched to the bars.

        The metal1 pads are already placed by `map_device`; here they are only
        alargan: fuente y drenador hasta la bar de su net y la puerta hasta la
        contraria.

        **The gate is always `boxes[-1]`**, the topmost plate, because both types
        are built with `gate_con="top"`. See the file header: taking `boxes[0]`
        for the PMOS took a drain for a gate and gave four `M1.2a` per tile, with
        the PMOS cut off on top of that.
        """
        pc = device(kind, w_gate)
        bb = pc.kdb_cell.dbbox()
        #  To MICRONS with the PCell's dbu, not the destination layout's. The
        #  boxes come out in integer units of the source layout (0.001) and here
        #  we draw in the top's (0.0005): multiplying them by the destination dbu
        #  the whole device came out **at half size**, with 0.18 um metal1 pads.
        #  1180 `M1.1` and 886 `M1.2a`, and not one on the loose tile, which is
        #  built in a 0.001 layout and therefore matched.
        dbu_pc = pc.kdb_cell.layout().dbu
        boxes = [poly.bbox().to_dtype(dbu_pc) for poly in _reg(pc, M1).merged().each()]
        if len(boxes) < 3:
            return []
        boxes.sort(key=lambda b: b.bottom)
        g = boxes[-1]
        sd = [b for b in boxes if b is not g]

        x0 = MARGEN_N if kind == "n" else margen_p[0]
        x1 = width - (MARGEN_N if kind == "n" else margen_p[1])
        #  Two tap sites per device, in PCell coordinates:
        #
        #  * the BOTTOM one goes in the internal gap, between the two S/D pads,
        #    baja recto a la bar;
        #  * the TOP one goes **over an S/D pad**, because up there the only
        #    thing of its own net within reach is that pad: in the middle sits
        #    de puerta, que es de la net contraria.
        sd_sorted = sorted(sd, key=lambda b: b.left)
        interno = (sd_sorted[0].right, sd_sorted[-1].left)
        over_pad = (sd_sorted[0].left, sd_sorted[0].right)
        x = x0
        sites, high_sites = [], []
        while x + bb.width() <= x1:
            cell = layout.create_cell(f"{name}_{idx}{kind}{len(devices)}")
            copy_device(pc, cell, layout)
            dx, dy = x - bb.left, y_base - bb.bottom
            top.insert(kdb.DCellInstArray(cell.cell_index(),
                                          kdb.DTrans(kdb.DVector(dx, dy))))
            for b, destino, estrecho in ([(k, y_sd, False) for k in sd]
                                         + [(g, y_g, True)]):
                a0, a1 = b.left + dx, b.right + dx
                if estrecho and a1 - a0 > RISER_W:
                    #  The gate pad is as wide as the channel (2 um) and sits
                    #  a 0.07 de la fuente y del drenador. Mientras no se solapen
                    #  in `y` that is legal -- it is the poly end cap -- but
                    #  stretching it towards the bar puts it in the band of the
                    #  dos y lo convierte en `M1.2a`. El riser va centrado y
                    #  narrow one, which leaves plenty on each side.
                    c = (a0 + a1) / 2
                    a0, a1 = c - RISER_W / 2, c + RISER_W / 2
                    m1(b.left + dx, b.bottom + dy, b.right + dx, b.top + dy)
                m1(a0, min(b.bottom + dy, destino), a1, max(b.top + dy, destino))
            devices.append((kind, w_gate, L_CANAL))
            sites.append((interno[0] + dx, interno[1] + dx))
            high_sites.append((over_pad[0] + dx, over_pad[1] + dx))
            x += bb.width() + DEVICE_GAP
        return sites, high_sites

    #  Rows first: the taps go into the gaps they leave.
    bar(y_vss, "VSS")
    bar(y_vdd, "VDD")
    sites_n, high_n = row("n", y_n0, y_vss + BAR, y_vdd) or ([], [])
    sites_p, high_p = row("p", y_p0, y_vdd + BAR, y_fin + BAR) or ([], [])
    taps(y_ptap0, PPLUS, y_vss, sites_n)
    taps(y_ntap0, NPLUS, y_vdd, sites_p)
    #  The top strips tie to the pad right below them, which is of their own net
    #  (the NMOS source/drain is VSS like the p+ tap; the PMOS one is VDD like
    #  the n+ tap). There is no need to reach any bar.
    taps(y_ptap1, PPLUS, y_ptap1 - CLR_TAP - BAR, high_n)
    taps(y_ntap1, NPLUS, y_ntap1 - CLR_TAP - BAR, high_p)

    #  The well covers BOTH n+ tap strips and the whole p row, with its
    #  enclosure, but stays `NWELL_BORDE` from the tile edge: without
    #  `CONNECTIVITY_RULES` the deck applies `NW.2b_MV` and asks 1.7 um to the
    #  neighbouring macro's well **even on the same net**, and the right one
    #  reaches right up to its edge.
    top.shapes(L[NWELL]).insert(
        kdb.DBox(sn(nw[0]), sn(y_ntap0 - NWELL_ENC),
                 sn(width - nw[1]), sn(y_ntap1 + TAP_W + NWELL_ENC)))
    return y_fin


# --------------------------------------------------------------------------- #
#  The top: where the tiles fit
# --------------------------------------------------------------------------- #
def shelves(macros) -> dict[tuple[float, float], list[tuple[float, float]]]:
    """The macros grouped by shelf: same `y` and same height.

    That is the condition for their rails to sit at the same level, which is what
    lets a tile dropped between two of them connect by abutment.
    """
    out: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for _, _, x, y, w, h in macros:
        out.setdefault((round(y, 3), round(h, 3)), []).append((x, x + w))
    for v in out.values():
        v.sort()
    return out


def gaps(macros, die: kdb.DBox):
    """The free intervals of each shelf, including the two die margins.

    Devuelve `(x0, x1, y, height, hay_izq, hay_der)`.

    What blocks a shelf is **not only the macros on that shelf**: WEIGHT_COMP
    sits on its own shelf (y = 202.15, 25 um tall) and reaches straight into the
    right-hand gap of the four COMP shelves. Subtracting only those on the shelf
    itself gave a 356 um wide "gap" that is in fact full of macros, and the only
    thing that caught it was the metal1 check.
    """
    out = []
    for (y, h), _ in sorted(shelves(macros).items()):
        if h < MIN_HEIGHT:
            continue
        #  Any macro overlapping this shelf in `y` blocks its slice of x.
        tapado = sorted((mx, mx + mw) for _, _, mx, my, mw, mh in macros
                        if my < y + h and my + mh > y)
        fundido: list[list[float]] = []
        for a, b in tapado:
            if fundido and a <= fundido[-1][1] + 1e-9:
                fundido[-1][1] = max(fundido[-1][1], b)
            else:
                fundido.append([a, b])
        edges = ([[die.left, die.left]] + fundido + [[die.right, die.right]])
        for i in range(len(edges) - 1):
            x0, x1 = edges[i][1], edges[i + 1][0]
            if x1 - x0 < MIN_WIDTH:
                continue
            out.append((x0, x1, y, h, i > 0, i + 1 < len(edges) - 1))
    return out


def alcance(m1: kdb.Region, dbu: float, y0: float, y1: float,
            x_borde: float, hacia: int) -> float:
    """How far a rail must stretch to OVERLAP the neighbour's.

    Returns the stretch (positive) if there is a rail on that side, and `-CLR` if
    there is not: then the rail **pulls back** from the edge, because anything
    sticking out could sit within 0.23 um of the macro's metal.

    What is looked for is a **solid horizontal bar**, not just any metal. A
    transistor finger crossing the rail band fills it top to bottom and is 0.9 um
    tall just like a rail: looking only at bbox height, the generator took three
    WEIGHT_COMP fingers for rails, stretched three tiles' VSS into them and
    **shorted `net5`/`net6` of three WEIGHTs against VSS**. DRC came out clean --
    they are overlaps, not spacings -- and only LVS saw it: 877 nets against 880.
    Hence the deep probe, which a 0.36 um wide finger cannot cover.
    """
    x0, x1 = (x_borde, x_borde + ALCANCE_MAX) if hacia > 0 else (x_borde - ALCANCE_MAX, x_borde)
    window = kdb.Region(kdb.DBox(x0, y0, x1, y1).to_itype(dbu))
    near = (m1 & window).merged()
    if near.is_empty():
        return 0.0
    #  Probe: half a micron of the WHOLE band, at the far end of the window.
    #  Only something crossing the window side to side at full height fills it.
    sx0, sx1 = (x1 - 0.5, x1) if hacia > 0 else (x0, x0 + 0.5)
    probe = kdb.Region(kdb.DBox(sx0, y0, sx1, y1).to_itype(dbu))
    rail = near.interacting(probe)
    if rail.is_empty() or not (probe - rail).is_empty():
        return -CLR
    box = rail.bbox().to_dtype(dbu)
    d = (box.left - x_borde) if hacia > 0 else (x_borde - box.right)
    return min(round(max(d, 0.0) + SOLAPE, 3), ALCANCE_MAX)


def comprobar(m1: kdb.Region, dbu: float, placed, ext_de) -> list[str]:
    """That each tile has its two rails separate and touching the neighbour's.

    `Region.merged()` fuses touching polygons, so **one polygon is one connected
    component**. That answers the two questions DRC does not: whether VDD and VSS
    ended up being the same thing (a short, which happened once) and whether the
    fill was left dangling (an open, which DRC does not see because 0.26 um of
    air passes the spacing easily).
    """
    fundido = m1.merged()
    fallos = []

    def componente(x, y):
        p = kdb.Region(kdb.DBox(x - 0.05, y - 0.05, x + 0.05, y + 0.05).to_itype(dbu))
        return fundido.interacting(p)

    for name, x0, x1, y, h, hay_izq, hay_der in placed:
        cx = (x0 + x1) / 2
        c_vss = componente(cx, y + RAIL_W / 2)
        c_vdd = componente(cx, y + h - RAIL_W / 2)
        if c_vss.is_empty() or c_vdd.is_empty():
            fallos.append(f"{name}: no metal found on one rail")
            continue
        if c_vss.bbox() == c_vdd.bbox():
            fallos.append(f"{name}: VDD and VSS are the SAME component (short)")
            continue
        for net, comp, yy, lado in (("VSS", c_vss, y + RAIL_W / 2, 0),
                                    ("VDD", c_vdd, y + h - RAIL_W / 2, 2)):
            x_vec = (x0 - 2.0) if ext_de[name][lado] > 0 else (x1 + 2.0)
            probe = kdb.Region(kdb.DBox(x_vec - 0.05, yy - 0.05,
                                        x_vec + 0.05, yy + 0.05).to_itype(dbu))
            if comp.interacting(probe).is_empty():
                fallos.append(f"{name}: rail {net} does not reach the neighbouring macro")
    return fallos


# --------------------------------------------------------------------------- #
#  Salidas
# --------------------------------------------------------------------------- #
#: Gate oxide capacitance of the 6 V device, in fF/um2. Comes from
#: `sm141064.ngspice` (the 6 V model's `toxe`) and is only used to print the
#: figure on screen: it enters no file and no check.
COX_FF_UM2 = 1.55


def lineas_spice(devices) -> list[str]:
    """The SPICE lines of the transistors, in the project format.

    `spiceprefix=X`, which is how xschem instantiates them and how magic extracts
    them: in this PDK the models are subcircuits, so an `M` element would not
    match the extracted `X0 ... nfet_06v0` call.

    Node order is the model's: `d g s b`.
    """
    out = []
    for i, (kind, w, l) in enumerate(devices):
        if kind == "n":
            nodes, model = "VSS VDD VSS VSS", "nfet_06v0"
        else:
            nodes, model = "VDD VSS VDD VDD", "pfet_06v0"
        out.append(f"XMdec{kind}{i} {nodes} {model} "
                   f"L={l}u W={w}u nf=1 m=1")
    return out


#: Marker of the code block in the schematic. Found by the instance `name=`,
#: the only stable thing: xschem moves the symbol geometry around.
NOMBRE_BLOQUE = "DESACOPLE"


def parchear_sch(lines: list[str]) -> bool:
    """Inserts (or replaces) the decoupling block in the top schematic.

    It is **written by the generator and not by hand** on purpose: layout and
    schematic have to come from the same run or LVS stops meaning anything. It is
    an instance of `devices/code_shown.sym` with `only_toplevel=true`, the same
    pattern the `XSCHEM/TEST*` benches use.
    """
    if not SCH.exists():
        print(f"  WARNING: {SCH} not found; leaving the schematic alone")
        return False
    text = SCH.read_text()
    cuerpo = "\n".join(lines)
    block = ("C {devices/code_shown.sym} 700 700 0 0 {name=" + NOMBRE_BLOQUE
              + " only_toplevel=true value=\"\n"
              + "* Decoupling capacitors: NMOS and PMOS in inversion dropped into\n"
              + "* the gaps between macros. WRITTEN BY scripts/decap_fill.py -- do\n"
              + "* not edit by hand: it must be exactly what is in the GDS.\n"
              + cuerpo + "\n\"}\n")
    patron = re.compile(r"^C \{devices/code_shown\.sym\}[^\n]*name=" + NOMBRE_BLOQUE
                        + r"\b.*?\"\}\n", re.S | re.M)
    nuevo, n = patron.subn(block, text)
    if not n:
        nuevo = text.rstrip("\n") + "\n" + block
    SCH.write_text(nuevo)
    return True


def main() -> int:
    args = sys.argv[1:]
    #  --- loose tile: the short DRC loop ---------------------------------------
    for a in args:
        if a.startswith("--tile"):
            spec = a.split("=", 1)[1] if "=" in a else args[args.index(a) + 1]
            w, h = (float(v) for v in spec.lower().split("x"))
            ly = kdb.Layout()
            ly.dbu = 0.001
            _, devices = tile(ly, w, h, f"T{spec.replace('.', 'p').replace('x', 'x')}")
            dst = OUT / "decap_tile.gds"
            dst.parent.mkdir(parents=True, exist_ok=True)
            ly.write(str(dst))
            print(f"  tile {w} x {h}: {len(devices)} devices -> {dst}")
            return 0

    if not GDS_IN.exists():
        sys.exit(f"{GDS_IN} is missing -- run `make top T={TOP}` first")
    if not DEF.exists():
        sys.exit(f"{DEF} is missing")

    ly = kdb.Layout()
    ly.read(str(GDS_IN))
    top = ly.top_cell()
    die = top.dbbox()
    dbu = ly.dbu
    m1 = kdb.Region(top.begin_shapes_rec(ly.layer(*M1)))
    m1.merge()

    macros = colocacion(DEF)
    libres = gaps(macros, die)

    #  The tiles are built INSIDE the top layout: `copy_device` handles
    #  the PCells' dbu change, so no intermediate file is needed (which changed
    #  the top's dbu; see there).
    specs, devs_per_tile, ext_de = [], {}, {}
    skipped = []
    #  Largest first, discarding anything overlapping a tile already placed: the
    #  shelves **overlap in `y`** (WEIGHT_COMP takes 202.15..227.15 and the COMP
    #  one 202.13..233.59), so the same piece of silicon shows up as a gap on two
    #  different shelves. Placing both put tiles on top of tiles -- and the
    #  connectivity check flagged it as a short.
    placed: list[tuple[float, float, float, float]] = []
    for x0, x1, y, h, hay_izq, hay_der in sorted(
            libres, key=lambda r: -(r[1] - r[0]) * r[3]):
        if any(x0 < bx1 and x1 > bx0 and y < by1 and y + h > by0
               for bx0, bx1, by0, by1 in placed):
            continue
        #  Guard margin against the die outline on the sides that touch it. The
        #  shelves never reach the top or bottom of the die -- the
        #  macros go at `MARGIN` = 9 um -- so it is only needed in x.
        nw = [NWELL_BORDE, NWELL_BORDE]
        if x0 <= die.left + 1e-6:
            x0 += BORDE_DIE
            nw[0] = NWELL_BORDE_DIE
        if x1 >= die.right - 1e-6:
            x1 -= BORDE_DIE
            nw[1] = NWELL_BORDE_DIE
        if x1 - x0 < MIN_WIDTH:
            skipped.append((x0, x1, y, h, "does not fit after the die margin"))
            continue
        width = round(x1 - x0, 3)
        window = kdb.Region(kdb.DBox(x0, y, x1, y + h).to_itype(dbu))
        if not (m1 & window).is_empty():
            skipped.append((x0, x1, y, h, "routing metal1 inside"))
            continue
        ext = (alcance(m1, dbu, y, y + RAIL_W, x0, -1),
               alcance(m1, dbu, y, y + RAIL_W, x1, +1),
               alcance(m1, dbu, y + h - RAIL_W, y + h, x0, -1),
               alcance(m1, dbu, y + h - RAIL_W, y + h, x1, +1))
        #  BOTH supplies must have something to hold on to. A macro beside it is
        #  not enough: WEIGHT_COMP brings no VSS rail out of its bottom edge --
        #  what shows there are its transistor fingers -- so a tile to its right
        #  would be left with VSS in the air, and DRC does not see that.

        if not ((ext[0] > 0 or ext[1] > 0) and (ext[2] > 0 or ext[3] > 0)):
            skipped.append((x0, x1, y, h, "the neighbouring macro has no rail at that height"))
            continue
        name = f"DECAP_{int(round(x0*100))}_{int(round(y*100))}"
        cell, devices = tile(ly, width, h, name, ext, tuple(nw))
        if not devices:
            #  And it is deleted: a tile created and not instantiated stays as a
            #  **loose top cell** in the layout, and on re-reading the GDS
            #  `top_cell()` aborta con "multiple top cells".
            ly.delete_cell_rec(cell.cell_index())
            skipped.append((x0, x1, y, h, "not even one band fits"))
            continue
        specs.append((name, x0, x1, y, h, hay_izq, hay_der))
        devs_per_tile[name] = devices
        ext_de[name] = ext
        placed.append((x0, x1, y, y + h))

    if not specs:
        sys.exit("  no gap could be filled")

    for name, x0, x1, y, h, _, _ in specs:
        cell = ly.cell(name)
        top.insert(kdb.DCellInstArray(cell.cell_index(),
                                      kdb.DTrans(kdb.DVector(x0, y))))
    #  Flattened, like the rest of the top (`def_to_gds.py::flatten_all`): LVS
    #  compares against a flattened reference and a new hierarchy here would make
    #  the deck extract subcircuits the reference does not have.
    top.flatten(-1, True)
    ly.write(str(GDS_OUT))

    #  --- comprobaciones -------------------------------------------------------
    ly2 = kdb.Layout()
    ly2.read(str(GDS_OUT))
    t2 = ly2.top_cell()
    m1_final = kdb.Region(t2.begin_shapes_rec(ly2.layer(*M1)))
    fallos = comprobar(m1_final, ly2.dbu, specs, ext_de)

    #  --- salidas --------------------------------------------------------------
    devices = [d for name, *_ in specs for d in devs_per_tile[name]]
    lines = lineas_spice(devices)
    DEV_TXT.write_text("\n".join(lines) + "\n")
    GAPS_TXT.write_text("\n".join(
        f"{x0:.3f} {y:.3f} {x1:.3f} {y + h:.3f}" for _, x0, x1, y, h, _, _ in specs) + "\n")
    parchear_sch(lines)

    #  --- informe --------------------------------------------------------------
    #  The UNION, not the sum: gaps of overlapping shelves count the same piece
    #  mismo silicio dos veces.
    reg_libre = kdb.Region()
    for x0, x1, y, h, _, _ in libres:
        reg_libre.insert(kdb.DBox(x0, y, x1, y + h).to_itype(dbu))
    reg_libre.merge()
    area_total = reg_libre.area() * dbu * dbu
    area_llena = sum((x1 - x0) * h for _, x0, x1, y, h, _, _ in specs)
    n_n = sum(1 for t, _, _ in devices if t == "n")
    w_n = sum(w for t, w, _ in devices if t == "n")
    w_p = sum(w for t, w, _ in devices if t == "p")
    cap = (w_n + w_p) * L_CANAL * COX_FF_UM2 / 1000.0
    print(f"  {TOP}: {len(specs)} tiles in {len(libres)} shelf gaps")
    print(f"    shelf gap         {area_total:9,.0f} um2")
    print(f"    rellenado         {area_llena:9,.0f} um2  "
          f"({100 * area_llena / area_total:.0f} %)")
    print(f"    sin rellenar      {area_total - area_llena:9,.0f} um2")
    for x0, x1, y, h, motivo in skipped:
        print(f"      gap {x0:7.2f}..{x1:7.2f} y={y:7.2f} "
              f"({(x1 - x0) * h:6.0f} um2): {motivo}")
    print(f"    {len(devices)} transistores: {n_n} NMOS + {len(devices) - n_n} PMOS")
    print(f"    W total  N {w_n:8.1f} um   P {w_p:8.1f} um   L {L_CANAL} um")
    print(f"    desacople estimado ~{cap:.2f} pF")
    print(f"  {GDS_OUT}")
    print(f"  {DEV_TXT}   ({len(lines)} lines, written into {SCH.name})")
    if fallos:
        print("\n  CONNECTIVITY:")
        for f in fallos:
            print(f"    {f}")
        return 1
    print("  connectivity: every tile with its two rails separate and "
          "pegados al macro vecino")
    return 0


if __name__ == "__main__":
    sys.exit(main())
