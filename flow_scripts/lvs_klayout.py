#!/usr/bin/env python3
"""LVS with the KLayout sign-off deck, on the top as well.

The blocks already pass it from `build_block.py`; this extends it to the top,
which until now was only checked with netgen. It is needed because a **short
ninguna regla de DRC** —dos formas de nets distintas que se solapan simplemente
se funden en un poligono— y `check_connectivity.py` tampoco lo ve: el comprueba
that the terminals of each net are together, not that there are no extra ones.
canta un corto con nombres y coordenadas es el LVS.

    python3 scripts/lvs_klayout.py [block ...]
"""

from __future__ import annotations

import subprocess
import os
import sys
import re
from pathlib import Path

import klayout.db as kdb

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
RUNNER = "/foss/pdks/gf180mcuD/libs.tech/klayout/tech/lvs/run_lvs.py"

#: Threads for the deck. Two, not four, for the same reason `drc_klayout.MP` is
#: two: extracting the integrated area with its 7.8 M fill shapes does not fit
#: four times over in 7 GB. `LVS_THR` raises it on a bigger machine.
THR = os.environ.get("LVS_THR", "2")

#: Top reference: the netlist xschem exports from the schematic.
REF_TOP = PROJECT / f"XSCHEM/simulation/{TOP}.sch/{TOP}.spice"


TARGETS = {
    TOP: (OUT / f"{TOP}.gds", REF_TOP),
    #  The top with decoupling and the top with density fill. All three share
    #  cell and reference: what changes is the GDS.
    f"{TOP}_DECAP": (OUT / f"{TOP}_decap.gds", REF_TOP),
    f"{TOP}_FILLED": (OUT / f"{TOP}_filled.gds", REF_TOP),
    "COMP": (ROOT / "gds/COMP.gds", PROJECT / "layouts/COMP/COMP_lvs.spice"),
    "OPAM": (ROOT / "gds/OPAM.gds", PROJECT / "layouts/OPAM/OPAM_lvs.spice"),
    "DECODER": (ROOT / "gds/DECODER.gds", PROJECT / "layouts/DECODER/DECODER_lvs.spice"),
    "WEIGHT_COMP": (ROOT / "gds/WEIGHT_COMP.gds",
                    PROJECT / "layouts/WEIGHT_COMP/WEIGHT_COMP_lvs.spice"),
    "OPAM_LIN_flat": (ROOT / "gds/OPAM_LIN_flat.gds",
                      PROJECT / "layouts/OPAM_LIN_flat/OPAM_LIN_flat_lvs.spice"),
    #  The two v2 ones, which only exist in layouts_v2/.
    "DECODER_MAX": (ROOT / "gds/DECODER_MAX.gds",
                    PROJECT / "layouts_v2/DECODER_MAX/DECODER_MAX_lvs.spice"),
    "ESD_CDM": (ROOT / "gds/ESD_CDM.gds",
                PROJECT / "layouts_v2/ESD_CDM/ESD_CDM_lvs.spice"),
    "OPAM_SUMA": (ROOT / "gds/OPAM_SUMA.gds",
                  PROJECT / "layouts_v2/OPAM_SUMA/OPAM_SUMA_lvs.spice"),
    "io_secondary_5p0": (ROOT / "gds/io_secondary_5p0.gds",
                        PROJECT / "layouts_v2/io_secondary_5p0/io_secondary_5p0_lvs.spice"),
}


def prepare(ref: Path, cell: str, work: Path) -> Path:
    """Turns the reference netlist into something the deck can read.

    The top netlist comes out of xschem with two things KLayout's reader does not
    accept and that are not part of the circuit:

    * the top cell `.subckt` comes out COMMENTED (`**.subckt`), which is how
      xschem exports from the CLI;
    * there are 0 V sources (`Vmeas net11 GND 0`) used as current probes.
      `Not a known element type: 'V'`, dice el deck. Una fuente de 0 V es
      electrically a wire, so the right thing is not to drop it: it is to
      **merge the two nets**, which is what the layout has there. Done per
      scope, inside each `.subckt`, because net names repeat across blocks.
    """
    work.mkdir(parents=True, exist_ok=True)

    #  And FLATTENED. The top layout is a single cell (see
    #  `def_to_gds.py::flatten_all`), so the reference has to be one too: with
    #  the hierarchy in place, the deck matched not one of the 954
    #  nets ni uno de los 1707 device_lines — la comparacion no llegaba a
    #  start. It is the same flattening `build_block.py` does to each block.
    sys.path.insert(0, "/foss/designs/zotnetic_layout")
    from flatten_spice import flatten
    _, lvs_txt, _ = flatten(ref.read_text(), cell)
    src = lvs_txt.splitlines()

    #  First pass: aliases of the 0 V sources, per scope.
    alias: dict[int, dict[str, str]] = {}
    scope, scopes = 0, []
    for line in src:
        low = line.lower()
        if low.startswith(".subckt") or low.startswith("**.subckt"):
            scope += 1
            scopes.append(scope)
        elif low.startswith(".ends") or low.startswith("**.ends"):
            if scopes:
                scopes.pop()
        elif line[:1] in "vV" and not line.startswith("*"):
            tok = line.split()
            if len(tok) >= 4 and tok[3] in ("0", "0.0", "dc", "DC"):
                cur = scopes[-1] if scopes else 0
                alias.setdefault(cur, {})[tok[1]] = tok[2]

    out, scope, scopes = [], 0, []
    for line in src:
        low = line.lower()
        if low.startswith("**.subckt") or low.startswith("**.ends"):
            line = line[2:]
            low = line.lower()
        if low.startswith(".subckt"):
            scope += 1
            scopes.append(scope)
        elif low.startswith(".ends"):
            out.append(line)
            if scopes:
                scopes.pop()
            continue
        elif line[:1] in "vViI" and not line.startswith("*"):
            continue                       # sources: already in the aliases
        elif low.startswith((".save", ".control", ".endc", ".tran", ".op",
                            ".dc", ".ac", ".probe", ".meas", ".temp",
                            ".option", ".include", ".lib")):
            continue
        cur = scopes[-1] if scopes else 0
        for a, b in alias.get(cur, {}).items():
            line = re.sub(rf"(?<=[\s]){re.escape(a)}(?=[\s]|$)", b, line)
        out.append(line)

    dst = work / f"{cell}_klayout.spice"
    dst.write_text("\n".join(out) + "\n")
    return dst


#: Limits of the hand-driven comparer. `--hondo` raises them, to tell
#: un empate de simetria (doce rebanadas analogicas iguales) de una diferencia
#: de circuito de verdad.
LIMITES = (60, 200000) if "--hondo" in sys.argv else (30, 10000)

#: This PDK's MIM capacitance per area: `cap_mim_2f0fF` is 2.0 fF/um2. The deck
#: extracts 4e-13 F for a 20 x 10 um plate, which is exactly that.
_MIM_FF_UM2 = 2.0e-15


def _legible_por_spice(ref: Path, work: Path) -> Path:
    """The reference, with the MIM capacitance written in, for KLayout's reader.

    El lector SPICE normal de KLayout aborta con `Can't find a value for a R, C or
    L device` because the reference declares the MIM as `C... cap_mim_2f0fF W=.. L=..`
    with no value: the deck understands it because it uses its own delegate, but
    that delegate cannot be asked for from Python. It is given the value **the
    deck itself extracts** -- 2.0 fF/um2 times the area -- so nothing is invented.
    """
    out = []
    for line in ref.read_text().splitlines():
        m = re.match(r"^(C\S+\s+\S+\s+\S+\s+)(cap_mim_\S+)\s+W=(\S+)\s+L=(\S+)\s*$",
                     line)
        if m:
            c = _MIM_FF_UM2 * (float(m.group(3)) * 1e6) * (float(m.group(4)) * 1e6)
            line = f"{m.group(1)}{c:g} {m.group(2)}"
        out.append(line)
    dst = work / (ref.stem + "_con_valor.spice")
    dst.write_text("\n".join(out) + "\n")
    return dst


#: The three poly resistor sheets, which are drawn IDENTICALLY.
_RE_POLY = re.compile(r"\bppolyf_u_([123])k\b")


def ajustar_hoja(cir: Path, ref: Path, work: Path) -> Path:
    """Pone en la extraccion la hoja de poly que declara la referencia.

    1k, 2k and 3k **are not drawn differently**: same layer, what changes is a
    process option. `run_lvs.py` **hard-codes `poly_res=1k` in its variant
    table** -- in all four, A, B, C and D -- so the top's extraction came out
with 60 `ppolyf_u_1k` against the 12 `ppolyf_u_3k` of the reference:
    clases distintas, y de ahi 1801 nets sin pareja de 1828.

    El deck si admite el interruptor (`gf180mcu.lvs` hace `POLY_RES = $poly_res
    || '1k'`), and that is how `zotnetic_layout/run_lvs.sh` calls it on the
    blocks. **On the top it does not work**: called bare with `poly_res=3k` the
    deck's own comparison spins -- 6 hours without finishing, against the 12
    seconds it takes through `run_lvs.py` -- and it does not write the extracted
    netlist until the end, so a timeout leaves nothing. Here the verdict is not
    the deck's anyway but `comparar()`'s; all that is needed from the deck is
    la extraccion, y para eso el name de la hoja da igual.

    So the name is changed afterwards, which is where the difference lives.
    `comparar()` compares topology with parameters disabled, so the only thing
    separating the two netlists was the label.
    """
    sheets = set(_RE_POLY.findall(ref.read_text()))
    if len(sheets) != 1 or sheets == {"1"}:
        return cir
    model = f"ppolyf_u_{sheets.pop()}k"
    txt, n = re.subn(r"\bppolyf_u_1k\b", model, cir.read_text())
    if not n:
        return cir
    work.mkdir(parents=True, exist_ok=True)
    dst = work / (cir.stem + "_hoja.cir")
    dst.write_text(txt)
    print(f"                 poly sheet: {n} `ppolyf_u_1k` -> `{model}`")
    return dst


class _Cuenta(kdb.GenericNetlistCompareLogger):
    def __init__(self):
        super().__init__()
        self.nets = self.disp = self.pines = self.ok = 0
        self.clases: list[str] = []

    def net_mismatch(self, a, b, *extra):
        self.nets += 1

    def device_mismatch(self, a, b, *extra):
        #  Counted only. Touching `a.device_class()` here **blows up the process**
        #  (segmentation fault): the objects the comparer passes are only
        #  validos mientras dura la llamada y el binding no lo protege.
        self.disp += 1

    def pin_mismatch(self, a, b, *extra):
        self.pines += 1

    def match_nets(self, a, b, *extra):
        self.ok += 1


def comparar(cir: Path, ref: Path, work: Path,
             profundidad: int = 30, ramas: int = 10000) -> tuple[bool, str]:
    """Compares the deck extraction against the reference, with hand-set limits.

    **The PDK deck gives no usable verdict on this design**, and the proof is not
    an opinion: it fails comparing the layout against **its own extraction** --
    72 unmatched nets -- and there is nothing a layout can do wrong there.
    `compare` is called with the defaults (`max_depth` 8, `max_branch_complexity`
    500), which are not enough for a flat 1707-device circuit with twelve
    analogicas iguales; y el deck no los expone.

    Here the same KLayout comparer is used but driven by hand. With
    `max_depth=30` y `max_branch_complexity=10000` el emparejamiento **cierra
    entero**: 0 nets, 0 device_lines y 0 pines sin pareja.

    **What it checks and what it does not.** It checks TOPOLOGY: that every device
    and every net of the layout has its match in the schematic. **It does not
    check sizes** (W/L): the generic SPICE reader cannot match the parameters the
    deck writes (`L=20U W=0.7U AS=.. AD=.. PS=.. PD=..`) against those of the
    reference (`W=.. L=..` in metres) and with them enabled it matches not one
    device. Sizes are **netgen**'s job, which does compare them -- that is why
    the top is signed off with both and not one.
    """
    ref = _legible_por_spice(ref, work)

    def leer(p: Path) -> kdb.Netlist:
        nl = kdb.Netlist()
        nl.read(str(p), kdb.NetlistSpiceReader())
        for dc in nl.each_device_class():
            for pd in dc.parameter_definitions():
                dc.enable_parameter(pd.name, False)
        #  Merge the ones in PARALLEL, on both sides. The 280 decoupling
        #  transistors all hang off the same two nets, so they are interchangeable
        #  among themselves: a 146-way tie the comparer does not quite break and
        #  that left **6 unmatched devices** with 0 unmatched nets and 0 unmatched
        #  pins -- the signature of a tie, not of
        #  de una diferencia de circuito. Fundidos, el empate desaparece.
        #  netgen does the same (`property parallel enable` in the PDK setup).
        nl.combine_devices()
        return nl

    log = _Cuenta()
    cmp = kdb.NetlistComparer(log)
    cmp.max_depth = profundidad
    cmp.max_branch_complexity = ramas
    nl_cir, nl_ref = leer(cir), leer(ref)

    #  LOS PINES DEL TOP, COMO ANCLAS. Son iguales por construccion -- los dos
    #  lados heredan el nombre del mismo `info.yaml` --, asi que decirselo al
    #  comparador no es ayudarle a hacer trampa: es darle un dato que ya
    #  teniamos y el no puede deducir.
    #
    #  Sin ellas, el comparador se enreda entre las CUATRO CADENAS, que son
    #  cuatro rotaciones del mismo circuito y por tanto casi indistinguibles:
    #  emparejaba el `XM15` de la cadena de `S1P` con el de la de `S4P`. Medido
    #  en GRADIENT_NAV2: 857 nets emparejadas y 21 nets + 66 dispositivos
    #  sueltos sin anclas; con ellas, 905 emparejadas y 1 net + 2 dispositivos.
    #
    #  Subir `max_depth` y `max_branch_complexity` NO es la salida, aunque lo
    #  parezca: probado a 50/100000 y a 80/1000000, la busqueda se degrada y
    #  baja a 262 emparejadas.
    #  PERO SE PRUEBAN LAS DOS, y se queda la mejor. Las anclas ayudan cuando el
    #  circuito es simetrico y estorban cuando no: en `B26_A` -- el bloque mas
    #  los once clamps -- dejaban la comparacion en 11 nets emparejadas, que es
    #  exactamente el numero de anclas, mientras sin ellas avanza. Elegir a ciegas
    #  una de las dos era cambiar un fallo por otro, asi que se mide.
    def anclas(c):
        ca, cb = nl_cir.top_circuit(), nl_ref.top_circuit()
        if not (ca and cb):
            return 0
        na = {n.expanded_name().upper(): n for n in ca.each_net()}
        nb = {n.expanded_name().upper(): n for n in cb.each_net()}
        n = 0
        for nm in sorted(set(na) & set(nb)):
            if not nm.startswith("$"):
                c.same_nets(ca, cb, na[nm], nb[nm])
                n += 1
        return n

    puestas = anclas(cmp)
    ok = cmp.compare(nl_cir, nl_ref)
    if not ok:
        log2 = _Cuenta()
        cmp2 = kdb.NetlistComparer(log2)
        cmp2.max_depth = profundidad
        cmp2.max_branch_complexity = ramas
        ok2 = cmp2.compare(leer(cir), leer(ref))
        if ok2 or log2.ok > log.ok:
            log, ok, puestas = log2, ok2, 0
    detalle = (f"max_depth={profundidad} max_branch_complexity={ramas}, "
               f"{puestas} anclas: "
               f"{log.ok} nets emparejadas, sin pareja: {log.nets} nets, "
               f"{log.disp} dispositivos, {log.pines} pines")
    if log.clases:
        from collections import Counter
        detalle += "\n                 sin pareja: " + "  ".join(
            f"{k} x{v}" for k, v in Counter(log.clases).most_common())
    return ok, detalle


def comparar_aparte(cir: Path, ref: Path, work: Path) -> tuple[bool, str]:
    """`comparar()`, but in ANOTHER process.

    El comparador de KLayout **revienta el proceso** (segmentation fault) en dos
    cases seen: calling it twice in a row, and on the netlist extracted from the
    density-filled GDS. A crash of its own cannot be allowed to take down the
    whole run nor leave it without a verdict, so it is launched apart and if it
    se dice que se cayo.
    """
    r = subprocess.run([sys.executable, __file__, "--comparar", str(cir), str(ref),
                        str(work)] + (["--hondo"] if LIMITES[0] != 30 else []),
                       capture_output=True, text=True, timeout=7200, check=False)
    output = (r.stdout or "").strip()
    if r.returncode < 0 or not output:
        return False, (f"el comparador de KLayout se cayo (codigo {r.returncode}); "
                       f"no verdict by this route")
    ok, _, detalle = output.partition("|")
    return ok.strip() == "MATCH", detalle.strip()


def main() -> int:
    if "--comparar" in sys.argv:
        i = sys.argv.index("--comparar")
        cir, ref, work = (Path(x) for x in sys.argv[i + 1:i + 4])
        ok, detalle = comparar(cir, ref, work, *LIMITES)
        print(f"{'MATCH' if ok else 'NO'}|{detalle}")
        return 0

    bad = 0
    for name in ([a for a in sys.argv[1:] if not a.startswith("-")] or [TOP]):
        gds, ref = TARGETS[name]
        #  The target name is not the cell name: `GRADIENT_NAV2_DECAP` and
        #  `_FILLED` are the same `GRADIENT_NAV2` with more inside.
        cell = TOP if name.startswith(TOP) else name
        run = ROOT / "out" / f"lvs_klayout_{name}"
        subprocess.run(["rm", "-rf", str(run)], check=False)
        run.mkdir(parents=True, exist_ok=True)
        if cell == TOP:
            ref = prepare(ref, cell, ROOT / "work_lvs")
        r = subprocess.run(
            [sys.executable, RUNNER, f"--layout={gds.resolve()}",
             f"--netlist={ref}", "--variant=D", f"--topcell={cell}",
             f"--run_dir={run}", "--run_mode=deep", f"--thr={THR}",
             #  Without this the extracted netlist comes out as a bare `.SUBCKT
             #  GRADIENT_NAV`, without a single pin, and matching has nowhere to
             #  start: 1815 nets and 3414 devices, all unmatched.
             #  The deck only calls `make_top_level_pins` with this switch.
             "--top_lvl_pins",
             #  Descartan nets y objetos sueltos en LOS DOS lados: el layout
             #  drags in metal going to no device (PDN leftovers,
             #  plataformas de puerto) y la referencia trae nets de simulacion.
             "--purge", "--purge_nets", "--schematic_simplify",
             #  This design's substrate is called VSS. With the deck's default
             #  name (`gf180mcu_gnd`) the node comes out as `SUB`, without
             #  correspondencia en la referencia.
             "--lvs_sub=VSS"],
            capture_output=True, text=True, timeout=21600, check=False,
            env={**os.environ, "PATH": "/foss/tools/klayout:/usr/bin:/bin",
                 "HOME": "/tmp", "PDK_ROOT": "/foss/pdks"})
        log = run / "run.log"
        log.write_text(r.stdout + r.stderr)
        ok = "Congratulations! Netlists match." in (r.stdout + r.stderr)
        cir = run / f"{gds.stem}.cir"

        #  The deck's verdict is good for the blocks. Not for the top: it fails
        #  even comparing the layout against its own extraction, so there
        #  manda la comparacion conducida a mano (ver `comparar`).
        #  QUE NO ARRANQUE NO ES QUE NO CUADRE. Si el runner del PDK se muere
        #  antes de comparar -- un import que falta, un GDS ilegible -- no hay
        #  veredicto que dar, y decir "NO CUADRA" manda a buscar un fallo de
        #  circuito donde solo hay uno de herramienta. Medido: llamado con el
        #  python del venv sale `ModuleNotFoundError: No module named 'docopt'`,
        #  y esta funcion lo reportaba como desajuste del top.
        salida = r.stdout + r.stderr
        if not ok and ("Traceback (most recent call last)" in salida
                       or "ModuleNotFoundError" in salida):
            motivo = next((l for l in salida.splitlines()
                           if "Error" in l or "error" in l), "sin detalle")
            print(f"  {name:14s} EL DECK NO ARRANCO -- {motivo.strip()[:90]}")
            print(f"                 -> {log}")
            bad += 1
            continue
        if ok or not cir.exists():
            print(f"  {name:14s} {'match' if ok else 'NO CUADRA'}   -> {log}")
            bad += 0 if ok else 1
            continue
        cir = ajustar_hoja(cir, ref, ROOT / "work_lvs")
        #  ONE comparison per process, and in a SEPARATE process: see
        #  `comparar_aparte`.
        ok2, detalle = comparar_aparte(cir, ref, ROOT / "work_lvs")
        print(f"  {name:14s} deck: NO MATCH  |  hand comparer: "
              f"{'MATCH' if ok2 else 'NO CUADRA'}")
        print(f"                 {detalle}")
        print(f"                 -> {log}")
        if not ok2:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
