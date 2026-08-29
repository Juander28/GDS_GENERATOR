#!/usr/bin/env python3
"""Turn the hierarchical Xschem netlist of GRADIENT_NAV into structural Verilog.

The netlist is the only place where the connectivity of the chip is written
down, so the Verilog is derived from it instead of being typed by hand: a wrong
wire routes perfectly and gives you the wrong chip.

    a_zonetic2026/XSCHEM/simulation/GRADIENT_NAV.sch/GRADIENT_NAV.spice
        -> openroad/verilog/GRADIENT_NAV.v

Two kinds of module come out:

  * **structural** — a `.subckt` whose body is only subcircuit calls. It gets a
    real body: one instance per call, ports connected by name.
  * **black box** — a `.subckt` that contains transistors, or one named in
    `MACROS` because it has a layout and therefore a LEF. It gets ports and an
    empty body. OpenROAD binds those to the LEF `MACRO` of the same name; yosys
    needs them declared so it does not invent a cell.

Port directions come from the `*.PININFO` / `*.ipin` / `*.opin` / `*.iopin`
annotations that Xschem writes, which is why the schematic pin type matters.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path("/foss/designs/a_zonetic2026")
XSCHEM = PROJECT / "XSCHEM"
VERILOG = Path(__file__).resolve().parent.parent / "verilog"

#: Which top gets translated. `GRADIENT_NAV` builds four GRADIENT blocks, with
#: the 98 dB OPAM; `GRADIENT_NAV2` is the same schematic with GRADIENT2, that is
#: with the linear amplifier. Both have to coexist, so everything generated
#: carries the name of its top.
TOP = os.environ.get("TOP_CELL", "GRADIENT_NAV")
NETLIST = XSCHEM / f"simulation/{TOP}.sch/{TOP}.spice"
OUT = VERILOG / f"{TOP}.v"
OUT_FLAT = VERILOG / f"{TOP}_macros.v"

#: Blocks that have a layout, so they are hard macros no matter what is inside.
MACROS = {"COMP", "OPAM", "OPAM_LIN_flat", "DECODER", "WEIGHT_COMP",
          "DECODER_MAX", "OPAM_SUMA", "ESD_CDM", "io_secondary_5p0"}

#: Schematic cell -> layout macro, when the two are not named the same.
#: `OPAM_LIN_flat.sch` is the flattened version of `OPAM_LIN.sch` drawn for the
#: layout: same circuit, different cell name.
ALIAS = {"OPAM_LIN": "OPAM_LIN_flat"}

#: A macro that is not instantiated as such in the top: its schematic packs two
#: of the top's sub-circuits into one cell. See `find_fusions`.
FUSED = {"WEIGHT_COMP": XSCHEM / "WEIGTH/simulation/WEIGHT_COMP.sch/WEIGHT_COMP.spice"}

#: SPICE element letters that mean "this is a device, not a subcircuit call".
DEVICE_LETTERS = "MQDJRCLVIKEFGHSTWZ"

DIR_WORD = {"I": "input", "O": "output", "B": "inout"}


class Subckt:
    def __init__(self, name: str, ports: list[str]) -> None:
        self.name = name
        self.ports = ports
        self.dirs: dict[str, str] = {}
        self.insts: list[tuple[str, str, list[str]]] = []   # (inst, cell, nets)
        self.has_devices = False

    @property
    def blackbox(self) -> bool:
        return self.has_devices or self.name in MACROS


def join_continuations(text: str) -> list[str]:
    """Fold SPICE '+' continuation lines onto the line they continue."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("+"):
            if lines:
                lines[-1] += " " + line[1:].strip()
            continue
        lines.append(line)
    return lines


def parse(text: str) -> tuple[dict[str, Subckt], Subckt]:
    """Read every .subckt, plus the top level that Xschem leaves commented out.

    The top level of an Xschem netlist is written as `**.subckt NAME ports` with
    the pin directions on `*.ipin` / `*.opin` / `*.iopin` lines; every level
    below it is a real `.subckt` with a single `*.PININFO` line. Both are read
    here so the top is not a special case anywhere else.
    """
    subckts: dict[str, Subckt] = {}
    top: Subckt | None = None
    cur: Subckt | None = None

    for line in join_continuations(text):
        stripped = line.strip()
        if not stripped:
            continue

        low = stripped.lower()

        if low.startswith("**.subckt "):            # top level, commented out
            tok = stripped.split()
            top = Subckt(tok[1], tok[2:])
            cur = top
            continue
        if low.startswith("**.ends"):
            cur = None
            continue

        if stripped.startswith("*.PININFO"):
            if cur is not None:
                for item in stripped.split()[1:]:
                    net, _, code = item.rpartition(":")
                    cur.dirs[net] = DIR_WORD.get(code, "inout")
            continue
        if stripped.startswith(("*.ipin", "*.opin", "*.iopin")):
            kind, _, net = stripped.partition(" ")
            if cur is not None and net:
                cur.dirs[net.strip()] = {"*.ipin": "input",
                                         "*.opin": "output"}.get(kind, "inout")
            continue

        if stripped.startswith("*"):                # any other comment
            continue

        if low.startswith(".subckt "):
            tok = stripped.split()
            #  The alias applies both when DEFINING and when INSTANTIATING, so
            #  that from here on the whole file speaks the macro name and not
            #  the schematic cell.
            cur = Subckt(ALIAS.get(tok[1], tok[1]), tok[2:])
            subckts[cur.name] = cur
            continue
        if low.startswith(".ends"):
            cur = None
            continue
        if stripped.startswith("."):                # .end, .include, ...
            continue

        if cur is None:
            continue

        tok = stripped.split()
        inst = tok[0]
        if inst[0].upper() in DEVICE_LETTERS:
            # A device, or an 'XM12 ... pfet_06v0 L=...' which is a device too:
            # the model card is what makes it one, not the leading letter.
            cur.has_devices = True
            continue
        if inst[0].upper() != "X":
            continue

        args = [t for t in tok[1:] if "=" not in t]
        if not args:
            continue
        cell, nets = ALIAS.get(args[-1], args[-1]), args[:-1]
        if cell in MACROS or not any(c in cell for c in "=."):
            cur.insts.append((inst, cell, nets))

    if top is None:
        raise SystemExit(f"no top-level '**.subckt' found in {NETLIST}")

    # An X-call whose cell has a model card is a device (a MIM cap, say), not a
    # hierarchy level. Drop those once every .subckt name is known.
    for sub in [top, *subckts.values()]:
        kept = []
        for inst, cell, nets in sub.insts:
            if cell in subckts or cell in MACROS:
                kept.append((inst, cell, nets))
            else:
                sub.has_devices = True
        sub.insts = kept

    return subckts, top


#: Xschem happily names a pin 'output' or 'input'; Verilog does not. Escaping is
#: preferred over renaming because the schematic is the user's, not ours.
KEYWORDS = {
    "always", "and", "assign", "begin", "buf", "case", "default", "defparam",
    "else", "end", "endcase", "endmodule", "for", "function", "generate",
    "genvar", "if", "initial", "inout", "input", "integer", "localparam",
    "logic", "module", "nand", "negedge", "nor", "not", "or", "output",
    "parameter", "posedge", "reg", "supply0", "supply1", "time", "tri",
    "wand", "while", "wire", "wor", "xnor", "xor",
}


def ident(net: str) -> str:
    """Verilog identifier, escaped if the SPICE name is not one already."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", net) and net not in KEYWORDS:
        return net
    return f"\\{net} "


def emit_module(sub: Subckt, subckts: dict[str, Subckt]) -> str:
    out: list[str] = []
    kind = "black box" if sub.blackbox else "structural"
    out.append(f"// {sub.name} ({kind})")
    out.append(f"module {sub.name} (")
    out.append(",\n".join(f"    {ident(p)}" for p in sub.ports))
    out.append(");")
    for p in sub.ports:
        out.append(f"    {sub.dirs.get(p, 'inout'):6s} {ident(p)};")

    if sub.blackbox:
        out.append("")
        out.append("endmodule")
        out.append("")
        return "\n".join(out)

    # Internal nets: everything an instance touches that is not a port.
    internal = []
    seen = set(sub.ports)
    for _, _, nets in sub.insts:
        for net in nets:
            if net not in seen:
                seen.add(net)
                internal.append(net)
    if internal:
        out.append("")
        for net in internal:
            out.append(f"    wire   {ident(net)};")

    out.append("")
    for inst, cell, nets in sub.insts:
        target = subckts.get(cell)
        names = target.ports if target else [f"p{i}" for i in range(len(nets))]
        if target and len(names) != len(nets):
            raise SystemExit(f"{sub.name}.{inst}: {cell} takes {len(names)} "
                             f"pins, {len(nets)} given")
        conns = ",\n".join(f"        .{ident(pin)}({ident(net)})"
                           for pin, net in zip(names, nets))
        out.append(f"    {cell} {inst} (\n{conns}\n    );")
    out.append("")
    out.append("endmodule")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
#  flat, macros-only top
# --------------------------------------------------------------------------- #
def load_fusions() -> list[tuple[str, Subckt, dict[str, Subckt]]]:
    """Read each fused macro's own netlist: ports, and the children it packs."""
    out = []
    for macro, path in FUSED.items():
        if not path.exists():
            raise SystemExit(f"{macro}: cannot read the fusion pattern, {path} missing")
        subs, pat = parse(path.read_text())
        if pat.name != macro:
            raise SystemExit(f"{path} declares {pat.name}, expected {macro}")
        out.append((macro, pat, subs))
    return out


def flatten(top: Subckt, subckts: dict[str, Subckt],
            leaves: set[str] = frozenset()) -> list[tuple[str, str, dict]]:
    """Expand every non-macro level, leaving only macro instances.

    Returns [(instance path, cell, {pin: net})]. Internal nodes are prefixed with
    the instance path, so `net1` inside `x1` becomes `x1_net1` and the four
    copies of GRADIENT stop sharing a node they never shared.
    """
    out: list[tuple[str, str, dict]] = []

    def walk(sub: Subckt, prefix: str, portmap: dict[str, str]) -> None:
        def net_of(local: str) -> str:
            return portmap.get(local, f"{prefix}{local}")

        for iname, cell, args in sub.insts:
            child = subckts[cell]
            nets = [net_of(a) for a in args]
            conns = dict(zip(child.ports, nets))
            # Stop at anything with no body to descend into: a macro, or a
            # transistor-level leaf. Leaves that are not macros survive to be
            # fused (WEIGHT, COMP_OUT); whatever is left over after that has no
            # LEF and is caught by the check in main().
            if child.blackbox or cell in leaves:
                out.append((f"{prefix}{iname}", cell, conns))
            else:
                walk(child, f"{prefix}{iname}_", conns)

    walk(top, "", {p: p for p in top.ports})
    return out


def apply_fusions(insts: list[tuple[str, str, dict]],
                  patterns: list[tuple[str, Subckt, dict[str, Subckt]]],
                  ) -> list[tuple[str, str, dict]]:
    """Replace groups of instances by the single macro that implements them.

    WEIGHT_COMP is one cell holding a WEIGHT and a COMP_OUT, but the top
    instantiates those two separately. The pattern is not written out here: it is
    read from WEIGHT_COMP's own netlist and then *matched*, so it stays true if
    the schematic changes and raises if it stops matching. That matters because
    the pin order is not the identity — WEIGHT_COMP feeds its `VB` into WEIGHT's
    `VC` pin and vice versa, and a hand-typed mapping would swap two weights and
    still route perfectly.
    """
    for macro, pat, pat_subs in patterns:
        by_cell: dict[str, list[int]] = {}
        for i, (_, cell, _) in enumerate(insts):
            by_cell.setdefault(cell, []).append(i)

        wanted = [cell for _, cell, _ in pat.insts]
        taken: set[int] = set()
        fused: list[tuple[str, str, dict]] = []

        for lead in by_cell.get(wanted[0], []):
            if lead in taken:
                continue
            for other in by_cell.get(wanted[1], []):
                if other in taken or len(wanted) != 2:
                    continue
                bind: dict[str, str] = {}
                good = True
                for (_, pcell, pargs), idx in zip(pat.insts, (lead, other)):
                    name, cell, conns = insts[idx]
                    child = pat_subs[pcell]
                    for local, pin in zip(pargs, child.ports):
                        if bind.setdefault(local, conns[pin]) != conns[pin]:
                            good = False
                if not good or any(p not in bind for p in pat.ports):
                    continue
                base = insts[lead][0]
                fused.append((f"{base}_{macro.lower()}", macro,
                              {p: bind[p] for p in pat.ports}))
                taken |= {lead, other}
                break

        if not fused:
            continue
        insts = [x for i, x in enumerate(insts) if i not in taken] + fused
    return insts


def emit_flat(top: Subckt, insts: list[tuple[str, str, dict]],
              subckts: dict[str, Subckt]) -> str:
    ports = top.ports
    nets: list[str] = []
    seen = set(ports)
    for _, _, conns in insts:
        for net in conns.values():
            if net not in seen:
                seen.add(net)
                nets.append(net)

    out = [
        "// " + "-" * 74,
        f"//  {top.name} — flat top: nothing but hard macros.",
        "//",
        "//  DO NOT EDIT: regenerate with",
        "//      python3 scripts/spice_to_verilog.py",
        "//",
        f"//  source: {NETLIST}",
        f"//  built:  {datetime.now():%Y-%m-%d %H:%M}",
        "//",
        "//  This is what OpenROAD reads. Every instance below has a LEF MACRO,",
        "//  so there is nothing left to elaborate and nothing to place but the",
        "//  blocks themselves. The black-box module headers live in the per-macro",
        "//  files that build_collateral.py writes; they are for yosys, not for",
        "//  OpenROAD (see the README).",
        "// " + "-" * 74,
        "",
        f"module {top.name} (",
        ",\n".join(f"    {ident(p)}" for p in ports),
        ");",
    ]
    out += [f"    {top.dirs.get(p, 'inout'):6s} {ident(p)};" for p in ports]
    if nets:
        out.append("")
        out += [f"    wire   {ident(n)};" for n in nets]
    out.append("")
    for name, cell, conns in sorted(insts, key=lambda t: (t[1], t[0])):
        body = ",\n".join(f"        .{ident(pin)}({ident(net)})"
                          for pin, net in conns.items())
        out.append(f"    {cell} {name} (\n{body}\n    );")
    out += ["", "endmodule", ""]
    return "\n".join(out)


def main() -> None:
    text = NETLIST.read_text()
    subckts, top = parse(text)
    #  The top level is never a black box, even when it carries loose devices.
    #  Since `decap_fill.py` started writing the decoupling capacitor block into
    #  the schematic, `parse` sets `has_devices` on the top and `emit_module`
    #  would write it with no body. OpenROAD reads `<TOP>_macros.v`, which comes
    #  from `emit_flat` and ignores this, so the flow never broke -- but it left
    #  `<TOP>.v` lying. The capacitors stay out of the Verilog on purpose: they
    #  are not macros, not placed and not routed; they go onto the GDS after.
    top.has_devices = False
    subckts_all = dict(subckts)
    subckts_all[top.name] = top

    #  A macro the top calls WITHOUT xschem having inlined its .subckt. That
    #  happens when the instance is written as text -- the eleven ESD_CDM cells
    #  are a code block, not eleven drawn symbols -- so the netlist carries the
    #  calls and no definition, and `flatten` died on a KeyError with no clue
    #  what was missing. The ports are read from the macro's OWN netlist in
    #  spice_blocks/, which is the source of truth for them anyway.
    for cell in sorted(MACROS):
        if cell in subckts_all:
            continue
        if not any(c == cell for _, c, _ in top.insts):
            continue
        src = PROJECT / "spice_blocks" / f"{cell}.spice"
        if not src.exists():
            sys.exit(f"  {cell} is instantiated in the top and has no .subckt; "
                     f"expected its ports in {src}")
        for line in join_continuations(src.read_text()):
            m = re.match(r"\*?\*?\.subckt\s+(\S+)\s+(.*)", line, re.I)
            if m and m.group(1) == cell:
                subckts_all[cell] = Subckt(cell, m.group(2).split())
                print(f"  {cell}: ports read from {src.name} "
                      f"({' '.join(subckts_all[cell].ports)})")
                break
        else:
            sys.exit(f"  no .subckt {cell} in {src}")

    # Only what the top actually reaches: the netlist carries every symbol the
    # schematic ever referenced, and unused ones are noise in the Verilog.
    used: set[str] = set()
    stack = [top.name]
    while stack:
        name = stack.pop()
        if name in used:
            continue
        used.add(name)
        sub = subckts_all.get(name)
        if sub is None or sub.blackbox:
            continue
        stack.extend(cell for _, cell, _ in sub.insts)

    order = [n for n in subckts_all if n in used and n != top.name]
    order.sort(key=lambda n: (not subckts_all[n].blackbox, n))

    header = [
        "// " + "-" * 74,
        f"//  {top.name} — structural Verilog, generated from the Xschem netlist.",
        "//",
        "//  DO NOT EDIT: regenerate with",
        "//      python3 scripts/spice_to_verilog.py",
        "//",
        f"//  source: {NETLIST}",
        f"//  built:  {datetime.now():%Y-%m-%d %H:%M}",
        "//",
        "//  Black-box modules have ports and no body. OpenROAD binds them to the",
        "//  LEF MACRO of the same name; giving it a body would make OpenROAD",
        "//  elaborate an empty hierarchy and drop the instance.",
        "// " + "-" * 74,
        "",
        "`default_nettype none",
        "",
    ]

    body = [emit_module(subckts_all[n], subckts_all) for n in order]
    body.append(emit_module(top, subckts_all))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(header) + "\n".join(body) + "\n`default_nettype wire\n")

    boxes = [n for n in order if subckts_all[n].blackbox]
    struct = [n for n in order if not subckts_all[n].blackbox] + [top.name]
    print(f"{OUT}")
    print(f"  structural: {' '.join(struct)}")
    print(f"  black box : {' '.join(boxes)}")
    total = sum(len(subckts_all[n].insts) for n in struct)
    print(f"  {len(order) + 1} modules, {total} instances")

    # ---- flat, macros-only view ------------------------------------------- #
    patterns = load_fusions()
    leaves = {cell for _, pat, _ in patterns for _, cell, _ in pat.insts}
    insts = apply_fusions(flatten(top, subckts_all, leaves), patterns)
    stray = sorted({cell for _, cell, _ in insts if cell not in MACROS})
    if stray:
        raise SystemExit(
            "no LEF macro for: " + ", ".join(stray) +
            "\nEither give the block a layout, or add it to FUSED if another "
            "macro already implements it.")
    OUT_FLAT.write_text(emit_flat(top, insts, subckts_all))

    count: dict[str, int] = {}
    for _, cell, _ in insts:
        count[cell] = count.get(cell, 0) + 1
    print(f"{OUT_FLAT}")
    print("  " + "  ".join(f"{n}x {c}" for c, n in sorted(count.items())))
    print(f"  {len(insts)} macro instances")


if __name__ == "__main__":
    sys.exit(main())
