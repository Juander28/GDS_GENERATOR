"""Condensadores MIM, colocados ENCIMA del array cuando ya esta ruteado.

El array vive en metal1/metal2 y deja metal3, metal4 y metal5 completamente
vacios. El MIM de la variante D va justo ahi (placa inferior en metal4, placa
superior en metal5), asi que puede montarse sobre los transistores sin gastar
area y **sin mover nada**: es un paso posterior al ruteo, puramente aditivo sobre
capas virgenes. Eso ademas rompe la circularidad — el condensador querria saber
donde cayeron los trunks, y los trunks no dependen de el.

Cada terminal baja hasta el trunk de su net con una pila de vias
(metal2 -> via2 -> metal3 -> via3 -> metal4 [-> via4 -> metal5]).

**Lo que impone la forma del dibujo son tres reglas**, y ninguna es evidente:

- `MIMTM.10`: no puede haber via3 donde el metal4 se solapa con el `fusetop`.
  Los dos contactos tienen que caer FUERA de la placa del condensador
  propiamente dicha.
- `MIMTM.1`: la placa inferior tiene que estar a 1.2 um de cualquier otro
  metal4. Por eso la placa se dibuja como un **rectangulo** que llega hasta el
  trunk de P1 en vez de como placa + brazo: un rectangulo es convexo y no puede
  violar la separacion consigo mismo, mientras que un brazo deja una escotadura
  con dos bordes enfrentados.
- `MT.1`/`MT.2b`: con 5LM el metal5 **es** el metal top, asi que le aplican las
  reglas de metaltop (0.44 de ancho minimo, no 0.28) y no las de metal5.

No se usa `gf180.cap_mim` ni `gf180.via_stack`. `via_stack` esta roto (usa
`m_enc` como float en una linea y lo indexa como tupla en la siguiente, asi que
falla se le pase lo que se le pase). Y `cap_mim` genera las via4 de **0.22**
cuando `V4.1` exige 0.26 exactos: 2804 violaciones de una tacada. Es el mismo
patron que los dos bugs de `fet.py` con `CO.7` (bitacora §6.4).
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

import gdsfactory as gf
import klayout.db as kdb

from coil_layout.pdk_manager import get_pdk_module
from coil_layout.placement import GRID, snap

# --- pila de vias ------------------------------------------------------------
_VIA = 0.26               # V2.1/V3.1/V4.1 exigen 0.26 EXACTO, como via1
_PAD = 0.40               # M3.3/M4.3 piden 0.1444 um2, que es 0.38^2 CLAVADO.
                          # 0.40 deja margen en area (0.16), ancho (M*.1: 0.28) y
                          # enclosure (0.07 contra los 0.06 de V*.3b).
_M2_SPACING = 0.28        # M2.3

# --- metal5 = metal top con 5LM ---------------------------------------------
_M5_W = 0.60              # MT.1 pide 0.44 de ancho minimo
_M5_CLEAR = 0.80          # MT.2b pide 0.6 contra metal top ancho (>10 um)

# --- MIM ---------------------------------------------------------------------
_MIM_SKIRT = 0.60         # cuanto sobresale la placa inferior del fusetop
_MIM_CLEAR = 1.2          # MIMTM.1
_MIM_VIA_INSET = 0.40     # MIMTM.4: solape del fusetop sobre via4
_MIM_VIA_GAP = 0.50       # MIMTM.9: separacion en el mar de vias
_FUSE_CLEAR = 0.50        # margen del riser de P1 al fusetop (MIMTM.10)
_SCAN_STEP = 0.10         # al buscar sitio en el trunk. Con 0.5 se escapaban casi
                          # todos los huecos de las nets cargadas: `OUT` pasaba de
                          # 6 puntos a mas de 200, y con 6 el segundo condensador
                          # no encontraba donde agarrarse.

_STACK = (("via2", "metal3"), ("via3", "metal4"), ("via4", "metal5"))
# Donde cae el contacto de P1 respecto al fusetop: pegado a la derecha, a la
# izquierda, o centrado. Los extremos van primero porque dejan libre todo un lado.
_SIDES = (1.0, 0.0, 0.5)


def place_caps(lay, caps) -> None:
    """Coloca los condensadores de `caps` sobre el layout ya ruteado.

    Lo que no se pueda colocar va a `lay.caps_failed` con el motivo. Nunca se
    calla: un condensador que falte no lo ve **ni el DRC ni el LVS**, porque la
    netlist de referencia sale del mismo aplanado y los dos saldrian limpios
    describiendo un circuito que no es el del esquematico.

    La busqueda es **con vuelta atras**, no de uno en uno. Colocandolos en orden
    y quedandose con la primera solucion de cada uno, el primero elegia su
    contacto en el primer punto libre de la net compartida —justo en medio— y el
    segundo se quedaba sin ventana: en OPAM, XC3 agarraba `OUT` en x=57.4 y XC1
    necesitaba una placa de 20 um en ese mismo tramo. Que el primero cediera no
    cuesta nada, pero hay que poder pedirselo.
    """
    if not caps:
        return
    gf180 = get_pdk_module("gf180")
    top = lay.component
    L = gf180.layer

    m2 = _region(top, L["metal2"])
    span = (top.dxmin, top.dxmax)
    #  Banda de y en la que puede vivir una placa: ENTRE los dos rieles.
    #
    #  No es una regla de DRC ni de esta celda: es que el bloque se usa como
    #  MACRO, y el top le baja la alimentacion desde metal4 a la barra de metal3
    #  que el bloque expone sobre cada riel. Una placa MIM encima de esa barra
    #  aparece en el LEF como obstruccion de Metal4/Metal5 y `pdngen` se planta:
    #
    #      ERROR PDN-0006  VSS on Metal3 is blocked by obstructions
    #                      on Metal4, Metal5 for x1_x1
    #
    #  Paso al permitir construir la placa hacia ABAJO del punto de agarre
    #  (§5.7.1): en la v2 de `OPAM` la obstruccion de Metal4 pasaba de
    #  `y 8.76..27.08` a `y -2.95..25.41`, o sea cruzando el riel VGND y saliendose
    #  de la celda por abajo. Con la banda puesta, la placa se queda dentro.
    from coil_layout.placement import RAIL_WIDTH
    banda_y = (min(lay.vgnd_y, lay.vpwr_y) + RAIL_WIDTH / 2,
               max(lay.vgnd_y, lay.vpwr_y) - RAIL_WIDTH / 2)
    pts: dict[str, list] = {}

    def free(net):
        if net not in pts:
            pts[net] = _free_points(lay.trunks.get(net), m2)
        return pts[net]

    todo, chosen = [], []
    for cap in caps:
        wc, lc = _dims_um(cap)
        n1, n2 = cap.nodes["p1"], cap.nodes["p2"]
        if wc <= 0 or lc <= 0:
            lay.caps_failed.append(f"{cap.name}: dimensiones invalidas ({wc}x{lc})")
            continue
        if not free(n1):
            lay.caps_failed.append(
                f"{cap.name} ({n1}/{n2}): la net {n1} no tiene trunk libre "
                "donde apoyar la pila")
            continue
        if not free(n2):
            lay.caps_failed.append(
                f"{cap.name} ({n1}/{n2}): la net {n2} no tiene trunk libre "
                "donde apoyar la pila")
            continue
        todo.append((cap, n1, n2, wc, lc))

    def search(i, busy4, busy5, solo_tumbados=False):
        if i == len(todo):
            return True
        cap, n1, n2, wc, lc = todo[i]
        for cand in _candidates(free(n1), free(n2), wc, lc, busy4, busy5, span,
                                n1, n2, lay.res_terminals, solo_tumbados,
                                banda_y):
            fuse, plate, p1, p2, m5, pad4 = cand
            chosen.append((cap, fuse, plate, p1, p2, m5))
            if search(i + 1, busy4 + [(plate, n1, True), (pad4, n2, False)],
                      busy5 + [fuse] + m5, solo_tumbados):
                return True
            chosen.pop()
        return False

    #  DOS pasadas, y la primera prohibe las placas de pie. Que `_candidates`
    #  pruebe tumbado antes que de pie no basta: es una preferencia LOCAL, dentro
    #  del generador de un condensador, y el que va primero se lleva el sitio.
    #  En `OPAM_LIN_flat` pasó justo eso al vetar la zona del terminal de la
    #  resistencia: `XC3` cogió sitio tumbado y `XC1` acabó **de pie**, con sus
    #  25 µm en vertical y su metal4 llegando al borde de la celda — o sea que el
    #  condensador volvía a ser lo que fijaba la altura, que es exactamente lo
    #  que se arregló tumbándolos (§5.7). La celda pasó de 49.57 a 55.16 µm.
    #  Con la pasada previa, o entran los dos tumbados o no entra ninguno de pie
    #  sin haberlo intentado antes.
    ok = search(0, [], [], solo_tumbados=True)
    if not ok:
        chosen.clear()
        ok = search(0, [], [])
    if ok:
        for cap, fuse, plate, p1, p2, m5 in chosen:
            _draw(top, L, gf180, cap, fuse, plate, p1, p2, m5)
            wc, lc = _dims_um(cap)
            lay.caps_placed.append(
                f"{cap.name} {wc:g}x{lc:g}um -> "
                f"{cap.nodes['p1']}/{cap.nodes['p2']}")
        return

    for cap, n1, n2, wc, lc in todo:
        lay.caps_failed.append(
            f"{cap.name} ({n1}/{n2}): sin combinacion de puntos que respete "
            "MIMTM.1 y las de metal top")


#: Cuantas soluciones se ofrecen por condensador antes de pasar al siguiente. La
#: busqueda es exponencial en este numero, y las alternativas utiles son las
#: primeras: las que agarran por un extremo del trunk. Con 24 y dos MIM son 576
#: combinaciones en el peor caso, todas comparaciones de cajas.
#: Subido de 40 a 90 al ofrecer la placa tambien HACIA ABAJO del punto de agarre:
#: cada (punto, lado) pasa a dar dos candidatos, asi que con 40 se exploraba la
#: mitad de puntos que antes y `OPAM` se quedaba sin colocar sus dos MIM. No
#: cuesta tiempo porque `_AGARRE_SEP` ya evita las alternativas que solo se
#: diferencian en una decima: con las dos cosas juntas, `OPAM` tarda 11 s; con
#: 90 ramas y sin adelgazar los puntos, cuatro minutos.
_BRANCH = 90
#: ...y cuantas de esas puede gastar un mismo punto de agarre. Sin este limite,
#: las 24 se iban en el MISMO sitio moviendo el otro contacto de decima en
#: decima: 24 candidatos con la misma placa, que es lo unico que estorba al
#: siguiente condensador. Dos bastan, y `_outward` hace que sean los dos extremos
#: del trunk de P2.
_P2_ALT = 3
#: Y cuantas rutas de metal5 distintas se ofrecen por cada par de puntos. Ver el
#: comentario en `_candidates`: con una sola, el primer condensador fijaba el
#: pasillo y el segundo se quedaba sin sitio tumbado.
_M5_ALT = 3
#: Cuanto se le deja asomar a una placa TUMBADA por el borde de la celda antes de
#: rendirse y ponerla de pie. Ver el razonamiento en `_candidates`: se cambian
#: micras de ancho por micras de alto, y en estos bloques el alto vale mucho mas.
_SPAN_EXTRA = 3.0


#: Separacion minima en x entre dos puntos de agarre que se ofrezcan como
#: alternativas distintas. `_free_points` barre el trunk a `_SCAN_STEP`, asi que
#: un trunk de 20 um da ~200 puntos separados una decima — y como el presupuesto
#: de ramas es finito, las 40 alternativas de un condensador se iban en 1.3 um de
#: trunk, moviendo la placa de decima en decima. Medido en `OPAM_LIN_flat`: 40
#: candidatos, **14 posiciones distintas**, todas dentro de 1.3 um. Para el
#: siguiente condensador eso es UNA sola alternativa, y acababa de pie.
_AGARRE_SEP = 2.0


def _outward(points):
    """Los puntos del trunk, de los extremos hacia el centro y bien repartidos.

    Dos criterios, y los dos importan:

    - **De los extremos hacia dentro**: agarrar por el centro parte en dos la
      ventana libre de una net compartida, que es lo que dejaba al segundo MIM
      sin sitio.
    - **Separados** al menos `_AGARRE_SEP`: alternativas que difieren en una
      decima de micra no son alternativas, y se comen el presupuesto de ramas.
    """
    out, lo, hi = [], 0, len(points) - 1
    while lo <= hi:
        for idx in ((lo,) if hi == lo else (lo, hi)):
            p = points[idx]
            if all(abs(p[0] - q[0]) >= _AGARRE_SEP for q in out):
                out.append(p)
        lo += 1
        hi -= 1
    return out


def _too_close(box: kdb.DBox, net: str, busy4, es_placa=False) -> bool:
    """MIMTM.1 contra el metal4 ya puesto, con la excepcion de la misma net.

    La regla pide 1.2 um a cualquier otro metal4, pero dos formas de la MISMA net
    pueden **fusionarse**: ahi no hay separacion que medir. Sin esta excepcion los
    dos MIM del OPAM no caben, porque `OUT` se quedo con un unico punto libre de
    trunk y los dos lo necesitan — uno como contacto y el otro como anclaje de su
    placa. Se exige contencion completa, no un solape cualquiera: rozarse por
    unas centesimas deja una escotadura, que es precisamente lo que la regla mira.
    """
    for other, onet, otra_es_placa in busy4:
        #  La excepcion de misma net NO vale contra una PLACA. El `cap_mk` de un
        #  MIM cubre exactamente su metal4, y magic pinta todo ese metal4 como
        #  `mimcap`: una via4 normal encima no es ni via ni contacto de MIM
        #  —`mimcc` exige ademas estar dentro del `fusetop`—, asi que el terminal
        #  se queda flotando. Es lo que pasaba en OPAM: el pad de bajada del MIM A
        #  caia entero dentro de la placa del MIM B, misma net `OUT`, y netgen veia
        #  el terminal de arriba del A como una net suelta (`m4_6467_2958#`). En
        #  silicio la via es buena; para la extraccion no existe. Aterrizar sobre
        #  metal4 liso lo dejan bien las dos herramientas.
        #  La comprobacion es SIMETRICA: da igual quien se coloque primero, si
        #  la placa acaba tragandose el pad el resultado es el mismo.
        if (es_placa or otra_es_placa) and box.overlaps(other):
            return True
        if net and net == onet and (box.contains(other.p1) and box.contains(other.p2)
                                    or other.contains(box.p1) and other.contains(box.p2)):
            continue
        if box.enlarged(_MIM_CLEAR, _MIM_CLEAR).overlaps(other):
            return True
    return False


def _candidates(p1, p2, wc, lc, busy4, busy5, span, net1="", net2="",
                vetados=(), solo_tumbados=False, banda_y=None):
    """Genera colocaciones validas, de las mas 'apartadas' a las mas centradas.

    Los puntos de agarre se recorren desde los dos extremos del trunk hacia
    dentro. Agarrar por el centro es lo que parte en dos la ventana libre de una
    net compartida, y es exactamente lo que dejaba al segundo MIM sin sitio.

    La placa se prueba primero **TUMBADA** (el lado largo en x) y solo de pie si
    tumbada no cabe. La celda es mucho mas ancha que alta -- 103.85 x 43.20 en
    OPAM_LIN_flat -- asi que una placa de 4 x 25 puesta de pie se come 25 de los
    43 de alto y ademas ES LA QUE FIJA la altura: su metal4 llegaba a y=43.20,
    justo el techo. Tumbada, esos 25 um caben de sobra en los 103.85 de ancho.
    El area no cambia, o sea que la capacidad tampoco: solo cambia el dibujo.

    `solo_tumbados` corta la orientacion vertical de raiz. Lo pide `place_caps`
    en una primera pasada, porque probar tumbado antes que de pie es una
    preferencia LOCAL --dentro del generador de UN condensador-- y el que va
    primero se lleva el sitio: en `OPAM_LIN_flat`, `XC3` cogio hueco tumbado y
    `XC1` acabo de pie, volviendo a ser lo que fijaba la altura de la celda.
    """
    n = 0
    order1 = _outward(p1)
    #  (lado en x, lado en y): primero tumbada, luego de pie.
    orientaciones = [(max(wc, lc), min(wc, lc))]
    if not solo_tumbados:
        orientaciones.append((min(wc, lc), max(wc, lc)))
    for wc, lc in orientaciones:
        n_ori = n
        for (x1, y1), side, arriba in ((p, s, a) for p in order1
                                       for s in _SIDES for a in (True, False)):
            # El fusetop va justo encima del contacto de P1, no encima del trunk mas
            # alto de la celda: atarlo a su propio contacto acorta la placa varias
            # micras y deja sitio al siguiente condensador.
            #
            # Y ARRIBA O ABAJO, las dos. Solo se probaba hacia arriba, y eso es
            # justo lo que hacia que una placa de pie fijara la altura de la
            # celda: anclada en un trunk a y=28.66, sus 25 um se iban a
            # y=29.5..54.5 y el metal4 acababa marcando el techo en 55.16.
            # Hacia abajo, esos mismos 25 um caen sobre las filas de
            # transistores -- que es donde tiene que estar un MIM, en metal4 y
            # metal5, por encima del array y sin gastar area (ver la cabecera de
            # este modulo) -- y no cuestan ni una micra de celda. La simetria es
            # exacta: `_FUSE_CLEAR` es el margen del riser de P1 al fusetop
            # (MIMTM.10) y vale igual por arriba que por abajo.
            fy = snap(y1 + _FUSE_CLEAR + _PAD) if arriba else \
                snap(y1 - _FUSE_CLEAR - _PAD - lc)
            # ...y se prueba a un lado y a otro del contacto. Centrarlo siempre hacia
            # que la placa se comiera la unica ventana libre de la otra net: `OUT`
            # solo tiene hueco en 3 um de trunk, y la placa de XC2 los tapaba todos,
            # dejando a XC3 sin donde agarrarse.
            fx = snap(x1 - wc * side)
            # placa inferior: RECTANGULO desde el contacto de P1 hasta cubrir el
            # fusetop. Convexo a proposito (ver MIMTM.1 en el docstring).
            plate = kdb.DBox(min(fx - _MIM_SKIRT, x1 - _PAD / 2 - _MIM_SKIRT),
                             min(fy - _MIM_SKIRT, y1 - _PAD / 2 - _MIM_SKIRT),
                             max(fx + wc + _MIM_SKIRT, x1 + _PAD / 2 + _MIM_SKIRT),
                             max(fy + lc + _MIM_SKIRT, y1 + _PAD / 2 + _MIM_SKIRT))
            fuse = kdb.DBox(fx, fy, fx + wc, fy + lc)
            # La placa tiene que caber DENTRO del bloque. Sin esto salia hasta
            # x=-8.2 en OPAM: legal para el DRC, pero engorda la celda por un lado
            # donde no hay nada y, ya como macro, se mete en el vecino.
            #
            # Con una excepcion acotada, y sale a cuenta con mucho: cuando se
            # esta buscando una solucion TUMBADA se admite que la placa se salga
            # hasta `_SPAN_EXTRA`. Lo que se compra con esas micras de ancho es no
            # tener que poner la placa de pie, y la moneda no es la misma: en
            # `OPAM_LIN_flat` la placa vertical cuesta **5.6 um de alto** sobre
            # una celda de 98 de ancho (549 um2), mientras que dejarla asomar
            # cuesta lo que asome por 55 de alto. La ultima posicion tumbada que
            # se probaba se pasaba por **0.64 um**.
            margen = _SPAN_EXTRA if solo_tumbados else 0.0
            if plate.left < span[0] - margen or plate.right > span[1] + margen:
                continue
            #  Y en y NO hay margen: la placa tiene que quedarse entre los dos
            #  rieles, o el top no puede bajarle la alimentacion al bloque.
            if banda_y and (plate.bottom < banda_y[0] or plate.top > banda_y[1]):
                continue
            #  La placa no puede taparle el terminal a una resistencia. No es una
            #  regla de DRC -- el DRC de ese layout daba 0 -- sino de EXTRACCION:
            #  con la placa encima, el deck deja el terminal en una net suelta
            #  aunque el metal2 que tiene justo arriba si sea la net buena. Se
            #  midio sobre el MISMO GDS: borrando solo las capas del MIM
            #  (metal4, metal5, fusetop, via3, via4) la cadena de la resistencia
            #  pasa a acabar en `OUT`; con ellas, en `$263`.
            if any(plate.enlarged(_MIM_CLEAR, _MIM_CLEAR).contains(kdb.DPoint(*q))
                   for q in vetados):
                continue
            if _too_close(plate, net1, busy4, es_placa=True):
                continue
            # Los puntos de P2 se prueban del mas cercano a la placa al mas lejano.
            # No es cosmetica: el metal5 tiene que ir de la placa hasta ahi, y con el
            # orden por extremos XC1 sacaba su pestana desde x=78 hasta x=14 y se
            # comia el metal5 del otro condensador a lo ancho de todo el bloque.
            #
            # Pero el mas cercano no puede ser la UNICA opcion, y `_P2_ALT` es
            # pequeno: cuando dos condensadores comparten una net —`OUT` en
            # `OPAM_LIN_flat`— uno la usa para anclar su placa y el otro para
            # bajar su pad, y **una placa no puede tragarse un pad** (la excepcion
            # de misma net no vale contra una placa, ver `_too_close`). Los unicos
            # puntos que sirven son entonces los del EXTREMO opuesto del trunk, o
            # sea justo los ultimos por proximidad. Sin ofrecerlos, el segundo MIM
            # no encontraba sitio tumbado y acababa de pie, fijando el alto de la
            # celda: 55.16 um en vez de 49.57. Se prueba el mas cercano primero y
            # los extremos despues.
            cx = fuse.center().x
            alt = 0
            cercanos = sorted(p2, key=lambda q: abs(q[0] - cx))
            orden2, vistos = [], set()
            for q in (cercanos[:1] + _outward(p2)):
                if q not in vistos:
                    vistos.add(q)
                    orden2.append(q)
            for x2, y2 in orden2:
                # MIMTM.1: el pad de metal4 del riser de P2, lejos de la placa
                pad4 = kdb.DBox(x2 - _PAD / 2, y2 - _PAD / 2,
                                x2 + _PAD / 2, y2 + _PAD / 2)
                if plate.enlarged(_MIM_CLEAR, _MIM_CLEAR).overlaps(pad4):
                    continue
                if _too_close(pad4, net2, busy4):
                    continue
                #  Se ofrece MAS DE UNA ruta de metal5 por par de puntos. Con una
                #  sola, la primera que no choca queda fijada, y el condensador
                #  que va detras se encuentra el pasillo ocupado sin que la
                #  busqueda pueda retroceder a otro: en `OPAM_LIN_flat` los dos
                #  MIM cruzan el bloque en sentidos opuestos —uno va de `net10`
                #  (izquierda) a `OUT` (derecha) y el otro de `OUT` a `net9`— y
                #  con una ruta por pareja no habia ninguna combinacion tumbada.
                #  metal5 esta practicamente vacio, asi que las alternativas
                #  existen; lo que faltaba era ofrecerlas.
                rutas = 0
                for m5 in _m5_routes(fuse, x2, y2):
                    if any(any(s.enlarged(_M5_CLEAR, _M5_CLEAR).overlaps(b)
                               for b in busy5) for s in m5):
                        continue
                    yield fuse, plate, (x1, y1), (x2, y2), m5, pad4
                    n += 1
                    rutas += 1
                    if n >= _BRANCH:
                        return
                    if rutas >= _M5_ALT:
                        break
                alt += 1 if rutas else 0
                if alt >= _P2_ALT:
                    break


def _m5_routes(fuse: kdb.DBox, x2: float, y2: float):
    """Caminos de metal5 en L desde la placa superior hasta el riser de P2.

    Se ofrecen varios porque con un solo trazado el segundo condensador no cabia:
    su pestaña tenia que cruzar por encima de la placa del primero. Variando la
    altura del tramo horizontal y por que lado sale, casi siempre hay uno libre —
    metal5 esta vacio salvo por los propios condensadores.
    """
    h = _M5_W / 2
    step = _M5_CLEAR + _M5_W
    # Varios pasillos horizontales a distintas alturas, no solo el de la propia
    # net. Con uno por condensador los dos querian el mismo: en OPAM, XC3 baja de
    # su placa al riser de `OUT` por y=11.25 y XC1 tenia que ir de x=57 a x=14
    # por esa misma altura para alcanzar `net9`. Metal5 esta vacio salvo por los
    # condensadores, asi que apartarse un pasillo no cuesta nada.
    lanes = [y2]
    for k in (1, 2, 3):
        lanes += [y2 - k * step, y2 + k * step]
    for x_side in (fuse.left + h, fuse.right - h):
        for y_run in lanes + [fuse.bottom + h, fuse.top - h,
                              fuse.bottom - step, fuse.top + step]:
            lo, hi = min(y_run, fuse.bottom + h), max(y_run, fuse.top - h)
            yield [
                # tramo vertical pegado a un lado de la placa
                kdb.DBox(x_side - h, lo - h, x_side + h, hi + h),
                # tramo horizontal hasta la x del riser
                kdb.DBox(min(x2, x_side) - h, y_run - h,
                         max(x2, x_side) + h, y_run + h),
                # bajada final hasta el riser
                kdb.DBox(x2 - h, min(y2, y_run) - h, x2 + h, max(y2, y_run) + h),
            ]


def _dims_um(cap) -> tuple[float, float]:
    from coil_layout.spice_parser import parse_value_um
    p = {k.lower(): v for k, v in cap.params.items()}
    return (parse_value_um(p.get("c_width", "0")),
            parse_value_um(p.get("c_length", "0")))


def _region(top, layer) -> kdb.Region:
    ly = top.kcl.layout
    return kdb.Region(top.begin_shapes_rec(ly.layer(*layer))).merged()


def _free_points(trunks, m2) -> list[tuple[float, float]]:
    """Puntos del trunk donde cabe el pad de metal2 del riser.

    Se mide contra la geometria REAL: el pad (0.40) es mas alto que el trunk
    (0.28) y sobresale hacia las pistas vecinas, asi que no vale razonar con el
    paso de pistas — hay que ver si el hueco existe.
    """
    out = []
    for (x0, x1, y, _w) in trunks or ():
        x = x0 + _PAD
        while x <= x1 - _PAD:
            xs = snap(x)
            box = kdb.DBox(xs - _PAD / 2, y - _PAD / 2,
                           xs + _PAD / 2, y + _PAD / 2)
            if _pad_fits(box, m2):
                out.append((xs, snap(y)))
            x += _SCAN_STEP
    return out


def _pad_fits(box: kdb.DBox, m2: kdb.Region) -> bool:
    """Corre el propio chequeo de espaciado sobre el metal2 con el pad puesto.

    Contar poligonos vecinos NO basta, y costo cuatro `M2.2a`: el trunk y sus
    pads de via son un unico poligono fusionado, asi que el pad podia caer a
    0.01 um del pad de via de un stub —de su misma net— y dejar una escotadura
    que la regla si mira. Lo unico fiable es reproducir la regla: se coge lo que
    hay alrededor, se une el pad y se pide que no salga ni espaciado ni ancho
    por debajo del minimo.

    Dos cuidados, y los dos costaron caros:

    1. Los vecinos se toman **enteros** (`interacting`), no recortados por la
       ventana (`& win`). Recortar parte los trunks vecinos por la mitad y deja
       esquirlas —se midio una de 0.02 um de alta— que el chequeo de ancho
       denuncia como si fueran del dibujo. Eso no pasaba mientras el paso entre
       trunks era pequeno, porque el vecino cabia dentro de la ventana; al
       ensanchar el canal para la resistencia el paso subio a 1.82 y el borde del
       vecino cayo justo encima del borde de la ventana. Resultado: `INN`, `INP`
       y `OUT` se quedaron **sin un solo punto libre** en trunks de 12 a 17 um
       que estaban vacios, y con ellos se cayeron los dos condensadores y la
       resistencia. Ningun aviso: la funcion simplemente decia "no cabe".

    2. Solo cuentan las violaciones que provoca EL PAD. Con los poligonos
       enteros entra en la cuenta geometria lejana que puede traer sus propios
       defectos, y no es asunto de esta funcion: se filtra por proximidad al pad.
    """
    win = kdb.Region(box.enlarged(1.5, 1.5).to_itype(1e-3))
    pad = kdb.Region(box.to_itype(1e-3))
    local = (m2.interacting(win) + pad).merged()
    d = int(_M2_SPACING * 1e3)
    cerca = kdb.Region(box.enlarged(_M2_SPACING, _M2_SPACING).to_itype(1e-3))
    for chequeo in (local.space_check(d, False, kdb.Region.Euclidian),
                    local.width_check(d, False, kdb.Region.Euclidian)):
        if not chequeo.polygons().interacting(cerca).is_empty():
            return False
    return True


def _draw(top, L, gf180, cap, fuse, plate, p1, p2, m5) -> None:
    x1, y1 = p1
    x2, y2 = p2
    _bar(top, L["metal4"], plate.left, plate.right, plate.bottom, plate.top)
    _bar(top, L["cap_mk"], plate.left, plate.right, plate.bottom, plate.top)
    _bar(top, L["fusetop"], fuse.left, fuse.right, fuse.bottom, fuse.top)
    _bar(top, L["metal5"], fuse.left, fuse.right, fuse.bottom, fuse.top)
    _bar(top, L["mim_l_mk"], fuse.left, fuse.right, fuse.bottom, fuse.bottom + 0.1)
    for b in m5:
        _bar(top, L["metal5"], b.left, b.right, b.bottom, b.top)

    # mar de via4 sobre la placa superior (MIMTM.4 el retranqueo, MIMTM.9 el paso)
    flat_add(top, gf180.via_generator(
        x_range=(fuse.left + _MIM_VIA_INSET, fuse.right - _MIM_VIA_INSET),
        y_range=(fuse.bottom + _MIM_VIA_INSET, fuse.top - _MIM_VIA_INSET),
        via_layer=L["via4"], via_size=(_VIA, _VIA),
        via_enclosure=(_MIM_VIA_INSET, _MIM_VIA_INSET),
        via_spacing=(_MIM_VIA_GAP, _MIM_VIA_GAP)))

    _riser(top, L, gf180, x1, y1, upto="metal4")   # P1: placa inferior
    _riser(top, L, gf180, x2, y2, upto="metal5")   # P2: placa superior
    top.add_label(cap.name, layer=(63, 63), position=(fuse.center().x,
                                                      fuse.center().y))


def _riser(top, L, gf180, x, y, upto: str) -> None:
    """Pila de vias desde el metal2 que ya hay en (x, y) hasta `upto`."""
    # el metal2 de partida es el trunk (0.28 de alto) y no envuelve la via2:
    # hace falta un pad propio, que es lo que obliga a medir el hueco al elegir x
    _bar(top, L["metal2"], x - _PAD / 2, x + _PAD / 2, y - _PAD / 2, y + _PAD / 2)
    for via_name, metal_name in _STACK:
        flat_add(top, gf180.via_generator(
            x_range=(x - _VIA / 2, x + _VIA / 2),
            y_range=(y - _VIA / 2, y + _VIA / 2),
            via_layer=L[via_name], via_size=(_VIA, _VIA),
            via_enclosure=((_PAD - _VIA) / 2, (_PAD - _VIA) / 2),
            via_spacing=(_VIA, _VIA)))
        if metal_name == "metal5":
            # metal top: 0.40 se queda corto para MT.1 (0.44)
            _bar(top, L[metal_name], x - _M5_W / 2, x + _M5_W / 2,
                 y - _M5_W / 2, y + _M5_W / 2)
        else:
            _bar(top, L[metal_name], x - _PAD / 2, x + _PAD / 2,
                 y - _PAD / 2, y + _PAD / 2)
        if metal_name == upto:
            break


def flat_add(top, comp) -> None:
    """Copia la geometria de `comp` DENTRO de `top`, sin instanciarla.

    Los booleanos con que magic lee un GDS se evaluan celda a celda. El mar de
    via4 del MIM sale de `gf180.via_generator`, que trae jerarquia propia, y en
    esa subcelda no hay ni `fusetop` ni `cap_mk` ni `metal5` — los marcadores
    viven en la celda de arriba, donde `_bar` los inserta directos. Asi que la
    regla `mimcc = VIA4 and MET5 and CAPM and CAPDEF` no dispara nunca, la via
    entra como via4 plana dentro de un `mimcap` y magic saca 572 "Can't overlap
    those layers" por bloque con MIM, ademas de dejar los terminales del
    condensador en nets propias al extraer.

    Se puede pedir `gds flatglob` al leer, pero hay que aplanar tambien los
    rectangulos y las celdas sin nombre —la jerarquia de `via_generator` cuelga de
    ellas— y eso son minutos por bloque. Copiar aqui la geometria sale gratis y
    deja el GDS bien para cualquiera que lo lea.
    """
    ly = comp.kcl.layout
    for li in ly.layer_indexes():
        it = comp.begin_shapes_rec(li)
        while not it.at_end():
            top.shapes(li).insert(it.shape().dpolygon.transformed(it.dtrans()))
            it.next()


def _bar(top, layer, x0, x1, y0, y1) -> None:
    """Rectangulo insertado directo en la celda.

    Sin pasar por `gf.components.rectangle`: su cache reutiliza la celda con otro
    origen y saca vertices fuera de rejilla (*_OFFGRID). Misma razon que en
    routing._rect.
    """
    li = top.kcl.layout.layer(*layer)
    top.shapes(li).insert(kdb.DBox(snap(x0), snap(y0), snap(x1), snap(y1)))
