#!/usr/bin/env python3
"""Is the filled user area actually CONNECTED?

    env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/check_integration.py

DRC says nothing about this. A tie-off drawn 0.02 um short of its bus, a via
that landed on the wrong layer, an escape that never met the router's wire --
all of them pass DRC and none of them conducts. So the GDS is extracted and
every one of the 73 pins is probed at the coordinate the padring put it, and
grouped by the net it comes out on.

What has to come out:

    VDD   the six OE pins, the supply pin, and the block's VDD pad
    VSS   the other 42 control pins, the supply pin, and the block's VSS pad
    each analogue signal, on its own with the block's pin of the same name
    each <sig>_OUT with the block's <sig>
    each <sig>_IN alone: the receiver is deliberately unconnected
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import klayout.db as kdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_collateral as bc                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GDS = ROOT / "out_integration" / "B26_A.gds"
DEFP = ROOT / "padframe" / "B26_A.def"
CONS = ROOT / "constraints" / "B26_A_pins.tcl"
DBU_PAD = 200.0

#: THE LAYER MAP IS NOT WRITTEN HERE. Writing it by hand is how this check told
#: me the area was disconnected when it was not: I had Metal3 on 38/0, which is
#: Via2, and Metal4 on 42/0, which is Metal3. Every net came out on its own and
#: the verdict was "113 problems". The metals come from `build_collateral._GDS`,
#: which the whole flow already uses, and the vias from the PDK's own LVS deck.
_VIAS_DECK = Path("/foss/pdks/gf180mcuD/libs.tech/klayout/tech/lvs/"
                  "rule_decks/layers_definitions.lvs")


def mapa_capas():
    """[(name, layer, datatype)] for metal1..metal5 and via1..via4."""
    capas = [(f"m{i}", *bc._GDS[f"Metal{i}"]) for i in range(1, 6)]
    txt = _VIAS_DECK.read_text()
    for i in range(1, 5):
        m = re.search(rf"^\s*via{i} *= *polygons\((\d+), *(\d+)\)", txt, re.M)
        if not m:
            sys.exit(f"  via{i} is not defined in {_VIAS_DECK.name}")
        capas.append((f"v{i}", int(m.group(1)), int(m.group(2))))
    return capas


PAREJAS = [("m1", "v1"), ("v1", "m2"), ("m2", "v2"), ("v2", "m3"),
           ("m3", "v3"), ("v3", "m4"), ("m4", "v4"), ("v4", "m5")]


def pines():
    """{name: (layer, x, y)} in um, a probe point per pin, from the padring."""
    out, cur = {}, None
    for line in DEFP.read_text().splitlines():
        m = re.match(r"^- (\S+) \+ NET", line)
        if m:
            cur = m.group(1); continue
        m = re.match(r"\s*\+ LAYER (\S+) \( (\d+) (\d+) \) \( (\d+) (\d+) \)", line)
        if m and cur:
            x0, y0, x1, y1 = (int(v) for v in m.groups()[1:])
            out[cur] = (m.group(1).lower().replace("metal", "m"),
                        (x0 + x1) / 2 / DBU_PAD, (y0 + y1) / 2 / DBU_PAD)
            cur = None
    return out


def rail():
    """{pin: VDD|VSS} for the tie-offs, from what the generator wrote."""
    return dict(re.findall(r"^set RAIL\((\S+)\) (\S+)$", CONS.read_text(), re.M))


def pines_macro():
    """{boundary pin: (layer, x, y)} of the BLOCK's own pin, once placed.

    Its position comes from the block's routed DEF plus where the integration
    put it, both read from files rather than assumed.
    """
    top_def = ROOT / "out_integration" / "B26_A_routed.def"
    blk_def = ROOT / "out_v2_GRADIENT_NAV2" / "GRADIENT_NAV2_routed.def"
    m = re.search(r"^\s*- \S+ GRADIENT_NAV2 \+ \S+ \( (-?\d+) (-?\d+) \)",
                  top_def.read_text(), re.M)
    if not m:
        sys.exit("  the integration DEF has no GRADIENT_NAV2 instance")
    dbu_top = int(re.search(r"UNITS DISTANCE MICRONS (\d+)",
                            top_def.read_text()).group(1))
    ox, oy = int(m.group(1)) / dbu_top, int(m.group(2)) / dbu_top

    txt = blk_def.read_text()
    dbu = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))
    out, cur, rel = {}, None, None
    for line in txt.splitlines():
        mm = re.match(r"\s*- (\S+) \+ NET", line)
        if mm:
            cur, rel = mm.group(1), None; continue
        mm = re.match(r"\s*\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)", line)
        if mm and cur:
            rel = (mm.group(1),) + tuple(int(v) for v in mm.groups()[1:]); continue
        mm = re.match(r"\s*\+ (?:PLACED|FIXED) \( (-?\d+) (-?\d+) \)", line)
        if mm and cur and rel:
            x, y = int(mm.group(1)), int(mm.group(2))
            if cur not in ("VDD", "VSS"):
                borde = cur if cur.startswith("S") or cur in ("X", "Y", "Z") \
                        else f"{cur}_OUT"
                out[borde] = (rel[0].lower().replace("metal", "m"),
                              ox + (x + (rel[1] + rel[3]) / 2) / dbu,
                              oy + (y + (rel[2] + rel[4]) / 2) / dbu)
            cur, rel = None, None
    return out


def main() -> int:
    if not GDS.exists():
        sys.exit(f"missing {GDS}: run integrate_top.tcl and def_to_gds.py first")
    ly = kdb.Layout()
    ly.read(str(GDS))
    top = ly.top_cell()
    top.flatten(-1, True)

    capas = mapa_capas()
    print("\n  layer map, read from the PDK and from build_collateral:")
    vacias = []
    for n, a, b in capas:
        idx = ly.layer(a, b)
        c = sum(1 for _ in top.each_shape(idx))
        print(f"    {n:3s} {a:3d}/{b}  {c:8d} polygons")
        if c == 0 and n.startswith("m"):
            vacias.append(f"{n} ({a}/{b})")
    if vacias:
        #  A metal layer with nothing on it in an area 1110 um across means the
        #  number is wrong, and extracting with it finds no connection anywhere.
        sys.exit(f"\n  empty metal layers: {', '.join(vacias)}. The map is wrong.")

    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, []))
    lay = {n: l2n.make_polygon_layer(ly.layer(a, b), n) for n, a, b in capas}
    for a, b in PAREJAS:
        l2n.connect(lay[a], lay[b])
    for x in lay.values():
        l2n.connect(x)
    l2n.extract_netlist()

    P = pines()
    R = rail()
    grupo: dict[str, list[str]] = {}
    sueltos = []
    for name, (l, x, y) in P.items():
        n = l2n.probe_net(lay[l], kdb.DPoint(x, y))
        if n is None:
            sueltos.append(name)
            continue
        grupo.setdefault(n.expanded_name(), []).append(name)

    #  which extracted net is VDD and which VSS: the one the supply pin is on
    de_pin = {v: k for k, vs in grupo.items() for v in vs}
    nVDD, nVSS = de_pin.get("VDD"), de_pin.get("VSS")

    print(f"\n  {len(P)} pins probed at the coordinate the padring put them\n")
    fallos = 0
    for name in P:
        esperado = (R.get(name)
                    or ("VDD" if name == "VDD" else "VSS" if name == "VSS" else None))
        if esperado is None:
            continue
        real = de_pin.get(name)
        bien = real is not None and real == (nVDD if esperado == "VDD" else nVSS)
        if not bien:
            print(f"    {name:10s} should be on {esperado}, came out on {real}")
            fallos += 1
    print(f"  tie-offs and supplies: {48 + 2 - fallos} of 50 on the right rail")
    if nVDD:
        print(f"    VDD carries {len(grupo[nVDD])} pins")
    if nVSS:
        print(f"    VSS carries {len(grupo[nVSS])} pins")

    #  THE SIGNALS. A boundary pin being alone among these 73 means nothing on
    #  its own -- it connects to the BLOCK, whose pins are not in this list. So
    #  the block's own pin is probed too, at where it sits once placed, and the
    #  two have to come out on the same net. `XP_OUT` on the boundary is `XP` on
    #  the block; the rest keep their name.
    macro = pines_macro()
    print(f"\n  the {len(macro)} signals, boundary against block:")
    for borde, (l, x, y) in sorted(macro.items()):
        n = l2n.probe_net(lay[l], kdb.DPoint(x, y))
        suyo = n.expanded_name() if n else None
        mio = de_pin.get(borde)
        if suyo is None:
            print(f"    {borde:8s} no metal at the block's pin")
            fallos += 1
        elif mio is None or suyo != mio:
            print(f"    {borde:8s} boundary on {mio}, block on {suyo}")
            fallos += 1
    print(f"    {len(macro) - fallos if fallos <= len(macro) else 0} of "
          f"{len(macro)} reach the block")

    esperados_solos = {p for p in P if p.endswith("_IN")}
    solos = [v[0] for n, v in grupo.items() if len(v) == 1]
    raros = [s for s in solos if s not in esperados_solos and s not in macro]
    if raros:
        print(f"    alone and not expected to be: {' '.join(raros)}")
        fallos += len(raros)
    if sueltos:
        print(f"    no metal at all at: {' '.join(sueltos)}")
        fallos += len(sueltos)

    print()
    if fallos:
        print(f"  {fallos} problem(s): the area is drawn but not connected.")
        return 1
    print("  every pin is on the net it should be. The area is wired.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
