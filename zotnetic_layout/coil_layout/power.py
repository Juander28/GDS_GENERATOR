"""Sube VDD/VSS de los rieles de metal1 hasta metal3, para que el top pueda bajar.

Un bloque terminado exporta sus rieles de alimentacion como pines de **metal1**,
y eso no le sirve de nada a quien lo coloque como macro: el LEF abstracto declara
ademas obstrucciones de metal1 a metal5 sobre casi toda la celda —los platos MIM
incluidos—, asi que no queda por donde meter una pila de vias hasta el riel.
`pdngen` lo dice sin ambiguedad y luego aborta:

    PDN-0232 grid "macro - x1_x7" does not contain any shapes or vias
    PDN-0233 Failed to generate full power grid

Lo que falta es una **plataforma de aterrizaje**: una barra de metal3 encima de
cada riel, del mismo ancho que el bloque, atada al riel con vias. metal3 es
horizontal en esta tecnologia y esta practicamente vacio en estos bloques (solo
lo pisan los risers de los condensadores, que viven en el canal y no en los
rieles), asi que la barra cabe entera y el top solo tiene que cruzarla con una
tira vertical de metal4 para engancharse.

Va **despues del ruteo**: las vias de bajada necesitan un hueco en metal2 y no se
sabe donde hay hueco hasta que el router ha terminado. Es el mismo motivo por el
que los condensadores van los ultimos.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

import klayout.db as kdb

from coil_layout.caps import (_bar, _free_points, _pad_fits, _region,
                             flat_add, _M2_SPACING, _PAD, _VIA)
from coil_layout.pdk_manager import get_pdk_module
from coil_layout.placement import (RAIL_WIDTH, VPWR_HINTS, _POWER_HINTS, snap)

#: Paso al que se intenta poner una bajada. No hace falta una por micra: la barra
#: de metal3 conduce, y lo que importa es que haya suficientes para la corriente y
#: repartidas. Donde el metal2 este ocupado se salta y se sigue.
_STEP = 2.0

#: Margen desde el borde para no dejar la primera bajada colgando del extremo.
_EDGE = 0.6

#: Rejilla de ruteo del top (Metal1..Metal4: paso 0.56, offset 0.28). Las
#: plataformas de los puertos se llevan a ella para que el cable del router
#: aterrice CENTRADO. Sin alinear, el router se conformaba con rozar el borde del
#: pad —0.07 um de solape— y la union dejaba un cuello mas estrecho que el minimo:
#: son las `M3.1` y `M3.2a` que quedaban en el top. Es tambien lo que avisa
#: `MPL-0002 Could not align all pins of the macro to the track-grid`.
_TRACK_PITCH = 0.56
_TRACK_OFFSET = 0.28


#: Hueco que se le exige a una plataforma de puerto contra el metal3 de OTROS
#: puertos. No basta el espaciado (0.28): encima de la plataforma va a aterrizar
#: un cable del router, y el de este flujo lleva la regla no estandar `ANCHO`, de
#: 0.38 de ancho. Con solo el espaciado, dos pads de puertos distintos quedaban a
#: 0.295 um —legal entre ellos— y el cable que aterrizaba en uno rozaba el otro:
#: eran diez de las `M3.2a` del top, todas en DECODER, que es el bloque apretado.
#: 0.28 + la mitad del cable deja sitio para los dos.
_LAND_CLEAR = _M2_SPACING + 0.19


def _on_track(x: float) -> float:
    k = round((x - _TRACK_OFFSET) / _TRACK_PITCH)
    return snap(_TRACK_OFFSET + k * _TRACK_PITCH)


def _caja_con_pista(x: float, y: float, lado: float) -> kdb.DBox:
    """El pad de metal3, estirado en Y hasta que una pista lo cruce.

    **Un pad de 0.40 um contra un paso de pista de 0.56 no siempre tiene punto
    de acceso.** Su x se lleva a pista (`_on_track`), pero su y es la del trunk,
    que la impone el canal y no se elige. Si entre `y - 0.20` e `y + 0.20` no
    cae ninguna pista horizontal, `detailed_route` del top aborta con
    `DRT-0073 No access point for <inst>/<pin>` -- y cual de los pines cae mal
    depende de donde aterrice el macro, asi que el mismo bloque rutea o no segun
    el floorplan. Medido: la v1 de OPAM_LIN_flat fallo en INN (pad centrado en
    y = 20.69) y la v2 en INP.

    La salida es estirar SOLO el metal3 hasta el centro de la pista mas cercana.
    El metal2 y la via se quedan donde estan -- siguen dentro -- y lo que crece
    es la chapa sobre la que aterriza el router, que es justo lo que le faltaba.
    """
    #  Y EN X TAMBIEN. Estirar solo en y garantiza que cruce una pista
    #  HORIZONTAL, y el router necesita las dos: `DRT-0073 No access point for
    #  x1_x1/INP (OPAM_LIN_flat)` con la plataforma centrada en x=9.29, cuando
    #  la pista mas cercana esta en 9.24. La x se lleva a pista antes de elegir
    #  el punto (`_on_track`), pero solo entre los huecos que ya estan sobre
    #  ella: cuando no hay ninguno se cae a un punto cualquiera, y ahi la
    #  plataforma se queda sin columna por la que bajar.
    #
    #  Cuesta como mucho medio paso de pista de metal3 sobre una capa que en el
    #  canal esta practicamente vacia, y el hueco se comprueba sobre esta misma
    #  caja (`_clear(chapa, ...)`), asi que crecer aqui no se salta ninguna
    #  comprobacion.
    xt = _on_track(x)
    yt = _on_track(y)
    return kdb.DBox(min(x, xt) - lado / 2, min(y, yt) - lado / 2,
                    max(x, xt) + lado / 2, max(y, yt) + lado / 2)


def _clear(box: kdb.DBox, region: kdb.Region, gap: float = _M2_SPACING) -> bool:
    """True si no hay nada de `region` bajo el pad ni a menos de `gap`.

    El margen es el espaciado COMPLETO, no la mitad. Con la mitad quedaban pads a
    0.14 um de un riser de condensador y salian `M2.2a` de 0.09 y `V2.2a` de 0.14:
    el pad de metal3 y su via2 van a la misma (x, y), asi que dejar libre el metal3
    por el espaciado de metal (0.28) cubre de paso el de las vias (0.26).
    """
    grown = kdb.Region(box.enlarged(gap, gap).to_itype(1e-3))
    return (region & grown).is_empty()


def add_power_access(lay) -> None:
    """Dibuja la barra de metal3 y sus bajadas sobre cada riel de `lay`."""
    if lay.pdk != "gf180":
        return
    gf180 = get_pdk_module("gf180")
    top = lay.component
    L = gf180.layer

    m2 = _region(top, L["metal2"])
    #  EL METAL1 DEL RIEL, que es lo que decide donde puede caer una bajada.
    #  `top.dxmin/dxmax` es el bbox de la CELDA, y ese lo estiran el nwell, los
    #  implantes y la propia barra de metal3 -- en WEIGHT_COMP llega a x=-3.945
    #  mientras el riel de metal1 empieza en x=-1.0. Recorriendo el bbox salian
    #  bajadas con su via1 en el aire: `V1.3a` (metal1 overlap of via1 is 0 um)
    #  x2, en x=-3.145 y x=-1.145. Y ninguna otra comprobacion lo veia, porque
    #  la unica que habia era que el metal2 estuviese libre -- y ahi fuera lo
    #  esta, precisamente porque no hay nada.
    m1 = _region(top, L["metal1"])
    x0, x1 = top.dxmin, top.dxmax

    for y in (lay.vgnd_y, lay.vpwr_y):          # ya son el CENTRO del riel
        _bar(top, L["metal3"], x0, x1,
             y - RAIL_WIDTH / 2, y + RAIL_WIDTH / 2)

        n = 0
        x = snap(x0 + _EDGE + _PAD / 2)
        while x <= x1 - _EDGE - _PAD / 2:
            pad = kdb.DBox(x - _PAD / 2, y - _PAD / 2,
                           x + _PAD / 2, y + _PAD / 2)
            # Vacio de metal2, no solo "sin violar el espaciado". `_pad_fits` es
            # el criterio de los condensadores, donde el pad se apoya en el trunk
            # de SU PROPIA net y fusionarse es justo lo que se busca. Aqui la
            # bajada nace del riel, asi que tocar cualquier metal2 es cortocircuitar
            # esa net contra la alimentacion — y fusionados ni el chequeo de
            # espaciado ni el DRC lo ven: solo lo canto el LVS de WEIGHT_COMP,
            # cuyo riel VGND va por DENTRO de la celda, entre las dos filas N.
            #  Y el pad ENTERO sobre el metal1 del riel, no solo dentro de la
            #  banda: la via1 no tiene de que agarrarse fuera de el.
            sobre_m1 = (kdb.Region(pad.to_itype(1e-3)) - m1).is_empty()
            if sobre_m1 and _clear(pad, m2) and _pad_fits(pad, m2):
                _bar(top, L["metal2"], pad.left, pad.right, pad.bottom, pad.top)
                for via in ("via1", "via2"):
                    flat_add(top, gf180.via_generator(
                        x_range=(x - _VIA / 2, x + _VIA / 2),
                        y_range=(y - _VIA / 2, y + _VIA / 2),
                        via_layer=L[via], via_size=(_VIA, _VIA),
                        via_enclosure=((_PAD - _VIA) / 2, (_PAD - _VIA) / 2),
                        via_spacing=(_VIA, _VIA)))
                n += 1
            x = snap(x + _STEP)
        lay.power_taps[round(y, 3)] = n

    add_signal_access(lay, top, L, gf180, m2)
    add_gate_to_rail(lay, top, L, gf180)


def add_gate_to_rail(lay, top, L, gf180) -> None:
    """Puentes de metal3 desde las puertas que cuelgan de un riel hasta el riel.

    UN RIEL LLEGA A LOS DISPOSITIVOS POR LOS RISERS DE S/D. Una **puerta** en el
    riel no tiene riser y se quedaba al aire, sin que nada lo dijera. Aparecio
    con la quinta rama de WEIGHT_COMP -- `XMF1 OUT VDD netF GND nfet_06v0`, un
    nfet siempre encendido -- y netgen lo canto asi: un `nfet_06v0/gate` sin
    pareja de un lado, y a VDD del esquematico le sobraba uno del otro. El DRC no
    dice nada de una puerta al aire.

    Y va por METAL3 a proposito. La puerta esta en la fila N, pegada a su riel, y
    VDD le queda al otro lado del canal; cruzarlo por metal1 o metal2 es meterse
    entre los trunks. Metal3 sobre el canal esta practicamente vacio --solo los
    risers de los MIM, las plataformas de puerto y el cruce de la resistencia--
    y ADEMAS el riel ya tiene ahi su barra de metal3 a todo lo ancho
    (`add_power_access`), que es justo donde hay que aterrizar.
    """
    m3 = _region(top, L["metal3"])
    m2 = _region(top, L["metal2"])
    #  La barra de metal3 del riel al que hay que llegar NO es un obstaculo: es
    #  el destino, y es la misma net. Sin sacarla de la comprobacion no habia
    #  columna valida en toda la celda, porque el puente termina justo encima de
    #  ella. Las dos barras se apartan y cada puente comprueba contra el resto.
    x0, x1 = top.dxmin, top.dxmax
    barras = {}
    for yr in (lay.vgnd_y, lay.vpwr_y):
        barras[round(yr, 3)] = kdb.Region(kdb.DBox(
            x0, yr - RAIL_WIDTH / 2, x1, yr + RAIL_WIDTH / 2).to_itype(1e-3))

    for name, pd in lay.placed.items():
        net = pd.wd.nodes.get("gate")
        if not net or net.lower() not in _POWER_HINTS:
            continue
        y_riel = lay.vpwr_y if net.lower() in VPWR_HINTS else lay.vgnd_y
        #  La puerta sale por arriba o por abajo del dispositivo; se coge la que
        #  mira al riel, que es la que menos canal cruza.
        puertos = [q for q in pd.ref.ports if q.name.startswith("G")]
        if not puertos:
            lay.signal_access_failed.append(
                f"{name}: puerta en {net} y el dispositivo no expone puerto G")
            continue
        def _xy(q):
            c = q.dcenter
            return (c[0], c[1]) if isinstance(c, tuple) else (c.x, c.y)

        p = min(puertos, key=lambda q: abs(_xy(q)[1] - y_riel))
        x, y = (snap(v) for v in _xy(p))

        #  El puente: pad en la puerta, pila de vias hasta metal3 y una tira
        #  vertical hasta la barra del riel. La x se lleva a pista por el mismo
        #  motivo que las plataformas de puerto.
        lo, hi = (min(y, y_riel), max(y, y_riel))
        #  TODAS las columnas de pista de la celda, de la mas cercana a la mas
        #  lejana. El puente cruza el canal entero, asi que se topa con cualquier
        #  plataforma de puerto, riser de MIM o cruce de resistencia que haya en
        #  metal3: con tres candidatas no encontraba hueco en WEIGHT_COMP.
        cand = []
        k = 0
        while True:
            hay = False
            for xc in ({_on_track(x + k * _TRACK_PITCH)}
                       | {_on_track(x - k * _TRACK_PITCH)}):
                if top.dxmin + _PAD / 2 <= xc <= top.dxmax - _PAD / 2:
                    cand.append(xc); hay = True
            if not hay and k > 0:
                break
            k += 1
            if k > 400:
                break
        #  Los rieles que hay que CRUZAR: el propio no, que es el destino, pero
        #  cualquier otro si. En WEIGHT_COMP la puerta esta en la fila N2, bajo
        #  el riel de VSS (y = 4.26), y VDD esta arriba del todo (y = 21.0): el
        #  puente pasa por encima de la barra de metal3 de VSS quiera o no. Ahi
        #  se BAJA A METAL2 -- la barra del riel es metal1 mas metal3, entre
        #  medias no hay nada -- y se vuelve a subir pasada.
        cruces = sorted(yr for yr in (lay.vgnd_y, lay.vpwr_y)
                        if abs(yr - y_riel) > 1e-6 and lo - _PAD < yr < hi + _PAD)
        #  `+ _PAD/2` porque el metal3 NO acaba en `a`: acaba en el pad de la
        #  via2, que va centrado en `a` y mide `_PAD`. Sin ese medio pad el hueco
        #  real hasta la barra del riel sale `salto - _PAD/2 - RAIL_WIDTH/2` =
        #  0.27 um, y `M3.2a` pide 0.28. Dos violaciones por un hundredth, una
        #  por cada extremo del cruce.
        salto = RAIL_WIDTH / 2 + _LAND_CLEAR + _PAD / 2

        elegido = None
        for xc in cand:
            tira = kdb.DBox(xc - _PAD / 2, lo - _PAD / 2, xc + _PAD / 2, hi + _PAD / 2)
            #  Y el tramo HORIZONTAL que lleva de la x de la puerta a la columna.
            #  Va por metal3 como el resto: hacerlo por metal1, que es donde esta
            #  la puerta, es tender 7 um de metal1 a lo ancho de la fila y cortar
            #  con lo que haya. Medido: asi el LVS acabo poniendo la etiqueta VDD
            #  sobre `x1_net6` y dejando el VDD de verdad sin pin.
            jog = kdb.DBox(min(x, xc) - _PAD / 2, y - _PAD / 2,
                           max(x, xc) + _PAD / 2, y + _PAD / 2)
            fuera = m3 - barras.get(round(y_riel, 3), kdb.Region())
            for yr in cruces:
                fuera = fuera - barras[round(yr, 3)]
            if not (_clear(tira, fuera, _LAND_CLEAR)
                    and _clear(jog, fuera, _LAND_CLEAR)):
                continue
            #  Y metal2 libre en la ventana de cada cruce, que es por donde pasa.
            #  La ventana que se comprueba es la que se DIBUJA, `_PAD/2` mas
            #  larga por cada extremo; comprobar la corta y dibujar la larga es
            #  como se cuela un cortocircuito por 0.19 um.
            if all(_clear(kdb.DBox(xc - _PAD / 2, yr - salto - _PAD / 2,
                                   xc + _PAD / 2, yr + salto + _PAD / 2),
                          m2, _M2_SPACING)
                   for yr in cruces):
                elegido = xc
                break
        if elegido is None:
            lay.signal_access_failed.append(
                f"{name}: no cabe el puente de la puerta a {net} en ninguna "
                f"columna ({len(cand)} probadas, {len(cruces)} riel(es) que cruzar)")
            continue
        xc = elegido

        #  La pila de vias va SOBRE LA PUERTA, en su propia x: el metal1 no se
        #  mueve de ahi. El desplazamiento hasta la columna se hace ya arriba,
        #  en metal3.
        for capa, via in (("metal2", "via1"), ("metal3", "via2")):
            flat_add(top, gf180.via_generator(
                x_range=(x - _VIA / 2, x + _VIA / 2),
                y_range=(y - _VIA / 2, y + _VIA / 2),
                via_layer=L[via], via_size=(_VIA, _VIA),
                via_enclosure=((_PAD - _VIA) / 2, (_PAD - _VIA) / 2),
                via_spacing=(_VIA, _VIA)))
            _bar(top, L[capa], x - _PAD / 2, x + _PAD / 2,
                 y - _PAD / 2, y + _PAD / 2)
        _bar(top, L["metal3"], min(x, xc) - _PAD / 2, max(x, xc) + _PAD / 2,
             y - _PAD / 2, y + _PAD / 2)
        #  El puente, tramo a tramo: metal3 salvo en la ventana de cada riel
        #  cruzado, donde va metal2 con su via2 a cada lado.
        cortes = []
        for yr in cruces:
            cortes.append((yr - salto, yr + salto))
        #  El metal2 del cruce va de `a - _PAD/2` a `b + _PAD/2`, no de `a` a `b`.
        #  Las dos via2 se centran EN `a` y en `b` (ver el bucle de `cortes` mas
        #  abajo), asi que con el tramo justo de a a b cada via se queda con la
        #  mitad fuera del metal2: `V2.3b` (metal2 overlap of via2) x2, con 0.13
        #  de 0.26 cubiertos. El metal3 no lo sufria porque ahi el `_bar` de cada
        #  via ya dibuja su pad de `_PAD` centrado en la via.
        tramos, y0 = [], lo - _PAD / 2
        for a, b in cortes:
            tramos.append(("metal3", y0, a))
            tramos.append(("metal2", a - _PAD / 2, b + _PAD / 2))
            y0 = b
        tramos.append(("metal3", y0, hi + _PAD / 2))
        for capa, ya, yb in tramos:
            if yb - ya <= 0:
                continue
            _bar(top, L[capa], xc - _PAD / 2, xc + _PAD / 2, ya, yb)
        for a, b in cortes:                     # las dos via2 de cada cruce
            for yv in (a, b):
                flat_add(top, gf180.via_generator(
                    x_range=(xc - _VIA / 2, xc + _VIA / 2),
                    y_range=(yv - _VIA / 2, yv + _VIA / 2),
                    via_layer=L["via2"], via_size=(_VIA, _VIA),
                    via_enclosure=((_PAD - _VIA) / 2, (_PAD - _VIA) / 2),
                    via_spacing=(_VIA, _VIA)))
                _bar(top, L["metal3"], xc - _PAD / 2, xc + _PAD / 2,
                     yv - _PAD / 2, yv + _PAD / 2)
        tira = kdb.DBox(xc - _PAD / 2, lo - _PAD / 2, xc + _PAD / 2, hi + _PAD / 2)
        m3 += kdb.Region(tira.to_itype(1e-3))
        m3.merge()
        print(f"   puerta:    {name}.G -> {net} en x={xc:.3f}"
              + (f", bajando a metal2 en {len(cruces)} riel(es)" if cruces else ""))


def add_signal_access(lay, top, L, gf180, m2) -> None:
    """Sube tambien los puertos de SENAL hasta metal3.

    Los pines de senal quedaban en metal1/metal2 dentro del bloque, rodeados por
    el ruteo del propio bloque. Colocado como macro, el router del top no puede
    bajarles una via sin tocar al vecino: salieron 43 `Cut Short` en el ruteo
    detallado, todos sobre un pin de un macro. Igual que con los rieles, lo que
    falta es una plataforma de aterrizaje, y aqui basta con un pad porque el
    puerto ya vive sobre el trunk de su net.
    """
    #  metal3 tambien cuenta: ahi ya estan las barras de alimentacion sobre los
    #  rieles y los risers de los condensadores. Y `m2` hay que irlo actualizando
    #  con cada pad puesto — capturado una sola vez, los pads no se veian entre
    #  ellos y salieron M2.2a en tres de los cuatro bloques.
    m3 = _region(top, L["metal3"])

    for net in lay.ports:
        if net in lay.power_ports:
            continue
        pts = _free_points(lay.trunks.get(net), m2)
        if not pts:
            #  Distinguir las dos causas, que piden arreglos opuestos: o la net
            #  no tiene trunk donde apoyarse (hay que alargarlo, o sea tocar la
            #  colocacion) o lo tiene pero esta todo ocupado (hay que quitarle
            #  sitio a quien se lo comio, que va antes en el flujo).
            tramos = lay.trunks.get(net) or []
            largo = sum(x1 - x0 for x0, x1, _y, _w in tramos)
            lay.signal_access_failed.append(
                f"{net}: trunk de {largo:.2f} um en {len(tramos)} tramo(s), "
                + ("sin un solo hueco libre de 0.40 um: se lo han comido los "
                   "condensadores, la resistencia o el ruteo"
                   if largo > 1.0 else "demasiado corto para apoyar un pad"))
            continue

        #  Una BARRA de metal3 a lo largo del trunk, no varios pads sueltos.
        #  Con un solo pad de 0.40 um todas las nets que llegan al bloque tenian
        #  que pasar por ese cuadrado y el ruteo global se atascaba ahi. Pero con
        #  varios pads separados aparecia `M3.2a`: el cable del router se pegaba a
        #  0.22 um de OTRO pad del MISMO puerto, y la regla de espaciado no
        #  perdona por ser la misma net — solo perdona si las formas se tocan.
        #  Una barra continua da acceso ancho y no deja huecos entre trozos.
        lo, hi = min(q[0] for q in pts), max(q[0] for q in pts)
        wanted = [_on_track(lo + (hi - lo) * f) for f in (0.25, 0.5, 0.75)]
        placed = []
        for target in wanted:
            best = None
            #  Solo posiciones sobre pista: fuera de ella el pad no le sirve al
            #  router para aterrizar centrado, que es de lo que se trata.
            on = [q for q in pts if abs(q[0] - _on_track(q[0])) < 1e-9]
            for x, y in sorted(on or pts, key=lambda q: abs(q[0] - target)):
                if any(abs(x - px) < _PAD + _M2_SPACING for px, _ in placed):
                    continue
                pad = kdb.DBox(x - _PAD / 2, y - _PAD / 2, x + _PAD / 2, y + _PAD / 2)
                #  El metal2 y la via caben en el pad de siempre; el metal3 es el
                #  estirado hasta la pista, y es el que tiene que estar libre.
                chapa = _caja_con_pista(x, y, _PAD)
                if (_pad_fits(pad, m2) and _clear(pad, m3, _LAND_CLEAR)
                        and _clear(chapa, m3, _LAND_CLEAR)):
                    best = (x, y)
                    break
            if best is None:
                continue
            x, y = best
            _bar(top, L["metal2"], x - _PAD / 2, x + _PAD / 2,
                 y - _PAD / 2, y + _PAD / 2)
            flat_add(top, gf180.via_generator(
                x_range=(x - _VIA / 2, x + _VIA / 2),
                y_range=(y - _VIA / 2, y + _VIA / 2),
                via_layer=L["via2"], via_size=(_VIA, _VIA),
                via_enclosure=((_PAD - _VIA) / 2, (_PAD - _VIA) / 2),
                via_spacing=(_VIA, _VIA)))
            chapa = _caja_con_pista(x, y, _PAD)
            _bar(top, L["metal3"], chapa.left, chapa.right,
                 chapa.bottom, chapa.top)
            box = kdb.Region(chapa.to_itype(1e-3))
            m2 += box ; m2.merge()
            m3 += box ; m3.merge()
            placed.append((x, y))
        if not placed:
            #  Aqui SI hay huecos en el trunk, pero ninguno vale: o el pad no
            #  cabe en metal2 o choca con metal3 (los risers de los MIM, las
            #  barras de los rieles o el cruce de la resistencia).
            lay.signal_access_failed.append(
                f"{net}: {len(pts)} hueco(s) en el trunk pero ninguno sirve; "
                f"el pad no cabe en metal2 o choca con metal3")
            continue
        #  Los pads del mismo puerto se unen en una barra: sueltos, el cable del
        #  router se pegaba a 0.22 um de OTRO pad de la MISMA net, y la regla de
        #  espaciado no perdona por ser la misma net — solo perdona si se tocan.
        bx0 = min(x for x, _ in placed) - _PAD / 2
        bx1 = max(x for x, _ in placed) + _PAD / 2
        by = placed[0][1]
        alto = _caja_con_pista(bx0, by, _PAD)
        bar = kdb.DBox(bx0, alto.bottom, bx1, alto.top)
        if len(placed) > 1 and _clear(bar, m3 - kdb.Region(bar.to_itype(1e-3))):
            _bar(top, L["metal3"], bx0, bx1, bar.bottom, bar.top)
            m3 += kdb.Region(bar.to_itype(1e-3))
            m3.merge()
        lay.signal_access[net] = placed
