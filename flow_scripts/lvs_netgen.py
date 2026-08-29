#!/usr/bin/env python3
"""netgen LVS on the blocks and on the top.

A second opinion against KLayout's LVS, with two independent engines and two
different extractions: KLayout's comes from its own deck and this one from
magic (`layouts/<B>/mag/<B>_extracted.spice`, already produced by `build_block.py`).
Both saying the same thing is worth a good deal more than one saying it.

    python3 scripts/lvs_netgen.py [block ...]

With no arguments it runs the blocks. `GRADIENT_NAV` is asked for separately
because the top must first be extracted with magic, which is slow.
"""

from __future__ import annotations

import re
import subprocess
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Output directory of the top. Defaults to `out`, which is v1's.
#: `TOP_OUT` changes it so the v2 top can be checked without stepping on v1:
#: both have to coexist to be compared.
OUT = ROOT / os.environ.get("TOP_OUT", "out")

#: Which top cell gets checked. `GRADIENT_NAV` builds four GRADIENT blocks
#: (the 98 dB OPAM); `GRADIENT_NAV2` is the same schematic with GRADIENT2,
#: that is with OPAM_LIN_flat. The Makefile sets it with `T=`, like `TOP_OUT`.
TOP = os.environ.get("TOP_CELL", "GRADIENT_NAV")

PROJECT = ROOT.parent
LAYOUTS = PROJECT / "layouts"
NETGEN = "/foss/tools/bin/netgen"
SETUP = "/foss/pdks/gf180mcuD/libs.tech/netgen/gf180mcuD_setup.tcl"
#: The PDK setup only declares `ppolyf_u_1k`, and without the device on its list
#: there is no SERIES reduction: the serpentine extracts as N chained segments
#: and the reference carries one. This adds 2k and 3k without touching the PDK.
#: It is the same one `zotnetic_layout/run_lvs.sh` uses on the blocks.
SETUP_POLYRES = "/foss/designs/zotnetic_layout/lvs/gf180mcuD_setup_polyres.tcl"
MAGIC = "/foss/tools/bin/magic"
MAGICRC = "/foss/pdks/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc"

BLOCKS = ("COMP", "OPAM", "OPAM_LIN_flat", "DECODER", "WEIGHT_COMP",
          "DECODER_MAX", "OPAM_SUMA", "ESD_CDM")

#: Blocks that only exist in v2, if any.
SOLO_V2: set[str] = {"DECODER_MAX", "OPAM_SUMA", "ESD_CDM"}


def block_pair(name: str) -> tuple[Path, Path]:
    """(layout netlist, reference netlist) of a block."""
    d = (PROJECT / "layouts_v2" if name in SOLO_V2 else LAYOUTS) / name
    return d / "mag" / f"{name}_extracted.spice", d / f"{name}_lvs.spice"


def extract_top(work: Path, gds: Path | None = None) -> Path:
    """Extracts the top GDS with magic. This is the slowest part of all of it.

    `gds` lets you pick which of the three top files gets extracted: the bare
    one, the one with decoupling, or the one that also has the density fill. All
    three share the same cell and compare against the same reference.
    """
    work.mkdir(parents=True, exist_ok=True)
    (work / ".ext").mkdir(exist_ok=True)
    gds = gds or (OUT / f"{TOP}.gds")
    out = work / f"{TOP}_extracted.spice"
    script = work / "extract_top.tcl"
    script.write_text(
        f"gds read {gds}\n"
        f"load {TOP}\n"
        # Flatten BEFORE extracting, the same as build_block.py does with each
        # block. Without this the extraction comes out hierarchical and the net
        # names carry the instance path (`Unnamed_976$1_0/w_...`): netgen saw 994
        # nets against the 880 of the reference, nearly all fragments of one.
        f"flatten {TOP}_f\n"
        f"load {TOP}_f\n"
        f"cellname delete {TOP}\n"
        f"cellname rename {TOP}_f {TOP}\n"
        "select top cell\n"
        #  The SAME recipe `build_block.py` uses on each block. The previous one
        #  had `extract do local` and no `extract path`, and with it every
        #  macro's n-well came out as a floating node (`w_1724_75756#`) instead
        #  of VDD: 43 extra well nets and 47 extra active ones, which is almost
        #  the whole 986 against 880 gap. Extracted like the blocks, it is gone.
        f"extract path {work / '.ext'}\n"
        "ext2spice lvs\n"
        "extract all\n"
        f"ext2spice -p {work / '.ext'} -o {TOP}_extracted.spice\n"
        "quit -noprompt\n")
    subprocess.run(
        [MAGIC, "-dnull", "-noconsole", "-rcfile", MAGICRC, script.name],
        cwd=work, capture_output=True, text=True, timeout=14400, check=False,
        env={"PATH": "/usr/bin:/bin", "PDK_ROOT": "/foss/pdks", "HOME": "/tmp"})
    if not out.exists():
        sys.exit(f"magic did not extract the top; {out} is missing")
    return out


#: What magic calls the MIM on extraction, versus what the schematic calls it.
#: They are the same device; the names differ because one comes from the magic
#: techfile and the other from the xschem symbol.
_CAP_MODEL = ("cap_mim_2f0fF", "cap_mim_2f0_m4m5_noshield")


def as_subckt_calls(ref: Path, work: Path) -> Path:
    """Turns the reference `M...` MOSFETs into `X...` subcircuit calls.

    The two LVS engines want opposite conventions and there is no single one that
    suits both. KLayout needs `M` -- an element starting with any other letter is
    not a MOSFET to SPICE, and with `X` it read zero transistors. magic, on the
    other hand, extracts `X0 ... pfet_06v0`, because in the PDK those models are
    subcircuits, and netgen then compares a subcircuit call against a device and
    empareja ni uno.

    Same with the MIM capacitors: the reference carries them as `C` elements with
    model `cap_mim_2f0fF` and magic extracts them as a call to
    `cap_mim_2f0_m4m5_noshield`, so netgen was comparing a capacitor with
    `top`/`bottom` pins against a subcircuit with positional pins and matched
    neither.

    So the reference is translated here, for netgen and only for netgen. The
    `<B>_lvs.spice` on disk is left alone: that is the one KLayout uses.
    """
    src = ref.read_text().splitlines()
    out, n = [], 0
    for line in src:
        # xschem comments out the top cell `.subckt` when exporting from
        # la CLI (`**.subckt GRADIENT_NAV ...`). netgen necesita verlo.
        if line.startswith("**.subckt ") or line.startswith("**.ends"):
            out.append(line[2:])
            n += 1
        elif re.match(r"^[Mm]\S*\s", line):
            out.append("X" + line)
            n += 1
        elif re.match(r"^[Cc]\S*\s", line) and _CAP_MODEL[0] in line:
            out.append("X" + line.replace(*_CAP_MODEL))
            n += 1
        else:
            out.append(line)
    if not n:
        return ref
    work.mkdir(parents=True, exist_ok=True)
    dst = work / (ref.stem + "_netgen.spice")
    dst.write_text("\n".join(out) + "\n")
    return dst


#: The poly resistor sheets magic canNOT tell apart.
_RE_POLY = re.compile(r"\bppolyf_u_([123])k\b")


def hoja_poly(ref: Path) -> str | None:
    """Which poly sheet the reference is written with: `ppolyf_u_3k` or none.

    1k, 2k and 3k **are drawn identically**: same layer, what changes is a
    process option. That is why the magic techfile only declares `ppolyf_u_1k`
    always extracts that one, even when the circuit asks for another.
    """
    sheets = set(_RE_POLY.findall(ref.read_text()))
    return f"ppolyf_u_{sheets.pop()}k" if len(sheets) == 1 else None


def _hoja_resistencia(layout: Path, model: str, work: Path) -> Path:
    """Sets on the extracted netlist the poly sheet the reference asks for.

    It is what `build_block.py::_hoja_resistencia` does to each block, and what
    the top was missing: magic extracted `ppolyf_u_1k (60->12)` against the
    `ppolyf_u_3k (12)` of the reference, and netgen cannot match two different
    device classes. With 1401 devices and 880 nets identical on both sides,
    **the 12 resistors brought down the whole comparison**: every net touching
    one was left in fragments and the top ended in `failed pin matching`. The v1
    top never saw it because its OPAM carries no resistors.

    The original on disk is untouched: the copy goes to `work/`.
    """
    txt = layout.read_text()
    nuevo, n = re.subn(r"\bppolyf_u_1k\b", model, txt)
    if not n:
        return layout
    work.mkdir(parents=True, exist_ok=True)
    dst = work / (layout.stem + "_hoja.spice")
    dst.write_text(nuevo)
    return dst


def _plegar(text: str) -> list[str]:
    """SPICE lines with their `+` continuations folded onto the line they continue.

    **magic splits the `.subckt` header by column**, not by content: the v2 top
    comes out as

        .subckt GRADIENT_NAV2 S1N S1P ... ZP VDD
        + VSS

    Reading only the first physical line, `VSS` is missing, `align_ports` sees
    the port sets disagree, gives up (rightly: a port is missing) and leaves
    magic's order. netgen then matches the top pins **by position** and falls
    over with `Top level cell failed pin matching` -- with 1401 devices and 880
    nets identical on both sides. The v1 top escaped by luck: its 19 ports fitted
    on one line.
    """
    out: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("+") and out:
            out[-1] += " " + raw[1:].strip()
        else:
            out.append(raw)
    return out


def align_ports(layout: Path, ref: Path, cell: str, work: Path) -> Path:
    """Reorders the extracted `.subckt` ports to follow the reference order.

    magic lists them in the order it finds the labels and the schematic in its
    own, and netgen matches the top pins **by position**: with the very same
    conectividad exacta (18 device_lines y 86 nets a cada lado en DECODER)
    it ended in `Top level cell failed pin matching` for that reason alone, and
    warning on top that the block's symmetries kept it from breaking the tie.

    Reordering the top cell's port list cannot change anything: nobody
    instantiates it, so that order is nothing but its interface.
    """
    def ports(path: Path) -> list[str]:
        for line in _plegar(path.read_text()):
            if line.lower().startswith(".subckt ") and line.split()[1] == cell:
                return line.split()[2:]
        sys.exit(f"no encuentro '.subckt {cell}' en {path}")

    want, have = ports(ref), ports(layout)
    if set(want) != set(have):
        # A missing or extra port is NOT fixed by reordering: it is a real
        # difference and LVS has to see it.
        return layout
    if want == have:
        return layout

    work.mkdir(parents=True, exist_ok=True)
    out = work / f"{cell}_extracted_ordered.spice"
    lines = []
    for line in _plegar(layout.read_text()):
        if line.lower().startswith(".subckt ") and line.split()[1] == cell:
            line = ".subckt " + cell + " " + " ".join(want)
        lines.append(line)
    out.write_text("\n".join(lines) + "\n")
    return out


def _mim_models(path: Path) -> list[str]:
    """Under what name the MIM appears in a netlist."""
    return sorted(set(re.findall(r"\bcap_mim\w*", path.read_text())))


def setup_with_cap_permute(work: Path, layout: Path, ref: Path) -> Path:
    """The PDK setup plus the two MIM terminals declared permutable.

    The two MIMs in COMP and OPAM are identical and share a terminal on `OUT`:
    topologically they are interchangeable but for the order of their two pins,
    and netgen cannot break that tie -- it says so itself, `Port matching may
    fail to disambiguate symmetries`. With 52 devices and 37 nets identical on
    each side, that was all that was left.

    Permuting the two terminals of a two-pin capacitor is what KLayout's LVS
does, and it reports `Netlists match` on these very netlists.

    **The name is taken from each netlist, not hard-coded.** It used to be
    written flat as `cap_mim_2f0_m4m5_noshield` in both circuits, and on the top
    that name only exists in the layout: the reference instantiates them as
    `cap_mim_2f0fF` (`as_subckt_calls` only renames those arriving as a `C`
    element, and on the top they already arrive as an `X` call). So **the MIM was
    permutable in the layout and fixed in the reference**, and neither side could
    match: the layout counted `cap/(1|2) = 2` where the reference counted
    `cap/1 = 1` and `cap/2 = 1`. Same connectivity, different pin class.
    """
    work.mkdir(parents=True, exist_ok=True)
    #  If the circuit carries 2k or 3k poly the local setup is needed: the PDK
    #  one does not declare those devices and without that it will not reduce
    base = SETUP_POLYRES if (hoja_poly(ref) or "1k") != "ppolyf_u_1k" else SETUP
    lines = [f"source {base}"]
    for n, path in ((1, layout), (2, ref)):
        for model in _mim_models(path):
            lines.append(f'permute "-circuit{n} {model}" 1 2')
    dst = work / "setup_con_permute.tcl"
    dst.write_text("\n".join(lines) + "\n")
    return dst


def compare(layout: Path, ref: Path, cell: str, report: Path,
            setup: Path) -> tuple[bool, str]:
    cmd = (f'lvs "{layout} {cell}" "{ref} {cell}" {setup} {report} '
           f'-json -blackbox\n')
    r = subprocess.run([NETGEN, "-batch", "source", "/dev/stdin"],
                       input=cmd, capture_output=True, text=True,
                       timeout=7200, check=False)
    out = r.stdout + r.stderr
    text = report.read_text() if report.exists() else out
    ok = "Circuits match uniquely" in text or "Circuits match uniquely" in out
    return ok, out


def main() -> int:
    names = sys.argv[1:] or list(BLOCKS)
    outdir = OUT
    outdir.mkdir(parents=True, exist_ok=True)
    bad = 0
    for name in names:
        if name.startswith(TOP):
            #  `GRADIENT_NAV2`, `..._DECAP` and `..._FILLED` are the same cell
            #  with more inside, and compare against the same reference.
            sufijo = {"_DECAP": "_decap", "_FILLED": "_filled"}.get(
                name[len(TOP):], "")
            layout = extract_top(ROOT / "work_lvs", OUT / f"{TOP}{sufijo}.gds")
            ref = PROJECT / f"XSCHEM/simulation/{TOP}.sch/{TOP}.spice"
            name = TOP
        else:
            layout, ref = block_pair(name)
        for p in (layout, ref):
            if not p.exists():
                print(f"  {name:14s} falta {p}")
                bad += 1
                break
        else:
            work = ROOT / "work_lvs"
            ref = as_subckt_calls(ref, work)
            model = hoja_poly(ref)
            if model and model != "ppolyf_u_1k":
                layout = _hoja_resistencia(layout, model, work)
            layout = align_ports(layout, ref, name, work)
            report = outdir / f"lvs_netgen_{name}.rpt"
            ok, log = compare(layout, ref, name, report,
                              setup_with_cap_permute(work, layout, ref))
            (outdir / f"lvs_netgen_{name}.log").write_text(log)
            print(f"  {name:14s} {'Circuits match uniquely' if ok else 'NO CUADRA'}"
                  f"   -> {report.name}")
            if not ok:
                bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
