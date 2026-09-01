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

#: MODO Y HEBRAS. En paralelo el deck se come la maquina con un GDS RELLENO:
#: en `B26_A_filled.gds` seis tablas -- dnwell, nwell, lvpwell, nat, ldnmos y
#: ldpmos -- murieron con **exit 137**, que es SIGKILL por falta de memoria. Y
#: una tabla que muere NO ESCRIBE `.lyrdb`, asi que contando solo los ficheros
#: que hay, un run reventado se lee como limpio; quien lo canta es
#: `completo()`, no el recuento.
#:
#: `DRC_MODE=deep DRC_THR=1 DRC_MP=1` corre una tabla cada vez y cabe de sobra
#: -- medido, 508 MB de pico contra los 7 GB de la maquina. Es mucho mas lento
#: y es lo que hay que usar sobre el fichero relleno.
MODE = os.environ.get("DRC_MODE", "")
THR = os.environ.get("DRC_THR", "")

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
    #  The delivery pointer. Byte-identical to `_filled`, renamed so that the
    #  file named in `lvs_config.json` is the file the evidence is filed under:
    #  `archivar_integracion.py` looks for `out/drc_<CELL>` and reports
    #  `not run` when the name it is given has no run directory of its own.
    #  A copy under a new name is how this project marks a verified delivery --
    #  `_filled2` was the same act -- and each one needs its target here.
    f"{TOP}_FILLED3": OUT / f"{TOP}_filled3.gds",
}


#: The filled GDS keeps the cell name of the original.
TOPCELL = {f"{TOP}_FILLED": TOP, f"{TOP}_FILLED3": TOP, f"{TOP}_DECAP": TOP}


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
        #  Si la UNICA que reventó es `mslot` se sigue mirando la cuenta antes de
        #  contestar: un run que ademas se quedo a medias tiene que salir como
        #  incompleto y no como "solo mslot". Paso -- un run matado a las 48
        #  tablas de 63 se leyo como limpio porque el mensaje de mslot llegaba
        #  primero.
        if cuales != "mslot" or escritos < lanzados - 1:
            return False, f"{len(errores)} table(s) raised: {cuales}"
    if not escritos:
        return False, f"no .lyrdb in {run_dir}"
    if escritos < lanzados:
        return False, f"only {escritos} .lyrdb of {lanzados} tables started"
    return True, f"{escritos} tables"


#: Anchura maxima de metal sin ranurar (`MSLOT.1`). Por encima de esto la regla
#: pide slots; por debajo, no aplica y no hay nada que dibujar.
MSLOT_MAX = 30.0

#: Los metales que `MSLOT.1` mira, con su capa GDS y las VIAS de debajo y de
#: encima -- que hay que restarles, porque el deck lo hace:
#:
#:     metal_slotted = metal_drawn - metal_slot - dont_slot
#:                     - via_below.sized(0.2) - via_above.sized(0.2)
#:
#: No es un detalle. Una placa grande cosida a matrices de vias no se ranura: la
#: via ya cumple la funcion. Sin restarlas, esta comprobacion cantaba 51
#: violaciones sobre el area integrada, todas dentro de la celda de ESD de los
#: organizadores, que es justo una placa ancha llena de vias.
_MSLOT_CAPAS = [("Metal1", 34, 33, 35), ("Metal2", 36, 35, 38),
                ("Metal3", 42, 38, 40), ("Metal4", 46, 40, 41),
                ("Metal5", 81, 41, None)]


def mslot1_local(gds: Path, topcell: str) -> tuple[int, str]:
    """`MSLOT.1` comprobada aqui, porque la tabla del PDK **no arranca**.

    `rule_decks/mslot.drc:470` hace

        metal_slotted = metal_drawn - metal_slot - dont_slot
                        - via_below.sized(0.2) - via_above.sized(0.2)

    y para metal1 `via_below` es `contact`, que en ese fichero llega **nil**:
    `undefined method 'sized' for nil:NilClass`, en la primera vuelta del bucle.
    No depende del diseno -- revienta igual en COMP, en DECODER y en
    WEIGHT_COMP --, asi que sin esto NINGUNA celda puede salir completa nunca.
    Es un fallo del deck del PDK y hay que reportarlo aguas arriba.

    Saltarsela sin mas seria justo lo que el resto de este fichero existe para
    evitar, asi que se comprueba con la misma morfologia que usa el deck: erosion
    de 15 um en cada eje y dilatacion de vuelta deja SOLO lo que mide mas de
    30 um en las dos direcciones, que es exactamente lo que la regla prohibe sin
    ranurar. Las otras tres (`MSLOT.0`, `.2`, `.3`) solo miden slots ya
    dibujados; sin un solo poligono en las capas de slot no tienen nada que
    decir.
    """
    import klayout.db as kdb
    ly = kdb.Layout()
    ly.read(str(gds))
    cell = ly.cell(topcell) or ly.top_cell()
    #  `Region.sized` va en UNIDADES DE LA BASE DE DATOS, no en nanometros. Los
    #  GDS de bloque estan a 1 nm y los que salen de un DEF a 0.5 nm, asi que dar
    #  el numero en nm mide la MITAD en estos ultimos: se comprobaba 15 um en vez
    #  de 30 y salian 51 violaciones que no lo eran.
    def um(v):
        return int(round(v / ly.dbu))
    malas = []
    for nombre, capa, v_abajo, v_arriba in _MSLOT_CAPAS:
        idx = ly.layer(capa, 0)
        reg = kdb.Region(cell.begin_shapes_rec(idx))
        #  El dummy de relleno (datatype 4) cuenta como metal para el deck, asi
        #  que tambien aqui.
        reg += kdb.Region(cell.begin_shapes_rec(ly.layer(capa, 4)))
        reg.merge()
        for v in (v_abajo, v_arriba):
            if v is None:
                continue
            vr = kdb.Region(cell.begin_shapes_rec(ly.layer(v, 0)))
            if not vr.is_empty():
                reg -= vr.sized(um(0.2))      # 0.2 um, como el deck
        reg.merge()
        if reg.is_empty():
            continue
        h = um(MSLOT_MAX / 2)
        ancho = reg.sized(0, -h).sized(-h, 0).sized(0, h).sized(h, 0)
        if not ancho.is_empty():
            malas.append(f"{nombre} x{ancho.count()}")
    if malas:
        return len(malas), "MSLOT.1: " + ", ".join(malas)
    return 0, f"MSLOT.1 comprobada aqui ({len(_MSLOT_CAPAS)} metales, ninguno >{MSLOT_MAX:.0f} um)"


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
            + ([f"--run_mode={MODE}"] if MODE else [])
            + ([f"--thr={THR}"] if THR else [])
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
        #  `mslot` revienta SIEMPRE, por un fallo del deck del PDK y no del
        #  diseno (ver `mslot1_local`). Si es la unica que ha caido, se comprueba
        #  su regla aqui y se sigue; si ha caido alguna mas, no.
        if not entero and porque.endswith("table(s) raised: mslot"):
            n_ms, detalle = mslot1_local(gds.resolve(), TOPCELL.get(name, name))
            if n_ms:
                print(f"  {name:14s} {detalle}")
                bad += 1
                continue
            entero, porque = True, f"{porque.split(' table')[0]} tables + {detalle}"
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
