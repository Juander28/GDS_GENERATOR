#!/usr/bin/env python3
"""magic DRC on the blocks and on the top.

This is a **second opinion**, not a replacement: the KLayout deck
(`libs.tech/klayout/tech/drc`) and the magic one (the `drc` section of
`gf180mcuD.tech`) do not cover exactly the same rules. What makes running
both worthwhile is precisely what shows up in one and not in the other.

    python3 scripts/drc_magic.py [block ...]

With no arguments it runs the blocks and the top. Returns a non-zero exit
code if any GDS has violations, so that `make` notices.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
MAGIC = "/foss/tools/bin/magic"
MAGICRC = "/foss/pdks/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc"

#: As in drc_klayout: output directory and top cell are chosen from outside.
OUT = ROOT / os.environ.get("TOP_OUT", "out")
#: Which top cell gets checked. `GRADIENT_NAV` builds four GRADIENT blocks
#: (the 98 dB OPAM); `GRADIENT_NAV2` is the same schematic with GRADIENT2,
#: that is with OPAM_LIN_flat. The Makefile sets it with `T=`, like `TOP_OUT`.
TOP = os.environ.get("TOP_CELL", "GRADIENT_NAV")

TARGETS = {
    "COMP": ROOT / "gds/COMP.gds",
    "OPAM": ROOT / "gds/OPAM.gds",
    "DECODER": ROOT / "gds/DECODER.gds",
    "WEIGHT_COMP": ROOT / "gds/WEIGHT_COMP.gds",
    "OPAM_LIN_flat": ROOT / "gds/OPAM_LIN_flat.gds",
    "io_secondary_5p0": ROOT / "gds/io_secondary_5p0.gds",
    TOP: OUT / f"{TOP}.gds",
    #  The same top with the density fill (`scripts/fill_density.py`). This is
    #  the submission deliverable; the one above stays for the debug loop.
    f"{TOP}_FILLED": OUT / f"{TOP}_filled.gds",
    f"{TOP}_DECAP": OUT / f"{TOP}_decap.gds",
}


#: The filled GDS keeps the cell name of the original.
TOPCELL = {f"{TOP}_FILLED": TOP, f"{TOP}_DECAP": TOP}


def run(cell: str, gds: Path, work: Path) -> tuple[int, str]:
    work.mkdir(parents=True, exist_ok=True)
    script = work / f"{cell}_drc.tcl"
    cell = TOPCELL.get(cell, cell)
    script.write_text(
        # `-noconsole -dnull` so it never tries to open any window.
        f"gds read {gds}\n"
        f"load {cell}\n"
        "select top cell\n"
        # Euclidean, like the KLayout deck: with the default metric
        # (Manhattan) magic is more permissive and the two would not compare.
        "drc euclidean on\n"
        "drc check\n"
        "drc catchup\n"
        "set n [drc list count total]\n"
        'puts "MAGIC_DRC_COUNT $n"\n'
        "if {$n > 0} { puts [drc listall why] }\n"
        "quit -noprompt\n")
    r = subprocess.run(
        [MAGIC, "-dnull", "-noconsole", "-rcfile", MAGICRC, script.name],
        cwd=work, capture_output=True, text=True, timeout=7200, check=False,
        env={"PATH": "/usr/bin:/bin", "PDK_ROOT": "/foss/pdks", "HOME": "/tmp"})
    out = r.stdout + r.stderr
    m = re.search(r"MAGIC_DRC_COUNT (\d+)", out)
    if not m:
        # Without the count there is no claiming it is clean: treated as a
        # failure rather than taking silence for a pass.
        return -1, out
    return int(m.group(1)), out


def main() -> int:
    names = sys.argv[1:] or list(TARGETS)
    work = ROOT / "work_drc"
    bad = 0
    for name in names:
        gds = TARGETS.get(name)
        if gds is None:
            sys.exit(f"unknown target {name}; I know {', '.join(TARGETS)}")
        if not gds.exists() or not gds.resolve().exists():
            print(f"  {name:14s} sin GDS todavía — saltado")
            continue
        n, out = run(name, gds.resolve(), work)
        rpt = ROOT / "out" / f"drc_magic_{name}.log"
        rpt.parent.mkdir(parents=True, exist_ok=True)
        rpt.write_text(out)
        if n < 0:
            print(f"  {name:14s} magic gave no count -- see {rpt}")
            bad += 1
        elif n:
            print(f"  {name:14s} {n} violations -- see {rpt}")
            bad += 1
        else:
            print(f"  {name:14s} limpio")
    shutil.rmtree(work, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
