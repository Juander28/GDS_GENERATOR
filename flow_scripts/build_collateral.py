#!/usr/bin/env python3
"""Build the OpenROAD collateral (LEF, Liberty, Verilog) for the analog macros.

A GDS is not enough for OpenROAD: to place a block as a hard macro it needs an
abstract LEF (outline, pins and obstructions), a Liberty view (even an empty
black box) and a Verilog declaration. This script produces all three from the
two sources that already exist in the project:

  * the layout   -> Layouts/<BLOCK>/<BLOCK>_flat_gf180.gds   (linked in gds/)
  * the netlist  -> XSCHEM/<DIR>/simulation/<BLOCK>.sch/<BLOCK>.spice

The LEF geometry comes from magic (`lef write`), which is the well-trodden path
and already gets the obstructions right, including the MIM plates up on Metal4
and Metal5. Two details are worth knowing:

  * magic only emits a LEF PIN for labels that are marked as *ports*, and labels
    read from a GDS arrive as plain text. `port makeall` promotes them, and
    without it the LEF comes out with zero pins and no error whatsoever.
  * magic has no netlist, so it cannot know pin directions. They are read here
    from the xschem netlist and patched into the LEF afterwards.

Run it from the openroad/ directory (or use the Makefile):

    python3 scripts/build_collateral.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import klayout.db as kdb

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
MAGIC = "/foss/tools/bin/magic"
MAGICRC = "/foss/pdks/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc"

# block -> netlist that declares its pins
BLOCKS = {
    "COMP": PROJECT / "XSCHEM/OPAM/simulation/COMP.sch/COMP.spice",
    "WEIGHT_COMP": PROJECT / "XSCHEM/WEIGTH/simulation/WEIGHT_COMP.sch/WEIGHT_COMP.spice",
    "OPAM": PROJECT / "XSCHEM/OPAM/simulation/OPAM.sch/OPAM.spice",
    "OPAM_LIN_flat": PROJECT / "XSCHEM/OPAM/simulation/OPAM_LIN_flat.sch/OPAM_LIN_flat.spice",
    "DECODER": PROJECT / "XSCHEM/DECODER/simulation/DECODER.sch/DECODER.spice",
    #  The two v2 ones. They live in XSCHEM_v2 because the GRADIENT_NAV3 top
    #  touches nothing of the already verified one.
    "DECODER_MAX": PROJECT / "XSCHEM_v2/simulation/DECODER_MAX.sch/DECODER_MAX.spice",
    "OPAM_SUMA": PROJECT / "XSCHEM_v2/simulation/OPAM_SUMA.sch/OPAM_SUMA.spice",
    #  The secondary ESD cell. Its layout is not built by coil_layout but by
    #  openroad/scripts/esd_layout.py -- see that file for why.
    #  KEPT, BUT NOT FABRICATED: what goes on silicon is io_secondary_5p0 below.
    "ESD_CDM": PROJECT / "XSCHEM_v2/simulation/ESD_CDM.sch/ESD_CDM.spice",
    #  The organisers' secondary ESD, adopted as drawn (see
    #  layouts_v2/io_secondary_5p0/README_ORIGEN.txt). It has no schematic of
    #  ours, so the pin names and directions come from the same file that is its
    #  LVS reference -- which is the file that describes what is drawn, and
    #  therefore the only one that can be right about the ports.
    "io_secondary_5p0": PROJECT / f"layouts_v2/io_secondary_5p0/io_secondary_5p0_lvs.spice",
}

#: Blocks that are NOT FINISHED. They are reported and let through instead of
#: failing the run, so the rest of the collateral can still be rebuilt; every
#: other missing or broken piece is an error, because a silently incomplete
#: collateral is how you end up floorplanning a chip that is missing a block.
#: A block in here must not appear in the top being built -- if it does, the
#: floorplan will place a macro whose LEF does not describe it.
#: `OPAM_SUMA` is here for a different reason: its layout EXISTS but is not
#: closed -- the generator could not route four of its seven ports, so magic
#: writes three LEF pins against seven in the netlist. It belongs to
#: GRADIENT_NAV3, which is not being built, and leaving it in the list stopped
#: the whole collateral. Take it out of here the day it closes.
PENDING = {"OPAM", "OPAM_SUMA"}

POWER = {"VDD", "VCC", "VPWR"}
GROUND = {"VSS", "VGND", "GND"}


# --------------------------------------------------------------------------- #
#  pin directions
# --------------------------------------------------------------------------- #
def read_directions(netlist: Path, block: str) -> dict[str, str]:
    """Pin -> INPUT / OUTPUT / INOUT for the TOP cell, from the xschem netlist.

    xschem writes the pin types in two different formats depending on the export
    style, and both show up in this project:

        *.ipin INN            /  *.opin OUT   /  *.iopin VDD
        *.PININFO VDD:B VSS:B VA:I OUT:B

    The result is restricted to the ports of the top `.subckt`, and returned in
    that order. The file also contains the sub-circuits (bias, sub_diff...) with
    pin declarations of their own: scanning the whole file returned 14 pins for
    COMP instead of 5, mixing in internal nodes such as `bias1` or `vinp`.

    Power and ground are forced to INOUT whatever the schematic says.
    """
    text = netlist.read_text()

    # the top may be a real `.subckt` or the commented `**.subckt` of the other
    # export format
    m = re.search(rf"^\*{{0,2}}\.subckt\s+{re.escape(block)}\s+(.*)$", text, re.M | re.I)
    if not m:
        raise SystemExit(f"no .subckt {block} found in {netlist}")
    ports = m.group(1).split()

    seen: dict[str, str] = {}
    for kind, name in re.findall(r"^\*\.(ipin|opin|iopin)\s+(\S+)", text, re.M):
        seen.setdefault(name, {"ipin": "INPUT", "opin": "OUTPUT",
                               "iopin": "INOUT"}[kind])
    pin_info = re.search(r"^\*\.PININFO\s+(.*)$", text, re.M)
    if pin_info:
        for tok in pin_info.group(1).split():
            if ":" in tok:
                pin, d = tok.rsplit(":", 1)
                seen.setdefault(pin, {"I": "INPUT", "O": "OUTPUT"}.get(d, "INOUT"))

    out: dict[str, str] = {}
    for p in ports:
        out[p] = ("INOUT" if p.upper() in POWER | GROUND
                  else seen.get(p, "INOUT"))
    return out


# --------------------------------------------------------------------------- #
#  LEF
# --------------------------------------------------------------------------- #
def write_lef(block: str, gds: Path, work: Path) -> Path:
    """Run magic to turn the GDS into an abstract LEF."""
    work.mkdir(parents=True, exist_ok=True)
    script = work / f"{block}_lef.tcl"
    script.write_text(
        f"gds read {gds}\n"
        f"load {block}\n"
        "select top cell\n"
        # Without this the LEF has no PIN at all, and magic does not complain.
        "port makeall\n"
        # NOT `-hide`. That mode collapses the obstructions into a few coarse
        # blocks, and one of them ended up covering the block's own Metal1 power
        # rail: pdngen reported `VSS on Metal1 is partially blocked (99.0%) by
        # obstructions on Metal2` and could not drop a single via into
        # WEIGHT_COMP. The detailed obstructions are bigger to read and leave the
        # rails reachable, which is the whole point of exporting them.
        f"lef write {block}\n"
        "quit -noprompt\n")
    subprocess.run([MAGIC, "-dnull", "-noconsole", "-rcfile", MAGICRC, script.name],
                   cwd=work, capture_output=True, text=True, timeout=600, check=False,
                   env={"PATH": "/usr/bin:/bin", "PDK_ROOT": "/foss/pdks", "HOME": "/tmp"})
    lef = work / f"{block}.lef"
    if not lef.exists():
        raise SystemExit(f"magic did not write {lef}")
    return lef


def patch_directions(lef_text: str, dirs: dict[str, str]) -> str:
    """Insert DIRECTION into every PIN; magic cannot know it."""
    out, current = [], None
    for line in lef_text.splitlines():
        out.append(line)
        m = re.match(r"\s*PIN\s+(\S+)\s*$", line)
        if m:
            current = m.group(1)
            d = dirs.get(current)
            if d:
                out.append(f"    DIRECTION {d} ;")
    return "\n".join(out) + "\n"


#: Which via connects which pair of metals. magic writes no obstructions on the
#: via layers, and without them the router thinks it may drop a via anywhere.
#: cualquier punto del interior de un macro: 255 violaciones en el top, casi
#: all INSIDE the blocks (M1.3 minimum area, M1.2a, V1.x, and even
#: `MIMTM.10 MiM cap cannot overlap via3`). A via can only exist where BOTH
#: metals it joins are free, so its obstruction is the union of the
#: dos.
_VIA_BETWEEN = {"Via1": ("Metal1", "Metal2"), "Via2": ("Metal2", "Metal3"),
                "Via3": ("Metal3", "Metal4"), "Via4": ("Metal4", "Metal5")}

#: How far each metal's obstruction is grown. Declaring it with the exact
#: geometry is not enough: the router slips through gaps where it then cannot
#: meet the spacing, and violations appear INSIDE the macro. It is given the
#: rule's own margin so it keeps its distance.
#:
#: Metal4 also carries the 1.2 um of `MIMTM.1`: the MIM plates live there and the
#: rule does not ask not to overlap them, it asks 1.2 um to any other metal4.
#: quedan bandas libres de sobra (en COMP, 48 de sus 104 um), y hacen falta:
#: it is how the router crosses a macro vertically. Without Metal4, all the
#: vertical traffic had to go through the channels and global routing did not close.
#: Half the router's wire width. The top signal nets use the
#: no estandar `ANCHO` (0.38, ver `route_top.tcl`), y el router mantiene el cable
#: OUTSIDE the obstruction but measured on its axis: growing the obstruction by
#: the spacing alone, the wire edge ended 0.24-0.27 um from the macro's metal.
#: The 15 violations left on the top were all that -- router wire
#: contra metal de un macro, ninguna macro contra macro ni router contra router.
_MEDIO_CABLE = 0.19

_OBS_GROW = {"Metal1": 0.23, "Metal2": 0.30 + _MEDIO_CABLE,
             "Metal3": 0.30 + _MEDIO_CABLE,
             "Metal4": 0.30 + _MEDIO_CABLE + 1.2, "Metal5": 0.30}


def add_via_obstructions(lef_text: str, extra: dict[str, list] | None = None,
                         exacta: dict[str, list] | None = None) -> str:
    """Rewrites the OBS block: grows the metals and adds the via layers.

    `extra` carries the geometry `keep_top_access` removed from the pins. It goes
    here and not in the bin: in COMP and OPAM those Metal4/Metal5 shapes are **the
    MIM plate**. Deleting them from the abstract left the plate invisible, and the
    top's power straps were laid beside it -- 22 `MIMTM.1`, which asks 1.2 um.
    As an obstruction, and with the rule's margin, nobody goes near it.

    `exacta` are the pads `drop_trapped_pads` removed, and they go **ungrown**.
    All that is asked of them is that nobody merges with them; growing them 0.49
    would have them eat the neighbour's pin, which is right beside -- that is what
    made them useless as an access point in the first place.
    """
    #  A cell can legitimately have NO obstruction: ESD_CDM is rails, devices
    #  and pins with nothing left over, so magic writes no OBS block at all and
    #  slicing on it raised ValueError. Cut before the closing END instead, and
    #  the block below gets built from scratch.
    #  ...cut before the macro's OWN closing END, found by name. `rindex("END ")`
    #  is not it: magic writes an `END LIBRARY` after it, so the cut landed past
    #  `END ESD_CDM` and the OBS block came out AFTER the macro had closed --
    #  which OpenROAD rejects with `LEFPARS-1 ... on token OBS`.
    _macro = re.search(r"MACRO (\S+)", lef_text).group(1)
    cut = (lef_text.index("  OBS") if "  OBS" in lef_text
           else lef_text.index(f"END {_macro}"))
    body = lef_text[cut:]
    by_layer: dict[str, kdb.Region] = {}
    for name, boxes in (extra or {}).items():
        for x0, y0, x1, y1 in boxes:
            by_layer.setdefault(name, kdb.Region()).insert(
                kdb.Box(round(x0 * 1000), round(y0 * 1000),
                        round(x1 * 1000), round(y1 * 1000)))
    layer = None
    for line in body.splitlines():
        m = re.match(r"\s*LAYER (\S+) ;", line)
        if m:
            layer = m.group(1)
            continue
        m = re.match(r"\s*RECT ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ;", line)
        if m and layer:
            x0, y0, x1, y1 = (float(v) for v in m.groups())
            by_layer.setdefault(layer, kdb.Region()).insert(
                kdb.Box(round(x0 * 1000), round(y0 * 1000),
                        round(x1 * 1000), round(y1 * 1000)))

    for name, grow in _OBS_GROW.items():
        if name in by_layer:
            by_layer[name] = by_layer[name].sized(round(grow * 1000)).merged()

    #  Despues de engordar, nunca antes.
    for name, boxes in (exacta or {}).items():
        for x0, y0, x1, y1 in boxes:
            by_layer.setdefault(name, kdb.Region()).insert(
                kdb.Box(round(x0 * 1000), round(y0 * 1000),
                        round(x1 * 1000), round(y1 * 1000)))
        by_layer[name].merge()

    extra = []
    for via, (lo, hi) in _VIA_BETWEEN.items():
        r = kdb.Region()
        for name in (lo, hi):
            if name in by_layer:
                r += by_layer[name]
        r.merge()
        if r.is_empty():
            continue
        extra.append(f"      LAYER {via} ;")
        for poly in r.each():
            b = poly.bbox()
            extra.append(f"        RECT {b.left / 1000:.3f} {b.bottom / 1000:.3f} "
                         f"{b.right / 1000:.3f} {b.top / 1000:.3f} ;")

    #  The whole OBS block is rewritten: the metal ones grown and the via ones
    #  new, so appending at the end will not do.
    for name in _OBS_GROW:
        if name not in by_layer:
            continue
        extra.append(f"      LAYER {name} ;")
        for poly in by_layer[name].each():
            b = poly.bbox()
            extra.append(f"        RECT {b.left / 1000:.3f} {b.bottom / 1000:.3f} "
                         f"{b.right / 1000:.3f} {b.top / 1000:.3f} ;")
    for name, region in by_layer.items():
        if name in _OBS_GROW or name in _VIA_BETWEEN:
            continue                       # Nwell y demas, tal cual venian
        extra.append(f"      LAYER {name} ;")
        for poly in region.each():
            b = poly.bbox()
            extra.append(f"        RECT {b.left / 1000:.3f} {b.bottom / 1000:.3f} "
                         f"{b.right / 1000:.3f} {b.top / 1000:.3f} ;")

    head = lef_text[:cut]
    end = f"END {_macro}\n"
    if not extra:
        return head + end
    return head + "  OBS\n" + "\n".join(extra) + "\n  END\n" + end


#: GDS layer number of each metal, so the real geometry can be inspected.
_GDS = {"Metal1": (34, 0), "Metal2": (36, 0), "Metal3": (42, 0),
        "Metal4": (46, 0), "Metal5": (81, 0)}


def _clip_to_real(rects: list[str], real) -> list[str]:
    """Replaces each pin RECT with its intersection with the real metal."""
    out = []
    for line in rects:
        m = re.match(r"\s*RECT ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ;", line)
        if not m:
            out.append(line)
            continue
        box = kdb.DBox(*(float(v) for v in m.groups()))
        got = real & kdb.Region(box.to_itype(1e-3))
        got.merge()
        pieces = []
        for poly in got.each():
            #  Ni `is_box()` ni la igualdad exacta de areas valen como criterio:
            #  the real metal reaches the pin with chamfered corners and an
            #  eight-vertex polygon comes out. The piece's box is accepted when
            #  the piece nearly fills it; what gets over-declared are those
            #  chamfers, hundredths of a micron and always INSIDE the rectangle
            #  magic ya declaraba.
            if poly.area() < 0.8 * poly.bbox().area():
                pieces = []            # forma rara: mejor dejar el RECT original
                break
            b = poly.bbox().to_dtype(1e-3)
            #  Nothing below the metal3 minimum width (M3.1 = 0.28): a
            #  esquirla no es un sitio donde aterrizar.
            if min(b.width(), b.height()) >= 0.28:
                pieces.append(f"      RECT {b.left:.3f} {b.bottom:.3f} "
                              f"{b.right:.3f} {b.top:.3f} ;")
        out.extend(pieces or [line])
    return out


#: Gap below which a Metal3 pad is not a place to land:
#: dos veces (medio cable + espaciado) = 2 * (0.19 + 0.28). Si entre el pad y el
#: the neighbouring pin's metal a wire with its spacing on each side does not
#: fit, the router has no LEGAL way to reach that neighbour without brushing the
#: pad -- and when it has none, it does not stop: it goes over. Since both shapes
#: layer, se funden en un poligono y no queda ni rastro en el DRC.
_HUECO_UTIL = 2 * (_MEDIO_CABLE + 0.28)


def drop_trapped_pads(lef_text: str):
    """Removes from a pin the Metal3 pads that sit against another pin.

    That is how the top's second short appeared: `DECODER` brings `XZ` up through
    0.4 x 0.4 (x = 10.03, 12.03 y 24.03 en coordenadas del macro) y la bar de
    `YZ` passes 0.92 um below the first two. The router entered `YZ` from
    (75.32, 374.92) y subio recto: a 0.92 um no cabe un cable de 0.38 con 0.28 a
    each side, so it crossed the `XZ` pad and left `x3_net2` and `x3_net3`
    siendo la misma net. Cero violaciones de DRC, claro.

    A pad is only removed if the pin keeps **another** that is not trapped: the
    third one of `XZ`, 12 um away, is free and gets in just as well. If all of
    them are trapped, they are left as they were -- an unreachable pin is worse
    than a short, because nobody can route it.
    """
    pins: dict[str, list[tuple]] = {}
    pin = layer = None
    for line in lef_text.splitlines():
        m = re.match(r"\s*PIN\s+(\S+)\s*$", line)
        if m:
            pin, layer = m.group(1), None
            continue
        if pin and re.match(r"\s*END\s+" + re.escape(pin) + r"\s*$", line):
            pin = None
            continue
        m = re.match(r"\s*LAYER\s+(\S+)\s*;", line)
        if m:
            layer = m.group(1)
            continue
        m = re.match(r"\s*RECT ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ;", line)
        if m and pin and layer == "Metal3":
            pins.setdefault(pin, []).append(tuple(float(v) for v in m.groups()))

    def region(rects):
        r = kdb.Region()
        for box in rects:
            r.insert(kdb.DBox(*box).to_itype(1e-3))
        return r.merged()

    fuera: dict[str, set] = {}
    for p, rects in pins.items():
        otros = kdb.Region()
        for q, rs in pins.items():
            if q != p:
                otros += region(rs)
        otros.merge()
        atrapados = {r for r in rects
                     if not region([r]).sized(round(_HUECO_UTIL * 1000))
                     .interacting(otros).is_empty()}
        if atrapados and len(atrapados) < len(rects):
            fuera[p] = atrapados

    if not fuera:
        return lef_text, {}

    exacta: dict[str, list] = {}
    out, pin, layer = [], None, None
    for line in lef_text.splitlines():
        m = re.match(r"\s*PIN\s+(\S+)\s*$", line)
        if m:
            pin, layer = m.group(1), None
        elif pin and re.match(r"\s*END\s+" + re.escape(pin) + r"\s*$", line):
            pin = None
        else:
            m = re.match(r"\s*LAYER\s+(\S+)\s*;", line)
            if m:
                layer = m.group(1)
            else:
                m = re.match(r"\s*RECT ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ;",
                             line)
                if m and pin and layer == "Metal3":
                    r = tuple(float(v) for v in m.groups())
                    if r in fuera.get(pin, ()):
                        exacta.setdefault("Metal3", []).append(r)
                        continue
        out.append(line)
    return "\n".join(out) + "\n", exacta


#: Metal stack for working out what is joined to what inside the block. It is the
#: same one scripts/check_connectivity.py uses, and on purpose it does NOT carry
#: poly: what is needed here is precisely that a poly resistor body
#: NO una sus dos extremos.
PILA = [("Metal1", (34, 0)), ("Via1", (35, 0)), ("Metal2", (36, 0)),
        ("Via2", (38, 0)), ("Metal3", (42, 0)), ("Via3", (40, 0)),
        ("Metal4", (46, 0)), ("Via4", (41, 0)), ("Metal5", (81, 0))]


def _extraer(gds: Path):
    """(l2n, regions, labels) of a block layout."""
    ly = kdb.Layout()
    ly.read(str(gds))
    top = ly.top_cell()
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, []))
    reg = {n: l2n.make_polygon_layer(ly.layer(*gl), n) for n, gl in PILA}
    for i in range(0, len(PILA) - 1, 2):
        m, v, u = PILA[i][0], PILA[i + 1][0], PILA[i + 2][0]
        l2n.connect(reg[m])
        l2n.connect(reg[m], reg[v])
        l2n.connect(reg[v], reg[u])
    l2n.connect(reg["Metal5"])
    l2n.extract_netlist()
    etiquetas = {}
    for li in ly.layer_indexes():
        layer = next((n for n, gl in PILA if ly.get_info(li).layer == gl[0]
                     and ly.get_info(li).datatype == gl[1]), None)
        if layer is None:
            continue
        for sh in top.shapes(li).each():
            if sh.is_text():
                etiquetas.setdefault(sh.text.string,
                                     (layer, sh.text.x * ly.dbu, sh.text.y * ly.dbu))
    return l2n, reg, etiquetas


def podar_islas_ajenas(lef_text: str, gds: Path, dirs: dict[str, str]):
    """Removes from each PIN the metal NOT electrically joined to its label.

    magic writes the port with all the geometry its connectivity model considers
    joined, **and that model goes straight through the body of a poly
    resistor**. In `OPAM_LIN_flat`, the only block with a resistor, pin `OUT`
    came out with metal from BOTH sides of the feedback: that of `OUT` and that
    de `G_OUT_P`, que es un nodo interno.

    Eso no da ningun error en ningun sitio. El router del top aterrizo en el lado
    wrong one and the three comparators of each GRADIENT2 ended up hanging off
    `G_OUT_P` instead of `OUT`. DRC sees nothing -- no rule is broken -- and the
    router's own report comes out empty.

    Here each port rectangle is probed against the block's metal extraction and
    only the group containing the pin's LABEL is kept. What is removed is
    returned so it can go in as an obstruction: it is still metal and nobody
    debe fundirse con el.

    The power pins are skipped: their metal is joined through substrate and well
    taps, which are not in the stack, so breaking into islands there is normal.
    """
    #  The LEF coordinates magic writes ARE the GDS ones, unshifted: the block
    #  declares `ORIGIN 1.26 0` and `SIZE 87.31` precisely because its geometry
    #  runs from -1.26 to 86.05, which is the GDS bbox. ORIGIN is added later,
    #  when placing the macro (see check_connectivity.place); not here.
    l2n, reg, etiquetas = _extraer(gds)

    def net_en(layer, x, y):
        n = l2n.probe_net(reg[layer], kdb.DPoint(x, y))
        return n.expanded_name() if n else None

    podado: dict[str, list] = {}
    out, pin, layer, alimentacion = [], None, None, False
    for line in lef_text.splitlines():
        m = re.match(r"\s*PIN\s+(\S+)\s*$", line)
        if m:
            pin, layer, alimentacion = m.group(1), None, False
            out.append(line)
            continue
        if pin and re.match(rf"\s*END\s+{re.escape(pin)}\s*$", line):
            pin = None
            out.append(line)
            continue
        if pin and re.match(r"\s*USE\s+(POWER|GROUND)\s*;", line):
            alimentacion = True
        m = re.match(r"\s*LAYER\s+(\S+)\s*;", line)
        if m:
            layer = m.group(1)
        m = re.match(r"\s*RECT ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ;", line)
        if not (pin and not alimentacion and layer in reg and m
                and pin in etiquetas):
            out.append(line)
            continue
        x0, y0, x1, y1 = (float(v) for v in m.groups())
        cap_et, ex, ey = etiquetas[pin]
        buena = net_en(cap_et, ex, ey)
        suya = net_en(layer, (x0 + x1) / 2, (y0 + y1) / 2)
        if buena is None or suya == buena:
            out.append(line)
        else:
            podado.setdefault(layer, []).append((x0, y0, x1, y1))
    return "\n".join(out) + "\n", podado


def keep_top_access(lef_text: str, dirs: dict[str, str], gds=None):
    """Leaves on each signal pin only the metal the top can enter through.

    Los bloques suben ahora sus puertos hasta Metal3 (ver
    `zotnetic_layout/coil_layout/power.py`). Si el LEF sigue anunciando ademas la
    Metal1 shape, the top's router goes in through it: it drops a via1 into the
    block and lands against the neighbour's metal -- `Cut Short` in detailed
    routing, which is exactly what the Metal3 landing pad was there to prevent.

    From the power ones **only Metal2** is removed, and for a specific reason:
    it is a SHORT, the only one the top had left. `lef write` declares as port
    pins the ~55 Metal2 pads of 0.4 x 0.4 each block uses to bring its Metal1
    rail up to the Metal3 bar, and the top's router believes
    it may cross them. It crossed one: the `S2P` Metal2 wire runs from
    (217.56, 258.44) to (217.56, 294.84) and on the way merges with the VDD pad
    of `x3_x5` at y=270.66 and with the VSS one of `x4_x3` at y=283.48 -- the LEF
    puts them 0.10 um from its axis -- so S2P, VDD and VSS end up the same net.
    **There is no DRC violation**: two overlapping shapes on the same layer merge
    into one polygon, so neither KLayout nor magic sees anything, and the router
    itself reports empty. Only LVS sees it, and there it shows as a node with
    2442 terminales que se come medio circuito.

    As an obstruction, on the other hand, the router respects them -- which is
    what it already does with all the block's internal Metal2 -- and besides
    `add_via_obstructions` derives the Via1 and Via2 obstruction from it, which

    Metal1 stays as a pin: those are the rails, they do not get in the way of
    signal routing (which runs Metal2 and up) and removing them fixes nothing.
    And the Metal3 bar too, which is the one `pdngen` hooks the grid to
    (`add_pdn_connect -grid macro -layers {Metal3 Metal4}`).
    """
    #  Metal3 ONLY. Leaving Metal4/Metal5 too looked harmless -- same net -- but
    #  in COMP and OPAM those shapes are **the MIM plate**: the router took them
    #  as an access point and ran Metal4 beside them, and `MIMTM.1` asks 1.2 um
    #  to any other metal4 without forgiving that it is the same net. That is
    #  where 60 of the 170 top violations came from.
    keep_senal = {"Metal3"}
    keep_power = {"Metal1", "Metal3"}
    keep = keep_senal
    dropped: dict[str, list] = {}
    #  The pin is clipped against the metal3 that is REALLY in the GDS. magic's
    #  `lef write` gives one rectangle per port, and when a port's pads never
    #  merged into a bar (`add_signal_access` only joins them if the spacing
    #  allows) that rectangle is their BOUNDING BOX: it declares as landable a
    #  gap where there is no metal. The router landed there, 0.14 um from the pad
    #  next door -- the `M3.2a` left on the top, and above all an OPEN circuit
    #  that netgen saw as one net fragment per
    #  macro (114 nets de mas en el top).
    real = None
    if gds is not None:
        ly = kdb.Layout()
        ly.read(str(gds))
        #  42/0 es Metal3 en GF180. 34/0 es Metal1: recortar contra el metal
        #  wrong one left the pins as 0.34 um slivers where there is a bar
        #  entera de 2.3 x 0.4, y el DRC del top subia de 14 a 32.
        real = kdb.Region(ly.top_cell().begin_shapes_rec(ly.layer(*_GDS["Metal3"])))
        real.merge()
    out, pin, groups, in_port = [], None, None, False
    for line in lef_text.splitlines():
        m = re.match(r"\s*PIN\s+(\S+)\s*$", line)
        if m:
            pin = m.group(1)
            out.append(line)
            continue
        if pin and re.match(r"\s*END\s+" + re.escape(pin) + r"\s*$", line):
            pin = None
            out.append(line)
            continue
        power = bool(pin) and pin.upper() in POWER | GROUND
        if pin and re.match(r"\s*PORT\s*$", line):
            in_port, groups = True, []
            keep = keep_power if power else keep_senal
            out.append(line)
            continue
        if in_port:
            if re.match(r"\s*END\s*$", line):
                #  If the port does not reach the entry layer, nothing is taken
                #  from it: better a spare pin than an unreachable one.
                has3 = any(g[0] in keep for g in groups)
                for layer, rects in groups:
                    if has3 and layer not in keep:
                        # No se tira: pasa a ser obstruccion (ver add_via_obstructions)
                        for r in rects:
                            m2 = re.match(r"\s*RECT ([-\d.]+) ([-\d.]+) "
                                          r"([-\d.]+) ([-\d.]+) ;", r)
                            if m2:
                                dropped.setdefault(layer, []).append(
                                    tuple(float(v) for v in m2.groups()))
                        continue          # the top enters from above, not here
                    out.append(f"      LAYER {layer} ;")
                    #  `real` is Metal3 and only Metal3: clipping the rail
                    #  de Metal1 de un pin de alimentacion lo borraria entero. Y
                    #  la bar de Metal3 de alimentacion tampoco se recorta —es
                    #  metal macizo de punta a punta y `pdngen` engancha ahi.
                    out.extend(_clip_to_real(rects, real)
                               if layer == "Metal3" and not power and real is not None
                               else rects)
                out.append(line)
                in_port, groups = False, None
                continue
            m = re.match(r"\s*LAYER\s+(\S+)\s*;", line)
            if m:
                groups.append((m.group(1), []))
            elif groups:
                groups[-1][1].append(line)
            continue
        out.append(line)
    return "\n".join(out) + "\n", dropped


def count_pins(lef_text: str) -> int:
    return len(re.findall(r"^\s*PIN\s+\S+\s*$", lef_text, re.M))


def macro_size(lef_text: str) -> tuple[float, float]:
    m = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", lef_text)
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


# --------------------------------------------------------------------------- #
#  Liberty
# --------------------------------------------------------------------------- #
def write_lib(block: str, dirs: dict[str, str], path: Path) -> None:
    """Minimal black-box Liberty view.

    OpenROAD refuses to link a design whose macros have no Liberty, even when it
    only has to place them. These blocks are analog and have no timing arcs, so
    the cell carries its pins and nothing else: no arcs are better than made-up
    ones, which would silently feed wrong numbers into the timer.
    """
    lines = [
        f'library ({block}) {{',
        '  comment                        : "Black-box view of an analog macro. '
        'No timing arcs on purpose.";',
        '  delay_model                    : table_lookup;',
        '  time_unit                      : "1ns";',
        '  voltage_unit                   : "1V";',
        '  current_unit                   : "1mA";',
        '  capacitive_load_unit (1, pf);',
        '  pulling_resistance_unit        : "1kohm";',
        '  leakage_power_unit             : "1nW";',
        '  nom_voltage                    : 5.0;',
        '  nom_temperature                : 25.0;',
        '  nom_process                    : 1.0;',
        '',
        f'  cell ({block}) {{',
        '    is_macro_cell : true;',
        '    dont_touch    : true;',
        '    dont_use      : true;',
        '    interface_timing : true;',
    ]
    for pin, d in dirs.items():
        up = pin.upper()
        if up in POWER:
            lines += [f'    pg_pin ({pin}) {{',
                      f'      voltage_name : "{pin}";',
                      '      pg_type      : primary_power;',
                      '    }']
        elif up in GROUND:
            lines += [f'    pg_pin ({pin}) {{',
                      f'      voltage_name : "{pin}";',
                      '      pg_type      : primary_ground;',
                      '    }']
        else:
            lines += [f'    pin ({pin}) {{',
                      f'      direction   : {d.lower()};',
                      '      capacitance : 0.01;',
                      '    }']
    lines += ['  }', '}', '']
    path.write_text("\n".join(lines))


# --------------------------------------------------------------------------- #
#  Verilog
# --------------------------------------------------------------------------- #
def write_verilog(block: str, dirs: dict[str, str], path: Path) -> None:
    """Black-box module declaration for synthesis and for link_design."""
    ports = list(dirs)
    body = [f"// Black-box declaration of the {block} analog macro.",
            "// The layout is the real implementation; this only gives the tools",
            "// an interface to bind against.",
            "",
            "(* blackbox *)",
            f"module {block} (",
            "    " + ",\n    ".join(ports),
            ");"]
    for pin, d in dirs.items():
        body.append(f"  {d.lower():6} {pin};")
    body += ["endmodule", ""]
    path.write_text("\n".join(body))


# --------------------------------------------------------------------------- #
def main() -> None:
    work = ROOT / "work"
    ok = True
    for block, netlist in BLOCKS.items():
        gds = ROOT / "gds" / f"{block}.gds"
        if not gds.exists() or not gds.resolve().exists():
            if block in PENDING:
                print(f"  {block:12} no layout yet — skipped")
                continue
            print(f"  {block}: missing {gds}")
            ok = False
            continue
        if not netlist.exists():
            print(f"  {block}: missing netlist {netlist}")
            ok = False
            continue

        dirs = read_directions(netlist, block)
        raw = write_lef(block, gds.resolve(), work)
        # The pins are clipped first, and what is taken from them goes in as
        # obstruccion: el orden inverso perderia la placa del MIM.
        text, podado = podar_islas_ajenas(
            patch_directions(raw.read_text(), dirs), gds.resolve(), dirs)
        for layer, rs in podado.items():
            print(f"               foreign island outside the pin: {len(rs)} rect(s)"
                  f" de {layer}")
        text, dropped = keep_top_access(text, dirs, gds.resolve())
        for layer, rs in podado.items():
            dropped.setdefault(layer, []).extend(rs)
        text, atrapados = drop_trapped_pads(text)
        text = add_via_obstructions(text, dropped, atrapados)
        for r in atrapados.get("Metal3", []):
            print(f"               pad atrapado -> obstruccion: RECT {r}")

        lef_path = ROOT / "lef" / f"{block}.lef"
        lef_path.write_text(text)
        write_lib(block, dirs, ROOT / "lib" / f"{block}.lib")
        write_verilog(block, dirs, ROOT / "verilog" / f"{block}.v")

        n_lef, n_net = count_pins(text), len(dirs)
        w, h = macro_size(text)
        flag = "OK " if n_lef == n_net else "PIN COUNT MISMATCH"
        if n_lef != n_net:
            if block in PENDING:
                flag += "  (unfinished block, let through)"
            else:
                ok = False
        print(f"  {block:12} {w:8.2f} x {h:6.2f} um   "
              f"{n_lef} LEF pins / {n_net} netlist pins   {flag}")
        short = {"INPUT": "in", "OUTPUT": "out", "INOUT": "inout"}
        print("               "
              + ", ".join(f"{p}:{short[d]}" for p, d in dirs.items()))

    shutil.rmtree(work, ignore_errors=True)
    if not ok:
        sys.exit("collateral is incomplete")


if __name__ == "__main__":
    main()
