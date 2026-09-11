#!/usr/bin/env python3
"""Collateral of GRADIENT_NAV2_V3 for the wafer.space project.

LibreLane needs four views to place a hard macro: GDS, LEF, Liberty and a
Verilog declaration. Two of them already exist and are NOT rebuilt here:

  * the GDS  -> openroad/out_v2_GRADIENT_NAV2_V3/GRADIENT_NAV2_V3.gds
  * the LEF  -> openroad/lef/GRADIENT_NAV2_V3.lef, written by macro_lef.py

The other two have never been built for the TOP cell -- `build_collateral.py`
only ever ran over the leaf blocks -- so this script writes them, reusing that
script's own `write_lib` and `write_verilog` so there is one implementation of
what a black box looks like, not two.

The top is deliberately NOT added to `build_collateral.BLOCKS`: everything in
that list gets its LEF regenerated with magic from a flat GDS, and the LEF of
the top does not come from magic. It comes from `macro_lef.py`, which reads the
routed DEF. Adding it there would quietly overwrite a good LEF with a worse one.

What this script does check is that the three descriptions agree. The netlist is
the authority on which ports exist; the LEF is what the placer believes. A port
that is in one and not the other routes perfectly and gives the wrong chip.

    python3 scripts/waferspace_collateral.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent            # waferspace/
PROJECT = WS.parent                                    # a_zonetic2026/
ROOT = PROJECT / "openroad"                            # el arbol del Chipathon

#  `build_collateral` se IMPORTA de openroad/scripts/, no se copia: write_lib y
#  write_verilog tienen que ser los mismos que usan las hojas del otro chip, o
#  acabaremos con dos ideas distintas de que es una caja negra.
sys.path.insert(0, str(ROOT / "scripts"))

from build_collateral import read_directions, write_lib, write_verilog  # noqa: E402

BLOCK = "GRADIENT_NAV2_V3"
NETLIST = PROJECT / "XSCHEM_v3/simulation" / f"{BLOCK}.spice"
LEF = ROOT / "lef" / f"{BLOCK}.lef"
GDS = ROOT / "out_v2_GRADIENT_NAV2_V3" / f"{BLOCK}.gds"
DEST = WS / "ip/gradient_nav2_v3"
SLOT_YAML = WS / "librelane/slots/slot_0p5x0p5.yaml"
MACRO_YAML = WS / "librelane/macros/macros_5v.yaml"
PDN_OUT = WS / "librelane/pdn/pdn_nav.tcl"

#: Metal5 carries 1.5 mA per um of width (tech-LEF DCCURRENTDENSITY AVERAGE,
#: not a DRC rule). The block is sized for 31 mA.
M5_MA_UM = 1.5
TARGET_MA = 31.0

#: Each strap is made a little narrower than the stub it lands on, so it is
#: always strictly inside it and no edge of the two has to line up.
STRAP_MARGIN = 0.5


def lef_pins(path: Path) -> list[str]:
    return re.findall(r"^  PIN (\S+)", path.read_text(), re.M)


def supply_ports(path: Path) -> dict[str, list[tuple[float, float]]]:
    """VDD / VSS -> the y span of every Metal5 PORT, in the block's own frame.

    These are the seven stubs the internal grid brings out of the west edge.
    They are NOT evenly spaced -- 43 um apart at the bottom and 65 at the top,
    because the shelves they come from have different heights -- which is the
    whole reason the power straps cannot be a pitch and have to be listed one
    by one.
    """
    out: dict[str, list[tuple[float, float]]] = {}
    pin = layer = None
    for line in path.read_text().splitlines():
        if m := re.match(r"^  PIN (\S+)", line):
            pin, layer = m.group(1), None
        elif m := re.match(r"^\s+LAYER (\S+) ;", line):
            layer = m.group(1)
        elif (m := re.match(r"^\s+RECT ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ;", line)) \
                and pin in ("VDD", "VSS") and layer == "Metal5":
            out.setdefault(pin, []).append((float(m.group(2)), float(m.group(4))))
    return {k: sorted(v) for k, v in out.items()}


def placement() -> tuple[float, float, str, list[float]]:
    """Where the macro is placed and how big the core is -- read, not retyped.

    The coordinates live in the librelane config, which is what OpenROAD acts
    on. Copying them into this script would make a second source of truth, and
    a power strap aimed at where the macro used to be lands on nothing.
    """
    import yaml
    core = yaml.safe_load(SLOT_YAML.read_text())["CORE_AREA"]
    inst = yaml.safe_load(MACRO_YAML.read_text())["MACROS"][BLOCK]["instances"]
    (info,) = inst.values()
    x, y = info["location"]
    return float(x), float(y), info["orientation"], [float(c) for c in core]


def write_pdn(path: Path) -> None:
    """Metal5 straps aimed at the block's supply stubs.

    The template's core grid puts horizontal Metal5 straps every 75 um. The
    block's stubs are 10 um tall and irregularly spaced, so of the seven, ONE
    is partly covered by that grid and six are missed entirely -- which would
    leave the whole block hanging off a single partial overlap. These are seven
    extra straps of the core grid, one aimed at each stub.

    They belong to the CORE grid on purpose, not to the macro grid. pdngen
    trims the core grid at the macro halo, so each of these runs in from the
    west ring, stops at the block and lands on its stub. A strap of the macro
    grid would instead be drawn across the block, and the block is a solid
    obstruction on all five metals with its own Metal5 grid underneath.
    """
    mx, my, orient, core = placement()
    ports = supply_ports(LEF)
    height = macro_height(LEF)
    if orient not in ("FS", "MX"):
        raise SystemExit(f"this script only knows how to mirror FS/MX, not {orient}")

    lines = [
        "#  GENERATED by openroad/scripts/waferspace_collateral.py -- do not edit.",
        "#",
        "#  One Metal5 strap of the core grid per supply stub of GRADIENT_NAV2_V3.",
        "#  See that script for why they are here and why they are not a pitch.",
        f"#  Macro at ({mx}, {my}) {orient}; core y0 = {core[1]}.",
        "",
    ]
    for net in ("VDD", "VSS"):
        total = 0.0
        lines.append(f"#  --- {net} " + "-" * 60)
        for y0, y1 in ports[net]:
            #  FS mirrors about the horizontal axis: y -> height - y.
            a, b = my + height - y1, my + height - y0
            w = round(b - a - STRAP_MARGIN, 3)
            off = round((a + b) / 2 - core[1], 3)
            total += w
            lines += [
                f"#  stub y {a:.3f} .. {b:.3f} absolute",
                "add_pdn_stripe \\",
                "    -grid stdcell_grid \\",
                "    -layer Metal5 \\",
                f"    -nets {net} \\",
                f"    -width {w} \\",
                f"    -offset {off} \\",
                "    -number_of_straps 1 \\",
                "    -extend_to_core_ring",
                "",
            ]
        lines.append(f"#  {net}: {len(ports[net])} straps, {total:.2f} um of Metal5"
                     f" -> {total * M5_MA_UM:.1f} mA against the {TARGET_MA:.0f} mA"
                     f" the block is sized for.")
        lines.append("")
    path.write_text("\n".join(lines))
    return {n: sum(round(b - a - STRAP_MARGIN, 3) for a, b in ports[n]) for n in ports}


def macro_height(path: Path) -> float:
    m = re.search(r"^  SIZE ([\d.]+) BY ([\d.]+) ;", path.read_text(), re.M)
    if not m:
        raise SystemExit("no SIZE in the LEF")
    return float(m.group(2))


def main() -> None:
    for p in (NETLIST, LEF, GDS):
        if not p.exists():
            sys.exit(f"missing {p}")

    dirs = read_directions(NETLIST, BLOCK)
    pins = lef_pins(LEF)

    if set(pins) != set(dirs):
        solo_lef = sorted(set(pins) - set(dirs))
        solo_net = sorted(set(dirs) - set(pins))
        sys.exit(f"LEF and netlist disagree on the ports of {BLOCK}\n"
                 f"  only in the LEF:     {solo_lef}\n"
                 f"  only in the netlist: {solo_net}")

    for sub in ("lib", "vh", "gds", "lef"):
        (DEST / sub).mkdir(parents=True, exist_ok=True)

    write_lib(BLOCK, dirs, DEST / "lib" / f"{BLOCK}.lib")
    write_verilog(BLOCK, dirs, DEST / "vh" / f"{BLOCK}.v")

    #  The GDS and the LEF are linked, never copied. A stale extracted copy of
    #  this very block once had the benches simulating weeks-old cells; the link
    #  makes that impossible because there is only ever one file.
    for sub, src in (("gds", GDS), ("lef", LEF)):
        link = DEST / sub / src.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(Path("../../../..") / src.relative_to(PROJECT))

    anchos = write_pdn(PDN_OUT)

    print(f"{BLOCK}: {len(dirs)} ports, LEF and netlist agree")
    for net, um in sorted(anchos.items()):
        ma = um * M5_MA_UM
        flag = "ok" if ma >= TARGET_MA else f"SHORT of {TARGET_MA} mA"
        print(f"  {net}: {um:6.2f} um of Metal5 -> {ma:6.2f} mA   {flag}")
    short = {"INPUT": "in", "OUTPUT": "out", "INOUT": "inout"}
    print("  " + ", ".join(f"{p}:{short[d]}" for p, d in dirs.items()))
    for sub in ("lib", "vh", "gds", "lef"):
        for f in sorted((DEST / sub).iterdir()):
            print(f"  {f.relative_to(PROJECT)}"
                  + (f" -> {f.readlink()}" if f.is_symlink() else ""))


if __name__ == "__main__":
    main()
