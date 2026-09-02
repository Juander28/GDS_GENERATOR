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

#: AND THE TOP FLOW DOES NOT READ THAT DIRECTORY.
#:
#: `openroad/gds/ESD_CDM.gds` is a symlink, and `usar_version.sh v2` -- which
#: `make collateral` runs -- points it at **`layouts_v2/ESD_CDM/`**, not at the
#: `layouts/` above. So regenerating the clamp here changes nothing on the top
#: until the result is copied across:
#:
#:     cp -a layouts/ESD_CDM/ESD_CDM_flat_gf180.gds \
#:           layouts_v2/ESD_CDM/ESD_CDM_flat_gf180.gds
#:     cp -a layouts/ESD_CDM/ESD_CDM_lvs.spice \
#:           layouts_v2/ESD_CDM/ESD_CDM_lvs.spice
#:
#: This cost a full integration cycle on 2026-09-01: the merged n-wells were
#: verified clean on the clamp, the top was rebuilt and refilled, and the DRC
#: still reported the same 33 NW.2b_MV -- because the symlink was still serving
#: the old GDS. **The clamp being clean is not the same as the top using it.**
#: Check with `sha256sum $(readlink -f openroad/gds/ESD_CDM.gds)`.
CELL = "ESD_CDM"

GRID = 0.005
RAIL_W = 0.9              # same as coil_layout.placement.RAIL_WIDTH
TRACK_PITCH, TRACK_OFF = 0.56, 0.28

#: Diode geometry. `wa` runs along x and `la` along y.
#:
#: 10 x 10 y CUATRO POR SENTIDO, que es el clamp de los organizadores medido
#: sobre su GDS (`r_w=10u r_l=10u m=4`). El que habia antes -- 10 x 5 y dos por
#: sentido -- da 100 um2 de diodo por sentido contra sus 400: cuatro veces menos
#: corriente de descarga. No era su celda mejor dibujada, era un clamp mas flojo.
D_WA, D_LA = 10.0, 10.0
#: Cuantos diodos por sentido.
D_N = 4
#: Column pitch of the two diodes in a row. The two pd2nw bring an n-well each
#: and NW.2 wants 0.6 um between wells at the same potential; at a pitch of 12
#: the gap came to 0.44. 13 leaves 1.44.
D_PITCH_X = 13.0

#: Resistencia: UN cuerpo de `ppolyf_u` de W=16 x L=4 um, que es lo que dice el
#: esquematico de los organizadores al pie de la letra:
#:
#:     C {symbols/ppolyf_u.sym} ... {name=R1 W=16e-6 L=4e-6 model=ppolyf_u m=1}
#:
#: 0.25 cuadros a 350 ohm/sq = 87.5 ohm. Ojo: su GDS la dibuja de 40 x 10, los
#: mismos cuadros y el mismo valor con otra geometria; aqui manda el ESQUEMATICO,
#: que es lo que se pidio.
#:
#: `ppolyf_res(res_type="ppolyf_u")` y no `ppolyf_u_high_Rs_res`: aquel es el
#: dispositivo de 1k y este es el pelado, que es el suyo. A cambio, el PCell no
#: esta limpio -- 64 `SB.4`, 2 `PRES.7`, 2 `PP.2` -- y hay que operarlo; ver
#: `_fix_res_heads`.
R_W, R_L = 16.0, 4.0
#: Cuanto se alargan las cabezas de poli hacia afuera y donde van sus contactos.
#:
#: El PCell deja el bloqueo de silicida pegado al cuerpo (x = 0 y x = L) y los
#: contactos de cabeza a 0.11 um de el, cuando `PRES.7` pide 0.22 y `SB.4` 0.15.
#: Y no basta con retirar el SAB: las cabezas miden 0.44 um, donde no caben un
#: contacto de 0.22, su encierro y la holgura. Asi que se alargan y el contacto
#: se va con ellas, que es la misma operacion que `_fix_strip_contacts` hace en
#: los diodos.
HEAD_GROW = 0.40          # cuanto crece cada cabeza hacia afuera
HEAD_CO_IN = 0.18         # del borde exterior de la cabeza al contacto
#: Pozo n bajo la resistencia (su bulk va a VDD) y la toma n+ que lo ata.
NW_MARGEN = 1.20
TAP_SEP, TAP_W, TAP_HUECO = 0.60, 0.60, 2.60
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
#: La fila de pd2nw va por encima de la de nd2ps con sitio para los DOS pozos:
#: el `LVPWELL` del nd2ps sube hasta `Y_ND + D_LA + LVPWELL_ENC` y el `nwell` del
#: pd2nw baja hasta `Y_PD - NWELL_PCOMP`. Con diodos de 10 de alto en vez de 5,
#: los 8.6 de antes metian el pozo de arriba DENTRO del de abajo.
Y_PD = 15.0
Y_LINK = 13.3             # the horizontal PAD bar between the two rows
Y_VDD = 27.0              # bottom of the VDD rail
#: La resistencia, a la derecha de los cuatro diodos.
RX = 55.0
RY = 5.5


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
        #  Extent of the pd2nw row's n-well, accumulated and drawn ONCE below.
        nw_x0 = nw_x1 = None
        for k in range(D_N):
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
                x0 = gx0 - 0.16 - 0.10
                x1 = x + D_WA + NWELL_PCOMP
                nw_x0 = x0 if nw_x0 is None else min(nw_x0, x0)
                nw_x1 = x1 if nw_x1 is None else max(nw_x1, x1)
            else:
                box(c, (204, 0), gx0 - LVPWELL_ENC, y - LVPWELL_ENC,
                    x + D_WA + LVPWELL_ENC, y + D_LA + LVPWELL_ENC)
            #  And the dualgate has to enclose every comp, tap included, by 0.24.
            box(c, L["dualgate"], gx0 - DUALGATE_ENC, y - DUALGATE_ENC,
                x + D_WA + DUALGATE_ENC, y + D_LA + DUALGATE_ENC)
            sx0, sx1 = gx0 + 0.02, gx1 - 0.02
            strips.append((x, y))
            box(c, L["metal1"], sx0, min(y, rail_y), sx1, max(y + D_LA, rail_y + RAIL_W))

        #  ONE n-well under the whole pd2nw row, not one per diode.
        #
        #  All four wells are the same node -- they are the cathodes of the four
        #  `pd2nw`, i.e. the `m=4` of a single device, and they all sit on VDD.
        #  Drawn as four islands they were 1.330 um apart, and that is fine ONLY
        #  if the deck knows they are equipotential: `NW.2a_MV` asks 0.74 um
        #  between wells at the same potential, `NW.2b_MV` asks 1.7 um between
        #  wells at different ones, and which of the two applies is decided by
        #  the connectivity extraction.
        #
        #  Run the deck WITHOUT connectivity -- `run_drc.py --no_connectivity`,
        #  which is a perfectly ordinary way to run it -- and it cannot know the
        #  potentials, so it falls back to `nw_mv.isolated(1.7.um)` and flags
        #  every pair. Measured: 3 per clamp, 33 over the eleven on the top,
        #  against 0 with connectivity on. The layout was right and the report
        #  was right; they were answering different questions.
        #
        #  A design that passes only in one mode is a design that depends on how
        #  someone else runs the check. `NW.2a_MV` states the remedy in its own
        #  text -- "Merge if the space is less than" -- so the wells are merged.
        #  Electrically nothing changes: they were already one node. The cell
        #  does not grow either, since this only fills the gaps that were
        #  already inside its outline.
        if kind == "pd2nw" and nw_x0 is not None:
            box(c, L["nwell"], nw_x0, y - NWELL_PCOMP,
                nw_x1, y + D_LA + NWELL_PCOMP)

    #  The bar that ties the four main comps together. It runs in the gap
    #  between the rows, clear of the n+ implant below (which stops at
    #  Y_ND + D_LA + 0.16) and of the n-well above (which starts at Y_PD - 0.43).
    x_pad_hi = DX + (D_N - 1) * D_PITCH_X + D_WA - 0.04
    box(c, L["metal1"], DX + 0.04, Y_LINK - 0.5, x_pad_hi, Y_LINK + 0.5)
    for k in range(D_N):
        x = DX + k * D_PITCH_X
        box(c, L["metal1"], x + 0.5, Y_ND + D_LA - 0.04, x + 2.0, Y_LINK + 0.5)
        box(c, L["metal1"], x + 0.5, Y_LINK - 0.5, x + 2.0, Y_PD + 0.04)

    #  --- la resistencia: UN cuerpo de ppolyf_u de W=16 x L=4 ---------------
    #  El PCell la dibuja con el cuerpo a lo largo de Y (`w_res`) y de `l_res` de
    #  ancho en X, con una cabeza de poli de 0.44 um a cada lado y una toma de
    #  SUSTRATO colgando a la izquierda.
    #
    #  Esa toma sobra: el bulk de esta resistencia va a VDD (el pin `B` de su
    #  simbolo), asi que el cuerpo va sobre POZO N y la toma tiene que ser n+
    #  DENTRO del pozo. La del PCell se borra en `_fix_res_heads` y aqui se
    #  dibuja la nuestra.
    r = c.add_ref(gf180.ppolyf_res(l_res=R_L, w_res=R_W, res_type="ppolyf_u"))
    r.dmove((RX, RY))
    r_top = RY + R_W

    #  El pozo n bajo todo el cuerpo, con holgura, y el dualgate que lo cubre.
    box(c, L["nwell"], RX - NW_MARGEN, RY - NW_MARGEN,
        RX + R_L + NW_MARGEN + TAP_HUECO, r_top + NW_MARGEN)

    #  Las cabezas alargadas y sus contactos: los dibuja `_fix_res_heads` sobre
    #  el GDS, porque el poli y los contactos son del PCell. Aqui solo va el
    #  metal1 que los tapa, que si es nuestro.
    hl0 = RX - 0.44 - HEAD_GROW
    hr1 = RX + R_L + 0.44 + HEAD_GROW
    box(c, L["metal1"], hl0 + 0.02, RY + 0.05, RX - 0.06, r_top - 0.05)
    box(c, L["metal1"], RX + R_L + 0.06, RY + 0.05, hr1 - 0.02, r_top - 0.05)

    #  La toma n+ del pozo, a la derecha, y su metal1 hasta el riel de VDD.
    tx0 = RX + R_L + 0.44 + HEAD_GROW + TAP_SEP
    tx1 = tx0 + TAP_W
    box(c, L["comp"], tx0, RY, tx1, r_top)
    box(c, L["nplus"], tx0 - IMPLANT_ENC, RY - IMPLANT_ENC,
        tx1 + IMPLANT_ENC, r_top + IMPLANT_ENC)
    #  Los contactos, como CAJAS y no por `via_generator`. Esa llamada, con un
    #  `y_range` del tamano justo de la via, no dibujaba nada -- ni un aviso -- y
    #  la toma se quedaba sin contactos: el pozo sin atar y la resistencia
    #  extraida con el bulk en una net suelta. Las cabezas ya se dibujan asi.
    cxc = (tx0 + tx1) / 2
    yc = RY + 0.4
    while yc <= r_top - 0.4:
        box(c, L["contact"], cxc - CONTACT / 2, yc - CONTACT / 2,
            cxc + CONTACT / 2, yc + CONTACT / 2)
        yc += 0.6
    box(c, L["metal1"], tx0 - 0.02, RY, tx1 + 0.02, Y_VDD + RAIL_W)

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
    #  El ancho tiene que cubrir TAMBIEN la toma n+ del pozo y su metal1: si el
    #  riel de VDD acaba antes, el pozo se queda sin atar y la resistencia se
    #  extrae con el bulk en una net suelta (`R$9 PAD CORE $4 87.5 ppolyf_u`),
    #  que es un fallo de LVS y no de DRC.
    W = max(RX + R_L + HEAD_R1 + MARGIN,
            RX + R_L + 0.44 + HEAD_GROW + TAP_SEP + TAP_W + MARGIN)
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
    _fix_res_heads(path)
    b = c.dbbox()
    print(f"  {CELL}: {b.width():.2f} x {b.height():.2f} um -> {path}")
    return path




def _fix_res_heads(path):
    """Alarga las cabezas de poli de la resistencia y saca sus contactos.

    El PCell deja el bloqueo de silicida pegado al cuerpo -- de x=0 a x=L -- y
    los contactos de cabeza a 0.11 um de el. `SB.4` pide 0.15 y `PRES.7`, que es
    la que manda sobre una resistencia de poli, pide 0.22. Medido a pelo sobre el
    PCell a 16 x 4: 64 `SB.4` y 2 `PRES.7`.

    Y no vale con retirar el SAB: las cabezas miden 0.44 um, donde no caben un
    contacto de 0.22, su encierro de poli y la holgura. Asi que se alargan
    `HEAD_GROW` hacia afuera y el contacto se va con ellas, que es exactamente lo
    que `_fix_strip_contacts` hace con las tomas de los diodos.

    Se borra ademas la TOMA DE SUSTRATO que el PCell cuelga a la izquierda: el
    bulk de esta resistencia va a VDD, no a sustrato, asi que su sitio lo ocupa
    la toma n+ que `build` dibuja dentro del pozo.
    """
    ly = kdb.Layout()
    ly.read(str(path))
    top = ly.top_cell()
    top.flatten(-1, True)
    dbu = ly.dbu
    co, poly = ly.layer(33, 0), ly.layer(30, 0)

    x_body0, x_body1 = RX, RX + R_L
    hl0 = x_body0 - 0.44 - HEAD_GROW
    hr1 = x_body1 + 0.44 + HEAD_GROW

    #  1) fuera los contactos de cabeza y los de la toma de sustrato del PCell
    fuera = 0
    for s in list(top.each_shape(co)):
        b = s.box if s.is_box() else s.polygon.bbox()
        xc = (b.left + b.right) / 2 * dbu
        yc = (b.bottom + b.top) / 2 * dbu
        #  SOLO los de la resistencia. Sin acotar tambien en x, el filtro se
        #  llevaba por delante los de los diodos -- 2390 contactos en vez de los
        #  del PCell -- porque la banda de y de la resistencia se solapa con las
        #  dos filas de diodos.
        #  Ventanas AJUSTADAS a lo que hay que quitar: a la izquierda la cabeza
        #  del PCell y su toma de sustrato; a la derecha SOLO la cabeza. Con la
        #  ventana derecha a 3 um se borraban tambien los contactos de la toma
        #  n+ del pozo, que dibuja `build` y que son justo los que atan el bulk
        #  a VDD -- y sin ellos la resistencia se extrae con el bulk suelto.
        if RY - 0.5 <= yc <= RY + R_W + 0.5 and (
                x_body0 - 2.0 <= xc < x_body0
                or x_body1 < xc <= x_body1 + 0.6):
            s.delete(); fuera += 1

    #  2) fuera tambien el COMP y el PPLUS de esa toma. Borrar solo sus
    #     contactos dejaba el comp p+ ahi al lado, y con el cinco violaciones:
    #     `PRES.3` (resistencia de poli a COMP, 0.6 y habia 0.32), `DF.4c_LV` y
    #     `DF.17_LV` (pozo contra ese PCOMP) y una `PP.2`.
    comp, pplus = ly.layer(22, 0), ly.layer(31, 0)
    for capa in (comp, pplus):
        for s in list(top.each_shape(capa)):
            b = s.box if s.is_box() else s.polygon.bbox()
            xc = (b.left + b.right) / 2 * dbu
            yc = (b.bottom + b.top) / 2 * dbu
            if RY - 1.0 <= yc <= RY + R_W + 1.0 and x_body0 - 3.0 <= xc <= x_body0 - 0.9:
                s.delete(); fuera += 1

    #  3) el poli de las cabezas, alargado
    for x0, x1 in ((hl0, x_body0), (x_body1, hr1)):
        top.shapes(poly).insert(
            kdb.DBox(snap(x0), snap(RY), snap(x1), snap(RY + R_W)))

    #  4) y el PPLUS que lo cubre todo. `PRES.5` pide 0.3 um de implante por
    #     fuera de la resistencia, y el del PCell estaba dimensionado para las
    #     cabezas cortas.
    top.shapes(pplus).insert(kdb.DBox(
        snap(hl0 - 0.30), snap(RY - 0.30), snap(hr1 + 0.30), snap(RY + R_W + 0.30)))

    #  5) y los contactos nuevos, a `HEAD_CO_IN` del borde exterior
    puestos = 0
    for cx in (hl0 + HEAD_CO_IN + CONTACT / 2, hr1 - HEAD_CO_IN - CONTACT / 2):
        y = RY + 0.4
        while y <= RY + R_W - 0.4:
            top.shapes(co).insert(kdb.DBox(
                snap(cx - CONTACT / 2), snap(y - CONTACT / 2),
                snap(cx + CONTACT / 2), snap(y + CONTACT / 2)))
            puestos += 1
            y += 0.6
    ly.write(str(path))
    print(f"  resistencia: {fuera} contactos del PCell fuera, {puestos} puestos")


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
    #  CUATRO por sentido, cada uno como una instancia. El `m=4` del esquematico
    #  de los organizadores NO lo expande KLayout, asi que la referencia tiene
    #  que traerlos escritos uno a uno o el LVS no empareja.
    a, pj = D_WA * D_LA, 2 * (D_WA + D_LA)
    dio = "\n".join(
        [f"D{i} VSS PAD diode_nd2ps_06v0 AREA={a:.0f}p PJ={pj:.0f}u"
         for i in range(1, D_N + 1)] +
        [f"D{i} PAD VDD diode_pd2nw_06v0 AREA={a:.0f}p PJ={pj:.0f}u"
         for i in range(D_N + 1, 2 * D_N + 1)])
    #  1000 ohm/square is the sheet the KLayout deck uses for ppolyf_u_1k, and
    #  netgen is given the same number through gf180mcuD_setup_polyres.tcl.
    #  It is the implant this shuttle runs; the GEOMETRY is the same for 1k, 2k
    #  and 3k, so nothing above this line changes with it.
    #  Una sola, `ppolyf_u` pelado y con el BULK EN VDD: es el pin `B` de su
    #  simbolo, y por eso el cuerpo va sobre pozo n. 350 ohm/sq x 0.25 cuadros.
    res = (f"R1 CORE PAD VDD ppolyf_u W={R_W}e-06 L={R_L}e-06 "
           f"R={R_L / R_W * 350:.1f}")
    p = path or (OUT / f"{CELL}_lvs.spice")
    p.write_text(LVS_TEMPLATE.format(diodes=dio, resistors=res))
    print(f"  LVS reference -> {p}")
    return p


if __name__ == "__main__":
    build()
    write_lvs()
