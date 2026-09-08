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

  * the block draws **15.50 mA of peak at 5 V**, measured on the RC-extracted
    layout, and the supply is sized for **double**: 31 mA. The sizing current is
    an ARGUMENT, not a constant in this file -- see `sys.argv[2]`.
  * the limits come from the **PDK's tech-LEF**, read at run time by
    `limites_del_pdk()`, as `DCCURRENTDENSITY AVERAGE`:

        Metal1..Metal4   0.67 mA per um of width
        Metal5           1.5  mA per um
        Via1..Via4       0.18 mA per cut

    They do **NOT depend on temperature**: the three corners carry identical
    numbers. What an earlier version of this file called
    "2.09 / 1.00 / 0.67 at 85 / 110 / 125 C" was the AC and the DC figure of
    the same layer misread as three temperatures; the DC one is what applies to
    a continuous supply, and it is the one that ended up being used.

  * the seventeen signals carry next to nothing -- eight drive MOS gates and six
    a pad's data input -- so for them the rule is not electromigration but the
    flow's own minimum width, and that is what gets checked.

HOW THE SUPPLIES ARE JUDGED. Not by the narrowest segment: the narrowest bits
of VDD and VSS are the 48 tie-off stubs, 0.38 um leaves that hold a control pin
at a rail and carry none of the block's current.  What limits is how much copper
CROSSES a line between the edge, where the current comes in, and the block,
where it is spent -- so a line is swept along each axis and the widths of
everything crossing it are added up.

AND THE CUT IS THE WORST ONE, NOT THE MIDDLE. It used to cut at
`max(width, height) / 2`, which on a rectangular die is the centre of neither
axis: it landed somewhere lucky and reported 30.15 mA of VSS where the worst
real cut carried 16. A bound that depends on where you look is not a bound.

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

#: LOS LIMITES SALEN DEL PDK, NO DE AQUI.
#:
#: Estan en los tech-LEF como `DCCURRENTDENSITY AVERAGE`, en mA por um de ancho
#: para las capas de ruteo y en mA por corte para las de via. NO dependen de la
#: temperatura: los tres corners (min/nom/max) traen los mismos numeros, y lo
#: que se leia como "85 / 110 / 125 C" en la version anterior de este fichero
#: eran en realidad AC y DC de la misma capa. El valor DC es el que vale para
#: una alimentacion continua, y por suerte es el que se acabo usando.
#:
#: Ninguna regla del DRC comprueba esto. Por eso existe este script.
TECHLEF = Path("/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/"
               "techlef/gf180mcu_fd_sc_mcu9t5v0__max.tlef")


def limites_del_pdk(f: Path = TECHLEF):
    """`DCCURRENTDENSITY AVERAGE` por capa, leido del tech-LEF."""
    if not f.exists():
        sys.exit(f"no encuentro el tech-LEF en {f}; sin el no hay limites que aplicar")
    lim, capa = {}, None
    for ln in f.read_text().splitlines():
        s = ln.strip()
        if s.startswith("LAYER "):
            capa = s.split()[1]
        elif s.startswith("DCCURRENTDENSITY AVERAGE") and capa:
            lim[capa] = float(s.split()[2].rstrip(";"))
    return lim


LIMITES = limites_del_pdk()
#: Las vias declaran su densidad por CORTE, no por micra.
LIMITE_MA_VIA = LIMITES.get("Via4", 0.18)

#: El lado por el que se corta el die. Se LEE del DEF (`DIEAREA`), no se cablea:
#: con 1110.0 fijo, sobre el DEF de un bloque el corte caia fuera y el script
#: devolvia ceros con cara de fallo.

#: Ancho minimo que el flujo promete para una senal (`create_ndr ANCHO_INT`).
#: Cada nivel promete lo suyo, y son reglas DISTINTAS. `ANCHO` es la del
#: bloque y `ANCHO_INT` la de la integracion; aplicarle al bloque la promesa de
#: la integracion suspendia dos capas que estaban en su ancho correcto.
MIN_SENAL = {"ANCHO":     {"Metal2": 0.38, "Metal3": 0.38, "Metal4": 0.38},
             "ANCHO_INT": {"Metal2": 0.38, "Metal3": 0.84, "Metal4": 0.84}}


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
    #  La corriente de dimensionado, por argumento. Sin el, la que trae el
    #  fichero, que es la del navegador v1 y se ha quedado corta.
    corriente = float(sys.argv[2]) if len(sys.argv) > 2 else I_BLOQUE_MA
    txt = d.read_text()
    u = float(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))

    #  El die, del propio DEF.
    da = re.search(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
                   r"\(\s*(-?\d+)\s+(-?\d+)\s*\)", txt)
    if not da:
        sys.exit(f"{d.name}: no encuentro DIEAREA")
    dw = (int(da.group(3)) - int(da.group(1))) / u
    dh = (int(da.group(4)) - int(da.group(2))) / u
    global SIDE_UM
    SIDE_UM = max(dw, dh)

    print(f"  {d.name}   die {dw:.2f} x {dh:.2f} um   dimensionado a "
          f"{corriente:.2f} mA")
    print(f"  limites del PDK (DC, del tech-LEF): "
          f"Metal1-4 {LIMITES['Metal4']} mA/um, Metal5 {LIMITES['Metal5']}, "
          f"vias {LIMITE_MA_VIA} mA/corte\n")

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
    print("  alimentacion: seccion de cobre en el PEOR corte de cada eje")
    #  SE SUMA CORRIENTE, NO ANCHO. Una micra de Metal5 lleva 1.5 mA y una de
    #  Metal4 lleva 0.67: sumar micras y compararlas con un unico limite
    #  suspendia mallas que van sobradas solo por estar en la capa buena.
    #  Y EL CORTE ES EL PEOR, NO EL DEL MEDIO. Antes se cortaba en
    #  `max(ancho, alto) / 2`, que sobre un die rectangular no es el centro de
    #  ningun eje: caia en un sitio afortunado y daba 30.15 mA de VSS vertical
    #  donde el peor corte real llevaba 16. Un limite que depende de donde se
    #  mire no es un limite, asi que ahora se barre.
    #
    #  Se barre solo DENTRO DEL VANO DE LA NET, entre su primer y su ultimo
    #  alimentador transversal: mas alla no hay que llevar corriente porque no
    #  hay de donde cogerla ni donde gastarla, y contar esos cortes daria cero
    #  sobre metal que no tiene por que existir.
    for net, lst in sorted(por_net.items()):
        cap = {}
        anc = {}
        for sentido in ("vertical", "horizontal"):
            #  las barras que llevan corriente en este sentido...
            largo = [s for s in lst
                     if abs((s[5] - s[3]) if sentido == "vertical"
                            else (s[4] - s[2])) > s[1]]
            #  ...y las TRANSVERSALES, que son las que la meten y la sacan.
            cruz = [s for s in lst if s not in largo and LIMITES.get(s[0])]
            if not largo or not cruz:
                cap[sentido], anc[sentido] = 0.0, 0.0
                continue
            #  Un tramo es (capa, ancho, x0, y0, x1, y1). El alimentador
            #  transversal de la malla VERTICAL es una barra horizontal, y lo
            #  que la situa es su Y -- no su X, que era lo que se leia aqui y
            #  ponia el peor corte en 369 um sobre un die de 387 de alto.
            pos = [(s[3] if sentido == "vertical" else s[2]) for s in cruz]
            lo, hi = min(pos), max(pos)
            peor, peor_c, peor_a = None, 0.0, 0.0
            n = max(2, int((hi - lo) / 0.5))
            for i in range(n + 1):
                c = lo + (hi - lo) * i / n
                tc = ta = 0.0
                for capa, w, x0, y0, x1, y1 in largo:
                    lim = LIMITES.get(capa)
                    if lim is None:
                        continue          # vias y capas sin densidad declarada
                    a, b = (y0, y1) if sentido == "vertical" else (x0, x1)
                    if min(a, b) - w / 2 <= c <= max(a, b) + w / 2:
                        tc += w * lim
                        ta += w
                if peor is None or tc < peor_c:
                    peor, peor_c, peor_a = c, tc, ta
            cap[sentido], anc[sentido] = peor_c, peor_a
            cap[sentido + "_y"] = peor
        for sentido in ("vertical", "horizontal"):
            ok = cap[sentido] >= corriente
            fallos += 0 if ok else 1
            donde = cap.get(sentido + "_y")
            print(f"    {net:4s} {sentido:10s} {anc[sentido]:6.2f} um -> "
                  f"{cap[sentido]:6.2f} mA -- pide {corriente:5.2f}   "
                  f"{'OK' if ok else 'CORTO'}"
                  + (f"   (peor corte en {donde:.1f} um)" if donde is not None else ""))
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
            minimo = MIN_SENAL.get(nombre, {}).get(capa)
            ok = minimo is None or w >= minimo
            fallos += 0 if ok else 1
            extra = "" if minimo is None else f" (el flujo promete {minimo})"
            print(f"    {nombre:10s} {capa:7s} {w:5.2f} um{extra}   "
                  f"{'OK' if ok else 'CORTO'}")

    #  --- las vias que HAY, no solo las que harian falta --------------------
    #  Cada `- viaX_Y_..._R_C_...` del bloque VIAS declara su `ROWCOL R C`, o
    #  sea cuantos cortes lleva. Contar instancias sin mirar eso subestima por
    #  un factor de doce.
    cortes_de = {}
    if "VIAS " in txt and "END VIAS" in txt:
        blq = txt[txt.index("VIAS "):txt.index("END VIAS")]
        for m in re.finditer(r"- (\S+).*?LAYERS (\S+) \S+ (\S+).*?ROWCOL (\d+) (\d+)",
                             blq, re.S):
            cortes_de[m.group(1)] = (f"{m.group(2)}-{m.group(3)}",
                                     int(m.group(4)) * int(m.group(5)))
    if cortes_de and "SPECIALNETS" in txt:
        sn = txt[txt.index("SPECIALNETS"):txt.index("END SPECIALNETS")]
        cuenta, net = {}, None
        for ln in sn.splitlines():
            s = ln.strip()
            if s.startswith("- "):
                net = s.split()[1]
            for v, (par, n) in cortes_de.items():
                if v in s and net:
                    d = cuenta.setdefault(net, {})
                    d[par] = d.get(par, 0) + n
        print("\n  vias de alimentacion que hay, en cortes")
        for net in sorted(cuenta):
            for par, n in sorted(cuenta[net].items()):
                cap = n * LIMITE_MA_VIA
                ok = cap >= corriente
                fallos += 0 if ok else 1
                print(f"    {net:4s} {par:14s} {n:5d} cortes -> {cap:7.2f} mA"
                      f" -- pide {corriente:5.2f}   {'OK' if ok else 'CORTO'}")

    #  --- cuantas vias hacen falta -----------------------------------------
    cortes = int(corriente / LIMITE_MA_VIA + 0.999)
    print(f"\n  vias: {corriente} mA a {LIMITE_MA_VIA} mA por corte "
          f"-> hacen falta {cortes} cortes por camino de alimentacion")

    print()
    if fallos:
        print(f"  {fallos} conductor(es) por debajo de lo que piden")
        return 1
    print("  todos los conductores dan la corriente que tienen que dar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
