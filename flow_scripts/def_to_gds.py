#!/usr/bin/env python3
"""Turn an OpenROAD DEF into a GDS, with the real layout inside every macro.

**This OpenROAD build has no `write_gds`** — the list of `write_*` commands ends
at `write_verilog` — so the stream-out is done with KLayout, which reads DEF and
can substitute each macro's abstract by the GDS it was abstracted from.

That substitution is the whole point. Without it the macros come out as their LEF
outlines: a chip-shaped box with pins and no transistors, which looks right in a
screenshot and is worthless.

    python3 scripts/def_to_gds.py [out/GRADIENT_NAV.def [out/GRADIENT_NAV.gds]]
"""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path

import klayout.db as kdb

ROOT = Path(__file__).resolve().parent.parent
PDK = Path("/foss/pdks/gf180mcuD")
SC_LIB = "gf180mcu_fd_sc_mcu9t5v0"
SC_REF = PDK / "libs.ref" / SC_LIB
MAP = PDK / "libs.tech/klayout/tech/gf180mcu.map"


def def_dbu(path: Path) -> float:
    """Database unit of a DEF, in um, from its `UNITS DISTANCE MICRONS` line."""
    for line in path.read_text().splitlines():
        if line.startswith("UNITS DISTANCE MICRONS"):
            return 1.0 / float(line.split()[3])
        if line.startswith("COMPONENTS"):
            break
    return 0.001


def lef_origin(path: Path) -> tuple[float, float]:
    """MACRO `ORIGIN`, in um. (0, 0) if it does not declare one."""
    m = re.search(r"^\s*ORIGIN\s+([-\d.]+)\s+([-\d.]+)\s*;", path.read_text(), re.M)
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def normalizar_origen(layout, macro_lefs) -> None:
    """Shifts each macro by +ORIGIN, which is where OpenROAD keeps it.

    **The two tools read `ORIGIN` differently and they have to be reconciled.**
    OpenROAD normalises the master: it adds ORIGIN to all the geometry, so that
    the lower-left corner of its box lands on (0, 0) and the DEF point is that
    corner. KLayout's DEF reader, when it swaps the abstract for the GDS
    (`macro_resolution_mode = 2`), places the GDS as is: in the block's own
    coordinate system, which here starts at -1.26 (COMP and OPAM), -1.00
    (DECODER) or (-1.45, -4.21) (WEIGHT_COMP), because the substrate taps stick
    out to the left of the origin.

    Result: **every macro came out shifted by its ORIGIN** from where the router
    thought it was. And since the router is right in its own model, the DEF has
    not one error and its DRC report comes out empty; the damage only shows on
    writing the GDS. Measured on `x5_weight_comp`: the via3 the router uses to
    reach `VA` lands at (354.20, 38.48), and the `VA` pad is at
    x[349.84, 354.34] y[38.28, 38.68] **with ORIGIN added** -- without it, it
    sits at y[34.07, 34.47], 4.21 um away, exactly the block's ORIGIN y.

    That is **42 of the 55 top nets open** in the GDS, and the shorts too: a wire
    that passes cleanly beside a pin in the router's model goes straight through
    it in the GDS. LVS saw it as 54 extra nets; DRC, as nothing.

    The CELL is moved, not the instance: that way it works for a rotated macro
    too, which is how OpenROAD does it (normalise the master, then orient).
    """
    for lef in macro_lefs:
        ox, oy = lef_origin(lef)
        if (ox, oy) == (0.0, 0.0):
            continue
        cell = layout.cell(lef.stem)
        if cell is None:
            continue
        cell.transform(kdb.DTrans(kdb.DVector(ox, oy)))
        print(f"  {lef.stem:14s} +ORIGIN ({ox}, {oy})")


#: Metal3 label layer in GF180 (`42/10`). That is where the LVS deck looks for
#: a Metal3 net's name, and where the top's pin labels already are.
_M3_LABEL = (42, 10)


def etiquetar_nets(layout, top, def_path) -> int:
    """Puts each DEF net name onto its metal, as a label.

    **NOT used, and worth knowing why before trying again.** The idea was to give
    KLayout's comparer some anchors: the 55 DEF nets are named the same in the
    reference -- checked, all 55 -- because both come from the same xschem
    netlist. But **a label on the top is not a hint: it is a PORT.** Both the
    KLayout deck and magic turn every labelled top net into a circuit pin, so the
    layout ended up with 55 pins against the 19 of the reference, and that breaks
    matching instead of helping it -- including
    netgen, que hoy cuadra.

    It is kept because the function is correct and may serve if one day the
    reference declares the same 55 ports; what does not work is plugging it in
    without touching the other side. Measured: with the labels on, the deck still
    mismos 170 mensajes.
    """
    #  Inside the function on purpose: `check_connectivity` imports `lef_origin`
    #  from here, and at module level the import would be circular.
    from check_connectivity import lef_pins, macro_size, place, read_def

    inst, nets, units = read_def(def_path)
    lefs, sizes, origenes = {}, {}, {}
    for p in (ROOT / "lef").glob("*.lef"):
        if p.name in ("vias.lef", "techlef_patched.tlef"):
            continue
        lefs[p.stem] = lef_pins(p)
        sizes[p.stem] = macro_size(p)
        origenes[p.stem] = lef_origin(p)

    #  The ones already labelled are the top pins: they are not duplicated.
    placed = {s.text.string for li in layout.layer_indexes()
               for s in top.shapes(li).each() if s.is_text()}
    layer = layout.layer(*_M3_LABEL)
    n = 0
    for net, pins in sorted(nets.items()):
        if net in placed:
            continue
        for iname, pin in pins:
            if iname not in inst:
                continue
            cell, x, y, orient = inst[iname]
            rects = lefs.get(cell, {}).get(pin, [])
            if not rects:
                continue
            a = place(rects[0], x / units, y / units, orient,
                      sizes[cell], origenes[cell])
            top.shapes(layer).insert(kdb.DText(
                net, (a[0] + a[2]) / 2, (a[1] + a[3]) / 2))
            n += 1
            break
    return n


def flatten_all(layout, top) -> None:
    """Flattens the whole top before writing the GDS.

    magic evaluates the booleans it reads a GDS with **cell by cell**: a shape
    only exists for it if all the layers defining it appear together in the SAME
    cell. We already paid for that with the MIM capacitor vias (see
    `coil_layout/caps.py::flat_add`), and here it returns, subtler: on swapping
    the macros, KLayout's DEF reader rebuilds the block's internal hierarchy
    differently, and the well tap -- `COMP and NPLUS and NWELL` -- stops being
    seen. The result was that **every macro's n-well came out floating** instead
    of VDD: 43 extra well nets and 47 extra active ones in the top LVS, almost
    the whole gap of 986 nets against the 880 of the reference. Reading the same
    block from its own GDS the well is tied, so it is not the layout: it is the
    hierarchy magic receives it in.

    KLayout, gdsfactory and the sign-off DRC give the same result with or without
    this -- their extraction does not depend on hierarchy -- and
    `check_connectivity.py` already reported all 55 nets connected before
    flattening. The gain is that magic and netgen see what they see.
    """
    #  The top labels BEFORE flattening are the DEF pin ones, and they are the
    #  only ones that must survive. Each macro also brings its own
    #  (`OUT`, `INN`, `Z`, `VDD`...), which once flattened all land in the same
    #  cell: twelve `OUT`, twelve `INN`, four `Z`. magic treats everything
    #  sharing a label name as JOINED, so net `Z` came out with 1501 pins and the
    #  chip dropped to 848 nets against the 880 of the reference. Inside their
    #  block those labels are correct -- each in its own cell -- but flattening
    #  serlo.
    keep = {li: [s.text.dup() for s in top.shapes(li).each() if s.is_text()]
            for li in layout.layer_indexes()}
    top.flatten(-1, True)
    #  Without this the macro cells are left orphaned and the GDS ends up with
    #  several top cells, which breaks everything downstream.
    layout.cleanup()
    for li in layout.layer_indexes():
        dead = [s for s in top.shapes(li).each() if s.is_text()]
        for s in dead:
            top.shapes(li).erase(s)
        for txt in keep.get(li, []):
            top.shapes(li).insert(txt)


def main() -> int:
    # The **routed** DEF by default: the floorplan one has no signal nets, and a
    # GDS without them looks complete and is not.
    #  `TOP_OUT` so as not to read the OTHER version's DEF when called bare.
    #  And the ROUTED one, not the floorplan one: the floorplan one carries no
    #  routing, so the GDS comes out with the macros placed and **without a
    #  single connection between them**. It raises no error -- DRC comes out
    #  clean because there is nothing that could break a rule -- and only LVS
    #  flags it, and indirectly: the 17 top pins are left as loose shapes.
    out = ROOT / os.environ.get("TOP_OUT", "out")
    default = out / "GRADIENT_NAV_routed.def"
    if not default.exists():
        default = out / "GRADIENT_NAV.def"
    def_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    gds_path = (Path(sys.argv[2]) if len(sys.argv) > 2
                else ROOT / "out/GRADIENT_NAV.gds")
    if not def_path.exists():
        sys.exit(f"no DEF at {def_path} — run the floorplan first")

    # `vias.lef` is not a macro: those are via definitions for the router.
    macro_lefs = sorted(p for p in (ROOT / "lef").glob("*.lef")
                        if p.name not in ("vias.lef", "techlef_patched.tlef"))
    macro_gds = [ROOT / "gds" / f"{p.stem}.gds" for p in macro_lefs]
    missing = [p for p in macro_gds if not p.resolve().exists()]
    if missing:
        sys.exit("missing macro GDS: " + ", ".join(str(p) for p in missing))

    opts = kdb.LoadLayoutOptions()
    cfg = opts.lefdef_config
    cfg.map_file = str(MAP)
    cfg.lef_files = [
        str(ROOT / "lef/techlef_patched.tlef"),
        str(SC_REF / f"lef/{SC_LIB}.lef"),
        str(ROOT / "lef/vias.lef"),
        *[str(p) for p in macro_lefs],
    ]
    # 2 = never draw the LEF abstract for a MACRO, always take the geometry from
    # the substitution layouts below. Mode 1 does the opposite and is the default
    # trap: it reads the GDS files, ignores them, and writes outlines.
    cfg.macro_resolution_mode = 2
    cfg.macro_layout_files = [str(p) for p in macro_gds]
    # Match the DEF's own precision. Left at the 1 nm default, KLayout warns and
    # rounds every coordinate of a DEF written at 0.5 nm.
    cfg.dbu = def_dbu(def_path)

    layout = kdb.Layout()
    layout.read(str(def_path), opts)

    top = layout.top_cell()

    #  The check that macro substitution happened goes BEFORE flattening; after
    #  that there is no macro cell left to count.
    box = top.dbbox()
    print(f"{gds_path}")
    print(f"  top cell   {top.name}   {box.width():.2f} x {box.height():.2f} um")
    #  Only macros the DEF USES are required to be substituted. The collateral
    #  covers every block with a layout, and a given top instantiates some and
    #  not others: GRADIENT_NAV uses OPAM and GRADIENT_NAV2 uses OPAM_LIN_flat.
    #  A macro absent from the DEF is no failure; one present in the DEF that was
    #  haya sustituido, si.
    usados = set(re.findall(r"^\s*-\s+\S+\s+(\S+)", def_path.read_text(), re.M))
    ok = True
    for p in macro_gds:
        name = p.stem
        cell = layout.cell(name)
        if name not in usados:
            print(f"  {name:14s} not used by this top")
            continue
        if cell is None:
            print(f"  {name:14s} NOT INSTANTIATED")
            ok = False
            continue
        # A macro that came in as its LEF abstract has a handful of shapes; the
        # real thing has thousands. Counting is the cheapest way to be sure the
        # substitution actually happened.
        n = sum(cell.shapes(i).size() for i in layout.layer_indexes())
        print(f"  {name:14s} {cell.child_instances():5d} sub-cells, {n:6d} shapes")

    normalizar_origen(layout, macro_lefs)
    flatten_all(layout, top)
    #  Second pass: moving a cell leaves it marked, and `cells()` keeps counting
    #  the ones flattening orphaned until it is cleaned again. The file already
    #  came out with a single cell; what misled was the number on this line.
    layout.cleanup()
    gds_path.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(gds_path))
    print(f"  flattened  {layout.cells()} cell(s), "
          f"{sum(top.shapes(i).size() for i in layout.layer_indexes())} formas")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
