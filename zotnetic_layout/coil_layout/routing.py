"""Ruteo de conexiones: nets de potencia a los rieles y nets de senal por el canal.

Estrategia (best-effort, orientada a conectividad):
  - Nets de potencia (vdd/vss): se extiende metal1 desde el pad S/D del transistor
    hasta el riel VPWR (arriba) o VGND (abajo).
  - Nets de senal con >=2 pines y que no quedaron resueltas por abutment: se rutean
    con un 'trunk' horizontal en metal2 dentro del canal entre filas, con stubs
    verticales en metal1 desde cada pin y vias metal1<->metal2.

El grosor de cada tipo de conexion es configurable (RouteConfig); por defecto usa
el ancho minimo de cada capa del PDK.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

warnings.filterwarnings("ignore")

import gdsfactory as gf
import klayout.db as kdb

from coil_layout.pdk_manager import get_info, get_pdk_module
from coil_layout.placement import (CHANNEL_MARGIN, TRUNK_PITCH, Layout,
                                   add_port_label)

_VPWR_NETS = {"vdd", "vcc", "vpwr"}
_VGND_NETS = {"vss", "vgnd", "gnd"}


@dataclass
class RouteConfig:
    """Grosores (um) de cada tipo de conexion."""

    stub_w: float        # stub vertical en metal1 (senales)
    trunk_w: float       # trunk horizontal en metal2 (senales)
    power_w: float       # strap de potencia a los rieles

    @classmethod
    def minimum(cls, pdk: str) -> "RouteConfig":
        """Config por defecto = ancho minimo de cada capa del PDK."""
        info = get_info(pdk)
        if pdk == "gf180":
            m1 = info.metals[0].min_width      # metal1
            m2 = info.metals[1].min_width      # metal2
        else:
            m1 = info.metals[1].min_width      # met1
            m2 = info.metals[2].min_width      # met2
        return cls(stub_w=m1, trunk_w=m2, power_w=m1)


def _routing_layers(pdk: str):
    """(capa stub vertical m1, capa trunk horizontal m2, capa via)."""
    info = get_info(pdk)
    if pdk == "gf180":
        return info.metals[0].layer, info.metals[1].layer, info.via_layers["via1"]
    return info.metals[1].layer, info.metals[2].layer, info.via_layers["via"]


def route_layout(lay: Layout, cfg: RouteConfig | None = None) -> Layout:
    cfg = cfg or RouteConfig.minimum(lay.pdk)
    c = lay.component
    m1, m2, via = _routing_layers(lay.pdk)

    _route_power(lay, c, m1, cfg)
    labelled = _route_signals(lay, c, m1, m2, via, cfg)
    _label_unrouted_ports(lay, c, labelled)
    return lay


def _label_unrouted_ports(lay: Layout, c: gf.Component, labelled: set[str]):
    """Etiqueta los puertos que el router no toco (los de un solo pin).

    Una entrada que ataca un unico gate no genera trunk, asi que se queda sin
    etiqueta y el LVS la veria como net interna en vez de como pin.
    """
    info = get_info(lay.pdk)
    for port in lay.ports:
        lo = port.lower()
        # Los rieles ya llevan su etiqueta. Repetirla sobre un pin ocultaria un
        # strap que no hubiera conectado: el LVS los uniria por nombre.
        if port in labelled or lo in _VPWR_NETS or lo in _VGND_NETS:
            continue
        for inst, term in lay.nets.get(port, []):
            if term == "bulk":
                continue
            a = _pin_access(lay, inst, term)
            if a is None:
                continue
            add_port_label(c, port, (a.x, a.y_edge), info)
            labelled.add(port)
            break


# ---------------------------------------------------------------------------
_M2_SPACING = 0.28       # M2.3, para separar dos trunks de la misma pista
_M1_SPACING = 0.23              # min. metal1 spacing en GF180 (M1.2a)
_GF180_CON_COMP_ENC = 0.07      # separacion bloque S/D <-> pad de gate
_GRID = 0.005                   # rejilla de fabricacion (reglas *_OFFGRID)


def _snap(v: float) -> float:
    """Lleva una coordenada a la rejilla de 0.005 um.

    Las posiciones de trunk salen de dividir el canal entre el numero de nets y
    las de los stubs de sumas de anchos: sin redondear caen entre puntos de
    rejilla y disparan las reglas OFFGRID.
    """
    return round(v / _GRID) * _GRID


def _sd_track_x(pd, term: str, px: float, w: float) -> float:
    """Centro x de una pista vertical que sale de un pin S/D, librando el gate.

    En un dispositivo de un solo dedo el pad de contacto de gate empieza a solo
    0.07 um del bloque S/D y sobresale por arriba y por abajo de la difusion,
    justo por donde la pista tiene que cruzar hacia el riel o hacia el canal.
    Centrada en el puerto quedaban 0.135 um (M1.2a pide 0.23), asi que se pega
    al borde exterior del bloque; asoma ~0.03 um fuera del pad pero conserva
    0.20 um de solape, de sobra para la conexion. En los multi-finger el puerto
    ya esta en un riser lateral, fuera de las barras de gate: ahi se centra.
    """
    if pd.wd.pdk != "gf180" or pd.wd.nf != 1 or pd.wd.rotated:
        # Girado, el puerto ya esta en un riser lateral fuera de las barras de
        # gate, igual que en los multi-finger: se centra y no hay nada que librar.
        return px
    blk = pd.wd.sd_block
    pc_x = max(pd.wd.L, 0.36)                       # ancho del pad de gate
    # De que lado esta el bloque se decide por GEOMETRIA, no por el nombre del
    # terminal: al reflejar un dispositivo para intercambiar S y D, el 'source'
    # pasa a estar a la derecha. Deducirlo del nombre dejaba el stub fuera de su
    # propio pad — pin flotante y M1.2a de 0.045 contra el vecino.
    if px < pd.ref.dxmin + pd.ref.dxsize / 2:       # bloque izquierdo
        gate_edge = (px + blk / 2) + _GF180_CON_COMP_ENC
        return gate_edge - _M1_SPACING - w / 2
    gate_edge = (px - blk / 2) - pd.wd.l_d + _GF180_CON_COMP_ENC + pc_x
    return gate_edge + _M1_SPACING + w / 2


def _route_power(lay: Layout, c: gf.Component, m1, cfg: RouteConfig):
    """Conecta los pines S/D que estan en vdd/vss al riel correspondiente."""
    for name, pd in lay.placed.items():
        for term in ("source", "drain"):
            net = pd.wd.nodes.get(term, "").lower()
            port_name = "S" if term == "source" else "D"
            if port_name not in pd.ref.ports:
                continue
            px, py = pd.ref.ports[port_name].dcenter
            w = cfg.power_w
            xc = _snap(_sd_track_x(pd, term, px, w))
            x0, x1 = xc - w / 2, xc + w / 2
            py = _snap(py)
            if net in _VPWR_NETS:
                _box(c, x0, x1, py, _snap(lay.vpwr_y), m1)
            elif net in _VGND_NETS:
                _box(c, x0, x1, py, _snap(lay.vgnd_y), m1)


def _rect(c, x0, y0, x1, y1, layer):
    """Inserta una caja alineada a rejilla, sin usar gf.components.rectangle.

    Esa funcion devuelve celdas cacheadas por tamano y acababa reutilizando la
    misma celda para alturas que diferian en menos de 1 nm: la caja dibujada no
    medía lo pedido y aparecian vertices OFFGRID. Insertando la caja directa,
    la conversion a unidades de base de datos la hace KLayout.
    """
    x0i, x1i = round(x0 / _GRID), round(x1 / _GRID)
    y0i, y1i = round(y0 / _GRID), round(y1 / _GRID)
    if x1i <= x0i or y1i <= y0i:
        return
    c.shapes(c.kcl.layout.layer(*layer)).insert(
        kdb.DBox(x0i * _GRID, y0i * _GRID, x1i * _GRID, y1i * _GRID))


def _box(c, x0, x1, y_a, y_b, layer):
    _rect(c, x0, min(y_a, y_b), x1, max(y_a, y_b), layer)


# ---------------------------------------------------------------------------
def _route_signals(lay: Layout, c: gf.Component, m1, m2, via, cfg: RouteConfig):
    to_route = []
    for net, pins in lay.nets.items():
        lo = net.lower()
        if lo in _VPWR_NETS or lo in _VGND_NETS:
            #  Un riel no se rutea por el canal: llega a cada dispositivo por los
            #  risers de S/D que dibuja `power.py`. Una PUERTA en el riel tampoco
            #  pasa por aqui -- se la lleva `power.add_gate_to_rail`, que le
            #  tiende un puente de metal3, que es la capa que en el canal esta
            #  practicamente vacia.
            continue
        nonbulk = [(i, t) for i, t in pins if t != "bulk"]
        # Un PUERTO entra siempre, tenga los pines que tenga: necesita trunk para
        # colgar de el la plataforma de metal3 con la que el top le baja una via.
        # Una net interna con un solo pin, o resuelta por difusion compartida, no.
        if net not in lay.ports:
            if len(nonbulk) < 2:
                continue
            if net in lay.abutted_nets and len(nonbulk) == 2:
                continue
        to_route.append((net, nonbulk))

    labelled: set[str] = set()
    if not to_route:
        return labelled

    # Cada pin va al canal que le toca segun su fila: los de P y N1 al canal A y
    # los de N2 al B (entre N1 y N2 esta el riel VGND y nadie lo cruza).
    per_channel: dict[str, list] = {}
    for net, pins in to_route:
        by_ch: dict[str, list] = {}
        #  Si la net sale por un bloque S/D compartido, se saca UN solo stub del
        #  bloque en vez de dos de los dispositivos: sus pads ya no existen --se
        #  quitaron al abutir-- y lo que hay es un contacto centrado.
        salidas = lay.abut_salidas.get(net) or []
        omitir = {d for _xc, _row, a_, b_ in salidas for d in (a_, b_)}
        for inst, term in pins:
            if inst in omitir:
                continue
            a = _pin_access(lay, inst, term)
            if a is not None:
                by_ch.setdefault(a.channel, []).append(a)
        for xc, row, a_, _b in salidas:
            a = _acceso_bloque(lay, xc, row, a_)
            by_ch.setdefault(a.channel, []).append(a)
        for ch, acc in by_ch.items():
            # una net con un solo pin en un canal igual necesita trunk ahi si
            # tiene mas pines en el otro: el enlace vertical se cuelga de el.
            # Y un PUERTO lo necesita siempre, aunque tenga un unico pin: de ese
            # trunk cuelga la plataforma de metal3 por la que el top le baja una
            # via (ver power.add_signal_access).
            if len(acc) >= 2 or len(by_ch) > 1 or net in lay.ports:
                per_channel.setdefault(ch, []).append((net, acc))

    # Las columnas de enlace se eligen ANTES de repartir pistas: el trunk tiene
    # que estirarse hasta su columna (si no, la via del enlace aterriza fuera del
    # metal2 y la net queda partida), y ese estirado cambia que nets pueden
    # compartir pista. Decidirlo despues provocaba trunks solapados -> cortos.
    links = _plan_links(lay, per_channel)

    info = get_info(lay.pdk)
    m3 = info.metals[2].layer if lay.pdk == "gf180" else info.metals[3].layer
    via2 = info.via_layers["via2"]
    #  Nets que NO pueden salir del canal porque otro paso posterior las lee de
    #  `lay.trunks` dando por hecho que son metal2: los puertos (plataforma de
    #  metal3), los condensadores (riser) y las resistencias (aterrizaje).
    atadas = set(lay.ports) | {n for n in lay.cap_nets} | {n for n in lay.res_nets}
    routes = []
    lay.tracks_used = 0
    for chan in lay.channels:
        prepared = per_channel.get(chan.name, [])
        if not prepared:
            continue
        arriba, prepared = _nets_a_metal3(lay, chan, prepared, atadas)
        band_lo, band_hi = _channel_band(lay, chan)
        tracks = _assign_tracks(prepared, cfg, links) if prepared else []
        lay.tracks_by_channel[chan.name] = len(tracks)
        lay.tracks_used += len(tracks)

        if band_hi <= band_lo:
            band_hi = band_lo + len(tracks) * 0.6
        # La parte de ARRIBA del canal puede estar reservada para un serpentin de
        # resistencia, y entonces no es del router. Sin descontarla, el reparto se
        # comia tambien esa banda: los 13 trunks de OPAM_LIN_flat se extendian por
        # los 16.65 um enteros y no dejaban en NINGUNA altura los 0.96 um limpios
        # que necesita el terminal de la resistencia para bajar su via
        # (`resistors.BANDA_TERMINAL`). El serpentin no se colocaba, y el reparto
        # de rechazos decia "caja de terminal" sin que se viera por que.
        reservado = lay.channel_reserved.get(chan.name, 0.0)
        util = max(band_hi - band_lo - reservado, 0.0)
        if util < (len(tracks) + 1) * (_VIA_PAD_M2 + 0.28):
            util = band_hi - band_lo          # sin sitio: el router va primero
        pitch = util / (len(tracks) + 1)
        # minimo: pad de via (0.34) + espaciado metal2 (0.28) entre trunks
        pitch = max(pitch, _VIA_PAD_M2 + 0.28)

        access_of = dict(prepared)
        chan_routes = []
        for i, track in enumerate(tracks):
            trunk_y = _snap(band_lo + (i + 1) * pitch)
            for net in track:
                access = access_of[net]
                for a in access:
                    a.trunk_y = trunk_y
                chan_routes.append((net, trunk_y, access))
        #  Y los que suben a metal3, en su propia banda por encima de la fila P.
        #  Van DESPUES de repartir el canal a proposito: el canal ya se ha
        #  dimensionado sin ellos, que es de donde sale el ahorro.
        if arriba:
            m3_lo, m3_hi = _banda_m3(lay)
            pistas3 = _assign_tracks(arriba, cfg, links)
            paso3 = max(_M3_PITCH,
                        (m3_hi - m3_lo) / (len(pistas3) + 1) if m3_hi > m3_lo else _M3_PITCH)
            acc3 = dict(arriba)
            #  El stub cambia de metal1 a metal2 en el borde INFERIOR de la fila:
            #  por debajo cruza el canal, donde metal2 son los trunks y no se
            #  puede; por encima cruza la fila, donde metal1 son los pads de los
            #  dispositivos y tampoco.
            for i, track in enumerate(pistas3):
                trunk_y = _snap(m3_lo + (i + 1) * paso3)
                for net in track:
                    for a in acc3[net]:
                        a.trunk_y = trunk_y
                        a.en_m3 = True
                        a.y_hop = a.y_edge if a.side == "top" else _snap(m3_lo - _M3_MARGEN)
                        #  Su tramo mas ancho es el pad de la via (0.38), no el
                        #  stub de metal1 (0.28): repartiendo con el ancho del
                        #  stub, los pads de dos vecinos se tocan.
                        a.w = max(a.w, _VIA_PAD_M2)
                    chan_routes.append((net, trunk_y, acc3[net]))
        short = _spread_stubs(chan_routes, cfg,
                              _gate_pad_obstacles(lay, chan, cfg),
                              lay.need_gap)
        if short > _GRID / 2:
            # ningun par pudo ceder lo que falta: sale como M1.2a en el DRC.
            # Se avisa en vez de dejarlo pasar (ver DRC_KLAYOUT.md, avisos mudos).
            lay.tight.append(f"{chan.name}: faltan {short:.3f} um de separacion")
        routes += chan_routes

    spans = {}
    for net, trunk_y, access in routes:
        xs = [a.x for a in access]
        if net in links:
            xs.append(links[net])
        spans[(net, trunk_y)] = [min(xs), max(xs)]
    _stretch_short_trunks(spans, lay, cfg)

    for net, trunk_y, access in routes:
        x0, x1 = spans[(net, trunk_y)]
        xs = [x0, x1]
        if access and access[0].en_m3:
            #  Trunk en metal3 sobre la fila. NO se apunta en `lay.trunks`: de ahi
            #  cuelgan condensadores, resistencias y plataformas de puerto, y los
            #  tres dan por hecho metal2. Por eso solo suben las nets que ninguno
            #  de los tres necesita (ver `_nets_a_metal3`).
            _hseg(c, min(xs), max(xs), trunk_y, cfg.trunk_w, m3)
            for a in access:
                if abs(a.y_hop - a.y_edge) > _GRID / 2:
                    _box(c, a.x - cfg.stub_w / 2, a.x + cfg.stub_w / 2,
                         a.y_edge, a.y_hop, m1)
                _via_patch(c, a.x, a.y_hop, via, cfg)          # metal1 -> metal2
                #  El tramo vertical va al ancho MINIMO de metal2, no al del pad:
                #  el pad de 0.38 solo hace falta donde esta la via, y con 0.38
                #  en todo el recorrido dos stubs vecinos se quedaban a 0.135 um
                #  cuando `M2.3` pide 0.28 -- 21 violaciones de golpe.
                _box(c, a.x - cfg.trunk_w / 2, a.x + cfg.trunk_w / 2,
                     a.y_hop, trunk_y, m2)
                _via2_patch(c, a.x, trunk_y, via2, m2, m3)     # metal2 -> metal3
            if net in lay.ports:
                add_port_label(c, net, (access[0].x, trunk_y), info)
                labelled.add(net)
            continue
        _hseg(c, min(xs), max(xs), trunk_y, cfg.trunk_w, m2)
        # Se apunta el trunk: es el metal2 del que se cuelgan los condensadores,
        # que se colocan despues de rutear (ver caps.py). Sin esto habria que
        # redescubrirlo de la geometria, y no se sabria de que net es cada tira.
        lay.trunks.setdefault(net, []).append(
            (min(xs), max(xs), trunk_y, cfg.trunk_w))
        for a in access:
            if a.salto is None:
                _box(c, a.x - cfg.stub_w / 2, a.x + cfg.stub_w / 2, a.y_edge,
                     trunk_y, m1)
                continue
            #  Stub con salto: metal1 dentro del bloque, via1, metal2 cruzando la
            #  banda del pad de gate, via1 otra vez y metal1 hasta el trunk.
            _via_patch(c, a.x, a.y_edge, via, cfg)
            _box(c, a.x - _VIA_PAD_M2 / 2, a.x + _VIA_PAD_M2 / 2,
                 a.y_edge, a.salto, m2)
            _via_patch(c, a.x, a.salto, via, cfg)
            _box(c, a.x - cfg.stub_w / 2, a.x + cfg.stub_w / 2, a.salto,
                 trunk_y, m1)
        # Dos pines de la MISMA net pueden caer muy juntos en el trunk (tipico:
        # uno en cada fila). Ahi no valen dos via1 —se fusionarian en una de
        # 0.46 um y V1.1 exige 0.26 exactos— ni separarlas, porque los pines S/D
        # casi no tienen holgura. Se unen en metal1 y se pone **una sola**.
        for group in _via_groups(access):
            xa = min(g.x for g in group)
            xb = max(g.x for g in group)
            if xb > xa:
                # La barra cubre los stubs de punta a punta: quedandose en sus
                # centros, el borde daba un escalon de medio stub justo donde
                # uno termina, y eso lo cuenta M1.1 como ancho por debajo del
                # minimo.
                _box(c, xa - cfg.stub_w / 2, xb + cfg.stub_w / 2,
                     trunk_y - _VIA_PAD_M1 / 2, trunk_y + _VIA_PAD_M1 / 2, m1)
            _via_patch(c, _snap((xa + xb) / 2), trunk_y, via, cfg)
        # Los puertos del .subckt necesitan una etiqueta sobre metal para que el
        # LVS los reconozca como pines; sin ella son nets internas sin nombre.
        if net in lay.ports and net.lower() not in (_VPWR_NETS | _VGND_NETS):
            add_port_label(c, net, (access[0].x, trunk_y), info)
            labelled.add(net)

    _draw_links(lay, c, routes, links, m1, m2, via, cfg)
    return labelled


def _plan_links(lay: Layout, per_channel) -> dict[str, float]:
    """Elige la columna x por la que subira el enlace de cada net que cruza."""
    by_net: dict[str, list] = {}
    for chan_nets in per_channel.values():
        for net, acc in chan_nets:
            by_net.setdefault(net, []).append(acc)
    crossing = {n: v for n, v in by_net.items() if len(v) > 1}
    if not crossing:
        return {}

    all_access = [a for chan in per_channel.values()
                  for _, acc in chan for a in acc]
    busy = _blocked_columns(lay, all_access)
    out: dict[str, float] = {}
    #  Sitio fuera de la celda para TODAS las que crucen, no para una.
    margen = _LINK_CLEAR * (1 + len(crossing))
    for net, groups in crossing.items():
        acc = [a for g in groups for a in g]
        x = _free_column(lay, busy, acc, margen)
        if x is None:
            # No se avisa por warnings: el flujo los silencia y un enlace que
            # falta parte la net en dos, que es justo lo que el LVS reporta como
            # mismatch. Tiene que verse.
            lay.unlinked.append(net)
            continue
        out[net] = x
        busy.append((x - _LINK_CLEAR, x + _LINK_CLEAR))
        busy.sort()
    return out


def _via_groups(access) -> list[list]:
    """Agrupa los accesos de una net cuyos pads de via no cabrian separados.

    Dos pads consecutivos necesitan `_VIA_PAD_M2 + 0.28` entre centros; por
    debajo de eso se juntan en un grupo y comparten una unica via1.
    """
    sep = _VIA_PAD_M2 + 0.28
    groups: list[list] = []
    for a in sorted(access, key=lambda a: a.x):
        if groups and a.x - groups[-1][-1].x < sep:
            groups[-1].append(a)
        else:
            groups.append([a])
    return groups


def _channel_band(lay: Layout, chan) -> tuple[float, float]:
    """Banda util del canal: entre las filas que lo rodean."""
    def extreme(rows, attr, default, fn):
        vals = [getattr(pd.ref, attr) for pd in lay.placed.values()
                if pd.row in rows]
        return fn(vals) if vals else default

    if chan.name == "A":                       # entre la fila P (arriba) y N1
        lo = extreme(("n1",), "dymax", 0.0, max)
        hi = extreme(("p",), "dymin", lay.channel_y + 2, min)
    else:                                      # canal B: debajo de N2
        hi = extreme(("n2",), "dymin", 0.0, min)
        lo = hi - (chan.tracks + 1) * TRUNK_PITCH - 2 * CHANNEL_MARGIN
    return lo + CHANNEL_MARGIN, hi - CHANNEL_MARGIN


def _draw_links(lay: Layout, c: gf.Component, routes, links, m1, m2, via,
                cfg: RouteConfig):
    """Une los trunks de una misma net cuando esta en los dos canales.

    El enlace sube por una columna libre entre dispositivos de la fila N1 y va
    cambiando de capa para no cortocircuitar nada:

      - dentro de cada canal, **metal1**: cruza los demas trunks (metal2) sin
        tocarlos;
      - al atravesar el riel VGND y la fila N1, **metal2**: cruza el riel y el
        metal1 de los dispositivos sin tocarlos.

    En la fila N1 la columna tiene que esquivar los straps de S/D en metal2 de
    los multi-finger, de ahi que se busque hueco entre dispositivos.
    """
    if not links:
        return
    by_net: dict[str, list] = {}
    for net, trunk_y, access in routes:
        by_net.setdefault(net, []).append((trunk_y, access))

    b_top = _snap(min((pd.ref.dymin for pd in lay.placed.values()
                       if pd.row == "n2"), default=0.0) - CHANNEL_MARGIN)
    a_bot = _snap(max((pd.ref.dymax for pd in lay.placed.values()
                       if pd.row == "n1"), default=0.0) + CHANNEL_MARGIN)

    for net, x in links.items():
        segs = sorted(by_net[net], key=lambda s: s[0])
        y_lo, y_hi = segs[0][0], segs[-1][0]
        # El cambio de capa se hace en los bordes de cada canal: asi las cuatro
        # via1 quedan a >= un paso de trunk unas de otras, muy por encima del
        # espaciado minimo de via1 (0.26).
        # Cada tramo se pasa _LINK_OV del punto de cambio: una via1 une metal1
        # con metal2 y necesita **las dos** capas encima. Acabando los tramos
        # justo en la frontera, cada via quedaba con metal1 solo por debajo y
        # metal2 solo por encima, y el enlace no conectaba (el LVS lo veia como
        # la net partida en dos).
        pad, ov = _VIA_PAD_M2 / 2, _LINK_OV
        _box(c, x - pad, x + pad, y_lo - ov, b_top + ov, m1)   # canal B
        _box(c, x - pad, x + pad, a_bot - ov, y_hi + ov, m1)   # canal A
        _box(c, x - pad, x + pad, b_top - ov, a_bot + ov, m2)  # N2, riel y N1
        for y in (y_lo, b_top, a_bot, y_hi):
            _via_patch(c, x, y, via, cfg)


# Separacion minima entre columnas de enlace: manda el metal2 (pad 0.38 +
# espaciado 0.28). Con 0.45 dos columnas quedaban a 0.5 y violaban tanto el
# espaciado de metal2 como el de via1 (0.26 entre bordes = 0.52 entre centros).
_LINK_CLEAR = 0.70
# Solape de cada tramo mas alla del cambio de capa. Tiene que cubrir la media
# via1 (0.13) y quedarse por debajo de 0.19, o el metal2 de la columna se acerca
# a menos de 0.28 al pad del trunk mas proximo del canal (M2.2a).
_LINK_OV = 0.16


def _blocked_columns(lay: Layout, all_access) -> list[tuple[float, float]]:
    """Intervalos x por los que NO puede pasar una columna de enlace.

    Al cruzar las filas la columna va en metal2, asi que ahi solo le estorba el
    metal2: los straps de S/D de los multi-finger. Los dispositivos de un solo
    dedo no llevan metal2 ninguno y se puede pasar por encima — bloquear su
    bounding box entero dejaba la fila sin un hueco libre y 5 de los 6 enlaces
    se quedaban sin sitio.
    """
    out = []
    for pd in lay.placed.values():
        if pd.row in ("n1", "n2") and pd.wd.nf > 1:
            out.append((pd.ref.dxmin - _LINK_CLEAR, pd.ref.dxmax + _LINK_CLEAR))
    # dentro de los canales la columna va en metal1 y si estorba a los stubs
    for a in all_access:
        out.append((a.x - _LINK_CLEAR, a.x + _LINK_CLEAR))
    return sorted(out)


def _free_column(lay: Layout, busy, access, margen: float = _LINK_CLEAR) -> float | None:
    """x libre para la columna, lo mas cerca posible de los pines de la net.

    Se permite salirse de la celda por los lados: ensancharla sale mucho mas
    barato que dejar la net partida en dos, que es un fallo de LVS.

    **`margen` crece con cuantas nets tengan que cruzar.** Con un solo
    `_LINK_CLEAR` a cada lado caben dos enlaces fuera y no mas, y a partir de
    ahi `_plan_links` empieza a devolver `None`. Medido en WEIGHT_COMP cuando el
    esquematico gano la quinta rama --de 23 transistores a 25--: tres nets sin
    enlace de golpe (`x2_net1`, `OUT`, `OUT_N`), o sea tres nets partidas en dos
    y un LVS que no casa. Las columnas de dentro estaban todas ocupadas y fuera
    no quedaba sitio. Un par de micras de ancho es un precio ridiculo al lado de
    eso.
    """
    want = sum(a.x for a in access) / len(access)
    step = _LINK_CLEAR / 2
    lo_lim, hi_lim = -margen, lay.width + margen
    for k in range(int((hi_lim - lo_lim) / step) + 2):
        for x in (_snap(want + k * step), _snap(want - k * step)):
            if x < lo_lim or x > hi_lim:
                continue
            if all(x <= lo or x >= hi for lo, hi in busy):
                return x
    return None


def _below_graph(prepared, cfg: RouteConfig) -> dict[str, set[str]]:
    """A -> {B,...} significa 'el trunk de A va por debajo del de B'.

    Si la net A tiene un pin en la fila n (su stub sube) y la net B uno en la
    fila p (su stub baja) casi en la misma x, los dos stubs comparten columna:
    solo dejan de pisarse si el trunk de A queda **por debajo** del de B, porque
    asi cada stub se queda en su mitad del canal. Es la restriccion vertical
    clasica del ruteo de canales, y es lo que fallaba antes de la iteracion #6:
    `x1_net6` (pin abajo) tenia el trunk alto y `WE` (pin arriba) el bajo, asi
    que sus stubs cruzaban el canal entero y se solapaban 0.095 um -> corto.
    """
    sep = max(cfg.stub_w, _VIA_PAD_M1) + _M1_SPACING
    access_of = dict(prepared)
    below: dict[str, set[str]] = {n: set() for n, _ in prepared}
    for na, aa in prepared:
        bots = [p.x for p in aa if p.side == "bot"]
        if not bots:
            continue
        for nb, ab in prepared:
            if na == nb:
                continue
            for pb in ab:
                if pb.side == "top" and any(abs(x - pb.x) < sep for x in bots):
                    below[na].add(nb)
                    break
    return below


def _assign_tracks(prepared, cfg: RouteConfig, links=None) -> list[list[str]]:
    """Reparte las nets en pistas compartidas (left-edge con restricciones).

    Dos nets caben en la misma pista si sus trunks no se solapan en x. Se
    recorren de izquierda a derecha y cada una se mete en la pista mas baja
    donde quepa, que es el algoritmo *left-edge* de toda la vida; la novedad
    frente a darle una pista a cada net es que asi el canal necesita muchas
    menos y la celda adelgaza.

    Las restricciones verticales mandan sobre el empaquetado: una net solo entra
    en la pista actual si ya se colocaron todas las que deben ir por debajo. Eso
    ademas garantiza que dos nets con restriccion entre ellas nunca compartan
    pista, que seria tanto como ignorarla.

    Si quedara un ciclo (A debe ir bajo B y B bajo A) no hay reparto que lo
    resuelva: haria falta partir un trunk en dos pistas unidas por un tramo
    vertical (*dog-leg*). Ese caso se coloca solo en su pista y se avisa.
    """
    sep = _VIA_PAD_M2 + 0.28 + 0.08   # +0.08 de margen sobre el minimo de metal2
    access_of = dict(prepared)
    below = _below_graph(prepared, cfg)

    preds: dict[str, set[str]] = {n: set() for n, _ in prepared}
    for na, outs in below.items():
        for nb in outs:
            preds[nb].add(na)

    # El span incluye la columna del enlace: el trunk tiene que llegar hasta
    # ella, y ese estirado cambia con quien puede compartir pista.
    links = links or {}

    def span_of(n, acc):
        xs = [p.x for p in acc]
        if n in links:
            xs.append(links[n])
        return min(xs), max(xs)

    span = {n: span_of(n, acc) for n, acc in prepared}
    # a igualdad de borde izquierdo, primero la de mas pines (trunk mas largo)
    remaining = sorted((n for n, _ in prepared),
                       key=lambda n: (span[n][0], -len(access_of[n])))

    tracks: list[list[str]] = []
    while remaining:
        track: list[str] = []
        cursor = None
        for n in remaining:
            if preds[n]:
                continue                      # aun falta alguna que va debajo
            lo, hi = span[n]
            if cursor is not None and lo < cursor + sep:
                continue                      # se solaparia con la anterior
            track.append(n)
            cursor = hi
        if not track:                         # ciclo de restricciones
            n = min(remaining, key=lambda n: len(preds[n]))
            warnings.warn(f"ciclo de restricciones verticales en '{n}': "
                          f"haria falta un dog-leg", stacklevel=2)
            track = [n]
        for n in track:
            remaining.remove(n)
            for s in preds.values():
                s.discard(n)
        tracks.append(track)
    return tracks


@dataclass
class _Access:
    """Punto por donde un stub baja/sube desde un pin hasta su trunk."""

    x: float          # x elegida (arranca en el centro del pad)
    y_edge: float     # borde del dispositivo desde el que sale el stub
    x_lo: float       # margen de maniobra: el stub debe seguir sobre el pad
    x_hi: float
    side: str = "bot"  # 'bot' = el stub sube hacia su trunk / 'top' = baja
    channel: str = "A"  # canal al que llega este pin
    trunk_y: float = 0.0
    w: float = 0.0     # ancho propio; 0 = el del stub
    owner: str = ""    # dispositivo, para no separar un stub de su propio pad
    term: str = ""     # 'gate' / 'source' / 'drain'
    obstacle: bool = False   # no se dibuja: solo ocupa sitio (pads de gate)
    #: Its x is NOT negotiable, but unlike an obstacle it IS drawn. A stub
    #: that escapes a SHARED source/drain block has no pad to slide on: it
    #: has to land on the block's own contact strip, so sliding it in x does
    #: not merely risk an M1.2a -- it takes the via off the metal1 and the
    #: net comes out OPEN. Measured in OPAM_LIN_flat: net13's escape was
    #: pushed 0.625 um off a 0.36 um strip and split the net in two, and the
    #: only warning was the M1.2a one, which reads as harmless.
    fijo: bool = False
    salto: float | None = None   # y donde acaba el salto por metal2 (v2)
    en_m3: bool = False          # su trunk va en metal3 sobre la fila (v2)
    y_hop: float = 0.0           # y donde el stub pasa de metal1 a metal2

    @property
    def y_span(self) -> tuple[float, float]:
        return min(self.y_edge, self.trunk_y), max(self.y_edge, self.trunk_y)


#: Largo minimo util de un trunk. No es una regla de DRC: es lo que necesita un
#: condensador para colgar su pila de vias (un pad de 0.40 con margen a los dos
#: lados) y encontrar sitio donde el metal2 vecino se lo permita.
_MIN_TRUNK = 3.0
#: Y mas para los que ademas son PUERTO del bloque: a esos hay que poder ponerles
#: la plataforma de metal3 con la que el top les baja una via, y con 3 um los
#: cuatro pesos de WEIGHT_COMP se quedaban sin un solo punto libre.
_MIN_TRUNK_PORT = 6.0


def _stretch_short_trunks(spans, lay, cfg) -> None:
    """Alarga los trunks demasiado cortos hasta donde deja su propia pista.

    Una net de solo dos pines juntos deja un trunk minusculo: `OUT` en el OPAM
    mide 1.77 um y de ahi no sale un solo punto donde apoyar la pila de un MIM,
    asi que los condensadores se quedaban sin colocar. Los trunks de una misma
    pista comparten `trunk_y` y por construccion no se solapan en x, de modo que
    el hueco hasta el vecino es exactamente lo que se puede aprovechar.
    """
    by_track = {}
    for (net, y), xs in spans.items():
        by_track.setdefault(y, []).append((net, xs))
    for y, items in by_track.items():
        items.sort(key=lambda it: it[1][0])
        for i, (net, xs) in enumerate(items):
            want_len = _MIN_TRUNK_PORT if net in lay.ports else _MIN_TRUNK
            if xs[1] - xs[0] >= want_len:
                continue
            # Entre dos trunks de la misma pista no basta el espaciado de metal2:
            # el PAD de via (0.38) sobresale 0.19 del extremo del trunk (0.28 de
            # alto), asi que hay que dejar sitio para el. Con solo 0.28 salia una
            # M2.2a de 0.09 en COMP, entre el pad de un trunk y el vecino.
            room = _M2_SPACING + _VIA_PAD_M2 - cfg.trunk_w / 2
            lo = items[i - 1][1][1] + room if i else -0.5
            hi = items[i + 1][1][0] - room if i + 1 < len(items) else lay.width + 0.5
            want = (want_len - (xs[1] - xs[0])) / 2
            xs[0] = _snap(max(lo, xs[0] - want))
            xs[1] = _snap(min(hi, xs[1] + want + max(0.0, lo - (xs[0] - want))))


def _gate_pad_obstacles(lay, chan, cfg) -> list:
    """Pads de contacto de gate que asoman al canal, como obstaculos fijos.

    El reparto de stubs solo se miraba entre stubs, y con las cadenas de
    difusion los dispositivos quedan mucho mas juntos: un stub S/D acaba pasando
    a 0.20 um del pad de gate del VECINO (M1.2a pide 0.23). El pad es ancho —mide
    el largo de canal, 1.0 um con L=1u— y sobresale del borde de la fila justo
    por donde cruzan los stubs.

    Se modelan como accesos fijos (`x_lo == x_hi`) para que el mismo solver exacto
    los tenga en cuenta; no se dibujan, ya vienen en el PCell.
    """
    out = []
    for name, pd in lay.placed.items():
        if pd.row not in chan.rows or pd.wd.nf != 1 or pd.wd.rotated:
            # Girado, el contacto de puerta ya no asoma al canal: baja por un
            # riser lateral y llega al borde como un terminal mas.
            continue
        for pname in ("G_bot", "G_top"):
            port = next((p for p in pd.ref.ports if p.name == pname), None)
            if port is None:
                continue
            gx, gy = port.dcenter
            # el pad ocupa una franja de _PC_H de alto centrada en el puerto: sin
            # darle alto, `_required_sep` lo veria como un punto y no cruzaria con
            # ningun stub
            out.append(_Access(x=_snap(gx),
                               y_edge=_snap(gy - _PC_H / 2),
                               x_lo=_snap(gx), x_hi=_snap(gx),
                               side="bot" if pname == "G_bot" else "top",
                               channel=chan.name,
                               trunk_y=_snap(gy + _PC_H / 2),
                               w=max(pd.wd.L, 0.36),
                               owner=name, obstacle=True))
    return out


_PC_H = 0.36    # alto del bloque de contacto de gate (device_map._GF180_PC_H)
_END_CAP = 0.22  # poly que sobresale de la difusion (device_map._GF180_END_CAP)

#: Paso entre trunks de metal3 sobre la fila. Mismo criterio que en el canal: el
#: pad de la via2 (0.38) mas el espaciado de metal (0.28).
_M3_PITCH = 0.38 + 0.28        # `_VIA_PAD_M2` + espaciado, definido mas abajo
#: Margen del borde de la fila al primer trunk de metal3.
_M3_MARGEN = 0.4


def _required_sep(a: _Access, b: _Access, stub_w: float) -> float:
    """Separacion minima entre los centros de dos stubs, 0 si no se cruzan."""
    if a.obstacle and b.obstacle:
        return 0.0                              # dos pads fijos: no hay nada que mover
    if (a.obstacle or b.obstacle) and a.owner and a.owner == b.owner:
        # Solo se exime el stub de GATE, que tiene que salir encima de su pad.
        # Los de S/D del mismo dispositivo si deben respetar los 0.23: es lo que
        # calcula `_sd_track_x`, y sin esta distincion el reparto los volvia a
        # empujar hacia el pad y reaparecia la M1.2a de 0.20.
        other = b if a.obstacle else a
        if other.term == "gate":
            return 0.0
    if a.obstacle or b.obstacle:
        # pad ancho contra stub: la separacion la fijan sus anchos reales
        wa = a.w or stub_w
        wb = b.w or stub_w
        a0, a1 = a.y_span
        b0, b1 = b.y_span
        if min(a1, b1) <= max(a0, b0):
            return 0.0
        return (wa + wb) / 2 + _M1_SPACING
    # Dos pines en el MISMO trunk tienen sus pads de via a la misma altura, asi
    # que se pisan aunque sus stubs salgan en direcciones opuestas y no compartan
    # franja vertical. Pasa con dos pines de una misma net, uno en cada fila:
    # las dos via1 se fusionan en una de 0.46 um y V1.1 exige 0.26 exactos.
    if abs(a.trunk_y - b.trunk_y) < _VIA_PAD_M2:
        return max(_VIA_PAD_M2 + 0.28,          # pads de metal2
                   _VIA_PAD_M1 + _M1_SPACING,   # pads de metal1
                   _VIA1_SIZE * 2)              # las via1 no pueden tocarse
    a0, a1 = a.y_span
    b0, b1 = b.y_span
    if min(a1, b1) <= max(a0, b0):
        return 0.0                              # no comparten franja vertical
    sep = stub_w + _M1_SPACING
    half = _VIA_PAD_M1 / 2
    for p, q in ((a, b), (b, a)):               # el pad de via de uno sobre el otro
        q_lo, q_hi = q.y_span
        if q_lo - half < p.trunk_y < q_hi + half:
            sep = max(sep, (stub_w + _VIA_PAD_M1) / 2 + _M1_SPACING)
    return sep


def _spread_stubs(routes, cfg: RouteConfig, extra=(), room=None) -> float:  # noqa: D401
    """Separa en x los stubs que se pisan, deslizandolos sobre su propio pad.

    Los pines de nets distintas pueden caer a menos de un espaciado de metal1
    unos de otros, y sus stubs cruzan el mismo canal: eso daba violaciones
    M1.2a y, cuando el solape era grande, llegaba a cortocircuitar dos nets. Los
    pads dan holgura (el de gate mide ~L, el de S/D 0.36), asi que se recorre la
    lista de izquierda a derecha empujando cada stub lo justo, sin sacarlo nunca
    de su pad. Solo se exige separacion entre stubs que comparten franja
    vertical: gastar holgura en pares que ni se cruzan dejaba sin margen a los
    que si lo hacen.

    Un solo barrido voraz de izquierda a derecha NO basta, aunque lo pareciera:
    **solo empuja a la derecha**, asi que un stub que ya esta en su x_hi no puede
    ceder y el roce se quedaba, mudo, como una M1.2a de centesimas (en COMP:
    net3 a 0.485 de 0.515 del pad de via de net4). Relajar despues tirando del
    vecino de la izquierda tampoco vale: oscila, porque mover uno para arreglar
    un par rompe el siguiente y viceversa.

    El problema es exactamente un sistema de **restricciones de diferencia** en
    1-D (x_j - x_i >= sep_ij, con cada x_i dentro de su pad), asi que se resuelve
    de una vez y bien:

    1. hacia la derecha, la posicion **minima viable** de cada stub;
    2. hacia la izquierda, cada uno tan cerca de su pin como permitan los que ya
       estan colocados a su derecha.

    El segundo paso siempre da una solucion valida si la hay: por la recurrencia
    del paso 1, x_i - sep_ki >= lo_k para todo k a la izquierda, asi que ninguno
    se queda sin sitio. La calidad tambien importa — el stub debe quedar sobre su
    propio pad —, y por eso el paso 2 va de derecha a izquierda buscando la
    posicion preferida en vez de amontonarlo todo contra el borde izquierdo.

    Devuelve el peor deficit que no cabe (0.0 si todo cuadra): quien llama tiene
    que avisar, o volveria a ser un fallo silencioso.
    """
    room = {} if room is None else room
    stubs = sorted([a for *_, access in routes for a in access] + list(extra),
                   key=lambda a: a.x)
    n = len(stubs)
    pref = [a.x for a in stubs]
    sep = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            sep[i][j] = _required_sep(stubs[j], stubs[i], cfg.stub_w)

    lo = [0.0] * n                              # 1) posicion minima viable
    for j in range(n):
        if stubs[j].obstacle or stubs[j].fijo:
            # geometria fija del PCell: no se negocia, y dejar que la recurrencia
            # la empujase inflaba el limite de todos los de su derecha. `fijo` is
            # the same deal for a shared-block escape: it is the neighbours that
            # give way, because this one cannot leave its contact strip.
            lo[j] = stubs[j].x
            continue
        v = stubs[j].x_lo
        for i in range(j):
            if sep[i][j]:
                v = max(v, lo[i] + sep[i][j])
        lo[j] = _snap(v)

    worst = max((lo[j] - stubs[j].x_hi
                 for j in range(n)
                 if not stubs[j].obstacle and not stubs[j].fijo), default=0.0)

    for j in range(n - 1, -1, -1):              # 2) lo mas cerca del pin posible
        if stubs[j].obstacle or stubs[j].fijo:
            continue          # ni un pad de gate ni un escape de bloque se mueven
        hi = stubs[j].x_hi
        for k in range(j + 1, n):
            if sep[j][k]:
                hi = min(hi, stubs[k].x - sep[j][k])
        #  **NUNCA FUERA DEL PAD.** `lo[j]` es la posicion minima viable de la
        #  recurrencia, y puede pasarse de `x_hi` cuando el canal no da de si.
        #  Dejarla pasar saca el stub de su pad de S/D y la net queda ABIERTA:
        #  es el mismo fallo que el escape de bloque compartido de OPAM_LIN_flat
        #  --net13, la via1 a 0.185 um de la tira de contacto-- y se anunciaba
        #  igual de mal, como un `AVISO: stubs justos` que suena a M1.2a de
        #  centesimas. Con el techo puesto, lo que no cabe sale como violacion de
        #  espaciado en el DRC, que se ve; un abierto no lo ve nadie hasta el LVS,
        #  y en el top ni eso.
        x = max(lo[j], min(pref[j], hi))
        stubs[j].x = _snap(min(stubs[j].x_hi, max(stubs[j].x_lo, x)))

    # Lo que despues de todo sigue sin caber contra un PAD DE GATE se le pide al
    # placement: el stub ya esta en el borde de su propio pad y no puede ceder
    # mas, y el pad de gate viene fijo en el PCell. Se mide sobre la posicion
    # FINAL y solo contra los pads, no contra el resto de restricciones: la de
    # 'mismo trunk' es conservadora (pide 0.66 aunque sean de la misma net, donde
    # el metal simplemente se fusiona) y realimentarla regalaba micras de ancho.
    for i, a in enumerate(stubs):
        if not a.obstacle:
            continue
        for b in stubs:
            if b.obstacle or not b.owner:
                continue
            s = _required_sep(a, b, cfg.stub_w)
            need = s - abs(a.x - b.x)
            if s and need > _GRID / 2:
                room[b.owner] = max(room.get(b.owner, 0.0), _snap(need))
    return max(worst, 0.0)


def _nets_a_metal3(lay: Layout, chan, prepared, atadas):
    """Reparte las nets del canal entre las que suben a metal3 y las que se quedan.

    **El canal se lleva ~40 % del alto de estas celdas** —13 pistas en `COMP`— y
    metal3 esta practicamente vacio por encima de las filas de transistores: solo
    lo pisan los risers de los MIM, las plataformas de puerto y el cruce de la
    resistencia, y todos viven en el canal. Subir alli los trunks que puedan es la
    ganancia grande que quedaba.

    **Sube la net que no la necesita nadie mas.** Se quedan en metal2, dentro del
    canal, las que son PUERTO (su plataforma de metal3 cuelga del trunk), las de
    un CONDENSADOR (su riser se agarra al trunk buscando metal2 libre) y las de una
    RESISTENCIA (su terminal cruza a metal3 y aterriza sobre el trunk). Esas tres
    familias son las que `caps`, `resistors` y `power` leen de `lay.trunks` dando
    por hecho que es metal2, asi que dejandolas abajo **no hay que tocar ninguno
    de los tres**: los trunks de metal3 sencillamente no se apuntan.

    Medido, lo que queda en el canal despues de subir el resto:

        COMP           13 pistas -> 3
        OPAM           13 -> 4          OPAM_LIN_flat  13 -> 4
        WEIGHT_COMP    11 -> 4          DECODER         6 -> 4

    Solo el canal A, que es el que tiene la fila P encima. El B queda como estaba.
    """
    if not (lay.opts.v2 and lay.opts.trunks_m3) or chan.name != "A":
        return [], prepared
    arriba, canal = [], []
    for net, acc in prepared:
        (canal if net in atadas else arriba).append((net, acc))
    return arriba, canal


def _banda_m3(lay: Layout) -> tuple[float, float]:
    """Banda de y utilizable para trunks de metal3, sobre la fila P.

    Va por ENCIMA de los transistores, que es donde metal3 esta libre, y no cuesta
    ni una micra de celda: es una capa distinta sobre area ya ocupada. Se deja
    margen al riel, cuya barra de metal3 la dibuja `power.add_power_access` a todo
    lo ancho del bloque.
    """
    ys = [pd.ref for pd in lay.placed.values() if pd.row == "p"]
    if not ys:
        return 0.0, 0.0
    lo = min(r.dymin for r in ys) + _M3_MARGEN
    hi = max(r.dymax for r in ys) - _M3_MARGEN
    return _snap(lo), _snap(hi)


def _acceso_bloque(lay: Layout, xc: float, row: str, ref_dev: str):
    """Acceso que sale de un bloque S/D COMPARTIDO, saltando el pad de gate.

    Un bloque compartido tiene puerta a los dos lados por definicion, asi que un
    stub de metal1 que salga de el pasa por encima del pad de contacto de gate
    del vecino -- medido, **0.155 um entre centros cuando `M1.2a` pide 0.845**.
    Por eso `_can_join` no dejaba abutir ninguna net que tuviera que salir del
    par, y por eso la v1 se quedaba en 7 abutments por fila en `COMP` cuando el
    circuito permite 13.

    La salida es cambiar de capa donde estorba: el stub arranca en el bloque, sube
    a **metal2** con una via1, cruza la banda del pad de gate --que es metal1, asi
    que no hay regla que los separe-- y vuelve a metal1 con otra via1 ya dentro
    del canal. `salto` marca esa segunda y.

    La banda del pad de gate va de la difusion a `END_CAP + PC_H` = 0.58 um hacia
    afuera; se sale de ella con el espaciado de `M1.2a` (0.23) mas medio pad de
    via (0.17).
    """
    pd = lay.placed[ref_dev]
    W = pd.wd.W
    channel = "B" if row == "n2" else "A"
    side = "top" if row in ("p", "n2") else "bot"
    fuera = _END_CAP + _PC_H + _M1_SPACING + _VIA_PAD_M1 / 2
    if side == "bot":                       # el canal le queda ARRIBA
        y_edge = _snap(pd.y + W / 2)
        salto = _snap(pd.y + W + fuera)
    else:                                   # el canal le queda ABAJO
        y_edge = _snap(pd.y + W / 2)
        salto = _snap(pd.y - fuera)
    x = _snap(xc)
    #  Sin holgura en x: el bloque esta encajonado entre las dos puertas y el
    #  stub tiene que salir por su centro.
    #  `fijo`: x_lo == x_hi already says there is no slack, but `_spread_stubs`
    #  used to push past x_hi and only warn about M1.2a. Here that warning is
    #  wrong -- off the strip means an open net, not a tight spacing.
    return _Access(x=x, y_edge=y_edge, x_lo=x, x_hi=x, side=side,
                   channel=channel, owner=ref_dev, term="drain", salto=salto,
                   fijo=True)


def _pin_access(lay: Layout, inst: str, term: str):
    pd = lay.placed.get(inst)
    if pd is None:
        return None
    kind = pd.wd.kind
    # Cada fila alcanza un canal y desde un lado:
    #   P  -> canal A, bajando      N1 -> canal A, subiendo
    #   N2 -> canal B, bajando (su canal esta debajo)
    # De ese lado depende la restriccion vertical al asignar trunks.
    channel = "B" if pd.row == "n2" else "A"
    #  `span` va a la altura de la fila N1 (`placement`: `ref.dmovey(n1_base_y -
    #  ...)`), o sea DEBAJO del canal, aunque su pozo suba hasta la P. Estaba
    #  cayendo en el `else` y se rutaba como si estuviera encima: se le pedia el
    #  contacto de gate de ABAJO (`G_bot`) y el stub salia por el borde inferior
    #  del dispositivo para subir 12 um hasta su trunk, atravesando de paso el
    #  metal1 de sus PROPIOS terminales. En `OPAM_LIN_flat` eso fundia la puerta
    #  de los cuatro XM43 (`G_OUT_P`) con su drenador (`OUT`): un corto que el
    #  DRC no ve --dos metales que se tocan no violan ningun espaciado-- y que
    #  solo canto el LVS. Medido: cinco tiras de metal1 cruzando de y=2.38 a
    #  y=14.55, del borde de abajo del dispositivo al trunk de arriba.
    side = "top" if pd.row in ("p", "n2") else "bot"
    if term == "gate":
        # el contacto de gate que mira hacia el canal
        pname = "G_top" if side == "bot" else "G_bot"
        if pname not in pd.ref.ports:
            return None
        port = pd.ref.ports[pname]
        x, y = port.dcenter
        return _access(x, y, port, lay.pdk, side, channel, inst, term)
    pname = "S" if term == "source" else "D"
    if pname not in pd.ref.ports:
        return None
    px, py = pd.ref.ports[pname].dcenter
    # El stub arranca en el centro del pad S/D, no en el borde del bounding box:
    # el bbox lo marcan dualgate y los pads de gate, que sobresalen bastante por
    # encima del pad de metal1 (que solo llega a y=W). Arrancando en el borde,
    # el stub quedaba en el aire y la net se partia en dos.
    stub_w = RouteConfig.minimum(lay.pdk).stub_w
    x = _snap(_sd_track_x(pd, term, px, stub_w))
    # El pad de gate del propio dispositivo fija esta x por un lado, pero por el
    # otro queda algo de holgura: el stub puede alejarse del gate sin salirse del
    # pad S/D. Poca, pero suficiente para que `_spread_stubs` resuelva roces de
    # centesimas contra el pad de via del vecino.
    # La holgura va SIEMPRE alejandose del gate, y de que lado esta el gate lo
    # dice la geometria, no el nombre del terminal (el espejo que intercambia S y
    # D invierte el nombre pero no el sitio).
    out = -_SD_SLACK if px < pd.ref.dxmin + pd.ref.dxsize / 2 else _SD_SLACK
    lo, hi = sorted((x, _snap(x + out)))
    return _Access(x=x, y_edge=_snap(py), x_lo=lo, x_hi=hi, side=side,
                   channel=channel, owner=inst, term=term)


_SD_SLACK = 0.10          # cuanto puede alejarse del gate un stub de S/D


def _access(x, y_edge, port, pdk: str, side: str, channel: str,
            owner: str = "", term: str = "") -> _Access:
    cfg_w = RouteConfig.minimum(pdk).stub_w
    slack = _snap(max(0.0, (port.dwidth - cfg_w) / 2.0))
    x = _snap(x)
    return _Access(x=x, y_edge=_snap(y_edge), x_lo=x - slack, x_hi=x + slack,
                   side=side, channel=channel, owner=owner, term=term)


def _hseg(c, x0, x1, y, h, layer):
    if x1 <= x0:
        x1 = x0 + 0.2
    _rect(c, x0, y - h / 2, x1, y + h / 2, layer)


# via1 en GF180 es tamano EXACTO 0.26 (V1.1, min y max a la vez). El pad de
# aterrizaje mide 0.34 en AMBOS metales: metal2 lo necesita por el enclosure de
# 0.01 (V1.4a) y metal1 por V1.3d (si el solape es < 0.04 por un lado exige que
# solapen los bordes adyacentes). Ademas, al medir >= 0.34, la linea queda
# exenta de las reglas end-of-line V1.3c / V1.4b / V1.4c. Achicar el pad de
# metal1 a 0.26 para descongestionar el canal dispara 43 x V1.3d: no es opcion.
# En metal2 el pad ademas tiene que valerse por si solo: en un trunk corto o en
# un enlace entre canales queda como poligono aislado y M2.3 pide 0.1444 um2 de
# area minima, o sea 0.38 de lado. En metal1 no hace falta porque el pad siempre
# se fusiona con su stub, y dejarlo en 0.34 ahorra espacio en x, que en el canal
# es justo lo que escasea.
_VIA1_SIZE = 0.26
_VIA_PAD_M2 = 0.38
_VIA_PAD_M1 = 0.34


def _via2_patch(c, x, y, via_layer, m2, m3):
    """Pila via2 con sus pads de metal2 y metal3, para subir un stub a metal3."""
    gf180 = get_pdk_module("gf180")
    for layer in (m2, m3):
        r = c.add_ref(gf.components.rectangle(size=(_VIA_PAD_M2, _VIA_PAD_M2),
                                              layer=layer))
        r.dmove((x - _VIA_PAD_M2 / 2, y - _VIA_PAD_M2 / 2))
    half = _VIA1_SIZE / 2
    c.add_ref(gf180.via_generator(
        x_range=(x - half, x + half), y_range=(y - half, y + half),
        via_layer=via_layer, via_size=(_VIA1_SIZE, _VIA1_SIZE),
        via_enclosure=(0.0, 0.0), via_spacing=(_VIA1_SIZE, _VIA1_SIZE)))


def _via_patch(c, x, y, via_layer, cfg: RouteConfig):
    gf180 = get_pdk_module("gf180")
    m1, m2, _ = _routing_layers("gf180")
    for layer, size in ((m1, _VIA_PAD_M1), (m2, _VIA_PAD_M2)):
        r = c.add_ref(gf.components.rectangle(size=(size, size), layer=layer))
        r.dmove((x - size / 2, y - size / 2))
    half = _VIA1_SIZE / 2
    v = gf180.via_generator(
        x_range=(x - half, x + half), y_range=(y - half, y + half),
        via_layer=via_layer, via_size=(_VIA1_SIZE, _VIA1_SIZE),
        via_enclosure=(0.0, 0.0), via_spacing=(_VIA1_SIZE, _VIA1_SIZE))
    c.add_ref(v)


if __name__ == "__main__":
    from coil_layout.pdk_manager import activate_pdk
    from coil_layout.spice_parser import parse_spice
    from coil_layout.placement import build_layout

    activate_pdk("gf180")
    nl = parse_spice(open("examples/bias.spice").read())
    lay = build_layout(nl, "gf180")
    route_layout(lay)
    lay.component.write_gds("out_routed.gds")
    print(f"routed; final size {lay.component.dxsize:.2f} x {lay.component.dysize:.2f}")
