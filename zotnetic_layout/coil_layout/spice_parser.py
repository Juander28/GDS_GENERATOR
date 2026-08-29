"""Parser de netlists SPICE tipo .subckt con instancias de MOSFET (lineas X...).

gdsfactory no trae importador SPICE, asi que parseamos nosotros. Soporta el
formato tipico de export de Xschem/Magic:

    .subckt bias vdd bias1 bias2 bias3 bias4 vss
    *.PININFO bias1:O ...
    XM4 net3 bias1 vdd vdd pfet_05v0 L=1.0u W=10.0u nf=1 m=1
    ...
    .ends

Orden de terminales de un MOSFET de 4 nodos: drain gate source bulk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Terminales de un MOSFET de 4 nodos, en el orden en que aparecen en la linea X.
MOS_TERMINALS = ("drain", "gate", "source", "bulk")
# Nodos 1 y 2 del modelo: '.subckt cap_mim_2f0fF 1 2'. En la extraccion de
# KLayout el 1 es P1 (placa inferior, metal4) y el 2 es P2 (fusetop -> metal5).
CAP_TERMINALS = ("p1", "p2")
_CAP_MODEL_HINTS = ("cap_mim",)

# Terminales de una resistencia de poly. El modelo del PDK es
# '.subckt ppolyf_u_3k 1 2 3': los dos extremos y el cuerpo (sustrato).
RES_TERMINALS = ("r0", "r1", "body")
_RES_MODEL_HINTS = ("ppolyf", "npolyf", "nplus_u", "pplus_u", "rm1", "rm2", "rm3")


def is_cap_model(model: str) -> bool:
    return any(h in model.lower() for h in _CAP_MODEL_HINTS)


def is_res_model(model: str) -> bool:
    """True si el modelo es una resistencia del PDK.

    Hace falta mirarlo ANTES que el MOSFET: una resistencia se instancia con
    'X' y tres nodos igual que un transistor de tres terminales, asi que sin
    esto cae en la rama de MOSFET y se coloca como tal. Peor aun, sus
    dimensiones vienen en r_width/r_length y el lector de W/L no las encuentra,
    con lo que se queda con los valores por defecto: paso de verdad, la
    resistencia de realimentacion de OPAM_LIN acababa siendo un transistor de
    1 x 0.5 um y no lo avisaba nadie.
    """
    return any(h in model.lower() for h in _RES_MODEL_HINTS)

# Sufijos de unidades SPICE -> factor para convertir a micrometros (um).
# El layout de gdsfactory trabaja en um, asi que normalizamos todo a um.
_UNIT_TO_UM = {
    "t": 1e18, "g": 1e15, "meg": 1e12, "k": 1e9,
    "": 1e6,            # sin sufijo -> metros -> um  (1 m = 1e6 um)
    "m": 1e3,           # mili
    "u": 1.0,           # micro -> um (1:1)
    "n": 1e-3,          # nano
    "p": 1e-6,          # pico
    "f": 1e-9,          # femto
}

_NUM_UNIT = re.compile(
    r"^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*(meg|[a-zA-Z]?)$"
)


def _res_um(text: str) -> float:
    """Como parse_value_um pero para resistencias, donde un numero pelado son
    METROS y no micras.

    En los MOSFET la convencion del proyecto es que un numero sin sufijo ya
    viene en um, porque muchos netlists de PDK escriben 'W=2' queriendo decir
    2 um. Con las resistencias no vale: el simbolo del PDK emite
    'r_width=0.8e-6 r_length=302e-6', en metros, y con la regla de los MOSFET
    una resistencia de 302 um salia como si midiera 0.000302 um.
    """
    v = parse_value_um(text)
    t = text.strip().lower()
    #  Si no llevaba sufijo de unidad, parse_value_um lo dio por micras; aqui
    #  hay que deshacerlo y tratarlo como metros.
    if not t or t[-1].isdigit() or t.endswith((")", ".")):
        return v * 1e6
    return v


def parse_value_um(text: str) -> float:
    """Convierte un valor SPICE ('1.0u', '10u', '0.5', '2') a micrometros (float).

    Por convencion SPICE, un numero sin sufijo esta en metros. Pero muchos
    netlists de PDK escriben W/L ya en um sin sufijo ('W=2'); para W/L asumimos
    que un valor pequeno sin sufijo ya viene en um. Para evitar ambiguedad
    tratamos el sufijo 'u' como um (caso comun) y un numero pelado como um.
    """
    text = text.strip()
    m = _NUM_UNIT.match(text)
    if not m:
        # ultimo recurso: intentar float directo
        return float(re.sub(r"[a-zA-Z]+$", "", text))
    num = float(m.group(1))
    unit = m.group(2).lower()
    if unit in ("", "u"):
        # sin unidad o 'u' -> ya en um (convencion practica de netlists de PDK)
        return num
    factor = _UNIT_TO_UM.get(unit)
    if factor is None:
        return num
    # factor esta calibrado para entrada en metros; aqui interpretamos el numero
    # con su prefijo respecto a metros y pasamos a um.
    metric = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3,
              "n": 1e-9, "p": 1e-12, "f": 1e-15}
    return num * metric.get(unit, 1.0) * 1e6


@dataclass
class Device:
    """Un MOSFET de la netlist."""

    name: str                       # ej. 'XM4'
    model: str                      # ej. 'pfet_05v0'
    nodes: dict[str, str]           # {'drain': 'net3', 'gate': 'bias1', ...}
    params: dict[str, str]          # {'L': '1.0u', 'W': '10.0u', 'nf': '1', 'm': '1'}

    # --- helpers de conveniencia ---
    @property
    def kind(self) -> str:
        """'p' o 'n' segun el modelo (pfet/nfet, pmos/nmos)."""
        m = self.model.lower()
        if "pfet" in m or "pmos" in m:
            return "p"
        return "n"

    @property
    def R_width_um(self) -> float:
        """Ancho del cuerpo resistivo. PRES.1 pide 0.8 um como minimo."""
        return _res_um(self.params.get("r_width", self.params.get("W", "0.8e-6")))

    @property
    def R_length_um(self) -> float:
        """Largo del cuerpo resistivo, que puede ser de cientos de micras."""
        return _res_um(self.params.get("r_length", self.params.get("L", "1e-6")))

    @property
    def L_um(self) -> float:
        return parse_value_um(self.params.get("L", self.params.get("l", "0.5")))

    @property
    def W_um(self) -> float:
        return parse_value_um(self.params.get("W", self.params.get("w", "1")))

    @property
    def nf(self) -> int:
        return int(float(self.params.get("nf", self.params.get("NF", "1"))))

    @property
    def mult(self) -> int:
        return int(float(self.params.get("m", self.params.get("M", "1"))))

    def node(self, terminal: str) -> str:
        return self.nodes[terminal]


@dataclass
class SubcktNetlist:
    """Resultado de parsear un .subckt."""

    name: str
    ports: list[str]
    devices: list[Device]
    pininfo: dict[str, str] = field(default_factory=dict)  # puerto -> direccion
    # Los condensadores van aparte de `devices` A PROPOSITO: no ocupan sitio en
    # las filas ni pasan por el router de canal. Viven en metal4/metal5, por
    # encima de todo, y se cuelgan del trunk que la net ya tiene (ver caps.py).
    # Meterlos en `devices` los colaria en `nets()` y el router reservaria pistas
    # para pines que nunca va a ver.
    caps: list[Device] = field(default_factory=list)
    # Las resistencias tambien van aparte, pero por un motivo distinto al de los
    # condensadores: un MIM vive en metal4/metal5 y se monta ENCIMA sin gastar
    # area, mientras que una resistencia de poly esta al nivel de las puertas y
    # SI ocupa suelo. Van fuera de `devices` porque no caben en las filas de
    # transistores -- un serpentin de 300 um no es un dispositivo de fila -- y
    # se colocan en una banda propia (ver resistors.py).
    resistors: list[Device] = field(default_factory=list)

    # --- analisis de conectividad ---
    def nets(self) -> dict[str, list[tuple[str, str]]]:
        """net -> lista de (instancia, terminal) conectados a esa net.

        Es la 'tabla 2' (net-centrica) que pide el flujo: la representacion mas
        clara de las conexiones entre terminales.
        """
        result: dict[str, list[tuple[str, str]]] = {}
        for d in self.devices:
            for term, net in d.nodes.items():
                result.setdefault(net, []).append((d.name, term))
        return result

    def transistor_table(self) -> list[dict[str, str]]:
        """Tabla 1: una fila por transistor con sus parametros principales."""
        rows = []
        for d in self.devices:
            rows.append({
                "inst": d.name,
                "type": "PFET" if d.kind == "p" else "NFET",
                "model": d.model,
                "L_um": f"{d.L_um:g}",
                "W_um": f"{d.W_um:g}",
                "nf": str(d.nf),
                "m": str(d.mult),
                "drain": d.nodes.get("drain", ""),
                "gate": d.nodes.get("gate", ""),
                "source": d.nodes.get("source", ""),
                "bulk": d.nodes.get("bulk", ""),
            })
        return rows

    def connection_table(self) -> list[dict[str, str]]:
        """Tabla 2: una fila por net con todos los pines conectados."""
        rows = []
        for net, pins in self.nets().items():
            rows.append({
                "net": net,
                "n_pins": str(len(pins)),
                "pins": ", ".join(f"{inst}.{t}" for inst, t in pins),
                "is_power": "yes" if net.lower() in _POWER_HINTS else "no",
            })
        # nets de potencia primero, luego por numero de pines desc
        rows.sort(key=lambda r: (r["is_power"] != "yes", -int(r["n_pins"])))
        return rows


_POWER_HINTS = {"vdd", "vcc", "vpwr", "vss", "vgnd", "gnd", "vnb", "vpb"}


def parse_spice(text: str) -> SubcktNetlist:
    """Parsea el texto de una netlist y devuelve el primer .subckt encontrado.

    Soporta continuacion de linea con '+' y comentarios '*'.
    """
    # unir continuaciones de linea ('+') y normalizar
    raw_lines = text.splitlines()
    lines: list[str] = []
    for ln in raw_lines:
        if ln.lstrip().startswith("+") and lines:
            lines[-1] = lines[-1] + " " + ln.lstrip()[1:].strip()
        else:
            lines.append(ln)

    name = "top"
    ports: list[str] = []
    devices: list[Device] = []
    resistors: list[Device] = []
    caps: list[Device] = []
    pininfo: dict[str, str] = {}
    in_subckt = False

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        low = s.lower()

        # PININFO (va en comentario *.PININFO ...)
        if "pininfo" in low:
            for tok in s.split()[1:]:
                if ":" in tok:
                    p, d = tok.split(":", 1)
                    pininfo[p] = d
            continue

        if s.startswith("*"):
            continue  # comentario

        if low.startswith(".subckt"):
            toks = s.split()
            name = toks[1] if len(toks) > 1 else "top"
            ports = toks[2:]
            in_subckt = True
            continue

        if low.startswith(".ends"):
            in_subckt = False
            continue

        if low.startswith("."):
            continue  # otras directivas (.param, .model, etc.) ignoradas

        # instancia de subcircuito/MOSFET/condensador: empieza con X, M o C
        if s[0] in ("X", "x", "M", "m", "C", "c"):
            dev = _parse_instance(s)
            if dev is not None:
                if is_cap_model(dev.model):
                    caps.append(dev)
                elif is_res_model(dev.model):
                    resistors.append(dev)
                else:
                    devices.append(dev)

    return SubcktNetlist(name=name, ports=ports, devices=devices, caps=caps,
                         resistors=resistors, pininfo=pininfo)


def _parse_instance(line: str) -> Device | None:
    """Parsea una linea 'XM4 n1 n2 n3 n4 model L=.. W=.. ...'."""
    toks = line.split()
    if len(toks) < 3:
        return None
    inst = toks[0]

    # separar params (clave=valor) del resto
    params: dict[str, str] = {}
    positional: list[str] = []
    for t in toks[1:]:
        if "=" in t:
            k, v = t.split("=", 1)
            params[k] = v
        else:
            positional.append(t)

    # positional = [nodos..., model]. El ultimo positional sin '=' es el modelo.
    if len(positional) < 2:
        return None
    model = positional[-1]
    node_list = positional[:-1]

    if is_cap_model(model):
        if len(node_list) != 2:
            return None
        return Device(name=inst, model=model, params=params,
                      nodes=dict(zip(CAP_TERMINALS, node_list)))

    if is_res_model(model):
        #  Dos nodos (los extremos) o tres (extremos y cuerpo).
        if len(node_list) not in (2, 3):
            return None
        return Device(name=inst, model=model, params=params,
                      nodes=dict(zip(RES_TERMINALS, node_list)))

    # mapear nodos a terminales (4 nodos -> drain gate source bulk; 3 -> d g s)
    nodes: dict[str, str] = {}
    terms = MOS_TERMINALS if len(node_list) >= 4 else MOS_TERMINALS[:3]
    for term, net in zip(terms, node_list):
        nodes[term] = net
    if "bulk" not in nodes:
        # MOSFET de 3 terminales: bulk = source por defecto
        nodes["bulk"] = nodes.get("source", "")

    return Device(name=inst, model=model, nodes=nodes, params=params)


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "examples/bias.spice"
    nl = parse_spice(open(path).read())
    print(f"subckt: {nl.name}  ports: {nl.ports}")
    print(f"\n--- TABLA 1: {len(nl.devices)} transistores ---")
    for r in nl.transistor_table():
        print(r)
    print(f"\n--- TABLA 2: {len(nl.nets())} nets ---")
    for r in nl.connection_table():
        print(r)
