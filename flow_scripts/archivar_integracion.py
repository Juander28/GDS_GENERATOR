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


def veredicto_drc(run_dir: Path, gds: Path | None = None) -> str:
    """What the deck actually said, or why there is nothing to say.

    **Y sobre QUE fichero lo dijo.** Un directorio de ejecucion mas viejo que el
    GDS es un veredicto sobre otra cosa. Paso aqui: `out/drc_B26_A_FILLED` era de
    las 16:54 y el GDS de las 22:39 -- casi seis horas antes, y ademas de un run
    que se mato a las 48 tablas -- y este archivo lo anoto como `clean`. Un
    historico que atribuye a una version el DRC de otra es peor que no tenerlo.
    """
    if not run_dir.is_dir():
        return "not run"
    if gds is not None and run_dir.stat().st_mtime < gds.stat().st_mtime:
        return "STALE -- the run predates this GDS"
    entero, porque = dk.completo(run_dir)
    #  `mslot` revienta SIEMPRE, por un fallo del deck del PDK y no del diseno,
    #  y `drc_klayout` ya lo trata comprobando `MSLOT.1` por su cuenta. Si el
    #  archivo no hace lo mismo, anota "INCOMPLETE" en una version que en
    #  realidad esta limpia -- y un historico que subestima es tan inutil como
    #  uno que exagera.
    if not entero and porque.endswith("table(s) raised: mslot"):
        porque = porque.replace("1 table(s) raised: mslot",
                                "mslot lo comprueba drc_klayout")
        entero = True
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


def veredicto_netgen(cell: str) -> str:
    """Lo que dijo netgen, que es el motor independiente.

    Sin esto el archivo registraba SOLO el LVS de KLayout y se quedaba corto por
    omision: en `B26_A` el deck de KLayout no casa y netgen si -- `Circuits match
    uniquely`, con 1442 dispositivos y 894 nets identicos en los dos lados. Un
    historico que anota una de las dos y calla la otra es exactamente la clase de
    registro que este fichero existe para evitar.
    """
    rpt = ROOT / "out_integration" / f"lvs_netgen_{cell}.rpt"
    if not rpt.exists():
        return "not run"
    t = rpt.read_text(errors="replace")
    if "Circuits match uniquely" in t:
        return "match uniquely"
    if "Netlists match" in t:
        return "match"
    if "Netlists do not match" in t:
        return "NO MATCH"
    return "no verdict in the report"


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
    if filas:
        return ", ".join(filas)
    #  El deck solo imprime los ratios en modo verbose. Sin ellos, lo que
    #  importa igual: si la pasada de densidad encontro algo o no.
    entero, porque = dk.completo(run)
    if not entero:
        return f"INCOMPLETE -- {porque}"
    c = dk.counts(run)
    return "clean" if not c else (f"{sum(c.values())} violations: "
                                  + ", ".join(f"{k} x{v}" for k, v in c.most_common()))


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
    #  El GDS sin rellenar del que sale este, para fechar su DRC contra el suyo.
    sin_relleno = gds.with_name(gds.name.replace("_filled", ""))
    if not sin_relleno.exists():
        sin_relleno = gds
    notas = [
        f"{dest.name} -- {gds.name}",
        "=" * (len(dest.name) + len(gds.name) + 4),
        "",
        f"source      openroad/{a.gds}",
        f"written     {datetime.datetime.fromtimestamp(gds.stat().st_mtime):%Y-%m-%d %H:%M}",
        f"size        {len(crudo):,} bytes raw, {tam:,} gzipped",
        f"sha256      {sha}",
        "",
        #  Las dos: el circuito se firma sobre el GDS SIN rellenar y la
        #  densidad sobre el relleno. Anotar solo una deja media verdad.
        f"DRC filled  {veredicto_drc(ROOT / 'out' / f'drc_{cel}', gds)}",
        #  Y cada uno contra SU fichero: el del circuito corrio sobre el GDS sin
        #  rellenar, asi que compararlo con la fecha del relleno lo daria por
        #  caducado sin serlo.
        f"DRC circuit {veredicto_drc(ROOT / 'out' / ('drc_' + cel.split('_FILLED')[0]), sin_relleno)}",
        f"density     {densidad(gds)}",
        f"LVS klayout {veredicto_lvs(ROOT / 'out' / f'lvs_klayout_{cel}')}",
        f"LVS netgen  {veredicto_netgen(gds.stem.split('_filled')[0])}",
        "",
    ]
    if a.nota:
        notas += ["what changed", "------------", a.nota, ""]
    (dest / "NOTAS.txt").write_text("\n".join(notas) + "\n")

    linea = (f"{dest.name}  {gds.name:22s} "
             f"DRC {veredicto_drc(ROOT / 'out' / ('drc_' + cel.split('_FILLED')[0]), sin_relleno)[:34]:34s} "
             f"dens {densidad(gds)[:22]:22s} "
             f"LVS netgen {veredicto_netgen(gds.stem.split('_filled')[0]):16s} "
             f"klayout {veredicto_lvs(ROOT / 'out' / f'lvs_klayout_{cel}')}")
    viejo = HISTORIAL.read_text() if HISTORIAL.exists() else ""
    cabeza, _, cuerpo = viejo.partition("\n\n")
    HISTORIAL.write_text(f"{cabeza}\n\n{linea}\n{cuerpo}" if cabeza else linea + "\n")

    print(f"  {dest}")
    for l in notas[3:11]:
        print("  " + l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
