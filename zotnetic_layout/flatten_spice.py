"""Aplana una netlist SPICE jerarquica (export de Xschem) a un solo .subckt
de MOSFETs, el formato que consume coil_layout.spice_parser.

Maneja lo que el parser plano no soporta:
  - instancias x1/x2 de subcircuitos anidados (expansion recursiva),
  - nombres de subckt con caracteres raros (p.ej. 'comp._out'),
  - fuentes V de 0 V (shunts de medida tipo Vmeas): se convierten en un
    merge de nets (un corto), prefiriendo el nombre de puerto/power,
  - multiplicador m: se convierte a fingers (nf = nf*m) — device_map ya
    construye el multi-finger con straps de S/D y puente de gate. Solo si
    el dispositivo es demasiado pequeno para los straps (W < 1.2 um o
    L < 0.8 um) se expande a copias paralelas como antes,
  - lineas .save y comentarios: se descartan.

Soporta los dos formatos que exporta Xschem:

  a) El bloque como '.subckt' normal, con los MOSFET en lineas 'M...'.
  b) El bloque como netlist de nivel superior: la cabecera va **comentada**
     ('**.subckt NOMBRE puertos') y las instancias quedan sueltas fuera de
     cualquier subckt. Los MOSFET vienen como 'XM...' con el modelo en la
     ultima posicion, y los parametros traen expresiones entre comillas con
     espacios dentro ("ad='int((nf+1)/2) * W/nf * 0.18u'").

Uso:
    python flatten_spice.py entrada.spice [salida_flat.spice] [subckt_top]

Si no se indica subckt_top se usa el top comentado si existe y, si no, el
primer .subckt del archivo (convencion del export de Xschem: el top va primero).
"""

from __future__ import annotations

import sys
from pathlib import Path

_POWER_HINTS = {"vdd", "vcc", "vpwr", "vss", "vgnd", "gnd", "vnb", "vpb"}

# limites geometricos para mapear m -> nf (deben coincidir con device_map):
# los straps de S/D en metal2 necesitan W >= 1.2 y el riser de gate L >= 0.8.
_FINGER_MIN_W = 1.2
_FINGER_MIN_L = 0.8

# Del monton de parametros que escribe Xschem solo estos afectan al layout. El
# resto (ad/as/pd/ps/nrd/nrs/sa/sb/sd) son de simulacion y netgen los borra en su
# setup del PDK, asi que se descartan: ademas son los que traen expresiones entre
# comillas y arrastrarlos solo propaga el problema a las netlists derivadas.
_KEEP_PARAMS = {"l", "w", "nf", "m"}

_MOS_MODEL_HINTS = ("nfet", "pfet", "nmos", "pmos")
_CAP_MODEL_HINTS = ("cap_mim",)
#: Resistencias del PDK. Van reconocidas EXPLICITAMENTE porque se instancian con
#: 'X' y tres nodos igual que un MOSFET de tres terminales: sin esto el aplanado
#: no las reconocia como nada y las tiraba en silencio, dejando un layout
#: coherente con una netlist que no era el circuito -- justo el fallo contra el
#: que avisa la cabecera de este fichero.
_RES_MODEL_HINTS = ("ppolyf", "npolyf", "nplus_u", "pplus_u", "rm1", "rm2", "rm3")
_CAP_PARAMS = {"c_width", "c_length"}


def _is_mos_model(token: str) -> bool:
    return any(h in token.lower() for h in _MOS_MODEL_HINTS)


def _is_res_model(token: str) -> bool:
    return any(h in token.lower() for h in _RES_MODEL_HINTS)


def _is_cap_model(token: str) -> bool:
    return any(h in token.lower() for h in _CAP_MODEL_HINTS)


def _cap_um(value: str) -> float:
    """Dimension de un condensador -> um.

    Xschem no es coherente: los MOSFET salen con sufijo ('10.0u') pero los
    condensadores en SI ('20e-6'). Un valor sin sufijo se interpreta por tanto en
    METROS, que es lo que espera el modelo (`.subckt cap_mim_2f0fF 1 2
    c_length=l c_width=w`).
    """
    v = value.strip().lower()
    if v and v[-1] in "unp":
        return _um(v)
    try:
        return float(v) * 1e6
    except ValueError:
        return 0.0


def _split_tokens(line: str) -> list[str]:
    """Parte una linea SPICE respetando comillas simples y llaves.

    Xschem escribe parametros como ad='int((nf+1)/2) * W/nf * 0.18u': con un
    split() normal los espacios de dentro de las comillas rompen el token y los
    trozos sin '=' acaban colandose en la lista de nodos.
    """
    tokens: list[str] = []
    buf: list[str] = []
    quote = ""
    for ch in line:
        if quote:
            buf.append(ch)
            if (quote == "'" and ch == "'") or (quote == "{" and ch == "}"):
                quote = ""
        elif ch in "'{":
            quote = ch
            buf.append(ch)
        elif ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _um(value: str) -> float:
    """'4u' -> 4.0, '2.48u' -> 2.48, '700n' -> 0.7, '2' -> 2.0 (ya en um)."""
    v = value.strip().lower()
    try:
        if v.endswith("u"):
            return float(v[:-1])
        if v.endswith("n"):
            return float(v[:-1]) * 1e-3
        return float(v)
    except ValueError:
        return 0.0


def _join_continuations(text: str) -> list[str]:
    lines: list[str] = []
    for ln in text.splitlines():
        if ln.lstrip().startswith("+") and lines:
            lines[-1] += " " + ln.lstrip()[1:].strip()
        else:
            lines.append(ln)
    return lines


def parse_subckts(text: str) -> tuple[dict, list[str]]:
    """-> ({nombre: {'ports': [...], 'lines': [...]}}, orden_de_aparicion)

    El primer nombre del orden es el top. Cuando Xschem exporta el bloque como
    netlist de nivel superior la cabecera va comentada ('**.subckt ...') y sus
    instancias quedan fuera de todo subckt: aqui se reconstruye como un subckt
    normal para que el resto del flujo no note la diferencia.
    """
    subckts: dict[str, dict] = {}
    order: list[str] = []
    cur: dict | None = None
    top: dict | None = None          # bloque de nivel superior (cabecera comentada)
    for ln in _join_continuations(text):
        s = ln.strip()
        low = s.lower()

        if s.startswith("*"):
            # '**.subckt NOMBRE puertos' declara el top; el resto son comentarios
            bare = s.lstrip("*").strip()
            lb = bare.lower()
            if lb.startswith(".subckt") and cur is None and top is None:
                toks = bare.split()
                if len(toks) > 1:
                    top = {"name": toks[1], "ports": toks[2:], "lines": []}
            continue

        if not s:
            continue

        if low.startswith(".subckt"):
            toks = s.split()
            cur = {"name": toks[1], "ports": toks[2:], "lines": []}
        elif low.startswith(".ends"):
            if cur is not None:
                subckts[cur["name"]] = cur
                order.append(cur["name"])
                cur = None
        elif cur is not None:
            if low.startswith("."):
                continue  # .save, .param, etc.
            cur["lines"].append(s)
        elif top is not None and not low.startswith("."):
            top["lines"].append(s)          # instancia suelta del nivel superior

    if top is not None and top["lines"]:
        subckts[top["name"]] = top
        order.insert(0, top["name"])        # el top va primero
    return subckts, order


class Flattener:
    def __init__(self, subckts: dict):
        self.subckts = subckts
        self.devices: list[tuple[str, list[str], str, list[str]]] = []
        self.shorts: list[tuple[str, str]] = []   # merges por fuentes de 0 V
        self.warnings: list[str] = []
        self.fingered: list[str] = []             # 'Mxx: m=3 -> nf=3'
        self.src_name: dict[str, str] = {}        # nombre aplanado -> nombre en el .sch
        self.caps: list[tuple[str, list[str], str, float, float]] = []
        #   (nombre, [n1, n2], modelo, ancho_um, largo_um)
        self.resistors: list[str] = []            # lineas tal cual, ya con nets mapeadas
        #  Diodes, the same as resistors: the line as it is, with the nets
        #  mapped. There used to be NO branch for 'D' and the line fell through
        #  every `if` without a word -- the four diodes of each ESD_CDM vanished
        #  from the reference netlist and LVS compared a circuit that was not
        #  the one in the layout.
        self.diodes: list[str] = []
        self.res_info: list[tuple[str, list[str], str, float, float, int]] = []
        #   (nombre, [r0, r1, bulk], modelo, ancho_m, largo_m, s)
        #   Lo mismo que `resistors` pero desmontado, porque la netlist de LVS no
        #   puede copiarla tal cual: ahi hay que escribirla como elemento 'R' con
        #   W/L, no como 'X' con r_width/r_length (ver `build_lvs_netlist`).

    def expand(self, name: str, port_map: dict[str, str], prefix: str) -> None:
        sc = self.subckts[name]

        def mapnet(net: str) -> str:
            return port_map.get(net, f"{prefix}{net}" if prefix else net)

        for ln in sc["lines"]:
            toks = _split_tokens(ln)
            inst = toks[0]
            kind = inst[0].lower()
            params = [t for t in toks[1:] if "=" in t]
            pos = [t for t in toks[1:] if "=" not in t]

            # Un 'X...' es llamada a subcircuito o MOSFET segun lo que haya en la
            # ultima posicion: Xschem escribe los MOSFET como 'XM2 ... pfet_06v0'.
            is_subckt_call = kind == "x" and pos and pos[-1] in self.subckts
            is_mos = kind == "m" or (
                kind == "x" and pos and _is_mos_model(pos[-1]))
            is_cap = kind in ("c", "x") and pos and _is_cap_model(pos[-1])
            is_res = kind in ("r", "x") and pos and _is_res_model(pos[-1])
            is_diode = kind == "d" and pos

            if is_diode:
                #  A PDK diode: 'D1 anode cathode diode_nd2ps_06v0 area=.. pj=..'
                nets = [mapnet(n) for n in pos[:-1]]
                flat = f"{inst}{prefix and '_' + prefix.rstrip('_')}" if prefix else inst
                self.diodes.append(" ".join([flat] + nets + [pos[-1]] + params))
                continue

            if is_res:
                #  La resistencia se copia tal cual, solo con las nets mapeadas y
                #  el nombre aplanado. No hay nada que convertir: r_width,
                #  r_length y el multiplicador de serie `s` los entiende igual el
                #  simulador y el generador de layout.
                nets = [mapnet(n) for n in pos[:-1]]
                flat = f"{inst}{prefix and '_' + prefix.rstrip('_')}" if prefix else inst
                self.resistors.append(
                    " ".join([flat] + nets + [pos[-1]] + params))
                p = {k.lower(): v for k, v in (t.split("=", 1) for t in params)}
                #  `_cap_um` no tiene nada de condensador: es la regla de Xschem
                #  para una dimension, con sufijo o en metros. r_width/r_length
                #  la siguen igual.
                self.res_info.append(
                    (flat, nets, pos[-1],
                     _cap_um(p.get("r_width", "0")), _cap_um(p.get("r_length", "0")),
                     int(float(p.get("s", "1")))))
                continue

            if kind == "x" and not (is_subckt_call or is_mos or is_cap or is_res):
                #  An 'X' that is neither a known subcircuit nor a device used
                #  to fall through every `if` and disappear without a word. That
                #  is how eleven ESD_CDM instances were lost while the top still
                #  called them from a code block: the reference came out with
                #  exactly the same 2027 devices as before they went in, which
                #  is the worst way to fail there is.
                raise ValueError(
                    f"{prefix}{inst}: '{pos[-1]}' is neither a subcircuit "
                    f"defined in this netlist nor a known device model; "
                    f"it cannot be flattened")

            if is_subckt_call:
                child = self.subckts[pos[-1]]
                nets = [mapnet(n) for n in pos[:-1]]
                if len(nets) != len(child["ports"]):
                    raise ValueError(
                        f"{prefix}{inst}: {len(nets)} nodos para subckt "
                        f"'{pos[-1]}' que tiene {len(child['ports'])} puertos")
                self.expand(pos[-1], dict(zip(child["ports"], nets)),
                            f"{prefix}{inst}_")
            elif is_mos:
                nets = [mapnet(n) for n in pos[:-1]]
                flat_name = f"M{prefix}{inst}" if prefix else inst
                # multiplicador m -> fingers (nf = nf*m): device_map construye
                # el multi-finger con straps de S/D y puente de gate. Fallback
                # a copias paralelas si el dispositivo no da para los straps.
                mult = 1
                nfing = 1
                w_um = l_um = 0.0
                kept_params = []
                for p in params:
                    k, v = p.split("=", 1)
                    kl = k.lower()
                    if kl not in _KEEP_PARAMS:
                        continue          # ad/as/pd/ps/nrd/... no afectan al layout
                    if kl == "m":
                        mult = int(float(v))
                    elif kl == "nf":
                        nfing = int(float(v))
                    else:
                        if kl == "w":
                            w_um = _um(v)
                        elif kl == "l":
                            l_um = _um(v)
                        kept_params.append(p)
                total_nf = nfing * mult
                if total_nf <= 1:
                    self.devices.append((flat_name, nets, pos[-1],
                                         kept_params, 1))
                    self.src_name[flat_name] = inst
                elif w_um >= _FINGER_MIN_W and l_um >= _FINGER_MIN_L:
                    if mult > 1:
                        self.fingered.append(
                            f"{flat_name}: m={mult} nf={nfing} -> nf={total_nf}")
                    self.devices.append((flat_name, nets, pos[-1],
                                         kept_params, total_nf))
                    self.src_name[flat_name] = inst
                else:
                    self.warnings.append(
                        f"{flat_name}: W={w_um}u/L={l_um}u muy chico para "
                        f"fingers; m={mult} expandido a copias paralelas")
                    for i in range(1, mult + 1):
                        self.devices.append((f"{flat_name}_m{i}", nets,
                                             pos[-1], kept_params, nfing))
                        self.src_name[f"{flat_name}_m{i}"] = f"{inst}_m{i}"
            elif is_cap:
                nets = [mapnet(n) for n in pos[:-1]]
                if len(nets) != 2:
                    self.warnings.append(
                        f"{prefix}{inst}: condensador con {len(nets)} nodos, "
                        "se esperaban 2; ignorado")
                    continue
                dims = {}
                for p in params:
                    k, v = p.split("=", 1)
                    if k.lower() in _CAP_PARAMS:
                        dims[k.lower()] = _cap_um(v)
                wc, lc = dims.get("c_width", 0.0), dims.get("c_length", 0.0)
                if wc <= 0 or lc <= 0:
                    self.warnings.append(
                        f"{prefix}{inst}: sin c_width/c_length utilizables "
                        f"({wc}x{lc}); ignorado")
                    continue
                flat_name = f"{prefix}{inst}" if prefix else inst
                self.caps.append((flat_name, nets, pos[-1], wc, lc))
                self.src_name[flat_name] = inst
            elif kind == "v":
                # Vxxx n+ n- <valor>: shunt de medida si el valor es 0
                try:
                    val = float(pos[2]) if len(pos) > 2 else 0.0
                except ValueError:
                    val = None
                if val == 0.0:
                    self.shorts.append((mapnet(pos[0]), mapnet(pos[1])))
                else:
                    self.warnings.append(
                        f"{prefix}{inst}: fuente V con valor {pos[2:]} "
                        f"!= 0 ignorada (no representable en layout)")
            else:
                self.warnings.append(
                    f"{prefix}{inst}: instancia tipo '{inst[0]}' ignorada")

    # ---- nombres ----------------------------------------------------------
    def keep_source_names(self) -> int:
        """Devuelve a cada dispositivo el nombre que tiene en el esquematico.

        Al aplanar hay que anteponer la ruta de instancias ('M4' dentro de x1 ->
        'Mx1_M4') porque dos subcircuitos distintos pueden usar el mismo nombre.
        Pero eso solo hace falta cuando **de verdad** hay choque: en COMP los
        M1..M50 son unicos en todo el diseno, asi que el prefijo no aportaba nada
        y hacia imposible seguir un transistor del esquematico al layout.

        Se conserva el nombre original cuando es unico, y solo los que chocan se
        quedan con la ruta completa. El nombre siempre empieza por 'M' o 'X'
        (es lo que hace que la instancia sea un MOSFET), asi que sigue siendo
        SPICE valido. Devuelve cuantos conservaron el prefijo.
        """
        seen: dict[str, int] = {}
        for flat in self.src_name:
            seen[self.src_name[flat]] = seen.get(self.src_name[flat], 0) + 1
        ren = {flat: src for flat, src in self.src_name.items() if seen[src] == 1}
        self.devices = [(ren.get(nm, nm), nets, model, params, nf)
                        for nm, nets, model, params, nf in self.devices]
        self.caps = [(ren.get(nm, nm), nets, model, wc, lc)
                     for nm, nets, model, wc, lc in self.caps]
        for msg in (self.fingered, self.warnings):
            for i, s in enumerate(msg):
                head, sep, rest = s.partition(":")
                if sep and head in ren:
                    msg[i] = ren[head] + sep + rest
        return len(self.devices) - len(ren)

    # ---- fusion de nets cortocircuitadas por fuentes de 0 V ----------------
    def apply_shorts(self, top_ports: list[str]) -> dict[str, str]:
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def rank(net: str) -> tuple:
            # preferimos conservar: power > puerto del top > resto
            return (net.lower() in _POWER_HINTS, net in top_ports)

        for a, b in self.shorts:
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            keep, drop = (ra, rb) if rank(ra) >= rank(rb) else (rb, ra)
            parent[drop] = keep

        alias = {n: find(n) for n in list(parent)}
        self.devices = [
            (nm, [alias.get(n, n) for n in nets], model, params, nf)
            for nm, nets, model, params, nf in self.devices
        ]
        self.caps = [
            (nm, [alias.get(n, n) for n in nets], model, wc, lc)
            for nm, nets, model, wc, lc in self.caps
        ]
        return {k: v for k, v in alias.items() if k != v}


def _lvs_mos_name(name: str, taken) -> str:
    """Nombre del MOSFET para la netlist de LVS, que DEBE empezar por 'M'.

    Xschem exporta en dos formatos y en uno los transistores se llaman `XM4`. Al
    conservar el nombre del esquematico (`keep_source_names`) ese nombre llega
    tal cual a la netlist, y para SPICE un elemento que empieza por **X es una
    llamada a subcircuito, no un MOSFET**: KLayout buscaba un subckt `pfet_06v0`,
    no encontraba nada y el LVS daba `Netlists don't match` con 0 transistores de
    un lado. Misma regla de la primera letra que obliga a escribir los
    condensadores como `C...` (ver `_lvs_cap_name`).

    Se intenta lo menos sorprendente: `XM4` -> `M4`. Si al quitar la X no queda
    una M delante, o el resultado chocaria con otro, se antepone la M.
    """
    if name[:1].upper() == "M":
        return name
    cand = name[1:] if name[:1].upper() == "X" and name[1:2].upper() == "M" else None
    if cand and cand not in taken:
        return cand
    return f"M{name}"


def _lvs_cap_name(name: str, caps) -> str:
    """Nombre del condensador para la netlist de LVS, que DEBE empezar por 'C'.

    Se intenta conservar el del esquematico: 'XC2' -> 'C2' se lee natural. Si al
    quitar la 'X' no queda una 'C' delante, o el resultado chocaria con otro, se
    antepone la 'C' y ya. En la netlist del layout y en la etiqueta del GDS el
    nombre sigue siendo el original.
    """
    if name[:1].upper() == "C":
        return name
    cand = name[1:] if name[:1].upper() == "X" and name[1:2].upper() == "C" else None
    if cand and sum(1 for c in caps if c[0] == cand) == 0:
        return cand
    return f"C{name}"


def _hoja_ohm_sq(model: str) -> float:
    """Ohmios por cuadro que el DECK le atribuye a este modelo de resistencia.

    No es el valor medido del silicio (la de 3k mide 3.138 kohm/cuadro): es el
    numero que usa `res_extraction.lvs` al extraer, y la netlist de referencia
    tiene que hablar en esos terminos o el comparador ve dos valores distintos
    para la misma resistencia.
    """
    m = model.lower()
    for clave, valor in (("3k", 3000.0), ("2k", 2000.0), ("1k", 1000.0)):
        if clave in m:
            return valor
    return 1000.0


def _lvs_res_name(name: str, res_info) -> str:
    """Nombre de la resistencia para la netlist de LVS, que DEBE empezar por 'R'.

    La misma regla de la primera letra que `_lvs_mos_name` y `_lvs_cap_name`, y
    aqui costo que la resistencia no llegara siquiera a la netlist de referencia:
    `build_lvs_netlist` emitia MOSFET y condensadores y se dejaba las
    resistencias, asi que el LVS comparaba un circuito sin realimentacion contra
    otro sin realimentacion y decia que casaban. 'XRFB' -> 'RFB' se lee natural.
    """
    if name[:1].upper() == "R":
        return name
    cand = name[1:] if name[:1].upper() == "X" and name[1:2].upper() == "R" else None
    if cand and sum(1 for r in res_info if r[0] == cand) == 0:
        return cand
    return f"R{name}"


def flatten(text: str, top: str | None = None) -> tuple[str, str, dict]:
    """-> (netlist para layout [nf=N], netlist para LVS [m=N], stats).

    Son el mismo circuito escrito de dos formas, porque cada herramienta lee una:

    - **Layout** (`spice_parser` -> `device_map`): `nf=N` construye un
      dispositivo de N dedos, cada uno de ancho W.
    - **LVS** (netgen): su setup del PDK (`gf180mcuD_setup.tcl`) hace
      `property ... delete ... nf` y fusiona los paralelos con `{w add}`. El
      extractor ve cada dedo como un transistor suelto, asi que del layout le
      llegan N dispositivos de ancho W. Con `nf=N` netgen leeria un unico W y
      no cuadraria, y `m=N` tampoco sirve: netgen no lo expande al leer, deja un
      solo dispositivo (20 vs 23 en la comparacion). Se escriben, por tanto, los
      N transistores en paralelo de forma explicita, que es lo que el extractor
      ve y lo que netgen sabe fusionar.
    """
    subckts, order = parse_subckts(text)
    if not order:
        raise ValueError("no se encontro ningun .subckt en el archivo")
    top = top or order[0]
    if top not in subckts:
        raise ValueError(f"subckt top '{top}' no existe; hay: {order}")

    fl = Flattener(subckts)
    ports = subckts[top]["ports"]
    fl.expand(top, {p: p for p in ports}, "")
    n_prefixed = fl.keep_source_names()
    merged = fl.apply_shorts(ports)

    head = [f"* netlist plana generada por flatten_spice.py (top: {top})",
            f"* {len(fl.devices)} MOSFETs; nets fusionadas por V=0: "
            + (", ".join(f"{k}->{v}" for k, v in merged.items()) or "ninguna"),
            "* nombres: los del esquematico; solo llevan la ruta de instancias "
            f"(Mx1_M4) los {n_prefixed} que chocaban",
            "* m -> fingers: " + ("; ".join(fl.fingered) or "ninguno")]

    def build_layout_netlist() -> str:
        out = head + ["* para generar el layout: nf = numero de dedos",
                      f".subckt {top} {' '.join(ports)}"]
        for nm, nets, model, params, nf in fl.devices:
            out.append(f"{nm} {' '.join(nets)} {model} {' '.join(params)} nf={nf}")
        for nm, nets, model, wc, lc in fl.caps:
            out.append(f"{nm} {' '.join(nets)} {model} "
                       f"c_width={wc}u c_length={lc}u")
        #  Las resistencias van tal cual: r_width, r_length y el multiplicador
        #  de serie `s` los leen igual el simulador y el generador de layout.
        out.extend(fl.resistors)
        out.extend(fl.diodes)
        out.append(".ends\n")
        return "\n".join(out)

    def build_lvs_netlist() -> str:
        out = head + ["* para LVS: cada dedo, un transistor en paralelo",
                      f".subckt {top} {' '.join(ports)}"]
        names = {nm for nm, *_ in fl.devices}
        for nm, nets, model, params, nf in fl.devices:
            base = f"{' '.join(nets)} {model} {' '.join(params)}"
            mos = _lvs_mos_name(nm, names)
            if nf <= 1:
                out.append(f"{mos} {base}")
            else:
                for i in range(1, nf + 1):
                    out.append(f"{mos}_f{i} {base}")
        if fl.diodes:
            out.append("* diodes: the line as it is. KLayout's deck reads them"
                       " with 'A=' and 'P=', which is what the simulator calls")
            out.append("*   area and pj; written as numbers and not as xschem's"
                       " expression, because the reader does not evaluate.")
            out.extend(fl.diodes)
        if fl.caps:
            out.append("* condensadores: elemento 'C' con W/L en METROS, no 'X'"
                       " con c_width/c_length.")
            out.append("*   El deck de KLayout los lee con un delegate"
                       " (custom_classes.lvs, SubcircuitModelsReader#element)")
            out.append("*   que SOLO actua si el elemento empieza por 'C', y de"
                       " ahi saca A=W*L*1e12 y P=2*(W+L)*1e6.")
            out.append("*   Escrito como 'X...' se leeria como llamada a"
                       " subcircuito y no emparejaria con nada.")
        for nm, nets, model, wc, lc in fl.caps:
            out.append(f"{_lvs_cap_name(nm, fl.caps)} {' '.join(nets)} {model} "
                       f"W={wc * 1e-6:g} L={lc * 1e-6:g}")
        if fl.res_info:
            out.append("* resistencias: elemento 'R' con W/L/S en METROS, no 'X'"
                       " con r_width/r_length.")
            out.append("*   Mismo motivo que los condensadores: el delegate del"
                       " deck (custom_classes.lvs,")
            out.append("*   SubcircuitModelsReader#element) solo entra por la"
                       " primera letra, y para 'R' de tres")
            out.append("*   nodos monta un DeviceClassResistorWithBulk con los"
                       " terminales A, B, W.")
            out.append("*   El deck hace W=W*PAR*1e6 y L=L*S*1e6, o sea que la"
                       " 'S' MULTIPLICA el largo.")
            out.append("*   Aun asi la serie se escribe TRAMO A TRAMO, no con"
                       " un 'S=5': el layout dibuja")
            out.append("*   `s` cuerpos de poly encadenados por metal1 y las dos"
                       " herramientas los extraen")
            out.append("*   como `s` dispositivos. Juntarlos en uno exige la"
                       " reduccion en serie, y netgen no")
            out.append("*   la aplica aqui porque lee la resistencia de tres"
                       " nodos como si tuviera dos y le")
            out.append("*   pone de modelo el nodo de sustrato: la clase le sale"
                       " 'VSS' y su setup no la")
            out.append("*   reconoce. Escribiendo los tramos, las dos partes"
                       " cuentan lo mismo y no hace falta.")
        for nm, nets, model, wu, lu, s in fl.res_info:
            base = _lvs_res_name(nm, fl.res_info)
            r0, r1, bulk = nets[0], nets[1], (nets[2] if len(nets) > 2 else nets[1])
            #  Los nodos intermedios son internos de la resistencia: no existen
            #  en el esquematico y no tienen por que; el LVS empareja por
            #  topologia y el layout tiene exactamente los mismos.
            puntos = [r0] + [f"{base}${i}" for i in range(1, s)] + [r1]
            #  Y el VALOR, que el delegate no puede deducir: sin `R` lo deja en 0
            #  (su rescate de `parse_element` mete `R=0`) y el comparador de
            #  KLayout ve 0 contra los 229350 ohm que extrae del layout. La hoja
            #  sale del nombre del modelo, que es la misma equivalencia que usa
            #  el deck (`res_extraction.lvs`: `resistor_with_bulk('ppolyf_u_3k',
            #  3000, ...)`), asi que las dos partes cuentan lo mismo por
            #  construccion.
            hoja = _hoja_ohm_sq(model)
            r_seg = hoja * lu / wu if wu else 0.0
            for i in range(s):
                out.append(f"{base}_{i + 1} {puntos[i]} {puntos[i + 1]} {bulk} "
                           f"{model} W={wu * 1e-6:g} L={lu * 1e-6:g} R={r_seg:g}")
        out.append(".ends\n")
        return "\n".join(out)

    layout_txt = build_layout_netlist()
    lvs_txt = build_lvs_netlist()

    stats = {"n_mos": len(fl.devices), "merged": merged, "fingered": fl.fingered,
             "warnings": fl.warnings, "top": top, "ports": ports,
             "prefixed": n_prefixed, "n_cap": len(fl.caps),
             "caps": [(nm, f"{wc:g}x{lc:g}um") for nm, _, _, wc, lc in fl.caps],
             "n_res": len(fl.res_info),
             "res": [(nm, f"{wu:g}x{lu:g}um x{s}")
                     for nm, _, _, wu, lu, s in fl.res_info]}
    return layout_txt, lvs_txt, stats


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "zonetic/spice/WEIGHT_COMP.spice")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        src.with_name(src.stem + "_flat.spice")
    top = sys.argv[3] if len(sys.argv) > 3 else None

    flat, lvs, stats = flatten(src.read_text(), top)
    dst.write_text(flat, encoding="utf-8")
    dst_lvs = dst.with_name(dst.stem.replace("_flat", "") + "_lvs.spice")
    dst_lvs.write_text(lvs, encoding="utf-8")
    print(f"top: {stats['top']}  puertos: {' '.join(stats['ports'])}")
    print(f"MOSFETs: {stats['n_mos']}")
    if stats["merged"]:
        print("nets fusionadas (V=0):",
              ", ".join(f"{k}->{v}" for k, v in stats["merged"].items()))
    for f in stats["fingered"]:
        print(f"FINGERS: {f}")
    for w in stats["warnings"]:
        print(f"AVISO: {w}")
    for nm, d in stats["res"]:
        print(f"RESISTENCIA: {nm} {d}")
    print(f"escrito (layout, nf): {dst}")
    print(f"escrito (LVS, m):     {dst_lvs}")


if __name__ == "__main__":
    main()
