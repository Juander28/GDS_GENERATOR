#!/usr/bin/env python3
"""The top's DEF in the PADFRAME's frame, ready for the organisers to drop in.

    python3 scripts/padframe_def.py

WHAT THIS IS FOR. `d-m-bailey` attached `B26.def.tgz` to issue #58 on
2026-08-23: the padring generated for our slot. Inside it is the user area we
get -- 1110 x 1110 um -- and the exact place on its edge where each of our 19
pins comes out. Our own routed DEF is 418 x 442 um and knows nothing about any
of that. This writes the third file: our block PLACED inside the user area,
with the pins where the padring expects them.

WHY THE SLOTS ARE RECOMPUTED AND NOT COPIED. The padring assigns one slot per
entry OF info.yaml, IN ORDER. That file now opens with VSS and closes with VDD,
because `resources/info.yaml` of the chipathon repo says the first pin must be
a ground and that a power or ground cell breaks the I/O rails -- so they go at
the two ends, where the project boundary already breaks them. The attachment
was generated with VSS third and VDD fourth, so its assignment is stale. What
is taken from it is the SHAPE of each kind of pad; the names come from
info.yaml.

THE SLOT GEOMETRY, MEASURED ON THE ATTACHMENT AND NOT ASSUMED:

  * every slot is 100 um (20000 dbu) wide;
  * on the west edge the slots are centred at 8500 + 20000*k dbu, k = 0..10;
  * on the north edge at 13500 + 20000*j dbu, j = 0..7;
  * an analogue pad is eight rectangles, a supply pad six wider ones, and BOTH
    are centred on the slot: the offsets along the slot axis are the same on
    the two edges. Going west -> north is exactly
    (depth, along) -> (along, depth).

WHERE THE BLOCK GOES. Not in the middle and not in a corner: the origin is the
one that MINIMISES the total Manhattan distance from each pad to the die pin of
the same name, searched over a grid, with the block kept clear of the four
edges. The number is not a guess -- the search prints what it found.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
PADFRAME = ROOT / "padframe" / "B26_A.def"
#: The pin list. There used to be two -- one matching the padring in hand and
#: one being asked for -- and now there is one: info.yaml opens with VSS and
#: closes with VDD, which is what the chipathon template requires and what the
#: organisers are being asked to regenerate the padring from.
INFO_DEFAULT = "info.yaml"

TOP = os.environ.get("TOP_CELL", "GRADIENT_NAV2")
OUT = ROOT / os.environ.get("TOP_OUT", "out_v2_GRADIENT_NAV2")
ROUTED = OUT / f"{TOP}_routed.def"

DBU = 200                      # the padframe DEF's units
SLOT = 20000                   # dbu
WEST_C0, NORTH_C0 = 8500, 13500
N_WEST = 11                    # slots W12..W22
AREA = 222000                  # dbu, both sides
KEEPOUT = 5.0                  # um from the block to the user-area edge


def read_padframe(path: Path):
    """{name: (edge, [rect...])} with the rects RELATIVE to the slot centre.

    The rect is kept as (depth0, along0, depth1, along1) so west and north share
    one representation and the rotation is just which pair goes where.
    """
    txt = path.read_text()
    out = {}
    cur, rects = None, []
    for line in txt.splitlines():
        m = re.match(r"^- (\S+) \+ NET \S+ \+ DIRECTION \S+ \+ USE (\S+)", line)
        if m:
            if cur:
                out[cur[0]] = (cur[1], rects)
            cur, rects = (m.group(1), m.group(2)), []
            continue
        m = re.match(r"\s*\+ LAYER (\S+) \( (\d+) (\d+) \) \( (\d+) (\d+) \)", line)
        if m and cur:
            layer, x0, y0, x1, y1 = m.group(1), *(int(v) for v in m.groups()[1:])
            rects.append((layer, x0, y0, x1, y1))
    if cur:
        out[cur[0]] = (cur[1], rects)
    return out


def shapes_by_use(pf: dict):
    """One template per kind of pad, taken from the attachment's own pins.

    Every pad of a kind is identical bar its slot, so the first one of each is
    enough. The offsets are measured ALONG THE SLOT AXIS from its centre, and
    the depth is kept as it is: on the west edge that is x (0..200, from the
    left edge inwards) and on the north edge y (221800..222000, from the top).
    """
    tpl = {}
    for name, (use, rects) in pf.items():
        if use in tpl or not rects:
            continue
        first = rects[0]
        west = first[1] < 1000              # x near 0 -> this pad is on the west
        along = [(min(r[2], r[4]), max(r[2], r[4])) if west
                 else (min(r[1], r[3]), max(r[1], r[3])) for r in rects]
        centre = WEST_C0 if west else NORTH_C0
        #  Which slot this pad is in, so the offsets come out relative to it.
        k = round((sum(along[0]) / 2 - centre) / SLOT)
        c = centre + k * SLOT
        tpl[use] = {"layer": rects[0][0],
                    "along": [(a - c, b - c) for a, b in along]}
    return tpl


def read_info_pins(path: Path):
    """[(name, use)] in file order -- which IS the slot order."""
    out = []
    name = None
    for line in path.read_text().splitlines():
        m = re.match(r"\s*- name:\s*(\S+)", line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r"\s*io_type:\s*(\S+)", line)
        if m and name:
            use = {"ground": "GROUND", "power": "POWER"}.get(m.group(1), "SIGNAL")
            out.append((name, use))
            name = None
    return out


def read_die_pins(path: Path):
    """{name: (x, y)} in um, from our own routed DEF."""
    txt = path.read_text()
    dbu = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))
    out, cur = {}, None
    for line in txt.splitlines():
        m = re.match(r"\s*- (\S+) \+ NET", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"\s*\+ (?:PLACED|FIXED) \( (-?\d+) (-?\d+) \)", line)
        if m and cur:
            out[cur] = (int(m.group(1)) / dbu, int(m.group(2)) / dbu)
            cur = None
    size = re.search(r"DIEAREA \( 0 0 \) \( (\d+) (\d+) \)", txt)
    return out, (int(size.group(1)) / dbu, int(size.group(2)) / dbu)


def slot_centre(i: int):
    """(edge, centre along the axis) for the i-th pin of the list."""
    if i < N_WEST:
        return "W", WEST_C0 + i * SLOT
    return "N", NORTH_C0 + (i - N_WEST) * SLOT


def pad_point(edge: str, centre: int) -> tuple[float, float]:
    """Where a pad sits, in um: on the very edge of the user area."""
    return (0.0, centre / DBU) if edge == "W" else (centre / DBU, AREA / DBU)


def best_origin(pins, die_pins, die_w, die_h, step=5.0):
    """The origin that minimises the total pad -> die-pin Manhattan distance.

    A grid search, not a formula: the cost is separable in x and y only if every
    pin were on one edge, and ours are on three. The block is kept KEEPOUT away
    from the four sides of the user area so the integrator has a channel.
    """
    area = AREA / DBU
    lo, hi_x = KEEPOUT, area - die_w - KEEPOUT
    hi_y = area - die_h - KEEPOUT
    best = None
    y = lo
    while y <= hi_y:
        x = lo
        while x <= hi_x:
            cost = 0.0
            for i, (name, _use) in enumerate(pins):
                if name not in die_pins:
                    continue
                px, py = pad_point(*slot_centre(i))
                dx, dy = die_pins[name]
                cost += abs(px - (x + dx)) + abs(py - (y + dy))
            if best is None or cost < best[0]:
                best = (cost, x, y)
            x += step
        y += step
    return best


def _rect(slot, along):
    """One pad rectangle in absolute dbu, from its slot and its along-offset."""
    edge, centre = slot
    lo, hi = centre + along[0], centre + along[1]
    return (0, lo, 200, hi) if edge == "W" else (lo, AREA - 200, hi, AREA)


def emit(pins, tpl, origin, die_w, die_h) -> str:
    cost, ox, oy = origin
    out = [
        "# Written by openroad/scripts/padframe_def.py. Do not edit by hand.",
        "#",
        "# The block inside the 1110 x 1110 um user area of variant A, with the",
        "# 19 pins on the padring slots that the ORDER OF info.yaml assigns:",
        "# VSS opens the list and VDD closes it, so the two supply cells sit at",
        "# the project boundary, where the I/O rails are already broken.",
        "#",
        f"# Origin chosen by minimising total pad -> pin Manhattan distance:",
        f"#   ({ox:.1f}, {oy:.1f}) um, cost {cost:.0f} um, block {die_w:.2f} x {die_h:.2f} um.",
        "#",
        "# The pad SHAPES come from padframe/B26_A.def; the slot ASSIGNMENT does",
        "# not -- that attachment predates the reordering. See padframe/README_ORIGEN.txt.",
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        f"DESIGN B26_A_{TOP} ;",
        f"UNITS DISTANCE MICRONS {DBU} ;",
        f"DIEAREA ( 0 0 ) ( {AREA} {AREA} ) ;",
        "COMPONENTS 1 ;",
        f"- x_{TOP.lower()} {TOP} + FIXED ( {round(ox * DBU)} {round(oy * DBU)} ) N ;",
        "END COMPONENTS",
        f"PINS {len(pins)} ;",
    ]
    for i, (name, use) in enumerate(pins):
        edge, centre = slot_centre(i)
        t = tpl[use]
        direction = "INOUT"
        out.append(f"- {name} + NET {name} + DIRECTION {direction} + USE {use}")
        for a0, a1 in t["along"]:
            x0, y0, x1, y1 = _rect((edge, centre), (a0, a1))
            out.append(f"  + LAYER {t['layer']} ( {x0} {y0} ) ( {x1} {y1} )")
        out.append("  + FIXED ( 0 0 ) N ;")
    out += ["END PINS", "END DESIGN", ""]
    return "\n".join(out)


def main() -> int:
    which = INFO_DEFAULT
    info = PROJECT / which
    dest = OUT / f"{TOP}_top.def"
    if not info.exists():
        sys.exit(f"missing {info}")
    if not PADFRAME.exists():
        sys.exit(f"missing {PADFRAME} -- vendored from issue #58, see its README")
    if not ROUTED.exists():
        sys.exit(f"missing {ROUTED} -- run `make route` first")

    pf = read_padframe(PADFRAME)
    tpl = shapes_by_use(pf)
    pins = read_info_pins(info)
    die_pins, (die_w, die_h) = read_die_pins(ROUTED)

    if len(pins) != 19:
        sys.exit(f"info.yaml declares {len(pins)} pins, the slot map has 19")
    missing = [n for n, _ in pins if n not in die_pins]
    if missing:
        sys.exit(f"declared in info.yaml and absent from the routed DEF: {missing}")
    for use in {u for _, u in pins}:
        if use not in tpl:
            sys.exit(f"no pad of USE {use} in {PADFRAME.name} to take the shape from")

    #  SELF-CHECK. When the list in force is used, this DEF is being built
    #  against the very padring the organisers generated FROM IT, so the pin
    #  geometry must come out identical to theirs. If it does not, the slot
    #  derivation at the top of this file has drifted and everything downstream
    #  is wrong -- better to stop here than to hand them a DEF that looks right.
    theirs = read_padframe(PADFRAME)
    mine = {n: (u, [(tpl[u]["layer"],) + _rect(slot_centre(i), a)
                    for a in tpl[u]["along"]])
            for i, (n, u) in enumerate(pins)}
    #  The attachment was generated FROM a pin list. If this one is that list,
    #  the geometry must come out identical -- that is the only check there is
    #  that the slot derivation at the top of this file is right, so it is not
    #  optional. If the list has since been reordered on purpose, the attachment
    #  is stale and the check cannot pass; say so loudly instead of pretending.
    their_order = list(theirs)
    our_order = [n for n, _ in pins]
    if their_order == our_order:
        bad = [n for n in theirs if theirs[n] != mine[n]]
        if bad:
            sys.exit(f"  the geometry does not reproduce {PADFRAME.name}: {bad}")
        print(f"  self-check: the {len(mine)} pins come out identical to "
              f"{PADFRAME.name}, which was generated from this same list")
    else:
        moved = [n for a, b in zip(their_order, our_order) if a != b for n in (a,)]
        print(f"  NOTE: {PADFRAME.name} was generated from a DIFFERENT order, so")
        print(f"        it is STALE and the organisers have to regenerate it.")
        print(f"        theirs: {' '.join(their_order)}")
        print(f"        ours  : {' '.join(our_order)}")
        print(f"        This DEF is built from ours, which is the one to ask for.")

    origin = best_origin(pins, die_pins, die_w, die_h)
    dest.write_text(emit(pins, tpl, origin, die_w, die_h))

    cost, ox, oy = origin
    print(f"  pin list: {which}")
    print(f"  user area {AREA / DBU:.0f} x {AREA / DBU:.0f} um, "
          f"block {die_w:.2f} x {die_h:.2f} um")
    print(f"  origin ({ox:.1f}, {oy:.1f}) um   total pad->pin {cost:.0f} um")
    for i, (name, use) in enumerate(pins):
        edge, centre = slot_centre(i)
        slot = f"W{12 + i}" if edge == "W" else f"N{i - N_WEST + 1:02d}"
        px, py = pad_point(edge, centre)
        dx, dy = die_pins[name]
        d = abs(px - (ox + dx)) + abs(py - (oy + dy))
        print(f"    {name:5s} {use:7s} {slot:4s} pad ({px:7.1f},{py:7.1f}) "
              f"pin ({ox + dx:7.1f},{oy + dy:7.1f})  {d:6.1f} um")
    print(f"  -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
