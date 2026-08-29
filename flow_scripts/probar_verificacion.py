#!/usr/bin/env python3
"""Checks that the checks fail when they are supposed to.

A "clean" is only worth something if you know that tool would have flagged the
fault. In this project that is not theory: `check_connectivity.py` reported
**55/55 no matter what** for days, because it used `net.name` as net identity
and that field is empty on almost all of them. It did not fail: it lied.

So here the layout is broken **on purpose**, in three known ways, and we watch
who notices. It is the only way to show that a "clean" means
algo.

    python3 scripts/probar_verificacion.py            # all three, without DRC
    python3 scripts/probar_verificacion.py --con-drc  # plus DRC (slower)

The broken files are written to `work_prueba/` and nobody else uses them.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import klayout.db as kdb

ROOT = Path(__file__).resolve().parent.parent
GDS = ROOT / "out/GRADIENT_NAV.gds"
#: Everything here is disposable and NOT uploaded: `make clean` takes it away.
TMP = ROOT / "work_prueba"
DEF = ROOT / "out/GRADIENT_NAV_routed.def"
PY = sys.executable
KPY = "/headless/.venvs/zotnetic/bin/python"

M3 = (42, 0)
VIA2 = (38, 0)


def conectividad(gds: Path) -> tuple[int, int]:
    """(opens, shorts) the check reports on that GDS."""
    r = subprocess.run([PY, str(ROOT / "scripts/check_connectivity.py"),
                        str(DEF), f"--gds={gds}"],
                       capture_output=True, text=True, check=False)
    txt = r.stdout + r.stderr
    ab = len(re.findall(r"^\s*ABIERTA", txt, re.M))
    co = len(re.findall(r"^\s*CORTO", txt, re.M))
    return ab, co


def _pads_de_dos_nets():
    """Two Metal3 pads of DIFFERENT nets that are close, so they can be joined."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_connectivity import lef_pins, macro_size, place, read_def
    from def_to_gds import lef_origin

    inst, nets, units = read_def(DEF)
    lefs, sizes, orig = {}, {}, {}
    for p in (ROOT / "lef").glob("*.lef"):
        if p.name in ("vias.lef", "techlef_patched.tlef"):
            continue
        lefs[p.stem], sizes[p.stem], orig[p.stem] = (
            lef_pins(p), macro_size(p), lef_origin(p))

    points = []
    for net, pins in sorted(nets.items()):
        if net in ("VDD", "VSS"):
            continue
        for iname, pin in pins:
            if iname not in inst:
                continue
            cell, x, y, o = inst[iname]
            for r in lefs.get(cell, {}).get(pin, []):
                a = place(r, x / units, y / units, o, sizes[cell], orig[cell])
                points.append((net, (a[0] + a[2]) / 2, (a[1] + a[3]) / 2))
                break
            break
    #  The closest pair of different nets: the shorter the bridge, the less it
    #  parece a "he redibujado medio chip".
    mejor = None
    for i, (na, xa, ya) in enumerate(points):
        for nb, xb, yb in points[i + 1:]:
            if na == nb:
                continue
            d = abs(xa - xb) + abs(ya - yb)
            if mejor is None or d < mejor[0]:
                mejor = (d, (na, xa, ya), (nb, xb, yb))
    return mejor


def romper_corto(dst: Path):
    """Joins two nets with a Metal3 strip. **This breaks no DRC rule.**"""
    d, (na, xa, ya), (nb, xb, yb) = _pads_de_dos_nets()
    ly = kdb.Layout()
    ly.read(str(GDS))
    top = ly.top_cell()
    box = kdb.DBox(min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))
    box = box.enlarged(0.19, 0.19)
    top.shapes(ly.layer(*M3)).insert(box.to_itype(ly.dbu))
    ly.write(str(dst))
    return f"{na} and {nb} joined with Metal3 ({d:.1f} um bridge)"


def romper_abierto(dst: Path):
    """Deletes the Via2 in a window: cuts a net's climb to Metal3."""
    ly = kdb.Layout()
    ly.read(str(GDS))
    top = ly.top_cell()
    d, (na, xa, ya), _ = _pads_de_dos_nets()
    window = kdb.DBox(xa - 6, ya - 6, xa + 6, ya + 6).to_itype(ly.dbu)
    layer = ly.layer(*VIA2)
    fuera = [s for s in top.shapes(layer).each()
             if s.is_box() or s.is_polygon() or s.is_path()]
    n = 0
    for s in fuera:
        if window.contains(s.dbbox().center().to_itype(ly.dbu)):
            top.shapes(layer).erase(s)
            n += 1
    ly.write(str(dst))
    return f"{n} via2 deleted around {na} ({xa:.1f}, {ya:.1f})"


def romper_drc(dst: Path):
    """Mete Metal3 a 0.10 um de otro Metal3: `M3.2a` pide 0.28."""
    ly = kdb.Layout()
    ly.read(str(ROOT / "gds/COMP.gds"))
    top = ly.top_cell()
    layer = ly.layer(*M3)
    origen = next(s for s in top.shapes(layer).each() if s.is_box() or s.is_polygon())
    b = origen.dbbox()
    top.shapes(layer).insert(
        kdb.DBox(b.right + 0.10, b.bottom, b.right + 0.50, b.bottom + 0.40)
        .to_itype(ly.dbu))
    ly.write(str(dst))
    return f"Metal3 a 0.10 um de ({b.right:.2f}, {b.bottom:.2f}) en COMP"


def drc_limpio(gds: Path, cell: str) -> bool:
    """True if the KLayout DRC reports not one violation. Aborts if it did not run.

    The first version said "clean" when the deck **never even started** --
    `klayout` was not on PATH -- because it summed violations over zero files.
    This test exists precisely to catch that, so it began by catching itself.
    PATH must carry `/foss/tools/klayout`, and `PDK_ROOT` must be set: same as
    what `drc_klayout.py` does.
    """
    run = TMP / f"drc_{cell}"
    subprocess.run(["rm", "-rf", str(run)], check=False)
    run.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["python3", "/foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py",
         f"--path={gds}", "--variant=D", f"--topcell={cell}",
         f"--run_dir={run}", "--mp=4"],
        capture_output=True, text=True, check=False, timeout=14400,
        env={"PATH": "/foss/tools/klayout:/usr/bin:/bin",
             "HOME": "/tmp", "PDK_ROOT": "/foss/pdks"})
    dbs = list(run.glob("*.lyrdb"))
    if not dbs:
        sys.exit(f"DRC never ran on {gds} -- not one .lyrdb in {run}")
    return sum(len(re.findall(r"<item>", f.read_text(errors="replace")))
               for f in dbs) == 0


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    con_drc = "--con-drc" in sys.argv
    print("Baseline: the real layout\n")
    ab, co = conectividad(GDS)
    print(f"  connectivity on the good GDS: {ab} opens, {co} shorts"
          f"   {'OK' if (ab, co) == (0, 0) else 'OJO: ya venia roto'}\n")

    fallos = 0
    print("Ahora, roturas a proposito:\n")

    dst = TMP / "roto_corto.gds"
    print(f"  1. CORTO      {romper_corto(dst)}")
    ab, co = conectividad(dst)
    bien = co > 0
    print(f"     connectivity: {ab} opens, {co} shorts"
          f"      -> {'SEES IT' if bien else 'MISSES IT  <-- BAD'}")
    fallos += 0 if bien else 1

    dst = TMP / "roto_abierto.gds"
    print(f"  2. ABIERTO    {romper_abierto(dst)}")
    ab, co = conectividad(dst)
    bien = ab > 0
    print(f"     connectivity: {ab} opens, {co} shorts"
          f"      -> {'SEES IT' if bien else 'MISSES IT  <-- BAD'}")
    fallos += 0 if bien else 1

    if con_drc:
        dst = TMP / "roto_drc.gds"
        print(f"  3. DRC        {romper_drc(dst)}")
        bien = not drc_limpio(dst, "COMP")
        print(f"     DRC de KLayout sobre COMP roto: "
              f"{'SEES IT' if bien else 'MISSES IT  <-- BAD'}")
        fallos += 0 if bien else 1

        print("\n  And the control that says the most about all this:")
        clean = drc_limpio(TMP / "roto_corto.gds", "GRADIENT_NAV")
        print(f"     DRC on the GDS WITH THE SHORT: "
              f"{'clean' if clean else 'saca violaciones'}"
              f"   <- clean is EXPECTED: DRC does not see a short")
    else:
        print("\n  (--con-drc adds the two DRC tests)")

    print(f"\n{'every check reacts' if not fallos else str(fallos) + ' check(s) do NOT react'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
