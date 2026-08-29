#!/usr/bin/env python3
"""Files one version of the whole integrated area into integration/gds/.

    python3 scripts/archivar_integracion.py [--gds out_integration/B26_A.gds]
                                            [--nota "what changed"]

WHY A SCRIPT AND NOT A COPY. The point of the archive is to say which GDS passed
which check. A note written by hand drifts from the file beside it within a day,
and a version history that claims a clean DRC for a file that never had one is
worse than no history: it is the same failure as an LVS reference edited to
agree with the layout. So the verdicts are READ from the run directories the
tools actually wrote, and the file is hashed.

Each version gets `integration/gds/<date>_<nn>/` with the GDS gzipped -- 42.5 MB
each, and there is one per revision; `FINAL/.gitattributes` already declares
`*.gds.gz binary` -- plus a NOTAS.txt. One line per version goes into
`integration/HISTORIAL.txt`, newest first.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import glob
import gzip
import hashlib
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drc_klayout as dk                                          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
ARCHIVO = PROJECT / "integration" / "gds"
HISTORIAL = PROJECT / "integration" / "HISTORIAL.txt"


def veredicto_drc(run_dir: Path) -> str:
    """What the deck actually said, or why there is nothing to say."""
    if not run_dir.is_dir():
        return "not run"
    entero, porque = dk.completo(run_dir)
    if not entero:
        return f"INCOMPLETE -- {porque}"
    c = dk.counts(run_dir)
    if not c:
        return f"clean ({porque})"
    return (f"{sum(c.values())} violations: "
            + ", ".join(f"{k} x{v}" for k, v in c.most_common()))


def veredicto_lvs(run_dir: Path) -> str:
    log = run_dir / "run.log"
    if not log.exists():
        return "not run"
    t = log.read_text(errors="replace")
    if "Congratulations! Netlists match." in t:
        return "match"
    if "Netlists don't match" in t:
        return "NO MATCH"
    return "no verdict in run.log"


def densidad(gds: Path) -> str:
    """The seven density ratios, straight out of the deck's own log."""
    run = ROOT / "out" / f"density_{gds.stem.upper()}"
    logs = sorted(run.glob("drc_run_*.log")) if run.is_dir() else []
    if not logs:
        return "not run"
    filas = []
    for line in logs[-1].read_text(errors="replace").splitlines():
        if " ratio: " in line:
            capa, _, resto = line.split("|")[-1].strip().partition(" ratio: ")
            filas.append(f"{capa} {float(resto.split()[0]):.2f}%")
    return ", ".join(filas) if filas else "no ratios in the log"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gds", default="out_integration/B26_A.gds")
    ap.add_argument("--nota", default="")
    a = ap.parse_args()

    gds = (ROOT / a.gds).resolve()
    if not gds.exists():
        sys.exit(f"{gds} does not exist")

    hoy = datetime.date.today().isoformat()
    n = 1 + sum(1 for d in ARCHIVO.glob(f"{hoy}_*") if d.is_dir())
    dest = ARCHIVO / f"{hoy}_{n:02d}"
    dest.mkdir(parents=True)

    crudo = gds.read_bytes()
    sha = hashlib.sha256(crudo).hexdigest()
    with gzip.open(dest / (gds.name + ".gz"), "wb", compresslevel=9) as f:
        f.write(crudo)
    tam = (dest / (gds.name + ".gz")).stat().st_size

    #  The run directories of THIS cell, by the naming drc_klayout.py uses.
    cel = gds.stem.upper()
    notas = [
        f"{dest.name} -- {gds.name}",
        "=" * (len(dest.name) + len(gds.name) + 4),
        "",
        f"source      openroad/{a.gds}",
        f"written     {datetime.datetime.fromtimestamp(gds.stat().st_mtime):%Y-%m-%d %H:%M}",
        f"size        {len(crudo):,} bytes raw, {tam:,} gzipped",
        f"sha256      {sha}",
        "",
        f"DRC         {veredicto_drc(ROOT / 'out' / f'drc_{cel}')}",
        f"density     {densidad(gds)}",
        f"LVS         {veredicto_lvs(ROOT / 'out' / f'lvs_klayout_{cel}')}",
        "",
    ]
    if a.nota:
        notas += ["what changed", "------------", a.nota, ""]
    (dest / "NOTAS.txt").write_text("\n".join(notas) + "\n")

    linea = (f"{dest.name}  {gds.name:22s} "
             f"DRC {veredicto_drc(ROOT / 'out' / f'drc_{cel}')[:40]:40s} "
             f"LVS {veredicto_lvs(ROOT / 'out' / f'lvs_klayout_{cel}')}")
    viejo = HISTORIAL.read_text() if HISTORIAL.exists() else ""
    cabeza, _, cuerpo = viejo.partition("\n\n")
    HISTORIAL.write_text(f"{cabeza}\n\n{linea}\n{cuerpo}" if cabeza else linea + "\n")

    print(f"  {dest}")
    for l in notas[3:11]:
        print("  " + l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
