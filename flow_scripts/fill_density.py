#!/usr/bin/env python3
"""Density fill for the top GDS.

The sign-off DRC does not check density unless the rules are asked for
separately (`--density`), and when asked the top breaks all of them: they are
MINIMUMS, i.e. metal is missing. This step adds it **after** OpenROAD has
produced the GDS, without touching anything upstream.

Three PDK facts define how this works:

* **The deck adds the dummy in.** `comp = comp_drawn + comp_dummy`, and the same
  per layer. Dummy lives on **datatype 4** of the same layer number.
* **DRC and LVS DO see the dummy.** `layers_def.drc` does
  `metal1 = metal1_drawn + metal1_dummy`, and `layers_definitions.lvs` likewise.
  What is defined as `get_polygons(34, 0)` is the *drawn* layer, not the physical
  one. So the fill **must pass the whole DRC** and shows up in extraction as
  floating metal. Hence only WHOLE squares are placed inside the clear zone:
  clipping them against the free area creates necks and slivers, and that is
  where 6214 width, area and spacing violations came from.
* **The PDK ships no fill generator.** Neither in `libs.tech/klayout` nor in
  `librelane`. Hence this file.

`MT.3` does not measure the `metaltop` layer: for the 5-metal stack the deck
does `top_metal = metal5`, so `MT.3` and `M5.4` look at the same thing.

    python3 scripts/fill_density.py             # canales; mide y reporta
    python3 scripts/fill_density.py --sobre-macros   # also on top of the macros
"""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path

import klayout.db as kdb

ROOT = Path(__file__).resolve().parent.parent
#: Output directory of the top. Defaults to `out`, which is v1's.
#: `TOP_OUT` changes it so the v2 top can be checked without stepping on v1:
#: both have to coexist to be compared.
OUT = ROOT / os.environ.get("TOP_OUT", "out")

#: Which top cell gets checked. `GRADIENT_NAV` builds four GRADIENT blocks
#: (the 98 dB OPAM); `GRADIENT_NAV2` is the same schematic with GRADIENT2,
#: that is with OPAM_LIN_flat. The Makefile sets it with `T=`, like `TOP_OUT`.
TOP = os.environ.get("TOP_CELL", "GRADIENT_NAV")

#: Where we start from: if `decap_fill.py` already dropped the decoupling
#: capacitors into the gaps, we fill ON TOP of that file. Otherwise on the one
#: the flow produces. The submission file is always `_filled`.
GDS_DECAP = OUT / f"{TOP}_decap.gds"
GDS_IN = GDS_DECAP if GDS_DECAP.exists() else OUT / f"{TOP}.gds"
GDS_OUT = OUT / f"{TOP}_filled.gds"
DEF = OUT / f"{TOP}_routed.def"
#: Rectangles of the decoupling tiles, which must be treated as macros: fill
#: cannot put COMP inside their well nor poly over their gates.
GAPS = OUT / "decap_gaps.txt"

#: (name, GDS layer, minimum in %, spacing to real metal, spacing between
#: fill squares, minimum square side, rule).
#:
#: Poly2 uses very different numbers because **magic does have fill rules** even
#: though it has no density ones, and KLayout does not check them: `DPF.1` asks
#: 5.6 um width for poly fill, `DPF.2a` 2.4 um between fill shapes and `DPF.5`
#: **5 um clearance to real poly**. With 0.4 squares magic reported 134,488
#: violations on a file KLayout called clean.
#: Dummy goes on datatype 4 of the same number, which is what the decks add in.
#:
#: Metal5 is special: for the 5-metal stack the deck does `top_metal = metal5`,
#: so the `MT.*` rules apply and not the `M5.*` ones -- 0.36 minimum width,
#: 0.46 spacing and 0.5625 um2 area (exactly a 0.75 square). 0.80 a side is used
#: so as not to depend on rounding.
#: THE GUARD IS THE **WIDE-METAL** SPACING, NOT THE BASE ONE. Every metal layer
#: has two spacing rules and they differ: `M2.2a` asks 0.28 between any two
#: shapes, but `M2.2b` asks **0.30 to metal wider than 10 um in both
#: directions**. The 73 pin ports of the padring are Metal2 of 44 x 55 um, so
#: they are "wide" by definition, and 57 fill squares landed at 0.28 of one --
#: 57 x `M2.2b` on the integrated area, the only real DRC finding of the run.
#: Metal1, 3 and 4 carry the same 0.30 (`M*.2b`); Metal5 carries 0.50, which is
#: `MT.2b`, because for the 5-metal stack `top_metal = metal5`.
#: The spacing BETWEEN fill squares (next column) stays at the base rule: a
#: 0.40 square is not wide metal, so between them `M*.2a` is what applies.
LAYERS = [
    ("COMP",   22, 25.0, 0.40, 0.40, 1.00, "DCF.1b"),
    ("Poly2",  30, 14.0, 5.00, 2.40, 5.60, "PL.8 / DPF.1 / DPF.2a / DPF.5"),
    ("Metal1", 34, 30.0, 0.30, 0.23, 0.40, "M1.4 / M1.2b"),
    ("Metal2", 36, 30.0, 0.30, 0.28, 0.40, "M2.4 / M2.2b"),
    ("Metal3", 42, 30.0, 0.30, 0.28, 0.40, "M3.4 / M3.2b"),
    ("Metal4", 46, 30.0, 0.30, 0.28, 0.40, "M4.4 / M4.2b"),
    ("Metal5", 81, 30.0, 0.50, 0.46, 0.80, "M5.4 / MT.3 / MT.1 / MT.2b"),
]

#: MIM markers. `MIMTM.1` asks 1.2 um from the plate to any other metal4, and
#: the rule does not forgive fill.
CAP_MK = (117, 5)
MIM_CLEAR = 1.2

#: How far the square may grow chasing density, in multiples of its minimum
#: side. Relative and not absolute because the minimum sides differ wildly
#: between layers: 0.40 on metal and 5.60 on poly fill because of `DPF.1`. With
#: an absolute cap the poly loop never ran even once.
LADO_FACTOR = 3.0
PASO_HOLGURA = 0.05

#: Guard margin against the die outline. COMP fill was reaching **5 nm** from
#: the edge: in isolation that is DRC clean, because nothing is beside it, but
#: next to a seal ring or another project that is zero spacing. The ports do
#: touch the edge on purpose -- that is the way in -- but the fill has no
#: no.
BORDE_DIE = 2.0

#: **NOTHING GETS FILLED NEAR A PAD.** Clearance from every top-level pin port,
#: on every layer, over and above whatever the spacing rule asks for.
#:
#: The rules alone are not the point here. A pad is where the outside world
#: touches the die: the wire bonds to it, the probe lands on it, and the ESD
#: event arrives through it. Floating dummy metal parked half a micron away is
#: capacitance onto the one node whose impedance matters, an extra edge for a
#: discharge to jump to, and something for a probe tip to scrape into. It also
#: was, literally, the DRC failure of this design: all 57 violations of the
#: first filled integration were `M2.2b` between a fill square and a pin port.
#: Widening the guard to 0.30 makes those legal; keeping the fill away from the
#: pads altogether makes them not happen.
PAD_CLEAR = 3.0


def region(cell, layer_index, dbu: float) -> kdb.Region:
    """Every shape of a layer, flattened and on a 1 nm grid."""
    out = kdb.Region()
    it = cell.begin_shapes_rec(layer_index)
    while not it.at_end():
        out.insert(it.shape().dpolygon.transformed(it.dtrans()).to_itype(1e-3))
        it.next()
    out.merge()
    return out


def colocacion(defpath: Path | None = None) -> list[tuple[str, str, float, float, float, float]]:
    """The placed macros: `(instance, cell, x, y, width, height)`, from the DEF.

    Taken from here and not from the GDS because the top GDS is **flattened**
    (see `def_to_gds.py::flatten_all`) and has no instances left to look at. The
    size comes from each macro's LEF `SIZE`.

    `decap_fill.py` uses it too, to find the shelves: two macros are on the same
    shelf if they share `y` and height, which is the condition for their power
    rails to sit at the same level.
    """
    text = (defpath or DEF).read_text()
    unidades = float(re.search(r"UNITS DISTANCE MICRONS (\d+)", text).group(1))
    tam = {}
    for lef in (ROOT / "lef").glob("*.lef"):
        if lef.name in ("vias.lef", "techlef_patched.tlef"):
            continue
        m = re.search(r"\s*SIZE ([\d.]+) BY ([\d.]+) ;", lef.read_text())
        if m:
            tam[lef.stem] = (float(m.group(1)), float(m.group(2)))
    out = []
    block = text[text.index("COMPONENTS"):text.index("END COMPONENTS")]
    for m in re.finditer(r"-\s+(\S+)\s+(\S+)\s*\+\s+\S+\s+"
                         r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)", block):
        cell = m.group(2)
        if cell not in tam:
            continue
        x, y = int(m.group(3)) / unidades, int(m.group(4)) / unidades
        w, h = tam[cell]
        out.append((m.group(1), cell, x, y, w, h))
    return out


def zona_pines(defpath: Path | None = None) -> kdb.Region:
    """Every rectangle of every top-level PIN, from the DEF.

    Read from the DEF and not from the GDS labels because a pin is a set of
    boxes the padring dictates -- an analogue pad is a comb of eight of them --
    and the GDS keeps only their union with everything else on the same metal.

    Returns an empty region when there is no DEF, which is the block case: a
    block's ports are not pads and this does not apply to them.
    """
    path = defpath or DEF
    if not path.exists():
        return kdb.Region()
    texto = path.read_text()
    if "PINS" not in texto:
        return kdb.Region()
    unidades = float(re.search(r"UNITS DISTANCE MICRONS (\d+)", texto).group(1))
    bloque = texto[texto.index("\nPINS "):texto.index("END PINS")]
    out = kdb.Region()
    for m in re.finditer(r"\+ LAYER \S+ \(\s*(-?\d+)\s+(-?\d+)\s*\)"
                         r"\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", bloque):
        x0, y0, x1, y1 = (int(v) / unidades for v in m.groups())
        out.insert(kdb.DBox(min(x0, x1), min(y0, y1),
                            max(x0, x1), max(y0, y1)).to_itype(1e-3))
    out.merge()
    return out


def huella_macros() -> kdb.Region:
    """The macro footprint PLUS that of the decoupling tiles.

    The tiles do not appear in the DEF -- they go in later, onto the GDS -- but
    for fill purposes they are the same as a macro: inside there is well,
    diffusion and gates, and a COMP fill square landing in there would sit in a
    well with no implant of its own.
    """
    out = kdb.Region()
    for _, _, x, y, w, h in colocacion():
        out.insert(kdb.DBox(x, y, x + w, y + h).to_itype(1e-3))
    if GAPS.exists():
        for line in GAPS.read_text().split("\n"):
            if line.strip():
                x0, y0, x1, y1 = (float(v) for v in line.split())
                out.insert(kdb.DBox(x0, y0, x1, y1).to_itype(1e-3))
    out.merge()
    return out


def rejilla(zona: kdb.Region, lado: float, pitch: float, die: kdb.DBox) -> kdb.Region:
    """Squares of `lado` every `paso`, **whole**, inside `zona`.

    No clipping against the zone: a square either fits whole or is not placed.
    That way minimum width and minimum area hold by construction, which is what
    failed before -- clipping produced 0.1 um necks and pieces below minimum
    area, and DRC flagged thousands of `M*.1` and `M*.3`.
    """
    #  The coordinate comes from the INDEX, not from accumulating `pitch`.
    #  Accumulating drifts by a nanometre here and there once the boxes are
    #  snapped to the 1 nm grid, and `emitir()` then sees a step that is not
    #  exactly the pitch and cannot fold the row into an array reference.
    cuadros = kdb.Region()
    y0, x0 = die.bottom + pitch / 2, die.left + pitch / 2
    j = 0
    while y0 + j * pitch + lado <= die.top:
        y = y0 + j * pitch
        i = 0
        while x0 + i * pitch + lado <= die.right:
            x = x0 + i * pitch
            cuadros.insert(kdb.DBox(x, y, x + lado, y + lado).to_itype(1e-3))
            i += 1
        j += 1
    return cuadros.inside(zona)


def emitir(top, layout, capa: int, puesto: kdb.Region, lado: float,
           pitch: float, nombre: str) -> int:
    """Write the fill as ARRAY REFERENCES, not as loose polygons.

    Over the padring's whole 1110 x 1110 um user area the fill is 7.8 M
    squares. Written one boundary record each that is a **510 MB** GDS: past
    GitHub's 100 MB per-file limit, and slow for every tool that has to read
    it. The squares sit on a regular grid by construction, so each run of
    consecutive ones in a row collapses into a single AREF -- identical
    geometry once flattened, two orders of magnitude smaller on disk.

    Returns how many squares were written, so the caller can check nothing was
    lost on the way.
    """
    #  Regions here are on the 1 nm grid; the layout may not be (B26_A is at
    #  0.5 nm). `f` converts one into the other.
    f = 0.001 / layout.dbu
    dbu = lambda v: int(round(v * f))                              # noqa: E731
    celda = layout.create_cell(f"FILL_{nombre}")
    celda.shapes(capa).insert(kdb.Box(0, 0, dbu(lado * 1000), dbu(lado * 1000)))

    paso = dbu(round(pitch * 1000))
    filas: dict[int, list[int]] = {}
    for p in puesto.each():
        b = p.bbox()
        filas.setdefault(dbu(b.bottom), []).append(dbu(b.left))

    puestos = 0
    for y, xs in sorted(filas.items()):
        xs.sort()
        i = 0
        while i < len(xs):
            j = i
            #  Exact equality on purpose: an array whose vector is off by a
            #  nanometre puts every square after the first in the wrong place.
            #  A broken run just costs one more AREF.
            while j + 1 < len(xs) and xs[j + 1] - xs[j] == paso:
                j += 1
            n = j - i + 1
            top.insert(kdb.CellInstArray(
                celda.cell_index(), kdb.Trans(kdb.Vector(xs[i], y)),
                kdb.Vector(paso, 0), kdb.Vector(0, paso), n, 1))
            puestos += n
            i = j + 1
    return puestos


def main() -> int:
    sobre_macros = "--sobre-macros" in sys.argv
    if not GDS_IN.exists():
        sys.exit(f"{GDS_IN} is missing -- run `make top` first")

    layout = kdb.Layout()
    layout.read(str(GDS_IN))
    top = layout.top_cell()
    die = top.dbbox()
    area_die = die.width() * die.height()

    #  The die minus the guard margin: that is where fill may go.
    dentro = kdb.DBox(die.left + BORDE_DIE, die.bottom + BORDE_DIE,
                      die.right - BORDE_DIE, die.top - BORDE_DIE)
    macros = huella_macros()
    mim = region(top, layout.layer(*CAP_MK), layout.dbu)
    prohibido_mim = mim.sized(int(MIM_CLEAR * 1000))
    #  The pads, and PAD_CLEAR around them. Placed relative to the DEF pins, so
    #  the boxes are the ones the padring dictates and not our guess at them.
    pines = zona_pines()
    prohibido_pad = pines.sized(int(PAD_CLEAR * 1000))

    libre_total = kdb.Region(die.to_itype(1e-3)) - macros
    print(f"  parte de {GDS_IN.name}")
    print(f"  die {die.width():.2f} x {die.height():.2f} = {area_die:,.0f} um2   "
          f"macros {macros.area()/1e6:,.0f}   libre {libre_total.area()/1e6:,.0f}")
    if not pines.is_empty():
        print(f"  pads {pines.count()} rectangulos, {PAD_CLEAR} um de guarda "
              f"-> {prohibido_pad.area()/1e6:,.0f} um2 vedados")
    print(f"  fill {'in channels AND over the macros' if sobre_macros else 'in channels only'}\n")
    print(f"    {'layer':7s} {'regla':12s} {'antes':>7s} {'despues':>8s} {'pide':>5s}   estado")

    corto = []
    for name, gl, minimo, guarda, sep_relleno, lado_min, regla in LAYERS:
        idx = layout.layer(gl, 0)
        real = region(top, idx, layout.dbu)
        antes = 100 * real.area() / 1e6 / area_die

        #  Where fill MAY go: the die minus the geometry itself grown by its
        #  spacing, minus the macros (unless asked for), and always minus the
        #  MIM guard.
        zona = kdb.Region(dentro.to_itype(1e-3)) - real.sized(int(guarda * 1000))
        if not sobre_macros:
            zona -= macros
        zona -= prohibido_mim
        zona -= prohibido_pad
        zona.merge()

        #  The side is raised until the rule passes. The step is tied to the
        #  side, so a bigger square is more coverage and neighbour spacing always
        #  stays at the layer's spacing.
        def buscar(z: kdb.Region) -> tuple[kdb.Region, float, float]:
            puesto, lado = kdb.Region(), lado_min
            pitch = lado + sep_relleno + PASO_HOLGURA
            while lado <= lado_min * LADO_FACTOR + 1e-9:
                pitch = lado + sep_relleno + PASO_HOLGURA
                puesto = rejilla(z, lado, pitch, die)
                if 100 * (real.area() + puesto.area()) / 1e6 / area_die >= minimo:
                    break
                lado += 0.20
            return puesto, lado, pitch

        puesto, lado, pitch = buscar(zona)
        #  If channels are not enough, fill also goes OVER the macros, but only
        #  on that layer and only where needed. GRADIENT_NAV2 is 22 % bigger than
        #  GRADIENT_NAV with the same macros inside, so its metals 2 to 5 fall
        #  below minimum where v1's reached it: `M2.4`, `M3.4`, `M4.4`, `M5.4`
        #  and `MT.3`, one violation per rule in the density pass. Over a macro
        #  fill only fits where none of its own metal is, because the zone
        #  already comes from subtracting its geometry with the layer's spacing.
        #  with the layer's spacing.
        encima = False
        if (not sobre_macros
                and 100 * (real.area() + puesto.area()) / 1e6 / area_die < minimo):
            ampliada = kdb.Region(dentro.to_itype(1e-3)) - real.sized(int(guarda * 1000))
            ampliada -= prohibido_mim
            ampliada -= prohibido_pad          # los pads no se pisan ni aqui
            ampliada.merge()
            otro, otro_lado, otro_pitch = buscar(ampliada)
            if otro.area() > puesto.area():
                puesto, lado, pitch, encima = otro, otro_lado, otro_pitch, True

        capa_dummy = layout.layer(gl, 4)
        escritos = emitir(top, layout, capa_dummy, puesto, lado, pitch, name)
        assert escritos == puesto.count(), (
            f"{name}: {escritos} squares written of {puesto.count()}")

        despues = 100 * (real.area() + puesto.area()) / 1e6 / area_die
        ok = despues >= minimo
        if not ok:
            corto.append((name, regla, despues, minimo))
        print(f"    {name:7s} {regla:12s} {antes:6.2f}% {despues:7.2f}% "
              f"{minimo:4.0f}%   {'cumple' if ok else 'SIGUE CORTA'}"
              f"{'  (also over the macros)' if encima else ''}")

    GDS_OUT.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(GDS_OUT))
    print(f"\n  {GDS_OUT}")

    if corto:
        print(f"\n  {len(corto)} layer(s) short of the minimum:")
        for name, regla, d, m in corto:
            print(f"    {name} ({regla}): {d:.2f}% de {m:.0f}%")
        if not sobre_macros:
            print("  With --sobre-macros the fill also goes over the macros.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
