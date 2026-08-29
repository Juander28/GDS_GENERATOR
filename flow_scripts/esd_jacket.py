#!/usr/bin/env python3
"""The organisers' secondary-ESD cell, made usable by our flow.

    env -u PYTHONPATH .../python scripts/esd_jacket.py

`io_secondary_5p0` comes from the chipathon repo (`sscs-ose/sscs-chipathon-2026`,
commit `aa834f5`, `resources/Integration/Chipathon2025_pads/magic/`). It is
adopted AS DRAWN: it already passes the sign-off DRC with 0 violations and LVS
against a reference describing its own geometry, so nothing of theirs is
redrawn, moved or deleted. This script only ADDS what our flow needs on top:

* **the cell sits at the origin.** Theirs runs from (-36, -24.15); everything is
  shifted so the macro starts at (0, 0). magic would otherwise write a non-zero
  `ORIGIN` into the LEF and `def_to_gds.lef_origin()` would have to undo it --
  it can, but a macro whose corner is its corner is one less thing to get wrong.
* **labels on datatype 0.** Theirs are on 34/10 and 36/10, which is the label
  purpose. `build_collateral.write_lef` takes the LEF PINs from magic's
  `port makeall`, and `podar_islas_ajenas` indexes texts only from the `PILA`
  list, which is all datatype 0. Without a copy on /0 the cell gets no pins and
  the collateral silently comes out empty.
* **a Metal3 landing pad per port.** `build_collateral.keep_top_access` keeps
  `keep_senal = {"Metal3"}`: a signal pin that does not reach Metal3 cannot be
  used by the router one level up. Their ports stop at Metal2 (the two signals)
  and Metal1 (the two supplies), so each one gets a via stack up to Metal3.

WHERE THE PADS GO IS MEASURED, NOT CHOSEN. For each port the script takes the
polygon its label sits on, subtracts every shape of the layers it has to cross
that belongs to any OTHER net -- grown by the spacing rule -- and puts the pad
in the largest clear rectangle left. A pad placed by hand at a coordinate that
looked free in the viewer is how you short a supply to a signal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import klayout.db as kdb

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
SRC = PROJECT / "integration/esd/secondary_ESD.gds"
CELL = "io_secondary_5p0"
OUTDIR = PROJECT / "layouts_v2" / CELL
OUT = OUTDIR / f"{CELL}_flat_gf180.gds"

M1, M2, M3 = (34, 0), (36, 0), (42, 0)
V1, V2 = (35, 0), (38, 0)
LBL = {34: (34, 10), 36: (36, 10), 42: (42, 10)}

#: port -> the layer its label is drawn on in THEIR cell.
PUERTOS = {"VDD": 34, "VSS": 34, "ASIG5V": 36, "to_gate": 36}

#: Spacing to keep from any shape of another net, per layer. These are the
#: WIDE-metal numbers (`M*.2b`, 0.30) and not the base ones, for the same reason
#: `fill_density.LAYERS` uses them: their supply plates are 50 x 73 um, which is
#: wide by any measure, so anything we put next to them is judged by `M1.2b`.
SEP = {34: 0.30, 36: 0.30, 42: 0.30}

#: Via and enclosure geometry, from the GF180 rules: a via is 0.26 square
#: (`V1.1`/`V2.1`), and the metal above and below must overhang it by 0.06
#: (`V1.3d`/`V1.4c`, the adjacent-edge case).
VIA = 0.26
ENC = 0.06
#: Via pitch. **0.36 of spacing, not 0.26.** `V1.2a` asks 0.26 between any two
#: vias, but `V1.2b` asks **0.36 inside a 4x4 or larger array**, and these pads
#: carry 7x7. Built at 0.26 the cell came back with 168 `V1.2b` and 252
#: `V2.2b` -- the rule that only exists once the array is big enough to matter.
PASO = VIA + 0.36
#: Target pad side. Big enough for a useful via array, small enough to fit in
#: the clear rectangles their layout leaves. Shrunk automatically if it does not.
LADO = 4.0
LADO_MIN = 1.0


def region(cell, ly, spec) -> kdb.Region:
    i = ly.find_layer(*spec)
    if i is None:
        return kdb.Region()
    r = kdb.Region(cell.begin_shapes_rec(i))
    r.merge()
    return r


def etiquetas(cell, ly) -> dict[str, tuple[float, float, int]]:
    """{name: (x, y, gds layer)} of every text in the cell."""
    out = {}
    for i in ly.layer_indexes():
        capa = ly.get_info(i).layer
        it = cell.begin_shapes_rec(i)
        while not it.at_end():
            sh = it.shape()
            if sh.is_text():
                t = sh.text.transformed(it.trans())
                out[t.string] = (t.x * ly.dbu, t.y * ly.dbu, capa)
            it.next()
    return out


def poligono_de(reg: kdb.Region, x: float, y: float) -> kdb.Region:
    """The one polygon of `reg` that contains the point, on its own."""
    punto = kdb.Region(kdb.DBox(x - 0.001, y - 0.001,
                                x + 0.001, y + 0.001).to_itype(1e-3))
    return reg.interacting(punto)


def mayor_cuadro(zona: kdb.Region, lado: float) -> kdb.DBox | None:
    """The biggest square of side <= `lado` that fits WHOLE inside `zona`.

    Whole, never clipped: a pad cut against the clear area grows necks and
    corners below minimum width, which is exactly the mistake that cost 6214
    violations in `fill_density` before it was made to place whole squares.
    """
    while lado >= LADO_MIN - 1e-9:
        #  Shrinking by half the side and re-growing leaves only the places
        #  where a square of that side actually fits.
        cabe = zona.sized(int(-lado / 2 * 1000))
        for p in sorted(cabe.each(), key=lambda q: -q.area()):
            c = p.bbox().center().to_dtype(1e-3)
            caja = kdb.DBox(c.x - lado / 2, c.y - lado / 2,
                            c.x + lado / 2, c.y + lado / 2)
            #  The erosion says a square of this side fits SOMEWHERE around
            #  here; it does not promise that one centred on the bounding-box
            #  centre does, because the piece need not be convex. Checked, not
            #  assumed: a pad half out of its own metal is 14 x `V1.3a`.
            if (kdb.Region(caja.to_itype(1e-3)) - zona).is_empty():
                return caja
        lado -= 0.5
    return None


def rejilla_vias(caja: kdb.DBox) -> list[kdb.DBox]:
    """Vias inside `caja`, with `ENC` of metal all around."""
    out = []
    y = caja.bottom + ENC
    while y + VIA + ENC <= caja.top:
        x = caja.left + ENC
        while x + VIA + ENC <= caja.right:
            out.append(kdb.DBox(x, y, x + VIA, y + VIA))
            x += PASO
        y += PASO
    return out


def main() -> int:
    if not SRC.exists():
        sys.exit(f"missing {SRC} -- vendor the organisers' GDS first")

    ly = kdb.Layout()
    ly.read(str(SRC))
    top = ly.cell(CELL)
    if top is None:
        sys.exit(f"{SRC.name} has no cell named {CELL}")

    #  1. To the origin. Their corner is at (-36, -24.15).
    b = top.dbbox()
    top.transform(kdb.DCplxTrans(1.0, 0.0, False, -b.left, -b.bottom))
    print(f"  shifted by ({-b.left:+.3f}, {-b.bottom:+.3f}) -> {top.dbbox()}")

    m1, m2 = region(top, ly, M1), region(top, ly, M2)
    marcas = etiquetas(top, ly)
    falta = [p for p in PUERTOS if p not in marcas]
    if falta:
        sys.exit(f"their cell has no label for {falta}; found {sorted(marcas)}")

    #  2. Per port: its own polygon, and everything of the other nets.
    propio, ajeno = {}, {}
    for nombre, capa in PUERTOS.items():
        x, y, capa_marca = marcas[nombre]
        if capa_marca != capa:
            sys.exit(f"{nombre}: label on layer {capa_marca}, expected {capa}")
        base = m1 if capa == 34 else m2
        propio[nombre] = poligono_de(base, x, y)
        if propio[nombre].is_empty():
            sys.exit(f"{nombre}: the label at ({x}, {y}) is on no polygon")
    for nombre in PUERTOS:
        resto = kdb.Region()
        for otro, reg in propio.items():
            if otro != nombre:
                resto += reg
        ajeno[nombre] = resto

    l_m3 = ly.layer(*M3)
    l_v1, l_v2 = ly.layer(*V1), ly.layer(*V2)
    l_m2 = ly.layer(*M2)

    for nombre, capa in PUERTOS.items():
        #  Where the stack may land: inside our own metal, clear of every other
        #  net on THIS layer and on Metal2 (which the Metal1 ports have to cross)
        #  by the wide-metal spacing.
        zona = propio[nombre] - ajeno[nombre].sized(int(SEP[capa] * 1000))
        if capa == 34:
            #  A Metal1 port needs a Metal2 patch on the way up, so the clear
            #  area must also miss every Metal2 shape there already -- ours and
            #  theirs alike.
            zona -= m2.sized(int(SEP[36] * 1000))
        zona.merge()

        caja = mayor_cuadro(zona, LADO)
        if caja is None:
            sys.exit(f"{nombre}: no clear square of {LADO_MIN} um to land on")
        vias = rejilla_vias(caja)
        if not vias:
            sys.exit(f"{nombre}: the pad at {caja} takes no via")

        caja_i = caja.to_itype(ly.dbu)
        if capa == 34:
            for v in vias:
                top.shapes(l_v1).insert(v.to_itype(ly.dbu))
            top.shapes(l_m2).insert(caja_i)
        for v in vias:
            top.shapes(l_v2).insert(v.to_itype(ly.dbu))
        top.shapes(l_m3).insert(caja_i)

        #  3. The labels: one on Metal3/0 so magic makes a port of it, and a
        #     copy on 42/10 for the viewer, matching their own convention.
        c = caja.center()
        for spec in (M3, LBL[42]):
            top.shapes(ly.layer(*spec)).insert(
                kdb.Text(nombre, kdb.Trans(kdb.Vector(
                    round(c.x / ly.dbu), round(c.y / ly.dbu)))))
        #  And a copy on the port's OWN layer, datatype 0, because
        #  `build_collateral.PILA` indexes 34/0 and 36/0 and not the /10s.
        #  `marcas` was read AFTER the shift to the origin, so its coordinates
        #  are already in the new frame -- shifting them again put the VDD label
        #  at y = 107.89 and grew the macro's bounding box by 22 um.
        x, y, _ = marcas[nombre]
        top.shapes(ly.layer(capa, 0)).insert(
            kdb.Text(nombre, kdb.Trans(kdb.Vector(
                round(x / ly.dbu), round(y / ly.dbu)))))

        print(f"  {nombre:9s} pad {caja.width():.2f} x {caja.height():.2f} um "
              f"at ({caja.left:.2f}, {caja.bottom:.2f})  {len(vias)} vias  "
              f"{'M1->M2->M3' if capa == 34 else 'M2->M3'}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    ly.write(str(OUT))
    print(f"\n  {OUT}")
    print(f"  {top.dbbox().width():.2f} x {top.dbbox().height():.2f} um")
    return 0


if __name__ == "__main__":
    sys.exit(main())
