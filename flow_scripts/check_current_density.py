#!/usr/bin/env python3
"""Is every conductor thick enough for the current it carries?

    env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python \
        scripts/check_current_density.py [out_integration/B26_A_routed.def]

WHY THIS EXISTS. `integrate_top.tcl` sizes the power ring with the arithmetic
written in its own comments -- 14.81 mA measured on the RC-extracted block, the
PDK's mA/um table, 24 um of bus -- and then **nothing checks that the metal
actually came out that wide**. A comment is not a measurement: change `BUS_W`,
add a supply, let the router narrow a strap, and the reasoning stays there
looking correct while the copper underneath is not. DRC will not say a word:
electromigration is not a design rule, it is a current limit, and the DEF has no
idea how much current runs through anything.

So this reads the ROUTED DEF, measures what is drawn, and contrasts it with the
current each net has to carry. It fails with numbers -- "this run is 0.84 um and
needs 22.10" -- not with a yes or no.

WHAT THE NUMBERS ARE, and where they come from:

  * the block draws **14.81 mA at 5 V**, measured on the RC-extracted layout.
    That is the whole current of the user area, so it is what each supply ring
    has to carry.
  * the PDK's maximum line current density (Integration README, from the design
    manual), unidirectional:

        Metal1..Metal4   2.09 / 1.00 / 0.67 mA/um   at 85 / 110 / 125 C
        Via 0.26 um      0.58 / 0.28 / 0.18 mA per cut

    Sized at **125 C**, the column that assumes nothing about where this runs.

  * the seventeen signals carry next to nothing -- eight drive MOS gates and six
    a pad's data input -- so for them the rule is not electromigration but the
    flow's own minimum width, and that is what gets checked.

HOW THE SUPPLIES ARE JUDGED. Not by the narrowest segment: the narrowest bits
of VDD and VSS are the 48 tie-off stubs, 0.38 um leaves that hold a control pin
at a rail and carry none of the block's current.  What limits is how much copper
CROSSES a line between the edge, where the current comes in, and the block,
where it is spent -- so the die is cut in half on each axis and the widths of
everything crossing are added up.

WHAT IT DOES NOT DO. It does not simulate: there is no IR-drop solve here and no
per-branch current.  It bounds, it does not distribute. `analyze_power_grid` would give
the measured distribution instead of the bound; that is a different job.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Corriente del bloque, medida sobre el layout extraido con parasitos.
I_BLOQUE_MA = 14.81

#: mA por um de ancho, por capa y temperatura (unidireccional).
LIMITE_MA_UM = {85: {"Metal1": 2.09, "Metal2": 2.09, "Metal3": 2.09, "Metal4": 2.09},
                110: {"Metal1": 1.00, "Metal2": 1.00, "Metal3": 1.00, "Metal4": 1.00},
                125: {"Metal1": 0.67, "Metal2": 0.67, "Metal3": 0.67, "Metal4": 0.67}}
#: Y mA por corte de via de 0.26 um.
LIMITE_MA_VIA = {85: 0.58, 110: 0.28, 125: 0.18}

#: La temperatura a la que se dimensiona. La mas exigente.
T = 125

#: El lado del area de usuario, para cortarla por la mitad.
SIDE_UM = 1110.0

#: Ancho minimo que el flujo promete para una senal (`create_ndr ANCHO_INT`).
MIN_SENAL = {"Metal2": 0.38, "Metal3": 0.84, "Metal4": 0.84}


def lee_def(path: Path):
    """(unidades, {net: [(capa, ancho_um, largo_um)]}, {net: cortes_de_via})."""
    txt = path.read_text()
    u = float(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))
    ndr = {}
    for m in re.finditer(r"- (\S+)\s+\+ NONDEFAULTRULE (\S+)", txt):
        ndr[m.group(1)] = m.group(2)
    #  Los anchos por regla no por defecto, de la propia definicion del DEF.
    anchos = {}
    for m in re.finditer(r"- (\S+)\s*\n((?:\s*\+ LAYER \S+ WIDTH \d+\s*\n)+)",
                         txt[txt.index("NONDEFAULTRULES") if "NONDEFAULTRULES" in txt
                             else 0:]):
        for mm in re.finditer(r"\+ LAYER (\S+) WIDTH (\d+)", m.group(2)):
            anchos[(m.group(1), mm.group(1))] = int(mm.group(2)) / u
    return u, ndr, anchos


def tramos_special(txt: str, u: float):
    """Los STRIPE de las nets `special`: (net, capa, ancho, x0, y0, x1, y1), en um.

    Son los anillos de alimentacion. En el DEF van como `SPECIALNETS`, con el
    ancho ESCRITO en la propia sentencia, que es lo que hay que medir.
    """
    if "SPECIALNETS" not in txt:
        return []
    blk = txt[txt.index("SPECIALNETS"):txt.index("END SPECIALNETS")]
    out, net = [], None
    for m in re.finditer(r"^\s*- (\S+)|(\S+)\s+(\d+)\s*\+ SHAPE\s+\S+\s*"
                         r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*([-\d*]+)\s+([-\d*]+)\s*\)",
                         blk, re.M):
        if m.group(1):
            net = m.group(1)
            continue
        if net is None:
            continue
        capa, w = m.group(2), int(m.group(3)) / u
        x0, y0 = int(m.group(4)) / u, int(m.group(5)) / u
        x1 = x0 if m.group(6) == "*" else int(m.group(6)) / u
        y1 = y0 if m.group(7) == "*" else int(m.group(7)) / u
        out.append((net, capa, w, x0, y0, x1, y1))
    return out


def main() -> int:
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "out_integration" / "B26_A_routed.def"
    if not d.exists():
        sys.exit(f"no hay DEF en {d}")
    txt = d.read_text()
    u = float(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))

    print(f"  {d.name}, a {T} C, con los {I_BLOQUE_MA} mA del bloque\n")

    #  --- los anillos de alimentacion --------------------------------------
    tr = tramos_special(txt, u)
    if not tr:
        print("  AVISO: el DEF no trae SPECIALNETS; no hay anillos que medir")
    fallos = 0
    por_net = {}
    for net, capa, w, x0, y0, x1, y1 in tr:
        por_net.setdefault(net, []).append((capa, w, x0, y0, x1, y1))

    #  LA SECCION QUE CRUZA UN CORTE, no el tramo mas estrecho de la net.
    #
    #  Tomar el minimo daba 0.38 um y suspendia las dos alimentaciones -- pero
    #  esos 0.38 son los STUBS DE LOS 48 TIE-OFFS, hojas que atan un pin de
    #  control a su riel y por las que no pasa la corriente del bloque. La malla
    #  no se estrangula en una hoja.
    #
    #  Lo que de verdad limita es cuanto cobre cruza una linea entre el borde,
    #  de donde viene la corriente, y el bloque, que es donde se consume. Asi
    #  que se corta el die por la mitad en cada eje y se suma el ancho de todo
    #  lo que lo atraviesa.
    corte = SIDE_UM / 2.0
    print("  alimentacion: seccion de cobre que cruza el centro del die")
    for net, lst in sorted(por_net.items()):
        secc = {"vertical": 0.0, "horizontal": 0.0}
        for capa, w, x0, y0, x1, y1 in lst:
            #  una barra que cruza la linea y=corte lleva corriente VERTICAL, y
            #  aporta su ancho en x; y al reves.
            if min(y0, y1) - w / 2 <= corte <= max(y0, y1) + w / 2 and abs(y1 - y0) > w:
                secc["vertical"] += w
            if min(x0, x1) - w / 2 <= corte <= max(x0, x1) + w / 2 and abs(x1 - x0) > w:
                secc["horizontal"] += w
        pide = I_BLOQUE_MA / LIMITE_MA_UM[T]["Metal4"]
        for sentido, s in secc.items():
            ok = s >= pide
            fallos += 0 if ok else 1
            print(f"    {net:4s} {sentido:10s} {s:7.2f} um de seccion -- "
                  f"pide {pide:5.2f}   {'OK' if ok else 'CORTO'}")
        print(f"         ({len(lst)} tramos en total, stubs de tie-off incluidos)")

    #  --- las senales -------------------------------------------------------
    #  No es electromigracion: ocho atacan puertas MOS y seis la entrada de dato
    #  de un pad. Lo que se comprueba es el ancho que el flujo promete.
    reglas = {}
    if "NONDEFAULTRULES" in txt:
        blq = txt[txt.index("NONDEFAULTRULES"):txt.index("END NONDEFAULTRULES")]
        #  `[^\n]*` al final: las lineas de Metal2..Metal4 llevan ademas `SPACING`,
        #  y sin eso la repeticion se cortaba en la primera y solo se leian dos
        #  capas de las cinco.
        for m in re.finditer(r"- (\S+)((?:\s*\+ LAYER \S+ WIDTH \d+[^\n]*)+)", blq):
            for mm in re.finditer(r"\+ LAYER (\S+) WIDTH (\d+)", m.group(2)):
                reglas.setdefault(m.group(1), {})[mm.group(1)] = int(mm.group(2)) / u
    print("\n  reglas de ancho de las senales")
    if not reglas:
        print("    AVISO: el DEF no declara NONDEFAULTRULES")
        fallos += 1
    for nombre, capas in sorted(reglas.items()):
        for capa, w in sorted(capas.items()):
            minimo = MIN_SENAL.get(capa)
            ok = minimo is None or w >= minimo
            fallos += 0 if ok else 1
            extra = "" if minimo is None else f" (el flujo promete {minimo})"
            print(f"    {nombre:10s} {capa:7s} {w:5.2f} um{extra}   "
                  f"{'OK' if ok else 'CORTO'}")

    #  --- cuantas vias hacen falta -----------------------------------------
    cortes = int(I_BLOQUE_MA / LIMITE_MA_VIA[T] + 0.999)
    print(f"\n  vias: {I_BLOQUE_MA} mA a {LIMITE_MA_VIA[T]} mA por corte "
          f"-> hacen falta {cortes} cortes por camino de alimentacion")

    print()
    if fallos:
        print(f"  {fallos} conductor(es) por debajo de lo que piden")
        return 1
    print("  todos los conductores dan la corriente que tienen que dar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
