"""Placement estilo logica digital + abutment por difusion compartida.

Coloca los PFET en una fila superior (junto al riel VPWR y bajo un nwell
continuo) y los NFET en una fila inferior (junto a VGND), con un canal de ruteo
en medio. Donde dos transistores estan en serie compartiendo un nodo S/D (y son
del mismo tipo y ancho) se solapan sus difusiones (abutment) en vez de unirlos
con metal. Genera tambien los taps de well/sustrato 'estilo logica' (sin guard
rings) conectados a los rieles.

Devuelve un objeto Layout con el componente y la info que necesita el router.
"""

from __future__ import annotations

import collections

import warnings
from dataclasses import dataclass, field

warnings.filterwarnings("ignore")

import gdsfactory as gf

from coil_layout.device_map import (WrappedDevice, map_device,
                                    strip_abutted_sd_gf180)
from coil_layout.pdk_manager import get_info
from coil_layout.spice_parser import SubcktNetlist

# parametros de floorplan (um)
DEVICE_GAP = 1.0          # separacion entre dispositivos no abutidos. Las barras
                          # de gate del envoltorio multi-finger llegan casi al
                          # borde del dispositivo; con 0.8 quedaban a 0.13 um del
                          # strap de potencia del vecino (M1.2a pide 0.23).
ROW_CHANNEL = 4.0         # alto MINIMO del canal de ruteo entre filas
RAIL_WIDTH = 0.9          # ancho de los rieles VPWR/VGND
RAIL_MARGIN = 1.2         # separacion device-riel (fila P, por encima)
RAIL_CLEAR = 0.35         # hueco entre el borde REAL de una fila y su riel.
                          # Es el MINIMO con DRC limpio, medido barriendo el
                          # valor: 0.35 pasa y 0.30 ya dispara DV.3 x2 (dualgate
                          # a COMP no relacionado, 0.24) contra el COMP del tap,
                          # que va centrado en el riel. Cuanto menor, mas cerca
                          # quedan los transistores del tap: acorta el camino de
                          # sustrato (latch-up) y baja el alto de la celda.
NWELL_ENC = 0.5           # enclosure de nwell sobre la difusion p
SPAN_GAP = 1.6            # hueco entre las filas y el dispositivo a caballo de
                          # las dos. Su pozo baja al lado de la difusion de la
                          # fila N y DF.16_MV pide 0.6 um de nwell a NCOMP fuera
                          # del pozo; con NWELL_ENC (0.5) el minimo seria 1.1.
TAP_PITCH = 6.0           # cada cuanto poner un tap

# El canal se dimensiona segun cuantas nets haya que rutear: cada una necesita su
# propio trunk horizontal y los trunks no pueden apretarse mas de este paso (pad
# de via 0.34 + espaciado metal2 0.28). Con el alto fijo de 4.0 los trunks se
# desbordaban dentro de las filas de dispositivos y chocaban con su metal.
TRUNK_PITCH = 0.66        # pad de via en metal2 (0.38) + espaciado metal2 (0.28)
CHANNEL_MARGIN = 0.4      # holgura entre el borde de una fila y el primer trunk

# nombres tipicos de los rieles; el nombre real se toma de los puertos del
# .subckt para que las etiquetas del layout casen con la netlist en el LVS.
VPWR_HINTS = {"vdd", "vcc", "vpwr"}
VGND_HINTS = {"vss", "vgnd", "gnd"}
_POWER_HINTS = VPWR_HINTS | VGND_HINTS


def nets_to_route(nets: dict, abutted: set, ports=()) -> list[str]:
    """Nets de senal que necesitan un trunk en el canal.

    Mismo criterio que usa el router; vive aqui porque el placement lo necesita
    para dimensionar el canal antes de colocar la fila p.

    Un **puerto** entra aunque solo tenga un pin. No es para conectarlo consigo
    mismo: es para que tenga trunk, y con el la plataforma de metal3 por la que el
    top le baja una via. Sin ella, `VA`..`VD` de WEIGHT_COMP —cada uno atacando un
    solo gate— se quedaban con la etiqueta puesta sobre el pin, dentro de la fila
    y rodeada del metal del bloque, que es justo donde el router del top no puede
    aterrizar.
    """
    ports = set(ports)
    out = []
    for net, pins in nets.items():
        if net.lower() in _POWER_HINTS:
            continue
        nonbulk = [p for p in pins if p[1] != "bulk"]
        if len(nonbulk) < 2 and net not in ports:
            continue
        if net in abutted and len(nonbulk) == 2:
            continue          # resuelta por difusion compartida
        out.append(net)
    return out


def _abutted_nets(order, nxt) -> set:
    """Nets que quedaran abutidas segun las cadenas ya calculadas."""
    out = set()
    for chain in order:
        for name in chain[:-1]:
            if name in nxt:
                out.add(nxt[name][1])
    return out


SPLIT_RATIO = 1.5         # ancho(N)/ancho(P) a partir del cual se parte la fila N.
                          # Medido: WEIGHT_COMP 2.63 (parte), COMP 0.92 (no parte).
                          # Los dos casos reales quedan lejos del umbral por los
                          # dos lados, asi que no hay que afinarlo.


def _row_ratio(n_order, p_order, wds) -> float:
    """Ancho de la fila n dividido por el de la p (inf si no hay pfets)."""
    def w(order):
        return sum(wds[n].component.dxsize for chain in order for n in chain)
    wp = w(p_order)
    return w(n_order) / wp if wp else float("inf")


def split_chains(chains, width_of, split: bool = True) -> tuple[list, list]:
    """Parte las cadenas en dos mitades contiguas de ancho parecido.

    Contiguas a proposito: las cadenas vecinas comparten nets, y separarlas
    alargaria justo lo que se intenta acortar. Se corta por ancho acumulado y no
    por numero de dispositivos, que es lo que iguala el largo de las dos filas.

    Con `split=False` devuelve todo en la primera fila: partir solo compensa si la
    fila n es bastante mas ancha que la p (ver SPLIT_RATIO).
    """
    if not split:
        return list(chains), []
    widths = [sum(width_of(n) for n in c) for c in chains]
    total = sum(widths)
    acc, cut = 0.0, len(chains)
    for i, w in enumerate(widths):
        if acc + w / 2 > total / 2:
            cut = i
            break
        acc += w
    cut = min(max(cut, 1), len(chains) - 1) if len(chains) > 1 else len(chains)
    return chains[:cut], chains[cut:]


def channels_of_net(pins, row_of) -> set[str]:
    """Canales que necesita una net segun en que filas tiene pines.

    Un pin de P o N1 solo llega al canal A y uno de N2 solo al B: entre N1 y N2
    esta el riel VGND y nadie lo cruza para rutear. Una net con pines a los dos
    lados necesita trunk en ambos y un enlace vertical que los una.
    """
    out = set()
    for inst, term in pins:
        if term == "bulk":
            continue
        row = row_of.get(inst)
        if row in ("p", "n1"):
            out.add("A")
        elif row == "n2":
            out.add("B")
    return out

GRID = 0.005              # rejilla de fabricacion (reglas *_OFFGRID)


def snap(v: float) -> float:
    """Lleva una coordenada a la rejilla de 0.005 um.

    Las alturas de rieles y filas salen del bounding box de los PCells mas
    margenes sumados en coma flotante; 1 nm de desvio ya dispara OFFGRID.
    """
    return round(v / GRID) * GRID


@dataclass
class PlacedDevice:
    name: str
    wd: WrappedDevice
    ref: object                       # ComponentReference colocada
    x: float                          # offset x aplicado
    y: float                          # offset y aplicado
    abut_left: bool = False           # comparte difusion con el vecino izq
    abut_right: bool = False
    row: str = "n1"                   # 'p', 'n1' o 'n2'
    mirrored: bool = False            # reflejado para intercambiar S y D


@dataclass
class Opciones:
    """Que version del generador se esta construyendo.

    La v1 es el camino por defecto y **no cambia**: cada optimizacion de la v2 va
    detras de un `if opts.v2`, para que la v1 siga siendo reproducible al
    nanometro y sirva de control. Viaja dentro del `Layout`, que ya es el objeto
    que arrastra el estado entre `placement`, `routing`, `caps` y `resistors`.
    """

    v2: bool = False
    #: Trunks de senal en metal3 POR ENCIMA de las filas, en vez de en metal2
    #: dentro del canal. **Experimento sin terminar, apagado a proposito.**
    #:
    #: La idea funciona y la ganancia esta medida: el canal de `COMP` pasa de
    #: **13 pistas a 3** y la celda de 99.75 x 31.46 (3138 um2) a
    #: 105.88 x 25.42 (**2690 um2, -14 %**). Lo que no esta resuelto es el DRC:
    #: los tramos verticales de metal2 que suben de la fila al trunk se pisan
    #: entre ellos y con los straps de los multi-finger -- 39 violaciones, y al
    #: estrechar el vertical para separarlos subieron a 72, o sea que el arreglo
    #: no es el ancho sino el reparto en x, que hoy solo sabe de metal1.
    #:
    #: Y hay un segundo problema, independiente: con metal3 sobre las filas la
    #: extraccion de magic se dispara y pasa de segundos a **mas de 10 minutos**,
    #: que es su tiempo limite.
    #:
    #: Se deja el codigo entero y comentado porque el camino es bueno; lo que
    #: falta es que `_spread_stubs` reparta contando el metal2, no solo el
    #: metal1. Ver `routing._nets_a_metal3`.
    trunks_m3: bool = False


@dataclass
class Channel:
    """Banda de ruteo entre dos filas.

    `rows` son las filas cuyos pines pueden alcanzarla; el resto no, porque
    tendrian que cruzar un riel.
    """

    name: str
    rows: tuple[str, ...]
    tracks: int = 0                   # pistas reservadas al dimensionarla


@dataclass
class Layout:
    component: gf.Component
    placed: dict[str, PlacedDevice]
    nets: dict[str, list[tuple[str, str]]]
    pdk: str
    width: float = 0.0
    vpwr_y: float = 0.0
    vgnd_y: float = 0.0
    channel_y: float = 0.0
    #  Alto del canal A. Hace falta para meter cosas dentro sin salirse: quien
    #  solo mire `channel_y` no sabe donde acaba, porque es el CENTRO del canal,
    #  no su borde. Los serpentines de resistencia se colaban en la fila N1 por
    #  colgarlos de `channel_y` hacia abajo.
    channel_h: float = 0.0
    #  Alto que se le pidio a cada canal POR ENCIMA de lo que gastan sus trunks,
    #  por nombre de canal. Hoy solo lo piden los serpentines de resistencia. El
    #  router tiene que descontarlo al repartir las pistas o se las lleva tambien
    #  a esa banda y deja al terminal de la resistencia sin donde bajar la via.
    opts: Opciones = field(default_factory=Opciones)
    channel_reserved: dict = field(default_factory=dict)
    #  (x, y) de cada pila de vias de una resistencia: los dos terminales del
    #  serpentin y los dos puntos donde aterriza en su trunk. Lo rellena
    #  `place_resistors` y lo lee `place_caps`, que no puede poner una placa MIM
    #  encima: con la placa delante, la extraccion deja ese terminal en una net
    #  suelta (ver `caps._candidates`).
    res_terminals: list = field(default_factory=list)
    #  Nets que NO pueden salir del canal a metal3, porque un paso posterior
    #  las lee de `trunks` dando por hecho que son metal2: el riser de un
    #  condensador y el aterrizaje de una resistencia. Los puertos van aparte
    #  (`ports`). Ver `routing._nets_a_metal3`.
    cap_nets: set = field(default_factory=set)
    res_nets: set = field(default_factory=set)
    abutted_nets: set[str] = field(default_factory=set)
    abut_pairs: list = field(default_factory=list)   # (devA, devB, net) solapados
    #  Bloques S/D compartidos por los que la net TIENE que salir: net -> lista
    #  de (x del bloque, fila, dispositivo de referencia). El router los usa
    #  para sacar un unico stub del bloque en vez de dos de los dispositivos,
    #  y ese stub salta el pad de gate por metal2 (v2, ver `routing`).
    abut_salidas: dict = field(default_factory=dict)
    ports: list[str] = field(default_factory=list)   # puertos del .subckt
    tracks_reserved: int = 0    # pistas para las que se dimensiono el canal
    tracks_used: int = 0        # pistas que gasto el router (lo rellena routing)
    channels: list = field(default_factory=list)     # Channel, de arriba abajo
    tracks_by_channel: dict = field(default_factory=dict)  # nombre -> usadas
    unlinked: list = field(default_factory=list)     # nets sin enlace entre canales
    tight: list = field(default_factory=list)        # stubs que no cupieron (M1.2a)
    # net -> [(x0, x1, y, alto)] de cada trunk de metal2. Lo rellena el router y
    # lo consume caps.py, que cuelga los condensadores de ahi.
    trunks: dict = field(default_factory=dict)
    power_taps: dict = field(default_factory=dict)
    power_ports: set = field(default_factory=set)
    signal_access: dict = field(default_factory=dict)
    signal_access_failed: list = field(default_factory=list)
    caps_placed: list = field(default_factory=list)
    caps_failed: list = field(default_factory=list)
    #  Igual que los condensadores, pero para las resistencias de poly: lo que
    #  no se coloque se reporta, nunca se calla.
    res_placed: list = field(default_factory=list)
    res_failed: list = field(default_factory=list)
    # dispositivo -> um de hueco extra que pide el router para que su stub quepa
    need_gap: dict = field(default_factory=dict)


ABUT_BLOCK = 0.36         # bloque S/D compartido SIN contacto
ABUT_BLOCK_CON = 0.52     # con contacto: CO.7 pide 0.22 + 2*0.15
JOIN_POWER = False        # permitir que VDD/VSS sean union de difusion


def _order_row(devices, nets, join_power: bool = True, salto: bool = False):
    """Ordena la fila maximizando la difusion compartida.

    Un MOSFET es simetrico, asi que **D y S son intercambiables**: basta con
    reflejar el dispositivo (`dmirror_x` sobre su centro intercambia los puertos
    y deja bbox y puertas donde estaban). Eso convierte esto en el problema
    clasico de comparticion de difusion: grafo con las **nets como nodos** y cada
    dispositivo `nf=1` como **arista** entre su fuente y su drenador. Una cadena
    abutida es un **camino**, recorrer una arista al reves es intercambiar S y D,
    y maximizar el abutment es cubrir las aristas con el minimo numero de
    caminos — un recubrimiento por caminos de Euler.

    Lo de antes era un encadenado voraz que solo aceptaba `A.drain == B.source`
    sobre nets de exactamente dos pines. Medido en COMP: daba 7 abutments por
    fila, que resulta ser **el optimo bajo esa restriccion**; el circuito permite
    13. Todo lo que falta exige que el bloque compartido lleve **contacto**, que
    es lo que le abre la puerta a las nets con mas pines y a VDD/VSS.

    Devuelve (cadenas, nxt, flip):
      cadenas  listas de nombres, en orden de colocacion
      nxt      nombre -> (siguiente, net compartida)
      flip     nombres que hay que reflejar para que su S caiga a la izquierda
    """
    order = {d.name: i for i, d in enumerate(devices)}
    names = {d.name for d in devices if d.nf == 1}
    #  W por dispositivo, para que `_can_join` pueda rechazar un bloque
    #  compartido entre dos de anchura distinta. Ver la nota alli.
    anchos = {d.name: round(d.W, 4) for d in devices if d.nf == 1}
    edges = []                      # (nombre, u, v, net_s, net_d)
    for d in devices:
        if d.nf != 1:               # los multi-finger llevan straps en los extremos
            continue
        s, dr = d.nodes.get("source"), d.nodes.get("drain")
        if not s or not dr or s == dr:
            continue

        def vertex(net):
            # un nodo que no puede ser union se duplica por dispositivo, asi solo
            # puede quedar como extremo de cadena
            if _can_join(net, nets, names, join_power, salto, anchos):
                return net
            return f"{net}\0{d.name}"
        edges.append((d.name, vertex(s), vertex(dr), s, dr))

    paths = _euler_paths(edges, order)

    chains, nxt, flip = [], {}, set()
    seen = set()
    for path in paths:              # path = [(idx_arista, v_entrada, v_salida)]
        # El sentido del recorrido es arbitrario, pero cada dispositivo recorrido
        # al reves hay que reflejarlo. Se elige el sentido que menos refleje: un
        # espejo gratuito cambia de sitio S y D y mueve los stubs, que es como
        # aparecieron roces nuevos contra los pads de gate.
        rev = [(ei, vo, vi) for ei, vi, vo in reversed(path)]
        n_fwd = sum(1 for ei, vi, _ in path if vi != edges[ei][1])
        n_rev = sum(1 for ei, vi, _ in rev if vi != edges[ei][1])
        if n_rev < n_fwd:
            path = rev
        chain = []
        for k, (ei, v_in, _v_out) in enumerate(path):
            name, u, _v, _s, _d = edges[ei]
            chain.append(name)
            seen.add(name)
            if v_in != u:           # entra por el drenador -> hay que reflejarlo
                flip.add(name)
            if k + 1 < len(path):
                nxt[name] = (edges[path[k + 1][0]][0], _vnet(edges, path[k][2]))
        chains.append(chain)
    for d in devices:               # multi-finger y sueltos, cada uno en su cadena
        if d.name not in seen:
            chains.append([d.name])
    chains.sort(key=lambda ch: min(order[n] for n in ch))
    return chains, nxt, flip


def _can_join(net, nets, names, join_power: bool, salto: bool = False,
              anchos: dict | None = None) -> bool:
    """Si esa net puede ser la union de difusion de dos dispositivos.

    Solo si **no tiene que salir del par**. Un bloque S/D compartido tiene puerta
    a los dos lados por definicion, asi que su pad de metal1 queda encajonado: un
    stub vertical que salga de el cruza por fuerza el pad de contacto de gate del
    vecino, que sobresale de la difusion justo por ahi (M1.2a, medido: 0.155 um
    entre centros cuando hacen falta 0.845).

    Se probo a ensanchar el bloque a 0.52 y ponerle contacto propio: el contacto
    pasa `CO.7`, pero no resuelve nada porque el problema no es el contacto sino
    el camino de salida. Para abutir nets que hay que rutear haria falta que el
    stub saltara el pad de gate por metal2 (via1 arriba, cruzar, via1 abajo), que
    es otro trabajo.

    Con esta restriccion el maximo de abutments coincide con lo que ya lograba el
    encadenado voraz D->S (7 por fila en COMP); lo que aporta el recubrimiento por
    caminos es que ademas acepta pares D-D y S-S, reflejando un dispositivo, y que
    encuentra el optimo en vez de depender del orden de la netlist.

    Con `salto=True` (v2) se levanta la restriccion: se admite abutir una net que
    ADEMAS tiene que salir del par, porque el stub ya sabe saltar el pad de gate
    por metal2. Lo que se gana esta medido, y no es poco:

        COMP           abutidas 14 -> 18   ancho 102.02 -> 97.22
        OPAM_LIN_flat  abutidas 14 -> 24   ancho  95.96 -> 83.96
        OPAM           abutidas 14 -> 24   ancho  85.78 -> 73.78
        DECODER        abutidas  3 ->  6   ancho  35.89 -> 30.42
    """
    if not join_power and net.lower() in _POWER_HINTS:
        return False
    pins = [p for p in nets.get(net, ()) if p[1] != "bulk"]
    if salto:
        #  Basta con que los DOS que se abuten sean S/D de esta fila; los demas
        #  pines de la net salen por el bloque compartido.
        aqui = [p for p in pins if p[0] in names and p[1] in ("drain", "source")]
        if len(aqui) != 2:
            return False
        #  **Y CON LA MISMA W.** Dos dispositivos de W distinta comparten un
        #  bloque cuya difusion es un escalon: la del ancho pasa de largo, y el
        #  end cap de la puerta del estrecho --0.58 um de poly fuera de su propia
        #  difusion-- queda ahi como field poly a 0.22 um del borde de COMP del
        #  ancho, donde `PL.5a_MV`/`PL.5b_MV` piden 0.30. Medido sobre
        #  OPAM_LIN_flat en la hoja de 1 kohm: 44 violaciones, `PL.5a_MV` x6,
        #  `PL.5b_MV` x6, `CO.4` x26 y `M1.2a` x6, en x = 22.4 y x = 30.1 de la
        #  fila P, los dos bloques compartidos de W desigual.
        #  **El LVS no lo ve**: es geometria, no conectividad, y por eso paso
        #  limpio mientras el DRC no. Con W iguales el escalon no existe.
        if anchos is not None:
            w = {anchos.get(i) for i, _t in aqui}
            if len(w) != 1:
                return False
        return True
    return (len(pins) == 2
            and all(i in names and t in ("drain", "source") for i, t in pins))


def _vnet(edges, vertex) -> str:
    """Net real de un vertice (los no-union llevan sufijo con el dispositivo)."""
    return vertex.split("\0")[0]


def _euler_paths(edges, order):
    """Recubrimiento por caminos: sale la lista de caminos de aristas.

    Se emparejan los vertices de grado impar de cada componente con aristas
    ficticias, se saca un circuito de Euler (Hierholzer) y se corta por las
    ficticias. Con todos los grados pares sale un circuito y se corta por donde
    sea. Al elegir arista se prefiere la de menor indice en la netlist, para no
    alejarse mas de lo necesario del orden original — que ya se comprobo que es
    bueno (ver `_barycenter_targets`).
    """
    adj = collections.defaultdict(list)         # vertice -> [(idx, otro)]
    deg = collections.Counter()
    for i, (_n, u, v, _s, _d) in enumerate(edges):
        adj[u].append((i, v)); adj[v].append((i, u))
        deg[u] += 1; deg[v] += 1

    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    for _n, u, v, _s, _d in edges:
        ru, rv = find(u), find(v)
        if ru != rv:
            parent[ru] = rv

    comps = collections.defaultdict(list)
    for i, (_n, u, _v, _s, _d) in enumerate(edges):
        comps[find(u)].append(i)

    paths = []
    for root, eids in sorted(comps.items(),
                             key=lambda kv: min(order[edges[i][0]] for i in kv[1])):
        verts = {v for i in eids for v in (edges[i][1], edges[i][2])}
        odd = sorted((v for v in verts if deg[v] % 2),
                     key=lambda v: min(order[edges[i][0]] for i, _ in adj[v]))
        dummies = []
        local = dict(adj)
        for a, b in zip(odd[::2], odd[1::2]):   # emparejar impares con ficticias
            di = -(len(dummies) + 1)
            local[a] = local[a] + [(di, b)]
            local[b] = local[b] + [(di, a)]
            dummies.append(di)

        start = odd[0] if odd else edges[eids[0]][1]
        circuit = _hierholzer(local, start, order, edges)
        # cortar por las aristas ficticias
        cur = []
        for step in circuit:
            if step[0] < 0:
                if cur:
                    paths.append(cur); cur = []
            else:
                cur.append(step)
        if cur:
            paths.append(cur)
    return paths


def _hierholzer(adj, start, order, edges):
    """Circuito de Euler sobre `adj`; devuelve [(idx_arista, v_entrada, v_salida)]."""
    def key(pair):
        ei = pair[0]
        return (1, ei) if ei < 0 else (0, order[edges[ei][0]])

    adj = {v: sorted(es, key=key) for v, es in adj.items()}
    it = collections.Counter()
    used = set()
    stack = [(start, None)]
    out = []
    while stack:
        v, incoming = stack[-1]
        nxt_edge = None
        lst = adj.get(v, ())
        while it[v] < len(lst):
            ei, w = lst[it[v]]
            it[v] += 1
            if ei not in used:
                nxt_edge = (ei, w)
                break
        if nxt_edge is None:
            stack.pop()
            if incoming is not None:
                out.append(incoming)
        else:
            ei, w = nxt_edge
            used.add(ei)
            stack.append((w, (ei, v, w)))
    out.reverse()
    return out


def build_layout(nl: SubcktNetlist, pdk: str,
                 overrides: dict[str, dict] | None = None,
                 manual_order: dict[str, list[str]] | None = None,
                 tracks: dict[str, int] | None = None,
                 extra_gap: dict[str, float] | None = None,
                 extra_channel: dict[str, float] | None = None,
                 reserva_x: float = 0.0,
                 opts: Opciones | None = None) -> Layout:
    """Construye el layout completo.

    overrides: por instancia, dict de params para forzar (no usado aun por GUI).
    manual_order: {'p': [...], 'n': [...]} para reordenar manualmente las filas.
    tracks: {canal: pistas} para dimensionar cada canal. Si no se indica se
        reserva una por net, que es el peor caso; el router comparte pistas entre
        nets cuyos trunks no se solapan y suele gastar bastantes menos, asi que
        `flow.run_flow` hace una segunda pasada con el numero real.
    """
    info = get_info(pdk)
    nets = nl.nets()

    # limpiar la cache de gdsfactory para poder reusar nombres de celda entre
    # ejecuciones (evita 'Cellname ... already exists' al re-colocar/exportar).
    opts = opts or Opciones()

    gf.clear_cache()

    # 1) envolver dispositivos
    wds = {d.name: map_device(d, pdk) for d in nl.devices}

    # Los de canal largo (girados 90 grados) salen de su fila y se van a la
    # derecha del bloque, a caballo de las dos. Si se quedan en la fila P la
    # estiran entera: en OPAM, M43 mide 22.96 de alto contra los 11.96 del resto,
    # y la celda pasaba de ~32 a 43.12 por un solo transistor. A la derecha no hay
    # nadie que le limite y cabe en lo que ya ocupan N + canal + P.
    span_devs = [wds[d.name] for d in nl.devices if wds[d.name].rotated]
    span_names = {w.name for w in span_devs}
    p_devs = [wds[d.name] for d in nl.devices
              if d.kind == "p" and d.name not in span_names]
    n_devs = [wds[d.name] for d in nl.devices
              if d.kind == "n" and d.name not in span_names]

    # Orden manual: reordena los dispositivos de la fila SIN romper el abutment
    # (las cadenas de difusion compartida se recalculan sobre el nuevo orden).
    # No hay orden automatico a proposito: el de la netlist ya es bueno, porque
    # el esquematico agrupa los dispositivos por funcion. Se probaron encadenado
    # voraz por nets compartidas y orden por baricentro, y **los dos empeoran**
    # (7->8 y 7->5 pistas frente a las 4 que salen sin tocar el orden). Lo que
    # faltaba no era ordenar sino alinear las filas: ver `_barycenter_targets`.
    if manual_order and manual_order.get("p"):
        p_devs = _reorder(p_devs, manual_order["p"])
    if manual_order and manual_order.get("n"):
        n_devs = _reorder(n_devs, manual_order["n"])

    p_order, p_nxt, p_flip = _order_row(p_devs, nets, join_power=JOIN_POWER,
                                        salto=opts.v2)
    n_order, n_nxt, n_flip = _order_row(n_devs, nets, join_power=JOIN_POWER,
                                        salto=opts.v2)
    flip = p_flip | n_flip

    # La fila n se parte en dos SOLO si esta muy desequilibrada respecto a la p.
    # En WEIGHT_COMP lo esta (56.2 um de N contra 21.4 de P): con una sola fila la
    # n marcaba el ancho de la celda y la p se quedaba a menos de la mitad. Pero
    # partir cuando las dos filas ya son parejas sale CARO: en COMP la P mide 94.7
    # y la N 87.4, asi que las dos mitades de 43.7 caben bajo una P que sigue
    # marcando el ancho, y encima se paga un canal, un riel y una fila de alto.
    n1_order, n2_order = split_chains(
        n_order, lambda n: wds[n].component.dxsize,
        split=_row_ratio(n_order, p_order, wds) > SPLIT_RATIO)
    row_of = dict.fromkeys(span_names, "span")
    for chain in n1_order:
        row_of.update(dict.fromkeys(chain, "n1"))
    for chain in n2_order:
        row_of.update(dict.fromkeys(chain, "n2"))
    for chain in p_order:
        row_of.update(dict.fromkeys(chain, "p"))
    n1_devs = [d for d in n_devs if row_of[d.name] == "n1"]
    n2_devs = [d for d in n_devs if row_of[d.name] == "n2"]

    if opts.v2:
        #  --- v2: un solo contacto de puerta, el que mira al canal -------------
        #  Se re-envuelve AQUI y no en el primer `map_device` porque el lado
        #  depende de la fila, y la fila no se sabe hasta haber repartido N1/N2.
        #  Rehacerlo es barato y no invalida nada de lo ya calculado: quitar un
        #  contacto de puerta cambia el ALTO del dispositivo, no su ancho, y todo
        #  lo decidido hasta aqui (cadenas de abutment, orden, reparto de filas)
        #  depende solo de anchos y de la netlist.
        lado = {"p": "bottom",     # fila P: el canal A le queda DEBAJO
                "n1": "top",       # fila N1: el canal A le queda ENCIMA
                "n2": "bottom"}    # fila N2: el canal B le queda DEBAJO
        for d in nl.devices:
            cara = lado.get(row_of.get(d.name))
            #  Los girados salen por carriles laterales y su geometria la monta
            #  `_rotate_gf180` contando con los dos contactos: se quedan como
            #  estan. Los multi-finger tambien (ver `_map_gf180`).
            if cara is None or wds[d.name].rotated or wds[d.name].nf != 1:
                continue
            wds[d.name] = map_device(d, pdk, gate_con=cara)
        #  Las listas guardan objetos, no nombres: hay que rehacerlas o se
        #  colocarian los envoltorios viejos.
        span_devs = [wds[w.name] for w in span_devs]
        p_devs = [wds[w.name] for w in p_devs]
        n_devs = [wds[w.name] for w in n_devs]
        n1_devs = [wds[w.name] for w in n1_devs]
        n2_devs = [wds[w.name] for w in n2_devs]

    # La celda top se llama igual que el .subckt: el LVS de KLayout exige que
    # coincidan ("Can't find a schematic counterpart for the top cell") y a
    # netgen le ahorra tener que renombrarla.
    top = gf.Component(name=nl.name)
    placed: dict[str, PlacedDevice] = {}
    abutted_nets: set[str] = set()
    abut_pairs: list[tuple[str, str, str]] = []   # (devA, devB, net) que solapan
    abut_salidas: dict[str, list] = {}
    shared: dict = {}                 # (devA, devB) -> (net, necesita_contacto)

    # 2) geometria vertical, de abajo arriba:
    #       canal B / fila N2 / riel VGND / fila N1 / canal A / fila P / VPWR
    #    Un solo riel VGND, compartido: N1 alimenta hacia abajo y N2 hacia
    #    arriba. Asi ninguna fila cruza un canal para llegar a su alimentacion,
    #    que es lo que estropearia el ruteo, y sobra una tira de taps.
    # Cada canal se dimensiona para las nets que le tocan: con alto fijo los
    # trunks se desbordaban dentro de las filas.
    abutted_pre = _abutted_nets(p_order, p_nxt) | _abutted_nets(n_order, n_nxt)
    routable = nets_to_route(nets, abutted_pre, nl.ports)
    want = {"A": 0, "B": 0}
    for net in routable:
        for ch in channels_of_net(nets[net], row_of):
            want[ch] += 1
    if tracks:                      # segunda pasada: pistas reales por canal
        want = {k: max(1, tracks.get(k, v)) if v else 0
                for k, v in want.items()}

    def band(n, cual=None):
        #  `extra_channel` sube el suelo de un canal concreto. Lo pide el serpentin
        #  de la resistencia, que va justo ahi: metido entre las dos filas la
        #  celda se queda en tres bandas y los terminales caen al lado de los
        #  trunks, en vez de tener que dar un rodeo por metal3 desde una banda
        #  lateral.
        base = max(ROW_CHANNEL, (n + 1) * TRUNK_PITCH + 2 * CHANNEL_MARGIN)
        #  Y se SUMAN, no se toma el mayor. Fue un error de modelo que costo
        #  caro: el canal tiene que alojar los trunks **y** el serpentin, que son
        #  dos cosas apiladas, no dos aspirantes al mismo sitio. Con `max` el
        #  canal salia del tamano del serpentin (17.45) y el router repartia sus
        #  13 trunks por TODO ese alto, quedandose tambien con la banda de la
        #  resistencia: el hueco entre trunks era de 0.91 um cuando el terminal
        #  necesita 0.96 (`resistors.BANDA_TERMINAL`), y no habia ninguna `y` en
        #  todo el canal donde bajar la via. Sumando, el router se queda con su
        #  parte (ver `routing`, `reservado`) y la del serpentin queda limpia.
        return base + (extra_channel or {}).get(cual, 0.0)

    ch_a = band(want["A"], "A")
    ch_b = band(want["B"], "B") if want["B"] else 0.0

    # Los limites de cada fila salen de la extension REAL de sus dispositivos, no
    # de 'max(W) + margen': el envoltorio sobresale por arriba y por abajo del
    # ancho de canal (pads de gate, dualgate), y esa cuenta aproximada dejaba a
    # la fila N2 a 1.72 um del riel mientras N1 estaba a 0.25. Los transistores
    # tienen que quedar lo mas cerca posible del tap: acorta el camino de
    # sustrato (latch-up) y baja el alto de la celda.
    def extent(devs):
        lo = min((d.component.dymin for d in devs), default=0.0)
        hi = max((d.component.dymax for d in devs), default=2.0)
        return lo, hi

    n1_lo, n1_hi = extent(n1_devs)
    p_lo, _ = extent(p_devs)

    # Con fila N2 el riel VGND va ENTRE las dos filas n y sirve a las dos (N1
    # alimenta hacia abajo y N2 hacia arriba), que es lo que ahorra una tira de
    # taps. Sin ella el riel baja al fondo de la celda. Ojo: `extent([])` devuelve
    # el valor por defecto (0.0, 2.0), asi que no se puede usar para la fila que
    # no existe — dejaria un hueco de 2 um bajo el riel.
    if n2_devs:
        n2_lo, n2_hi = extent(n2_devs)
        n2_base_y = 0.0
        vgnd_y = snap(n2_hi + RAIL_CLEAR)                # riel entre N2 y N1
    else:
        n2_base_y = 0.0
        vgnd_y = 0.0                                     # riel al fondo
    n1_base_y = snap(vgnd_y + RAIL_WIDTH + RAIL_CLEAR - n1_lo)
    p_base_y = snap(n1_base_y + n1_hi + ch_a - p_lo)
    channel_y = snap(n1_base_y + n1_hi + ch_a / 2)

    def place_row(order, row_named, base_y, nxt, targets=None, row="n1",
                  alinear="bot"):
        """Coloca una fila de izquierda a derecha.

        `targets` da, por cadena, la x donde conviene centrarla (el baricentro de
        sus vecinos de la otra fila). La cadena se pone lo mas cerca posible de
        ahi sin pisar a la anterior. Sirve para estirar la fila corta y que siga
        a la larga: empaquetada a la izquierda, cada net que cruza de una fila a
        otra tenia que recorrer la diferencia de largos.
        """
        x = 0.0
        mine: list[str] = []
        gaps = extra_gap or {}
        lead_gap = 0.0
        #  `alinear` dice por que borde se pega la fila a su riel. Las filas N
        #  tienen el riel DEBAJO y se alinean por abajo, que es lo que hacia la
        #  v1 para todas. La fila P lo tiene ENCIMA, y alinearla por abajo dejaba
        #  a los dispositivos estrechos colgando: medido en `COMP`, el hueco a
        #  VPWR iba de 0.35 (los de W=10) a **8.35** (`XM1`, W=2), mientras que
        #  en la fila N los 25 estaban a 0.35 clavados. Eso alarga el strap de
        #  VDD de cada uno y los hace asomar hacia el canal sin necesidad.
        #  Alinear por arriba no cambia el canal --su techo lo marca el
        #  `min(dymin)` de la fila, o sea el dispositivo mas ancho, que no se
        #  mueve-- y dentro de una cadena abutida todos tienen el MISMO ancho,
        #  asi que tampoco rompe ninguna cadena.
        #  Y en la fila N pasa lo mismo en cuanto conviven dispositivos con y sin
        #  el contacto de puerta de abajo (v2): alinear por el ORIGEN del PCell
        #  --la esquina de la difusion-- deja los bbox a distinta altura y los de
        #  un dedo se quedan 0.58 um mas lejos del riel que los multi-finger.
        #  Asi que se alinea por el BORDE del bbox del lado del riel, los dos.
        tope = max((row_named[n].component.dymax
                    for chain in order for n in chain), default=0.0)
        suelo = min((row_named[n].component.dymin
                     for chain in order for n in chain), default=0.0)
        for chain in order:
            if targets is not None:
                w = sum(row_named[n].component.dxsize for n in chain)
                x = max(x, snap(targets.get(chain[0], x) - w / 2))
            # El hueco extra que pide el router se aplica al principio de la
            # cadena: dentro de ella los dispositivos comparten difusion y no se
            # pueden separar sin romper el abutment.
            gap = max((gaps.get(n, 0.0) for n in chain), default=0.0)
            if not mine:
                lead_gap = gap          # ver el reajuste al origen, mas abajo
            x = snap(x + gap)
            for i, name in enumerate(chain):
                mine.append(name)
                wd = row_named[name]
                ref = top.add_ref(wd.component)
                # alinear la difusion: el origen del device es la esquina de la difusion
                ref.dmovex(x - wd.component.dxmin if False else 0)
                #  A REJILLA: `tope`/`suelo` y los bbox salen de sumar margenes
                #  en coma flotante, y 1 nm de desvio dispara los OFFGRID. Se
                #  midio: sin esto, DECODER sacaba 4 `metal1_OFFGRID` y 2
                #  `nwell_OFFGRID`.
                if alinear == "top":
                    dy = snap(base_y + tope - wd.component.dymax)
                elif alinear == "bot_flush":
                    dy = snap(base_y + suelo - wd.component.dymin)
                else:
                    dy = base_y
                ref.dmovey(dy)
                if name in flip:
                    # D y S son intercambiables: el espejo sobre el centro del
                    # dispositivo los permuta y deja bbox y puertas donde estaban
                    ref.dmirror_x(ref.dxmin + ref.dxsize / 2)
                ref.dmovex(x)
                abut_left = i > 0
                #  `y` es la base REAL de la difusion de ESTE dispositivo (el
                #  origen del PCell es esa esquina), no la de la fila: con la
                #  fila alineada por arriba ya no coinciden, y de `y` cuelga el
                #  bloque de contacto compartido del abutment.
                placed[name] = PlacedDevice(name=name, wd=wd, ref=ref, x=x, y=dy,
                                            abut_left=abut_left, row=row,
                                            mirrored=name in flip)
                # avanzar x
                if i < len(chain) - 1:
                    # abutment: el siguiente solapa el bloque de contacto
                    nb, net = nxt[name]
                    abutted_nets.add(net)
                    abut_pairs.append((name, nb, net))
                    placed[name].abut_right = True
                    # Si la net compartida tiene mas pines que los dos que se
                    # abuten, el bloque necesita contacto para salir, y con
                    # contacto no cabe en 0.36 (CO.7 pide 0.22 + 2*0.15).
                    #
                    # OJO: hoy esto es SIEMPRE False, porque `_can_join` solo deja
                    # unir nets de exactamente dos pines. El bloque ensanchado con
                    # su contacto esta hecho y verificado (pasa CO.7), pero no
                    # sirve de nada mientras el stub no sepa saltar el pad de gate
                    # por metal2: ver la leccion §37 y el pendiente en §11.
                    con = len([p for p in nets.get(net, ()) if p[1] != "bulk"]) > 2
                    shared[(name, nb)] = (net, con)
                    x += wd.l_d + (ABUT_BLOCK_CON if con else ABUT_BLOCK)
                else:
                    x += wd.component.dxsize + DEVICE_GAP
        if targets is not None and mine:
            # El empaquetado con objetivos solo empuja a la derecha, asi que la
            # primera cadena arrastra la fila entera: sin esto N2 arrancaba en
            # x=12.6 y desperdiciaba ese ancho por la izquierda. Se corre la fila
            # completa hasta el origen, que conserva el estirado interno (que es
            # lo que acorta las nets) sin regalar ancho.
            # `lead_gap` se descuenta a proposito. El reajuste resta lo mismo a
            # toda la fila, asi que conserva los huecos INTERNOS pero se comia
            # entero el de la primera cadena: el router pedia 0.36, el placement
            # los daba y el reajuste los quitaba, y la realimentacion volvia a
            # pedir 0.36 pasada tras pasada sin mover nada (en DECODER,
            # 'Mx1_XM4' contra su propio pad de gate). Un fallo mudo, porque el
            # bucle acaba por numero de pasadas, no por converger.
            shift = snap(min(placed[n].ref.dxmin for n in mine)
                         - x_origin - lead_gap)
            if shift:
                for n in mine:
                    placed[n].ref.dmovex(-shift)
                    placed[n].x -= shift
                x -= shift
        return x

    # N1 va primero y hace de referencia; las otras dos filas se cuelgan de ella
    # centrando cada cadena sobre sus vecinos. Alinear las filas es gratis en
    # area (el ancho lo marca la mas larga) y es lo que de verdad acorta las
    # nets: empaquetando cada fila a la izquierda, toda net que cruza de una a
    # otra tenia que recorrer la diferencia de largos.
    named = {d.name: d for d in n_devs + p_devs + span_devs}
    _abajo = "bot_flush" if opts.v2 else "bot"
    w_n1 = place_row(n1_order, named, n1_base_y, n_nxt, row="n1",
                     alinear=_abajo)
    x_origin = min((pd.ref.dxmin for pd in placed.values()), default=0.0)
    w_n2 = place_row(n2_order, named, n2_base_y, n_nxt, row="n2",
                     alinear=_abajo,
                     targets=_barycenter_targets(n2_order, nets, placed))
    w_p = place_row(p_order, named, p_base_y, p_nxt, row="p",
                    alinear="top" if opts.v2 else "bot",
                    targets=_barycenter_targets(p_order, nets, placed))
    width = max(w_p, w_n1, w_n2, 1.0)

    # 2b) los de canal largo, a la derecha de todo y a caballo de las dos filas.
    #     El hueco no es el de siempre: su pozo baja hasta la altura de la fila N
    #     y `DF.16_MV` pide 0.6 um de nwell a la difusion de fuera del pozo, que
    #     ahi al lado es la de los NFET. NWELL_ENC (0.5) + esos 0.6, con margen.
    span_x = snap(width + SPAN_GAP) if span_devs else width
    #     Y si hay un serpentin de resistencia en el canal, esta fila ademas se
    #     aparta hasta dejarle sitio: su pozo baja por TODO el canal y el
    #     marcador de la resistencia no puede cruzarlo (`NW.1b_MV`), asi que
    #     parte el canal en dos y la resistencia solo cabe a la izquierda. El
    #     borde del pozo esta a `span_x - NWELL_ENC`. Ver `resistors.ancho_necesario`.
    if span_devs and reserva_x:
        span_x = max(span_x, snap(reserva_x + NWELL_ENC))
    for wd in span_devs:
        ref = top.add_ref(wd.component)
        ref.dmovey(n1_base_y - wd.component.dymin)
        ref.dmovex(span_x - wd.component.dxmin)
        placed[wd.name] = PlacedDevice(name=wd.name, wd=wd, ref=ref,
                                       x=span_x, y=n1_base_y, row="span")
        span_x = snap(span_x + wd.component.dxsize + DEVICE_GAP)
    if span_devs:
        width = max(width, snap(span_x - DEVICE_GAP))

    # El bloque S/D compartido por abutment tiene gate a ambos lados y no cabe
    # un contacto legal (necesitaria 0.52 um y mide 0.36). Tampoco hace falta:
    # el nodo es interno al par y la difusion compartida es la conexion.
    if pdk == "gf180":
        for pd in placed.values():
            # 'left'/'right' son coordenadas LOCALES del componente: si esta
            # reflejado, el bloque que toca al vecino de la izquierda es el que
            # en local esta a la derecha.
            for placed_side in ("left", "right"):
                if not getattr(pd, f"abut_{placed_side}"):
                    continue
                local = placed_side
                if pd.mirrored:
                    local = "right" if placed_side == "left" else "left"
                strip_abutted_sd_gf180(pd.wd.component, info, local,
                                       pd.wd.W, pd.wd.l_d)
        # Los bloques cuya net tiene que salir del par se quedaron sin contacto
        # al quitarlo de los dos lados: se pone uno solo, centrado en el bloque
        # ya ensanchado a ABUT_BLOCK_CON.
        for (a, b), (net, con) in shared.items():
            if con:
                xc = _shared_sd_contact(top, info, placed[a], placed[b])
                abut_salidas.setdefault(net, []).append((xc, placed[a].row, a, b))

    # 3) rieles: VPWR encima de la fila P y VGND entre N1 y N2 (compartido)
    p_top = max((placed[d.name].ref.dymax for d in p_devs), default=p_base_y)
    vpwr_y = snap(p_top + RAIL_CLEAR)
    m1 = info.metals[0].layer
    _hbar(top, -1.0, width + 1.0, vgnd_y, RAIL_WIDTH, m1)            # VGND
    _hbar(top, -1.0, width + 1.0, vpwr_y, RAIL_WIDTH, m1)            # VPWR
    # Las etiquetas llevan el nombre que usa la netlist (VDD/GND, no VPWR/VGND):
    # el LVS compara pines por nombre.
    vgnd_name = _rail_name(nl.ports, VGND_HINTS, "VGND")
    vpwr_name = _rail_name(nl.ports, VPWR_HINTS, "VPWR")
    add_port_label(top, vgnd_name, (width / 2, vgnd_y + RAIL_WIDTH / 2), info)
    add_port_label(top, vpwr_name, (width / 2, vpwr_y + RAIL_WIDTH / 2), info)

    # 4) wells y taps 'estilo logica' (sin guard rings)
    if pdk == "gf180" and p_devs:
        _gf180_nwell_and_taps(top, info, placed, p_devs, n_devs,
                              vpwr_y, vgnd_y, width)

    _label_devices(top, placed)

    chans = [Channel("A", ("p", "n1"), want["A"])]
    if want["B"]:
        chans.append(Channel("B", ("n2",), want["B"]))
    lay = Layout(component=top, placed=placed, nets=nets, pdk=pdk, width=width,
                 vpwr_y=vpwr_y + RAIL_WIDTH / 2, vgnd_y=vgnd_y + RAIL_WIDTH / 2,
                 opts=opts,
                 cap_nets={n for c in getattr(nl, 'caps', ())
                           for n in (c.nodes.get('p1'), c.nodes.get('p2')) if n},
                 res_nets={n for r in getattr(nl, 'resistors', ())
                           for n in (r.nodes.get('r0'), r.nodes.get('r1')) if n},
                 channel_y=channel_y, channel_h=ch_a,
                 channel_reserved=dict(extra_channel or {}),
                 abutted_nets=abutted_nets,
                 abut_pairs=abut_pairs, abut_salidas=abut_salidas,
                 ports=list(nl.ports),
                 tracks_reserved=sum(want.values()), channels=chans,
                 power_ports={vgnd_name, vpwr_name})
    return lay


VTEXT_LAYER = (63, 63)    # capa de texto del propio PDK: gf180mcu.lyp la llama
                          # VTEXT y el techfile de magic la mapea ('calma VTEXT
                          # 63 63'), asi que el nombre se ve en las dos
                          # herramientas. Ninguna regla del deck DRC la lee (solo
                          # 63/0, que es Border), y el LVS solo mira las capas de
                          # etiqueta de metal, asi que no puede inventar nets.


def _label_devices(top, placed) -> None:
    """Escribe sobre cada transistor el nombre que tiene en el esquematico.

    Un GDS no guarda nombres de instancia, solo referencias a celdas, asi que sin
    esto no hay forma de senalar un transistor del layout y decir 'este es M15'.
    Va como texto, no como poligono: el DRC cuenta poligonos y el texto no suma
    ninguno.
    """
    for name, pd in placed.items():
        top.add_label(name, layer=VTEXT_LAYER,
                      position=(pd.ref.dxmin + pd.ref.dxsize / 2,
                                pd.ref.dymin + pd.ref.dysize / 2))


def _shared_sd_contact(top, info, pa, pb) -> float:
    """Contacto + pad de metal1 en el bloque S/D que comparten dos dispositivos.

    Los dos PCells traen su propio contacto en ese bloque, pero `strip_abutted_*`
    los quita: con puerta a los dos lados harian falta 0.52 um y el bloque media
    0.36. Cuando la net compartida tiene mas pines fuera del par, la difusion sola
    no basta —hay que poder salir— asi que el bloque se coloca a
    `ABUT_BLOCK_CON` y aqui se dibuja **un solo** contacto centrado, con lo que
    `CO.7` recupera sus 0.15 um a cada puerta.

    El pad de metal1 cubre el bloque entero para que cualquiera de los dos
    puertos (el router usa uno u otro) caiga encima de metal conectado.
    """
    from coil_layout.pdk_manager import get_pdk_module
    gf180 = get_pdk_module("gf180")

    xa = max(p.dcenter[0] for p in pa.ref.ports if p.name in ("S", "D"))
    xb = min(p.dcenter[0] for p in pb.ref.ports if p.name in ("S", "D"))
    xc = snap((xa + xb) / 2)
    half = ABUT_BLOCK_CON / 2
    #  se devuelve para que el router sepa por donde sale la net
    y0, y1 = snap(pa.y), snap(pa.y + pa.wd.W)

    top.add_ref(gf180.via_generator(
        x_range=(xc - half, xc + half), y_range=(y0, y1),
        via_layer=info.contact, via_size=(0.22, 0.22),
        via_enclosure=(0.15, 0.07), via_spacing=(0.28, 0.28)))
    # El pad de metal1 va de ABUT_BLOCK, no de ABUT_BLOCK_CON: quien necesita los
    # 0.52 es el CONTACTO (CO.7 pide 0.15 a cada puerta), pero al metal1 le basta
    # con envolver los 0.22 del contacto. Sacandolo a 0.52 asomaba 0.08 por cada
    # lado respecto al bloque que el router da por supuesto, y los stubs vecinos
    # se le quedaban a 0.17 (M1.2a pide 0.23).
    m1 = top.add_ref(gf.components.rectangle(
        size=(ABUT_BLOCK, y1 - y0), layer=info.metals[0].layer))
    m1.dmove((snap(xc - ABUT_BLOCK / 2), y0))
    return xc

def _rail_name(ports, hints, fallback):
    return next((p for p in ports if p.lower() in hints), fallback)


def add_port_label(c, name, position, info):
    """Etiqueta un puerto en las dos capas de texto que esperan las herramientas.

    El deck LVS de KLayout lee `labels(34, 10)`, pero magic solo recoge texto de
    la capa de dibujo de metal1 (`calma METAL1 34 0` en gf180mcuD-GDS.tech). Con
    el nombre en las dos, el mismo GDS sirve para los dos flujos de LVS.
    """
    for layer in (info.metal1_label, info.metals[0].layer):
        c.add_label(name, position=position, layer=layer)


def _barycenter_targets(order, nets, placed) -> dict[str, float]:
    """Por cadena, la x media de los dispositivos ya colocados con los que
    comparte alguna net de senal. -> {primer_dispositivo_de_la_cadena: x}"""
    where: dict[str, list[float]] = {}
    for name, pd in placed.items():
        cx = pd.ref.dxmin + pd.ref.dxsize / 2
        for term, net in pd.wd.nodes.items():
            if term != "bulk" and net.lower() not in _POWER_HINTS:
                where.setdefault(net, []).append(cx)

    targets = {}
    for chain in order:
        xs = []
        for name in chain:
            for net, pins in nets.items():
                if net.lower() in _POWER_HINTS:
                    continue
                if any(i == name and t != "bulk" for i, t in pins):
                    xs += where.get(net, [])
        if xs:
            targets[chain[0]] = sum(xs) / len(xs)
    return targets


def _reorder(devs, names):
    """Reordena la lista de WrappedDevice segun 'names' (los no listados al final)."""
    pos = {n: i for i, n in enumerate(names)}
    return sorted(devs, key=lambda d: pos.get(d.name, len(pos)))


def _caja(c, x0, y0, x1, y1, layer) -> None:
    """Rectangulo insertado como caja, a rejilla. Ver el porque en `_hbar`."""
    import klayout.db as kdb
    x0i, x1i = round(snap(x0) / GRID), round(snap(x1) / GRID)
    y0i, y1i = round(snap(y0) / GRID), round(snap(y1) / GRID)
    if x1i <= x0i or y1i <= y0i:
        return
    c.shapes(c.kcl.layout.layer(*layer)).insert(
        kdb.DBox(x0i * GRID, y0i * GRID, x1i * GRID, y1i * GRID))


def _hbar(c, x0, x1, y, h, layer):
    """Barra horizontal, insertada como caja y NO con `gf.components.rectangle`.

    Esa funcion cachea celdas por tamano, y `x1 - x0` en coma flotante puede
    quedarse 1 nm corto: la caja dibujada no mide lo pedido, se alinea por el
    otro extremo y el borde acaba fuera de rejilla. Es exactamente la trampa que
    ya obligo a reescribir `routing._rect`, y aqui seguia. Salto a la vista en la
    v2 de `DECODER`: los dos rieles y el nwell arrancaban en **x = -0.999** y
    **-1.139** en vez de -1.000 y -1.140, con 4 `metal1_OFFGRID` y 2
    `nwell_OFFGRID`. Insertando la caja directa, la conversion a unidades de base
    de datos la hace KLayout y el resultado mide lo que pone.
    """
    import klayout.db as kdb
    x0i, x1i = round(snap(x0) / GRID), round(snap(x1) / GRID)
    y0i, y1i = round(snap(y) / GRID), round(snap(y + h) / GRID)
    if x1i <= x0i or y1i <= y0i:
        return None
    c.shapes(c.kcl.layout.layer(*layer)).insert(
        kdb.DBox(x0i * GRID, y0i * GRID, x1i * GRID, y1i * GRID))
    return None


def _m1_ocupado(top, info, y_riel, alto=RAIL_WIDTH, margin=None):
    """Intervalos x donde un tap DENTRO del riel chocaria con metal1.

    **`y_riel` es el BORDE INFERIOR del riel, no su centro.** Es lo que guarda
    `lay.vgnd_y` en este modulo -- el riel ocupa `[y_riel, y_riel + RAIL_WIDTH]`
    --, y tomarlo por el centro deja la franja recortada medio riel mas abajo:
    el metal1 del riel sobrevive al corte, sale un unico intervalo de punta a
    punta y la celda se queda sin una sola toma.

    Lo que estorba a un tap metido en el riel **no es el dispositivo: es su strap
    de potencia**, y son cosas de tamanos muy distintos. `_device_x_spans` bloquea
    el bbox entero del dispositivo -- difusion, poly, dualgate e implante -- y con
    las dos filas N proyectadas sobre la misma x eso tapa la celda de punta a
    punta. Medido en WEIGHT_COMP: la banda del riel VGND (y 3.81..4.71) esta
    **vacia de COMP y de poly en 45 um**, y aun asi solo cabian dos taps, en
    x=29.52 y x=38.58. Todo el NCOMP a la izquierda de x=14.5 se quedaba a mas de
    15 um del mas cercano: seis `DF.14_MV`.

    Los straps de verdad son estrechos -- entre 0.23 y 1.0 um -- y dejan sitio de
    sobra. Asi que se miran, en las dos bandas de metal1 que rodean al riel: la de
    abajo porque por ahi suben los straps de la fila de abajo, y la de arriba
    porque por ahi suben los de la de arriba Y el propio metal1 del tap, que va
    del tap al borde superior del riel.

    Se mide la geometria ya dibujada en vez de deducirla del modelo de colocacion:
    los straps los pone el PCell de cada dispositivo y aqui no hay una lista de
    donde caen.
    """
    import klayout.db as kdb
    #  `TAP_CLEAR` se define mas abajo en el modulo y un valor por defecto se
    #  evalua al DEFINIR la funcion, no al llamarla: puesto en la firma, el
    #  import del modulo revienta con NameError.
    margin = TAP_CLEAR if margin is None else margin
    capa = top.kcl.layout.layer(*info.metals[0].layer)
    #  Por el BBOX de cada forma y no por su poligono: `Shape.dpolygon` devuelve
    #  None para las que se insertaron como caja, que aqui son casi todas. Para
    #  sacar intervalos en x el bbox da lo mismo y no se rompe con paths ni
    #  textos.
    dbu = 1e-3
    reg = kdb.Region()
    it = top.begin_shapes_rec(capa)
    while not it.at_end():
        reg.insert(it.shape().dbbox().transformed(it.dtrans()).to_itype(dbu))
        it.next()
    reg.merge()
    #  Y SE CORTA EL RIEL. Los straps llegan hasta el, asi que al fusionar se
    #  vuelven una sola forma con el, cuyo bbox va de punta a punta de la celda:
    #  medido, un unico intervalo (-1.25, 41.53) que dejaba la tira entera
    #  ocupada y la celda sin una sola toma de sustrato. Quitando la franja del
    #  riel, cada strap vuelve a ser una forma con su propia x.
    reg -= kdb.Region(kdb.DBox(-1e4, y_riel - GRID,
                               1e4, y_riel + RAIL_WIDTH + GRID).to_itype(dbu))
    reg.merge()
    fuera = []
    #  Las bandas NO pueden rozar el riel. Empezandolas justo en su borde, el
    #  propio metal1 del riel -- que va de punta a punta de la celda -- entra en
    #  la interseccion y deja la tira entera ocupada: de dos taps se pasaba a
    #  cero. `GRID` de separacion basta y no se come ningun strap, que llegan al
    #  riel pero vienen de mucho mas lejos.
    for lo, hi in ((y_riel - alto, y_riel - GRID),
                   (y_riel + RAIL_WIDTH + GRID, y_riel + RAIL_WIDTH + alto)):
        banda = kdb.Region(kdb.DBox(-1e4, lo, 1e4, hi).to_itype(dbu))
        for q in (reg & banda).merged().each():
            b = q.bbox()
            fuera.append((b.left * dbu - margin, b.right * dbu + margin))
    return sorted(fuera)


def _gf180_nwell_and_taps(top, info, placed, p_devs, n_devs, vpwr_y, vgnd_y, width):
    """nwell continuo sobre la fila p + taps n+ a VPWR y p+ a VGND."""
    # nwell continuo cubriendo toda la fila de pfets
    p_refs = [placed[d.name].ref for d in p_devs]
    x0 = min(r.dxmin for r in p_refs) - NWELL_ENC
    x1 = max(r.dxmax for r in p_refs) + NWELL_ENC
    y0 = min(r.dymin for r in p_refs) - NWELL_ENC
    y1 = vpwr_y + RAIL_WIDTH                     # extender hasta el riel
    _caja(top, x0, y0, x1, y1, info.nwell)

    # El pozo baja tambien por la franja del dispositivo a caballo de las dos
    # filas: es un PFET y su difusion llega hasta la altura de la fila N. Sale un
    # poligono en L, no dos pozos — asi no hay separacion pozo-pozo que respetar
    # (NW.2b_MV pide 1.7 um entre pozos de distinto potencial, y este es el mismo).
    # A su derecha va una COLUMNA de taps: la tira horizontal de bajo VPWR le
    # queda a mas de 15 um de su extremo inferior y `DF.13_MV` no lo permite.
    span = [pd for pd in placed.values() if pd.row == "span"]
    if span:
        sx0 = min(pd.ref.dxmin for pd in span) - NWELL_ENC
        sy0 = min(pd.ref.dymin for pd in span) - NWELL_ENC
        tap_col_x = snap(max(pd.ref.dxmax for pd in span) + TAP_CLEAR)
        sx1 = snap(tap_col_x + TAP_W + NWELL_ENC)
        _caja(top, sx0, sy0, sx1, y1, info.nwell)
        #  Una sola columna a la derecha del grupo no basta cuando el grupo es
        #  ancho: con XM43 partido en cuatro copias el grupo mide ~20 um y su
        #  difusion de mas a la izquierda se quedaba a 18.7 um de la columna,
        #  cuando DF.13_MV permite 15. Se anaden columnas en los huecos ENTRE
        #  dispositivos del grupo, que es el unico sitio donde cabe un tap sin
        #  meterse en la difusion, hasta que todos queden cubiertos.
        ocup = sorted((pd.ref.dxmin, pd.ref.dxmax) for pd in span)
        huecos = [snap(a_hi + TAP_CLEAR) for (_, a_hi), (b_lo, _) in zip(ocup, ocup[1:])
                  if b_lo - a_hi >= TAP_W + 2 * TAP_CLEAR]
        columnas = [tap_col_x]
        for lo, _hi in reversed(ocup):
            if min(abs(lo - c) for c in columnas) <= DF13_MAX_TAP_DIST:
                continue
            #  El hueco libre mas a la derecha que aun cubra a este dispositivo.
            util = [h for h in huecos if h < lo and h not in columnas]
            if util:
                columnas.append(max(util))
            #  Si no hay hueco no se puede hacer nada aqui — un tap no cabe
            #  dentro de la difusion — y lo denuncia el DRC, que es lo correcto.
        for cx in sorted(columnas):
            _tap_column(top, info, cx, sy0 + NWELL_ENC, vpwr_y, implant=info.nplus)

    # Los straps de potencia suben/bajan pegados al borde de cada dispositivo,
    # asi que los taps tienen que caer en los huecos entre dispositivos.
    # taps n+ (nwell tap) bajo VPWR: van dentro del nwell, asi que siguen la
    # extension de la fila p
    # Normalmente va pegada al riel, pero `DF.13_MV` pide que ningun PCOMP del
    # pozo quede a mas de 15 um de un tap, y una fila P alta lo incumple: con el
    # M43 del OPAM girado la fila mide 22 um y la difusion de abajo se quedaba a
    # 21 um de la tira. Se baja lo justo. Los taps van en los huecos ENTRE
    # dispositivos, que estan libres a cualquier altura de la fila, asi que
    # bajarla no estorba a nadie; solo alarga el riser hasta el riel.
    n_tap_y = min(vpwr_y - 0.1, y0 + NWELL_ENC + DF13_MAX_TAP_DIST)
    _tap_strip(top, info, x0 + 0.5, x1 - 0.5, snap(n_tap_y), implant=info.nplus,
               connect_y=vpwr_y, up=True, busy=_device_x_spans(placed, ("p",)))
    # taps p+ (sustrato) DENTRO del riel VGND, que va entre N1 y N2 y por tanto
    # sirve a las dos filas: quedan a menos de 6 um de cualquier NFET, de sobra
    # para la distancia maxima al tap (DF.14_MV, 15 um). Centrados en el riel
    # para no acercarse al dualgate de ninguna de las dos filas (DV.3/PL.5).
    # Recorren TODO el ancho de la celda, no solo la fila p.
    p_tap_y = snap(vgnd_y + (RAIL_WIDTH - TAP_W) / 2)
    # El pozo del dispositivo a caballo se lleva por delante su franja: un tap p+
    # ahi seria pplus DENTRO del nwell — error de DRC y, peor, un corto entre VGND
    # y el pozo de VDD. Se marca como ocupada.
    #  De los STRAPS, no de los bbox de los dispositivos: ver `_m1_ocupado`.
    busy_p = _m1_ocupado(top, info, vgnd_y)
    if span:
        busy_p = sorted(busy_p + [(min(pd.ref.dxmin for pd in span)
                                   - NWELL_ENC - TAP_CLEAR, width + 1.0)])
    _tap_strip(top, info, -0.5, width + 0.5, p_tap_y, implant=info.pplus,
               connect_y=vgnd_y + RAIL_WIDTH, up=False, busy=busy_p)


DF13_MAX_TAP_DIST = 13.0  # DF.13_MV permite 15 um del PCOMP al tap del pozo; se
                          # deja margen porque la medida es al borde real de la
                          # difusion y aqui se parte del bbox, que incluye dualgate.
TAP_W = 0.48              # DF.9 pide 0.2025 um2 de COMP: 0.45 es el lado minimo.
                          # Con DEVICE_GAP=1.0 y TAP_CLEAR a cada lado el hueco
                          # util entre dispositivos es 0.5, asi que 0.48 entra.
TAP_CLEAR = 0.25          # metal1 del tap <-> strap de potencia (M1.2a pide 0.23)


def _device_x_spans(placed, rows, margin=TAP_CLEAR):
    """Intervalos x ocupados por los dispositivos de unas filas y sus straps.

    Solo estorban los de las filas cuyo riel toca esta tira de taps: mezclar las
    dos filas no dejaba ningun hueco libre y los taps acababan sin colocarse.
    """
    return sorted((pd.ref.dxmin - margin, pd.ref.dxmax + margin)
                  for pd in placed.values() if pd.row in rows)


def _free_x(x, tap_w, busy):
    """Corre x a la derecha hasta un hueco libre; None si no queda ninguno.

    Antes esta busqueda tenia un presupuesto (TAP_PITCH/2) y, al agotarlo,
    devolvia la x original **aunque chocase**: se aceptaba el roce porque
    renunciar al tap parecia peor que una M1.2a. Con dispositivos anchos ese caso
    deja de ser raro — en COMP los PFET miden 10 um, asi que el primer hueco cae
    a mas de 3 um y el tap aterrizaba encima del strap de potencia (M1.2a de 0.09
    um). El roce no es negociable, asi que ahora se busca por toda la tira; si de
    verdad no hay hueco, el tap se salta y el que avisa es el DRC (DF.13_MV /
    DF.14_MV comprueban la distancia maxima al tap, que es lo que estaria en
    juego).
    """
    for _ in range(len(busy) + 1):
        for lo, hi in busy:
            if x < hi and (x + tap_w) > lo:
                x = hi
                break
        else:
            return x
    return None


def _tap_column(top, info, x, y0, connect_y, implant):
    """Columna vertical de taps, para un pozo que baja mas de lo que alcanza la tira.

    `DF.13_MV` pide que ningun PCOMP del pozo quede a mas de 15 um de un tap. El
    dispositivo a caballo de las dos filas mide 23 um de alto, asi que la tira
    horizontal de bajo VPWR no le llega al extremo de abajo por mucho que se baje.
    Esto le pone taps a su lado a lo largo de toda su altura, con un unico strap
    de metal1 que los une al riel.
    """
    from coil_layout.pdk_manager import get_pdk_module
    gf180 = get_pdk_module("gf180")
    imp_enc = 0.18                # NP.5di pide 0.16
    ys = []
    y = snap(y0)
    while y + TAP_W <= connect_y - RAIL_CLEAR:
        ys.append(y)
        y = snap(y + TAP_PITCH)
    if not ys:
        return
    for yy in ys:
        comp = top.add_ref(gf.components.rectangle(size=(TAP_W, TAP_W),
                                                   layer=info.diff))
        comp.dmove((x, yy))
        imp = top.add_ref(gf.components.rectangle(
            size=(TAP_W + 2 * imp_enc, TAP_W + 2 * imp_enc), layer=implant))
        imp.dmove((x - imp_enc, yy - imp_enc))
        top.add_ref(gf180.via_generator(
            x_range=(x + 0.05, x + TAP_W - 0.05),
            y_range=(yy + 0.05, yy + TAP_W - 0.05),
            via_layer=info.contact, via_size=(0.22, 0.22),
            via_enclosure=(0.05, 0.05), via_spacing=(0.28, 0.28)))
    # un solo strap de metal1 desde el tap mas bajo hasta el riel
    _hbar(top, x, x + TAP_W, ys[0], snap(connect_y - ys[0]),
          info.metals[0].layer)


def _tap_strip(top, info, x0, x1, y, implant, connect_y, up, busy=()):
    """Coloca taps periodicos (comp+implant+contacto+metal1) a lo largo de [x0,x1]."""
    from coil_layout.pdk_manager import get_pdk_module
    gf180 = get_pdk_module("gf180")
    tap_w = TAP_W
    imp_enc = 0.18            # NP.5di/PP.5di piden 0.16; 0.15 se quedaba corto
    x = x0
    while x <= x1:
        if busy:
            free = _free_x(x, tap_w, busy)
            if free is None:
                break             # no queda hueco en lo que resta de tira
            x = free
        if x + tap_w > x1:
            break                 # buscar hueco no puede sacar el tap del nwell
        # comp + implant
        comp = top.add_ref(gf.components.rectangle(size=(tap_w, tap_w),
                                                   layer=info.diff))
        comp.dmove((x, y))
        imp = top.add_ref(gf.components.rectangle(
            size=(tap_w + 2 * imp_enc, tap_w + 2 * imp_enc), layer=implant))
        imp.dmove((x - imp_enc, y - imp_enc))
        # contacto + metal1
        via = gf180.via_generator(
            x_range=(x + 0.05, x + tap_w - 0.05),
            y_range=(y + 0.05, y + tap_w - 0.05),
            via_layer=info.contact, via_size=(0.22, 0.22),
            via_enclosure=(0.05, 0.05), via_spacing=(0.28, 0.28))
        top.add_ref(via)
        # metal1 que une el tap con el riel
        m1y0 = snap(min(y, connect_y))
        m1y1 = snap(max(y + tap_w, connect_y))
        m1 = top.add_ref(gf.components.rectangle(size=(tap_w, m1y1 - m1y0),
                                                 layer=info.metals[0].layer))
        m1.dmove((snap(x), m1y0))
        x += TAP_PITCH


if __name__ == "__main__":
    from coil_layout.pdk_manager import activate_pdk
    from coil_layout.spice_parser import parse_spice

    activate_pdk("gf180")
    nl = parse_spice(open("examples/bias.spice").read())
    lay = build_layout(nl, "gf180")
    print(f"placed {len(lay.placed)} devices, width={lay.width:.2f}, "
          f"abutted nets={sorted(lay.abutted_nets)}")
    lay.component.write_gds("out_placement.gds")
    print("wrote out_placement.gds  size:",
          f"{lay.component.dxsize:.2f} x {lay.component.dysize:.2f}")
