"""Mapeo de un Device de la netlist al PCell del PDK, envuelto con puertos.

Los PCells de GF180 no exponen puertos ni dibujan metal1 sobre source/drain
(con bulk='None' solo hay difusion + contactos). Por eso aqui:

  1. Instanciamos el PCell real del PDK (con todas sus variables).
  2. Calculamos analiticamente la posicion de los terminales S / D / G.
  3. Anadimos pads de metal1 sobre los contactos y puertos nombrados,
     de modo que placement y routing puedan conectar de forma uniforme.

Tambien expone la metadata geometrica (longitud de difusion 'l_d', ancho del
bloque de contacto) que necesita el abutment por difusion compartida.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

warnings.filterwarnings("ignore")

import gdsfactory as gf
import klayout.db as kdb

from coil_layout.pdk_manager import get_info, get_pdk_module
from coil_layout.spice_parser import Device

# Constantes geometricas de los PCells de GF180 (de gf180/fet.py).
_GF180_CON_SIZE = 0.22
_GF180_CON_COMP_ENC = 0.07
_GF180_END_CAP = 0.22
_GF180_SD_BLOCK = 0.36          # ancho del bloque de contacto S/D (sd_con_col=1)
# El default del PCell (0.24) mete un contacto de 0.22 entre dos gates dejando
# 0.01 um por lado, cuando CO.7 pide 0.15: 0.22 + 2*0.15 = 0.52 es el minimo.
# Ademas 0.52 >= poly2_spacing + 2*pc_ext (0.32), lo que hace que fet.py tome la
# rama e_c=0 -> por eso _GF180_ALT_EC vale 0.
_GF180_INTER_SD_L = 0.52
_GF180_PC_H = 0.36              # alto del bloque de contacto de poly
_GF180_ALT_EC = 0.0             # extra de poly con gate alternating (rama e_c=0)

# geometria del wrapper multi-finger (nf > 1):
_GF180_VIA1 = 0.26              # via1 es tamano EXACTO 0.26 (regla V1.1)
_GF180_STRAP_H = 0.34           # alto strap S/D en metal2 (>=0.34 evita V1.4b EOL)
_GF180_STRAP_END = 0.19         # extension del strap tras el centro de la ultima
                                # via1: 0.13 (media via) + 0.06 de EOL (V1.4c)
_GF180_RISER_W = 0.30           # ancho de los risers laterales S/D en metal1
_GF180_RISER_GAP = 0.25         # riser a bloque S/D (> min spacing m1 0.23)
_GF180_GATE_RISER_W = 0.28      # riser de gate sobre el dedo 0
_MF_PAD_INSET = 0.02            # retranqueo vertical de los pads S/D internos
# limites para que quepan straps y riser (flatten_spice usa los mismos):
MULTIFINGER_MIN_W = 1.2
MULTIFINGER_MIN_L = 0.8


@dataclass
class WrappedDevice:
    """Dispositivo listo para colocar: componente con puertos + metadata."""

    name: str                 # instancia (XM4)
    component: gf.Component    # PCell envuelto con pads/puertos
    kind: str                 # 'p' o 'n'
    W: float
    L: float
    nf: int
    l_d: float                # longitud de la difusion intrinseca (para abutment)
    sd_block: float           # ancho del bloque de contacto S/D
    nodes: dict[str, str]     # mapa terminal->net del Device original
    pdk: str
    rotated: bool = False     # canal largo: girado 90 grados (ver _rotate_gf180)


# ---------------------------------------------------------------------------
#  Mapeo modelo SPICE -> (funcion PCell, kwargs base)
# ---------------------------------------------------------------------------
def _gf180_volt(model: str) -> str:
    m = model.lower()
    if "05v0" in m or "5v" in m:
        return "5V"
    if "06v0" in m or "6v" in m:
        return "6V"
    return "3.3V"


def map_device(dev: Device, pdk: str, gate_con: str | None = None) -> WrappedDevice:
    """Construye el WrappedDevice para el PDK indicado.

    `gate_con` ("top" / "bottom") pide un SOLO contacto de puerta, el del lado
    que se indique. Sin el, se dibujan los dos ("alternating"), que es el
    comportamiento de la v1. Ver `_map_gf180`.
    """
    if pdk == "gf180":
        return _map_gf180(dev, gate_con)
    return _map_sky130(dev)


# ---------------------------------------------------------------------------
#  GF180
# ---------------------------------------------------------------------------
def _map_gf180(dev: Device, gate_con: str | None = None) -> WrappedDevice:
    """
    `gate_con` = "top" o "bottom" dibuja UN solo contacto de puerta, el de ese
    lado. Por defecto (`None`) se dibujan los dos, que es lo que hacia la v1.

    De los dos contactos que pone el PCell con `gate_con_pos="alternating"` solo
    se usa uno: el que mira al canal de ruteo. El otro mira al riel, no lo toca
    nadie y cuesta `_GF180_PC_H + _GF180_END_CAP` = **0.58 um** de alto por fila.
    Quitarlo es un parametro del PCell, no un dibujo a mano: su firma acepta
    "bottom", "top" y "alternating".

    **Solo para un dedo.** El envoltorio multi-finger NECESITA `alternating`:
    reparte los contactos de los dedos pares en la barra de abajo y los impares
    en la de arriba, y los ata con un riser lateral. Forzarlos todos a un lado le
    cambiaria la geometria de debajo de los pies.
    """
    gf180 = get_pdk_module("gf180")
    info = get_info("gf180")
    volt = _gf180_volt(dev.model)
    L, W, nf = dev.L_um, dev.W_um, dev.nf

    pcell_fn = gf180.pfet if dev.kind == "p" else gf180.nfet
    inner = pcell_fn(
        l_gate=L,
        w_gate=W,
        nf=nf,
        volt=volt,
        bulk="None",            # requisito: sin guard ring ni bulk tie
        gate_con_pos=(gate_con if (gate_con and nf == 1) else "alternating"),
        con_bet_fin=1,
        inter_sd_l=_GF180_INTER_SD_L,
    )

    c = gf.Component()
    ref = c.add_ref(inner)

    # --- geometria de terminales (origen del PCell: difusion intrinseca en (0,0)) ---
    inter = _GF180_INTER_SD_L
    l_d = nf * L + (nf - 1) * inter + 2 * _GF180_CON_COMP_ENC
    cmpc_y = W if W > (_GF180_CON_SIZE + 2 * _GF180_CON_COMP_ENC) else (
        _GF180_CON_SIZE + 2 * _GF180_CON_COMP_ENC)
    y0 = -(cmpc_y - W) / 2.0
    blk = _GF180_SD_BLOCK
    m1 = info.metals[0].layer          # metal1 (34,0)
    pad_layer = m1

    if nf == 1:
        # bloques de contacto S/D: izquierdo [-blk,0], derecho [l_d, l_d+blk]
        sd_ys = (y0, y0 + cmpc_y)
        _add_pad(c, (-blk, sd_ys[0]), (0.0, sd_ys[1]), pad_layer)      # source (izq)
        _add_pad(c, (l_d, sd_ys[0]), (l_d + blk, sd_ys[1]), pad_layer)  # drain (der)

        yc = W / 2.0
        c.add_port(name="S", center=(-blk / 2, yc), width=min(blk, cmpc_y),
                   orientation=180, layer=pad_layer)
        c.add_port(name="D", center=(l_d + blk / 2, yc), width=min(blk, cmpc_y),
                   orientation=0, layer=pad_layer)

        # --- gate: contactos de poly arriba y abajo (gate_con_pos='alternating') ---
        pc_x = L if L > (_GF180_CON_SIZE + 2 * _GF180_CON_COMP_ENC) else (
            _GF180_CON_SIZE + 2 * _GF180_CON_COMP_ENC)
        gx0 = _GF180_CON_COMP_ENC                  # poly.dxmin
        g_xc = gx0 + pc_x / 2.0
        pc_h = _GF180_PC_H
        # contacto inferior: y en [-pc_h-end_cap, -end_cap]; superior simetrico
        g_bot = (-pc_h - _GF180_END_CAP + pc_h / 2)    # centro y inferior
        g_top = (W + _GF180_END_CAP + pc_h / 2)        # centro y superior
        #  El pad de metal1 solo donde el PCell ha dejado contacto: taparlo donde
        #  no lo hay dejaria metal1 suelto y, peor, un puerto que el router
        #  intentaria usar.
        if gate_con != "top":
            _add_pad(c, (gx0, -pc_h - _GF180_END_CAP), (gx0 + pc_x, -_GF180_END_CAP),
                     pad_layer)
            c.add_port(name="G_bot", center=(g_xc, g_bot), width=pc_x,
                       orientation=270, layer=pad_layer)
        if gate_con != "bottom":
            _add_pad(c, (gx0, W + _GF180_END_CAP),
                     (gx0 + pc_x, W + _GF180_END_CAP + pc_h), pad_layer)
            c.add_port(name="G_top", center=(g_xc, g_top), width=pc_x,
                       orientation=90, layer=pad_layer)
    else:
        _wrap_multifinger_gf180(c, gf180, info, L, W, nf, l_d)

    c.info["kind"] = dev.kind
    c.info["l_d"] = l_d
    c.info["sd_block"] = blk
    c.info["W"] = W
    c.info["L"] = L
    c.flatten()
    _fix_pcell_co7_gf180(c, info, dev.kind, W, l_d)

    # Un dispositivo de canal largo sale mas ancho que alto y se come la fila a lo
    # ancho: M43 del OPAM (L=20u, W=0.7u) mide 22.06 x 2.66 y es el 23% del ancho
    # de la fila P. Girado ocupa 2.66 de ancho. Se decide por la FORMA, no por un
    # umbral de L: es justo la condicion que hace que estorbe.
    #  Solo un dedo: los multi-finger salen anchos por el numero de dedos, no por
    #  el canal, y ya tienen su propio esquema de risers laterales. Sin la
    #  condicion `nf == 1` se giraban seis dispositivos de COMP y otros seis de
    #  WEIGHT_COMP, que crecio de 25.00 a 34.64 um de alto sin ganar nada.
    #  Y tiene que COMPENSAR, no solo ser mas ancho que alto. Girar cuesta
    #  bastante mas que unas micras de fila: el dispositivo se va a la fila
    #  `span`, arrastra un pozo en L que baja por todo el canal de ruteo, y sus
    #  terminales dejan de salir por arriba y por abajo para hacerlo por carriles
    #  laterales, que es un camino aparte en el router.
    #
    #  `XM43` de `OPAM_LIN_flat` es el caso que lo destapo. Partido en `m=4`
    #  copias de W=0.5/L=1, cada copia mide 3.96 x 4.26 y girada 4.26 x 3.96:
    #  **se ahorraban 0.30 um**. A cambio, las cuatro copias montaron una fila
    #  `span` de 21.77 um cuyo pozo partia el canal en dos y dejaba al serpentin
    #  de la resistencia sin sitio, y sus carriles laterales cortocircuitaban la
    #  puerta con el drenador (`G_OUT_P` con `OUT`), un corto que el DRC no ve.
    #  El `M43` del `OPAM` original, que es para lo que se hizo el giro, mide
    #  22.06 x 2.66: relacion 8.3. Con 3 se separan los dos casos de sobra.
    rotated = nf == 1 and L > W and c.dxsize > _ROT_MIN_RATIO * c.dysize
    if rotated:
        c = _rotate_gf180(c, dev.kind, pad_layer, _power_terms(dev))

    return WrappedDevice(name=dev.name, component=c, kind=dev.kind, W=W, L=L, nf=nf,
                         l_d=l_d, sd_block=blk, nodes=dict(dev.nodes), pdk="gf180",
                         rotated=rotated)


#: Cuanto mas ancho que alto tiene que ser un dispositivo para que compense
#: girarlo. Ver la decision en `wrap_device`.
_ROT_MIN_RATIO = 3.0

_ROT_RISER_W = 0.30       # M1.1 pide 0.23
_ROT_RISER_GAP = 0.30     # M1.2a pide 0.23


_POWER_HINTS = {"vdd", "vcc", "vpwr", "vss", "vgnd", "gnd"}


def _power_terms(dev) -> set[str]:
    """Roles ('S', 'D', 'G') del dispositivo que cuelgan de un riel."""
    role = {"source": "S", "drain": "D", "gate": "G"}
    return {role[t] for t, net in dev.nodes.items()
            if t in role and net.lower() in _POWER_HINTS}


def _rotate_gf180(inner, kind: str, m1, power: set[str]) -> gf.Component:
    """Gira el dispositivo 90 grados y saca cada terminal por el borde que le toca.

    Girado, la difusion queda vertical: source abajo, drain arriba y los contactos
    de puerta a los lados. El router, en cambio, da por hecho que a un dispositivo
    se le entra por arriba o por abajo, porque el canal es horizontal — y un stub
    que saliera del drain (arriba) hacia el canal (abajo) tendria que cruzar el
    dispositivo entero.

    Asi que aqui se resuelve dentro del envoltorio, con carriles de metal1 pegados
    a los costados. **Y no todos van al mismo borde**: un terminal de senal busca
    el canal y uno de alimentacion busca el riel, que estan en lados opuestos.
    Mandandolos todos al canal, el strap de VDD del source salia por abajo, subia
    al riel por el medio del dispositivo y cortocircuitaba su propio drain — el
    LVS lo daba como `OUT|VDD`.

    El tramo horizontal de cada carril sale por FUERA del dispositivo. Con L larga
    el pad de puerta mide L de largo, o sea 20 um una vez girado, y su punta queda
    al lado del bloque S/D: saliendo a la altura del terminal, el brazo pasaba a
    0.10 um de esa punta (M1.2a pide 0.23).
    """
    c = gf.Component()
    r = c.add_ref(inner)
    r.rotate(90)

    pos = {p.name: tuple(p.dcenter) for p in r.ports}
    bb = r.dbbox()
    step = _ROT_RISER_GAP + _ROT_RISER_W
    edge_bot = bb.bottom - step / 2
    edge_top = bb.top + step / 2
    #  P alcanza su canal por debajo y el riel por arriba; N al reves.
    chan_edge, rail_edge = (edge_bot, edge_top) if kind == "p" else (edge_top, edge_bot)

    #  De los dos contactos de puerta se usa el que quedo mas a la derecha; el
    #  otro se deja donde esta.
    gates = sorted((n for n in pos if n.startswith("G_")), key=lambda n: pos[n][0])
    terms = [("S", "S"), ("D", "D"), (gates[-1], "G")]

    #  Los carriles no se reparten a boleo: cada terminal sale con un brazo
    #  horizontal, y un brazo que cruce el carril de otro los cortocircuita (fue
    #  el `OUT VDD VDD VDD` del LVS, con la puerta pegada al carril del source).
    #  El reparto que no cruza nada:
    #    - la puerta, cuyo brazo sale a media altura, toma el carril INTERIOR de
    #      su propio lado; ese carril solo llega hasta el borde del canal;
    #    - el terminal que sale por ese mismo borde se va al lado CONTRARIO;
    #    - el que sale por el borde opuesto toma el carril exterior del lado de
    #      la puerta, y su brazo pasa por encima sin tocar el de ella.
    g_right = pos[gates[-1]][0] > (bb.left + bb.right) / 2
    lane_in = (bb.right + step - _ROT_RISER_W / 2) if g_right else (
        bb.left - step + _ROT_RISER_W / 2)
    outer = (bb.right + 2 * step - _ROT_RISER_W / 2) if g_right else (
        bb.left - 2 * step + _ROT_RISER_W / 2)
    far = (bb.left - step + _ROT_RISER_W / 2) if g_right else (
        bb.right + step - _ROT_RISER_W / 2)

    def bar(x0, y0, x1, y1):
        h = _ROT_RISER_W / 2
        _add_pad(c, (min(x0, x1) - h, min(y0, y1) - h),
                 (max(x0, x1) + h, max(y0, y1) + h), m1)

    ports = {}
    for pname, role in terms:
        fx, fy = pos[pname]
        target = rail_edge if role in power else chan_edge
        if role == "G":
            bar(fx, fy, lane_in, fy)
            bar(lane_in, fy, lane_in, target)
            ports[pname] = lane_in
            continue
        near = edge_bot if fy - bb.bottom < bb.top - fy else edge_top
        if near == target:                      # ya sale por su lado
            bar(fx, fy, fx, target)
            ports[pname] = fx
            continue
        lane = far if near == chan_edge else outer
        bar(fx, fy, fx, near)
        bar(fx, near, lane, near)
        bar(lane, near, lane, target)
        ports[pname] = lane

    for pname, role in terms:
        y = rail_edge if role in power else chan_edge
        c.add_port(name=pname, center=(ports[pname], y), width=_ROT_RISER_W,
                   orientation=270 if y == edge_bot else 90, layer=m1)
    #  El otro contacto de puerta comparte carril con el que si se saco.
    for pname in gates:
        if pname not in ports:
            g = gates[-1]
            c.add_port(name=pname, center=c.ports[g].dcenter,
                       width=_ROT_RISER_W, orientation=c.ports[g].orientation,
                       layer=m1)

    for k in ("kind", "l_d", "sd_block", "W", "L"):
        c.info[k] = inner.info[k]
    c.info["rotated"] = True
    c.flatten()
    return c

def _wrap_multifinger_gf180(c: gf.Component, gf180, info, L: float, W: float,
                            nf: int, l_d: float) -> None:
    if W < MULTIFINGER_MIN_W or L < MULTIFINGER_MIN_L:
        raise ValueError(
            f"multi-finger gf180 necesita W>={MULTIFINGER_MIN_W} y "
            f"L>={MULTIFINGER_MIN_L} (tengo W={W}, L={L}); usar copias "
            f"paralelas (flatten_spice ya lo hace automaticamente)")

    m1 = info.metals[0].layer
    m2 = info.metals[1].layer
    via1 = info.via_layers["via1"]
    inter = _GF180_INTER_SD_L
    blk = _GF180_SD_BLOCK
    enc = _GF180_CON_COMP_ENC
    pc_x = max(L, _GF180_CON_SIZE + 2 * enc)

    def region_center(k: int) -> float:
        if k == 0:
            return -blk / 2
        if k == nf:
            return l_d + blk / 2
        return enc + k * L + (k - 1) * inter + inter / 2

    def gate_center(k: int) -> float:
        return enc + k * (L + inter) + L / 2

    # bandas y de los contactos de poly (alternating con inter_sd_l=0.24 => e_c=0.2)
    pc_lo0 = -_GF180_PC_H - _GF180_END_CAP - _GF180_ALT_EC     # -0.78
    pc_lo1 = -_GF180_END_CAP - _GF180_ALT_EC                   # -0.42
    pc_hi0 = W + _GF180_END_CAP + _GF180_ALT_EC
    pc_hi1 = pc_hi0 + _GF180_PC_H
    y_lo, y_hi = pc_lo0, pc_hi1

    # --- gate: barra inferior (dedos pares), barra superior (impares) y riser ---
    last_even = 2 * ((nf - 1) // 2)
    last_odd = 2 * (nf // 2) - 1
    bar_x0 = gate_center(0) - pc_x / 2
    _add_pad(c, (bar_x0, pc_lo0), (gate_center(last_even) + pc_x / 2, pc_lo1), m1)
    _add_pad(c, (bar_x0, pc_hi0), (gate_center(last_odd) + pc_x / 2, pc_hi1), m1)
    gx = gate_center(0)
    _add_pad(c, (gx - _GF180_GATE_RISER_W / 2, y_lo),
             (gx + _GF180_GATE_RISER_W / 2, y_hi), m1)

    # parche del PCell: en draw_pfet (gf180 0.1.1) los dedos pares con gate
    # alternating quedan sin end-cap inferior y SEPARADOS de su contacto de
    # poly (hueco de 0.42 um). Rellenar el hueco en poly2 hasta el bloque de
    # contacto; inofensivo cuando el PCell ya lo dibuja bien (nfet).
    for k in range(nf):
        x0 = enc + k * (L + inter)
        if k % 2 == 0:
            _add_pad(c, (x0, pc_lo1), (x0 + L, 0.0), info.poly)
        else:
            _add_pad(c, (x0, W), (x0 + L, pc_hi0), info.poly)

    # --- S/D: pads de metal1, straps en metal2 y risers laterales en metal1 ---
    # el PCell no dibuja metal1 sobre S/D: cubrir los bloques extremos (como el
    # wrapper nf=1) y las regiones internas (su contacto mide 0.24 y no aguanta
    # via1 de 0.26, asi que el pad interno se ensancha a 0.30).
    cmpc_y = W if W > (_GF180_CON_SIZE + 2 * enc) else (
        _GF180_CON_SIZE + 2 * enc)
    y0 = -(cmpc_y - W) / 2.0
    _add_pad(c, (-blk, y0), (0.0, y0 + cmpc_y), m1)
    _add_pad(c, (l_d, y0), (l_d + blk, y0 + cmpc_y), m1)
    ys = 0.25                      # centro del strap S (banda baja de la difusion)
    yd = W - 0.25                  # centro del strap D (banda alta)
    # Los pads internos se meten 0.02 respecto a la difusion: a ras de ella
    # quedaban a 0.22 de las barras de gate (M1.2a pide 0.23). Siguen cubriendo
    # los contactos del PCell y las via1 de los straps.
    for k in range(1, nf):
        xc = region_center(k)
        _add_pad(c, (xc - 0.15, _MF_PAD_INSET), (xc + 0.15, W - _MF_PAD_INSET), m1)

    s_riser_x1 = -blk - _GF180_RISER_GAP
    s_riser_x0 = s_riser_x1 - _GF180_RISER_W
    d_riser_x0 = l_d + blk + _GF180_RISER_GAP
    d_riser_x1 = d_riser_x0 + _GF180_RISER_W
    _add_pad(c, (s_riser_x0, y_lo), (s_riser_x1, y_hi), m1)
    _add_pad(c, (d_riser_x0, y_lo), (d_riser_x1, y_hi), m1)

    s_xc = (s_riser_x0 + s_riser_x1) / 2
    d_xc = (d_riser_x0 + d_riser_x1) / 2
    s_regions = [region_center(k) for k in range(0, nf + 1, 2)]
    d_regions = [region_center(k) for k in range(1, nf + 1, 2)]
    h2 = _GF180_STRAP_H / 2
    ext = _GF180_STRAP_END
    _add_pad(c, (s_xc - ext, ys - h2), (max(s_regions) + ext, ys + h2), m2)
    _add_pad(c, (min(d_regions) - ext, yd - h2), (d_xc + ext, yd + h2), m2)
    for x in s_regions + [s_xc]:
        _via1(c, gf180, via1, x, ys)
    for x in d_regions + [d_xc]:
        _via1(c, gf180, via1, x, yd)

    yc = W / 2.0
    c.add_port(name="S", center=(s_xc, yc), width=_GF180_RISER_W,
               orientation=180, layer=m1)
    c.add_port(name="D", center=(d_xc, yc), width=_GF180_RISER_W,
               orientation=0, layer=m1)
    bot_xc = (bar_x0 + gate_center(last_even) + pc_x / 2) / 2
    top_xc = (bar_x0 + gate_center(last_odd) + pc_x / 2) / 2
    c.add_port(name="G_bot", center=(bot_xc, (pc_lo0 + pc_lo1) / 2), width=pc_x,
               orientation=270, layer=m1)
    c.add_port(name="G_top", center=(top_xc, (pc_hi0 + pc_hi1) / 2), width=pc_x,
               orientation=90, layer=m1)


# ---------------------------------------------------------------------------
#  Parche CO.7 de los PCells de gf180 0.1.1
#
#  El PCell deja el contacto S/D externo a 0.07 um del borde de la difusion
#  intrinseca, y el poly de gate empieza otros 0.07 um dentro -> 0.14 um de
#  separacion, cuando CO.7 exige 0.15. No basta con mover el contacto: entre el
#  enclosure de COMP (0.07, CO.4) y el poly (0.15, CO.7) la ventana legal mide
#  0.21 um y CO.1 obliga a que el contacto mida exactamente 0.22. Hay que
#  ensanchar COMP. Se corre el contacto 0.01 hacia fuera y se extiende COMP (y
#  el implante, para no perder su enclosure) esa misma cantidad.
# ---------------------------------------------------------------------------
_CO7_SHIFT = 0.01
_EPS = 1e-6


def _shapes_of(c: gf.Component, layer) -> "kdb.Shapes":
    return c.shapes(c.kcl.layout.layer(*layer))


def _in_diff_band(box, W: float) -> bool:
    """True si la caja esta en la banda de difusion (los contactos de gate no)."""
    return box.bottom > -0.05 and box.top < W + 0.05


def _fix_pcell_co7_gf180(c: gf.Component, info, kind: str, W: float,
                         l_d: float) -> None:
    """Corrige la separacion contacto-poly de los contactos S/D externos."""
    moved = False
    for s in _shapes_of(c, info.contact):
        b = s.dbbox()
        if not _in_diff_band(b, W):
            continue
        if b.right <= _EPS:                     # bloque S/D izquierdo
            s.transform(kdb.DTrans(-_CO7_SHIFT, 0.0))
            moved = True
        elif b.left >= l_d - _EPS:              # bloque S/D derecho
            s.transform(kdb.DTrans(_CO7_SHIFT, 0.0))
            moved = True
    if not moved:
        return
    implant = info.nplus if kind == "n" else info.pplus
    for layer in (info.diff, implant):
        _extend_layer_x(c, layer, _CO7_SHIFT)


def _extend_layer_x(c: gf.Component, layer, delta: float) -> None:
    """Extiende 'delta' hacia fuera los bordes izquierdo y derecho de la capa."""
    shapes = _shapes_of(c, layer)
    boxes = [s.dbbox() for s in shapes]
    if not boxes:
        return
    xmin = min(b.left for b in boxes)
    xmax = max(b.right for b in boxes)
    for b in boxes:
        if abs(b.left - xmin) < _EPS:
            shapes.insert(kdb.DBox(b.left - delta, b.bottom, b.left, b.top))
        if abs(b.right - xmax) < _EPS:
            shapes.insert(kdb.DBox(b.right, b.bottom, b.right + delta, b.top))


def strip_abutted_sd_gf180(c: gf.Component, info, side: str, W: float,
                           l_d: float) -> None:
    """Quita contacto y pad de metal1 del bloque S/D compartido por abutment.

    Un bloque S/D compartido tiene gate a ambos lados, asi que necesitaria
    0.22 + 2*0.15 = 0.52 um para alojar un contacto legal y solo mide 0.36
    (mismo callejon sin salida que los contactos inter-finger). Pero no hace
    falta contacto: el criterio de abutment exige que la net tenga exactamente
    2 pines, o sea que el nodo es interno al par y la propia difusion compartida
    es la conexion. Se borran contacto y pad para no violar CO.7 ni dejar metal
    flotante.
    """
    for layer in (info.contact, info.metals[0].layer):
        shapes = _shapes_of(c, layer)
        keep = []
        for s in shapes:
            b = s.dbbox()
            doomed = _in_diff_band(b, W) and (
                (side == "left" and b.right <= _EPS)
                or (side == "right" and b.left >= l_d - _EPS))
            if not doomed:
                keep.append(s.dpolygon)
        shapes.clear()
        for poly in keep:
            shapes.insert(poly)


def _via1(c: gf.Component, gf180, via_layer, xc: float, yc: float) -> None:
    """Una via1 de tamano exacto 0.26 um centrada en (xc, yc)."""
    half = _GF180_VIA1 / 2
    v = gf180.via_generator(
        x_range=(xc - half, xc + half), y_range=(yc - half, yc + half),
        via_layer=via_layer, via_size=(_GF180_VIA1, _GF180_VIA1),
        via_enclosure=(0.0, 0.0), via_spacing=(_GF180_VIA1, _GF180_VIA1))
    c.add_ref(v)


# ---------------------------------------------------------------------------
#  SKY130 (basico: usa el PCell de stock; trae bulk tie + wells propios)
# ---------------------------------------------------------------------------
def _map_sky130(dev: Device) -> WrappedDevice:
    sky130 = get_pdk_module("sky130")
    info = get_info("sky130")
    L, W, nf = dev.L_um, dev.W_um, dev.nf
    is5v = "g5v0" in dev.model.lower() or "5v" in dev.model.lower()

    if dev.kind == "p":
        fn = sky130.pcells.pmos_5v if is5v else sky130.pcells.pmos
    else:
        fn = sky130.pcells.nmos_5v if is5v else sky130.pcells.nmos
    try:
        inner = fn(gate_length=L, gate_width=W, nf=nf)
    except TypeError:
        inner = fn(gate_length=L, gate_width=W)

    c = gf.Component()
    ref = c.add_ref(inner)
    bb = ref.dbbox()
    m1 = info.metals[1].layer       # met1 (68,20)
    yc = (bb.bottom + bb.top) / 2

    # puertos a izquierda (source) y derecha (drain) del bounding box del nucleo activo
    c.add_port(name="S", center=(bb.left, yc), width=0.3, orientation=180, layer=m1)
    c.add_port(name="D", center=(bb.right, yc), width=0.3, orientation=0, layer=m1)
    c.add_port(name="G_top", center=((bb.left + bb.right) / 2, bb.top), width=0.3,
               orientation=90, layer=m1)
    c.add_port(name="G_bot", center=((bb.left + bb.right) / 2, bb.bottom), width=0.3,
               orientation=270, layer=m1)

    c.info["kind"] = dev.kind
    c.info["l_d"] = bb.right - bb.left
    c.info["sd_block"] = 0.3
    c.info["W"] = W
    c.info["L"] = L
    c.flatten()
    return WrappedDevice(name=dev.name, component=c, kind=dev.kind, W=W, L=L, nf=nf,
                         l_d=bb.right - bb.left, sd_block=0.3, nodes=dict(dev.nodes),
                         pdk="sky130")


def _add_pad(c: gf.Component, p0, p1, layer):
    """Anade un rectangulo de metal entre las esquinas p0 y p1."""
    w = abs(p1[0] - p0[0])
    h = abs(p1[1] - p0[1])
    if w <= 0 or h <= 0:
        return
    r = c.add_ref(gf.components.rectangle(size=(w, h), layer=layer))
    r.dmove((min(p0[0], p1[0]), min(p0[1], p1[1])))


if __name__ == "__main__":
    from coil_layout.pdk_manager import activate_pdk
    from coil_layout.spice_parser import parse_spice

    activate_pdk("gf180")
    nl = parse_spice(open("examples/bias.spice").read())
    for d in nl.devices[:3]:
        wd = map_device(d, "gf180")
        print(f"{wd.name}: kind={wd.kind} W={wd.W} L={wd.L} l_d={wd.l_d:.3f} "
              f"ports={list(wd.component.ports)} size="
              f"{wd.component.dxsize:.2f}x{wd.component.dysize:.2f}")
