#!/usr/bin/env python3
"""Sign-off DRC with KLayout, on the blocks and on the top.

The PDK deck (`libs.tech/klayout/tech/drc`) is the sign-off one: it decides.
OpenROAD's own router DRC (`out/route_drc.rpt`) checks fewer rules -- it knows
no `MIMTM.*` at all, for instance -- so settling for that one would be marking
your own homework.

    python3 scripts/drc_klayout.py [block ...]
"""

from __future__ import annotations

import collections
import glob
import subprocess
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
RUNNER = "/foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py"

#: Output directory of the top, so v2 can be checked without stepping on v1's.
#: The Makefile sets it (`TOP_OUT`), same as in the OpenROAD scripts.
OUT = ROOT / os.environ.get("TOP_OUT", "out")

#: Which top cell gets checked. `GRADIENT_NAV` builds four GRADIENT blocks
#: (the 98 dB OPAM); `GRADIENT_NAV2` is the same schematic with GRADIENT2,
#: that is with OPAM_LIN_flat. The Makefile sets it with `T=`, like `TOP_OUT`.
TOP = os.environ.get("TOP_CELL", "GRADIENT_NAV")

#: How many deck files KLayout runs at once. **Not 4 any more.** The density
#: pass on the integrated area (1110 x 1110 um, 7.8 M fill shapes) peaks near
#: 3 GB on its own; with four of those in flight this 7 GB machine OOM-kills
#: one and the deck writes not a single `.lyrdb`, which arrives here as
#: "THE DECK DID NOT RUN" and reads like a broken GDS. Two is what fits.
#: `DRC_MP` raises it again on a machine with the memory for it.
MP = os.environ.get("DRC_MP", "2")

TARGETS = {
    "COMP": ROOT / "gds/COMP.gds",
    "OPAM": ROOT / "gds/OPAM.gds",
    "DECODER": ROOT / "gds/DECODER.gds",
    "WEIGHT_COMP": ROOT / "gds/WEIGHT_COMP.gds",
    "OPAM_LIN_flat": ROOT / "gds/OPAM_LIN_flat.gds",
    "DECODER_MAX": ROOT / "gds/DECODER_MAX.gds",
    "ESD_CDM": ROOT / "gds/ESD_CDM.gds",
    "OPAM_SUMA": ROOT / "gds/OPAM_SUMA.gds",
    "io_secondary_5p0": ROOT / "gds/io_secondary_5p0.gds",
    TOP: OUT / f"{TOP}.gds",
    #  The same top with the decoupling capacitors dropped into the gaps
    #  (`scripts/decap_fill.py`). This is the intermediate step: the file that
    #  `fill_density.py` later fills comes from here.
    f"{TOP}_DECAP": OUT / f"{TOP}_decap.gds",
    #  The same top with the density fill (`scripts/fill_density.py`). This is
    #  the submission deliverable; the one above stays for the debug loop.
    f"{TOP}_FILLED": OUT / f"{TOP}_filled.gds",
}


#: The filled GDS keeps the cell name of the original.
TOPCELL = {f"{TOP}_FILLED": TOP, f"{TOP}_DECAP": TOP}


def counts(run_dir: Path) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    for f in glob.glob(str(run_dir / "*.lyrdb")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        for item in root.iter("item"):
            cat = (item.findtext("category") or "").strip("'")
            if cat:
                c[cat] += 1
    return c


def completo(run_dir: Path) -> tuple[bool, str]:
    """Did the deck actually finish, or did some of it die on the way?

    `.lyrdb` files are written one per rule table, and **a table that raises
    writes none**. Counting violations over whatever files happen to be there
    therefore reports a partial run as a full one: on the integrated area five
    tables (`ldnmos`, `dnwell`, `nwell`, `ldpmos`, `mslot`) died with an
    exception, 59 of 63 files were written, and this function's absence made
    that read exactly like 63 clean ones.

    The runner's own log is the witness: it prints one `Running Global
    Foundries ... on design <table>` per table it starts, and one `| ERROR |`
    per table that blows up. Both numbers are compared against the files.
    """
    logs = sorted(run_dir.glob("drc_run_*.log"))
    if not logs:
        return False, "no runner log: the deck never started"
    txt = logs[-1].read_text(errors="replace")
    lanzados = txt.count("Running Global Foundries")
    errores = [l for l in txt.splitlines() if "| ERROR   |" in l
               and "generated an exception" in l]
    escritos = len(list(run_dir.glob("*.lyrdb")))
    if errores:
        cuales = ", ".join(l.split("|")[2].split("generated")[0].strip()
                           for l in errores)
        return False, f"{len(errores)} table(s) raised: {cuales}"
    if not escritos:
        return False, f"no .lyrdb in {run_dir}"
    if escritos < lanzados:
        return False, f"only {escritos} .lyrdb of {lanzados} tables started"
    return True, f"{escritos} tables"


def main() -> int:
    #  DENSITY rules are a separate pass: the deck does not run them unless
    #  asked, so until now they had never been checked in this flow at all.
    #  magic is no alternative here -- its GF180 techfile carries not a single
    #  density rule, so this check only exists in KLayout.
    densidad = "--density" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("-")] or list(TARGETS)
    bad = 0
    for name in names:
        gds = TARGETS.get(name)
        if gds is None:
            sys.exit(f"unknown target {name}; I know {', '.join(TARGETS)}")
        if not gds.exists() or not gds.resolve().exists():
            print(f"  {name:14s} sin GDS todavia — saltado")
            continue
        run_dir = ROOT / "out" / (f"density_{name}" if densidad else f"drc_{name}")
        subprocess.run(["rm", "-rf", str(run_dir)], check=False)
        run_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["python3", RUNNER, f"--path={gds.resolve()}", "--variant=D",
             f"--topcell={TOPCELL.get(name, name)}", f"--run_dir={run_dir}", f"--mp={MP}"]
            + (["--density_only"] if densidad else []),
            capture_output=True, text=True, timeout=14400, check=False,
            env={"PATH": "/foss/tools/klayout:/usr/bin:/bin",
                 "HOME": "/tmp", "PDK_ROOT": "/foss/pdks"})
        #  **A partial run is not a clean one.** Without this, a tool failure --
        #  a `klayout` missing from PATH, an unreadable GDS, a table that ran
        #  out of memory -- counted as zero violations and printed as "clean".
        #  Same mistake as the empty `net.name` in `check_connectivity` and as
        #  `run_lvs.py` returning 0 on a mismatch: the check does not fail, it
        #  lies. See `completo()`.
        entero, porque = completo(run_dir)
        if not entero:
            print(f"  {name:14s} INCOMPLETO -- {porque}")
            bad += 1
            continue
        c = counts(run_dir)
        if not c:
            print(f"  {name:14s} limpio ({porque})")
            continue
        bad += 1
        total = sum(c.values())
        detail = "  ".join(f"{k} x{v}" for k, v in c.most_common(10))
        print(f"  {name:14s} {total} violations: {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
