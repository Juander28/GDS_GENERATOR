#!/usr/bin/env python3
"""Can this machine build and check the chip? Run it FIRST after a move.

    python3 scripts/check_environment.py

WHY THIS EXISTS. The flow does not live in one directory. It reaches out to a
PDK, to a virtualenv with a PINNED gdsfactory, to five separate binaries and to
a SIBLING TREE that is not in the design repository at all. Every one of those
is referenced by an absolute path written into the scripts, so on a new machine
the failure is not "it does not work": it is a script that runs, finds nothing
where it expected something, and reports a clean result about a circuit it never
read. This project has been bitten by that shape of failure four times.

So this checks the ground before anything is built on it, and it says what is
missing rather than how to feel about it.

See `docs/moving-machine.md` for what to copy and what to install.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # .../openroad
PROJECT = ROOT.parent                                   # .../a_zonetic2026

#: The virtualenv with the PINNED gdsfactory. `env -u PYTHONPATH` is not a
#: nicety: without it a system gdsfactory shadows this one and the geometry
#: changes without a word.
KPY = Path("/headless/.venvs/zotnetic/bin/python")
GDSFACTORY = "9.2.2"

#: The generator. A SIBLING TREE, not part of the design repository -- it lives
#: in `Juander28/GDS_GENERATOR`. Three scripts add it to `sys.path` by absolute
#: path, so without it they fail on import.
GENERATOR = Path("/foss/designs/zotnetic_layout")

PDK = Path("/foss/pdks/gf180mcuD")
#: The deck entry points, called as scripts and not as libraries.
DECKS = [PDK / "libs.tech/klayout/tech/drc/run_drc.py",
         PDK / "libs.tech/klayout/tech/lvs/run_lvs.py",
         PDK / "libs.tech/magic/gf180mcuD.magicrc",
         PDK / "libs.tech/netgen/gf180mcuD_setup.tcl"]

#: The version each was used at here. A different one is not an error, but it is
#: worth knowing before a result is trusted.
BINARIES = {"klayout": "0.30.8", "magic": "8.3", "netgen": None,
            "xschem": "3.4.8", "openroad": None, "python3": "3.1"}


def row(ok: bool | None, text: str) -> None:
    mark = "  ok " if ok else ("MISSING" if ok is False else " ?  ")
    print(f"  {mark:7s}  {text}")


def version(cmd: str) -> str:
    for flag in ("--version", "-v", "--v"):
        try:
            r = subprocess.run([cmd, flag], capture_output=True, text=True,
                               timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        out = (r.stdout or "") + (r.stderr or "")
        if out.strip():
            return out.strip().splitlines()[0]
    return ""


def memory_gb() -> tuple[float, float]:
    """(total, available) in GB."""
    total = free = 0.0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) / 1048576
        elif line.startswith("MemAvailable:"):
            free = int(line.split()[1]) / 1048576
    return total, free


def container_cap() -> str:
    """What the container is allowed to use, which is not what the host has.

    On native Linux Docker sets no cap of its own: the cgroup reads `max` and
    the container can use the whole machine. On WSL2 the cap is the VM's, from
    `%UserProfile%\\.wslconfig`, and it defaults to a fraction of the host's RAM.
    That difference is what decides whether a full-die DRC finishes or dies with
    `exit 137`.
    """
    for p in ("/sys/fs/cgroup/memory.max",
              "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        f = Path(p)
        if f.exists():
            v = f.read_text().strip()
            if v in ("max", "9223372036854771712"):
                return "no cap (the whole machine)"
            try:
                return f"{int(v) / 1024**3:.1f} GB"
            except ValueError:
                return v
    return "not declared"


def main() -> int:
    missing = 0
    print(f"\n  project  {PROJECT}")

    print("\n  binaries")
    for cmd, want in BINARIES.items():
        path = shutil.which(cmd)
        v = version(cmd) if path else ""
        if not path:
            row(False, f"{cmd}: not on PATH")
            missing += 1
        elif want and want not in v:
            row(None, f"{cmd}: {v}   (built here with {want})")
        else:
            row(True, f"{cmd}: {v or path}")

    print("\n  the PDK and the decks it is driven through")
    for p in [PDK] + DECKS:
        ok = p.exists()
        missing += 0 if ok else 1
        row(ok, str(p))
    #  `run_lvs.py` runs under the SYSTEM python3: the venv has no `docopt`, and
    #  called with the venv's interpreter it dies with ModuleNotFoundError --
    #  which this flow once reported as "the top does not match".
    try:
        subprocess.run(["python3", "-c", "import docopt"], check=True,
                       capture_output=True)
        row(True, "system python3 has `docopt` (run_lvs.py needs it)")
    except Exception:
        row(False, "system python3 has no `docopt`: run_lvs.py dies on import "
                   "and that reads as an LVS mismatch")
        missing += 1

    print("\n  the virtualenv, at the pinned version")
    if not KPY.exists():
        row(False, f"{KPY} does not exist")
        missing += 1
    else:
        r = subprocess.run(["env", "-u", "PYTHONPATH", str(KPY), "-c",
                            "import gdsfactory as g; print(g.__version__)"],
                           capture_output=True, text=True)
        got = ((r.stdout or "").strip().splitlines() or [""])[-1]
        ok = got == GDSFACTORY
        missing += 0 if ok else 1
        row(ok, f"gdsfactory {got or '?'}   (must be {GDSFACTORY}; without "
                f"`env -u PYTHONPATH` the 9.44 shadows it and the geometry "
                f"changes silently)")

    print("\n  the generator: a SIBLING tree, not in this repository")
    ok = (GENERATOR / "coil_layout").is_dir()
    missing += 0 if ok else 1
    row(ok, f"{GENERATOR}   (it is in Juander28/GDS_GENERATOR)")
    for f in ("build_block.py", "run_lvs.sh", "lvs/gf180mcuD_setup_polyres.tcl"):
        ok = (GENERATOR / f).exists()
        missing += 0 if ok else 1
        row(ok, f"  {f}")

    print("\n  the design tree")
    for f in ("info.yaml", "lvs_config.json", "XSCHEM/B26_A.sch",
              "openroad/Makefile", "openroad/padframe/B26_A.def",
              "openroad/out_integration/B26_A_filled2.gds"):
        ok = (PROJECT / f).exists()
        missing += 0 if ok else 1
        row(ok, f)
    #  `spice_blocks` is symlinks, RELATIVE in the repository and absolute in a
    #  working copy. Broken, `build_block.py` cannot find its input.
    broken = [p for p in (PROJECT / "spice_blocks").glob("*")
              if p.is_symlink() and not p.resolve().exists()]
    row(not broken, f"spice_blocks: {len(broken)} broken link(s)" if broken
        else "spice_blocks: every link resolves")
    missing += 1 if broken else 0

    #  NOT A WISHLIST. The first three lines are what was MEASURED on the 7.5 GB
    #  machine this chip was built on; the last is the one thing that could not
    #  be finished there.
    print("\n  memory")
    total, free = memory_gb()
    print(f"        {total:.1f} GB on the machine, {free:.1f} available; "
          f"container cap: {container_cap()}")
    print("        measured on 7.5 GB, which is where this chip was built:")
    print("          - the blocks and the whole top: they fit")
    print("          - full DRC (DRC_MODE=deep DRC_THR=1 DRC_MP=1) on the")
    print("            filled GDS: three minutes, clean")
    print("          - split-table DRC on the filled GDS: LOSES FIVE tables")
    print("            (ldnmos, nwell, ldpmos, lvpwell, mslot) for lack of")
    print("            memory, and a table that dies writes no .lyrdb")
    print("          - KLayout LVS on the filled GDS: DOES NOT FINISH")
    if total >= 24:
        print(f"        with {total:.0f} GB there should be room to raise DRC_MP")
        print("        and DRC_THR to 4 and for no table to die. The filled-GDS")
        print("        LVS is slow by net count and not only by memory, so that")
        print("        one has to be measured, not assumed.")

    print()
    if missing:
        print(f"  {missing} thing(s) missing. See docs/moving-machine.md\n")
        return 1
    print("  the environment is complete\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
