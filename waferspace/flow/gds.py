#!/usr/bin/env python3
"""Convierte el DEF del estudio en un GDS que se puede abrir.

Este OpenROAD no tiene `write_gds` -- su lista de `write_*` acaba en
`write_verilog` -- asi que el stream-out lo hace KLayout, que lee DEF y sabe
sustituir el abstracto de cada macro por el GDS del que se abstrajo.

**Esa sustitucion es todo el asunto.** Sin ella los pads y el bloque salen como
sus contornos de LEF: un chip con forma de chip, con pines y sin un solo
transistor, que en una captura de pantalla parece correcto y no vale nada.

    python3 flow/gds.py [out/quarter.def [out/quarter.gds]]

Hermano de `openroad/scripts/def_to_gds.py`, del que copia el planteamiento. No
se reutiliza aquel porque tiene cableadas las rutas del arbol del Chipathon
(`openroad/lef`, `openroad/gds`) y aqui las celdas son las del padring del PDK
propio de este proyecto.
"""

from __future__ import annotations

import sys
from pathlib import Path

import klayout.db as kdb

WS = Path(__file__).resolve().parent.parent          # waferspace/
PROYECTO = WS.parent
OPENROAD = PROYECTO / "openroad"
PDK = WS / "gf180mcu/gf180mcuD"
SC = "gf180mcu_fd_sc_mcu7t5v0"
IO = "gf180mcu_fd_io"
MAPA = PDK / "libs.tech/klayout/tech/gf180mcu.map"
MACRO = "GRADIENT_NAV2_V3"


def dbu_del_def(path: Path) -> float:
    """El DEF manda en la precision. Dejado en el nanometro por defecto,
    KLayout avisa y redondea cada coordenada de un DEF escrito a 0.5 nm."""
    for line in path.read_text().splitlines():
        if line.startswith("UNITS DISTANCE MICRONS"):
            return 1.0 / float(line.split()[3])
        if line.startswith("COMPONENTS"):
            break
    return 0.0005


def main() -> int:
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else WS / "out/quarter.def"
    g = Path(sys.argv[2]) if len(sys.argv) > 2 else d.with_suffix(".gds")
    if not d.exists():
        sys.exit(f"no hay DEF en {d} — corre antes flow/floorplan.tcl")

    lefs = [PDK / f"libs.ref/{SC}/techlef/{SC}__nom.tlef",
            PDK / f"libs.ref/{SC}/lef/{SC}.lef",
            Path(__file__).resolve().parent / "pad_sites.lef",
            *sorted((PDK / f"libs.ref/{IO}/lef").glob("*.lef")),
            OPENROAD / "lef" / f"{MACRO}.lef",
            OPENROAD / "lef/ESD_CDM.lef",
            #  Sin esto KLayout avisa `Invalid via name: Via3_SQ` -- un AVISO,
            #  no un error -- y escribe el GDS SIN las vias de alimentacion.
            #  Miles de cortes que desaparecen sin que nada falle.
            OPENROAD / "lef/vias.lef"]

    #  El GDS del bloque es el enlace de ip/, que apunta al de `openroad/`. Una
    #  copia propia aqui es como un banco acaba simulando una celda de hace
    #  semanas sin que nadie lo note.
    gdss = [PDK / f"libs.ref/{IO}/gds/gf180mcu_fd_io.gds",
            PDK / f"libs.ref/{IO}/gds/gf180mcu_ef_io.gds",
            WS / "ip/gradient_nav2_v3/gds" / f"{MACRO}.gds"]

    faltan = [p for p in lefs + gdss if not p.resolve().exists()]
    if faltan:
        sys.exit("faltan ficheros:\n  " + "\n  ".join(str(p) for p in faltan))

    opts = kdb.LoadLayoutOptions()
    cfg = opts.lefdef_config
    cfg.map_file = str(MAPA)
    cfg.lef_files = [str(p) for p in lefs]
    #  2 = no dibujes NUNCA el abstracto del LEF de un MACRO, coge siempre la
    #  geometria de los layouts de abajo. El modo 1 hace lo contrario y es la
    #  trampa por defecto: lee los GDS, los ignora y escribe contornos.
    cfg.macro_resolution_mode = 2
    cfg.macro_layout_files = [str(p) for p in gdss]
    cfg.dbu = dbu_del_def(d)

    layout = kdb.Layout()
    layout.read(str(d), opts)
    top = layout.top_cell()

    caja = top.dbbox()
    celdas = layout.cells()
    formas = sum(top.shapes(i).size() for i in layout.layer_indexes())
    print(f"  celda superior : {top.name}")
    print(f"  extension      : {caja.width():.1f} x {caja.height():.1f} um")
    print(f"  instancias     : {top.child_instances()}")
    print(f"  celdas         : {celdas}")
    print(f"  capas con algo : {sum(1 for i in layout.layer_indexes() if not layout.begin_shapes(top, i).at_end())}")

    #  Un GDS de contornos pesa unos pocos kB y uno con geometria real, megas.
    #  Si esto sale pequeno, la sustitucion no ocurrio.
    g.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(g))
    mb = g.stat().st_size / 1e6
    print(f"  escrito        : {g}  ({mb:.1f} MB)")
    if mb < 1.0:
        print("\n  AVISO: pesa menos de 1 MB. Eso es un GDS de contornos, no de")
        print("  geometria: la sustitucion de macros no ha ocurrido.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
