"""Genera el layout de un bloque a partir de su netlist de Xschem.

**La fuente de verdad es siempre el .spice de `spice_blocks/`.** Ahi las netlists
son **enlaces simbolicos** al directorio de simulacion de Xschem
(`XSCHEM/<bloque>/simulation/<nombre>.sch/<nombre>.spice`), asi que basta con
exportar desde el esquematico: no hay que copiar nada y no puede quedarse una
copia vieja. Todo lo que aparece en la carpeta de salida es derivado y se
reescribe en cada corrida; no se reutiliza nada de una anterior. El esquematico cambia a menudo, y trabajar sobre
un derivado viejo daria un layout que ya no corresponde al circuito — y encima
un DRC y un LVS que pasan, porque serian coherentes entre si pero con la netlist
equivocada. Las netlists derivadas llevan en la cabecera la fecha y el sha1 de la
fuente de la que salieron, para poder comprobarlo de un vistazo.

Corolario: para regenerar, **usar siempre este guion**. `test_flow.py` acepta una
netlist ya aplanada y sirve para depurar, pero salta el paso de aplanado y por
tanto no ve los cambios del esquematico.

Encadena los dos pasos del flujo (aplanar -> colocar/rutear/exportar) y deja
todo lo generado en una carpeta con el nombre del bloque:

    /foss/designs/a_zonetic2026/spice_blocks/WEIGHT_COMP.spice   (entrada)
    /foss/designs/a_zonetic2026/layouts/WEIGHT_COMP/             (salida)
        WEIGHT_COMP_flat.spice          netlist plana (nf) que consume el layout
        WEIGHT_COMP_lvs.spice           netlist para LVS (dedos en paralelo)
        WEIGHT_COMP_flat_gf180.gds      el layout
        WEIGHT_COMP_flat_gf180.png      render para inspeccion rapida
        WEIGHT_COMP_flat_gf180_report.txt
        mag/WEIGHT_COMP.mag             el mismo layout, para abrirlo en magic
        mag/*.mag                       sus subceldas (magic las necesita al lado)
        mag/WEIGHT_COMP_extracted.spice netlist extraida del layout, SIN parasitos
        mag/WEIGHT_COMP_pex_c.spice     la misma CON capacidades (C)
        mag/WEIGHT_COMP_pex_rc.spice    la misma CON capacidades y resistencias (RC)

Las netlists derivadas van en la carpeta de salida a proposito: 'spice_blocks/'
es entrada del usuario y no debe ensuciarse con artefactos generados.

Uso:
    python build_block.py [nombre_o_ruta] [pdk]
    python build_block.py WEIGHT_COMP

OJO: hay que lanzarlo con 'env -u PYTHONPATH' o se ignora el venv y se importa
gdsfactory 9.44 en vez de la 9.2.2 clavada (ver DRC_KLAYOUT.md §10):

    env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python build_block.py WEIGHT_COMP
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

BLOCKS_DIR = Path("/foss/designs/a_zonetic2026/spice_blocks")
LAYOUTS_DIR = Path("/foss/designs/a_zonetic2026/layouts")
#  La v2 escribe en su propia carpeta para poder tener las DOS a la vez y
#  compararlas en los bancos. El nombre de la celda NO cambia: asi el LVS de
#  la v2 se compara contra la MISMA netlist de referencia que la v1, que es
#  justo lo que demuestra que las dos implementan el mismo circuito.
LAYOUTS_DIR_V2 = Path("/foss/designs/a_zonetic2026/layouts_v2")
MAGIC = "/foss/tools/bin/magic"
MAGICRC = "/foss/pdks/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc"


def write_mag(gds: Path, top: str, out: Path,
              modelo_res: str | None = None) -> Path | None:
    """Convierte el GDS a .mag para poder abrir el layout en magic.

    Se usa 'writeall force', que guarda la celda top **y todas sus subceldas**:
    guardando solo la top el .mag queda con ~180 'use' apuntando a celdas que no
    existen en disco y magic no puede abrirlo. El 'flatten' de magic sobre esta
    jerarquia no termina (probado: >10 min), asi que todo va a una subcarpeta
    'mag/' para no llenar la carpeta de salida.

    **El GDS se aplana ANTES de dárselo a magic, con KLayout.** No es una
    optimizacion: sin eso magic NO EXTRAE la resistencia de poly. Su tech la
    deriva como una AND de cuatro capas --`layer hires POLY and SBLK and HRES and
    RESDEF`-- y esa AND la evalua **celda a celda** al leer el GDS. gdsfactory
    escribe cada rectangulo en su propia celda, asi que el poly, el bloqueo de
    silicida, la capa `resistor` y el `res_mk` acaban en cuatro celdas distintas
    y la interseccion sale vacia. El `flatten` que ya hacia el script llega tarde:
    para entonces la conversion GDS -> tipos de magic ya ha ocurrido.

    Medido en `OPAM_LIN_flat`: cero `ppolyf` en el `.mag`, en el extraido y en
    los dos de parasitos, mientras KLayout extraia los cinco tramos. Aplanando
    antes con KLayout (0.1 s) salen los **cinco**, encadenados hasta `OUT`.

    magic escribe en su directorio de trabajo, de ahi el cwd. Si algo falla no se
    corta la generacion: el .mag es una comodidad, el entregable es el GDS.
    """
    magdir = out / "mag"
    magdir.mkdir(parents=True, exist_ok=True)
    extdir = magdir / ".ext"
    extdir.mkdir(exist_ok=True)
    #  Aplanado previo (ver el docstring). KLayout tarda decimas; el de magic
    #  sobre esta jerarquia no termina.
    #
    #  **Solo si hay resistencias.** El aplanado es lo que permite que magic vea
    #  las cuatro capas juntas, pero le quita la comparticion de celdas y su
    #  extraccion se dispara: medido, `WEIGHT_COMP` pasa de segundos a **mas de
    #  10 minutos**, mientras que `OPAM_LIN_flat` --que es mas grande-- se queda
    #  en 11 s. No compensa pagarlo en los bloques que no tienen ninguna
    #  resistencia que rescatar, que son cuatro de los cinco.
    plano = magdir / f".{top}_plano.gds"
    if not modelo_res:
        plano = None
    try:
        if plano is None:
            raise RuntimeError("sin resistencias: no hace falta aplanar")
        import klayout.db as _kdb
        _ly = _kdb.Layout()
        _ly.read(str(gds))
        _ci = _ly.cell_by_name(top)
        _ly.flatten(_ci, -1, True)
        for _c in list(_ly.each_cell()):
            if _c.cell_index() != _ci and _c.parent_cells() == 0:
                _ly.delete_cell_rec(_c.cell_index())
        _ly.write(str(plano))
        gds = plano
    except RuntimeError:
        pass                                      # camino normal sin resistencias
    except Exception as exc:                      # noqa: BLE001
        print(f"   AVISO: no se pudo aplanar el GDS para magic ({exc}); "
              f"la resistencia de poly NO saldra en las netlists extraidas")

    script = magdir / ".gds2mag.tcl"
    # Una sola pasada de magic: primero guarda la jerarquia en .mag y luego
    # aplana una copia para extraer las netlists. El aplanado va DESPUES del
    # writeall para no alterar lo que se guarda.
    # 'ext2spice lvs' es el preset sin parasitos; 'cthresh 0.01' anade las
    # capacidades. Se extrae una sola vez y se escribe dos veces.
    script.write_text(
        f"gds read {gds}\n"
        f"load {top}\n"
        "select top cell\n"
        "writeall force\n"
        f"flatten {top}_f\n"
        f"load {top}_f\n"
        f"cellname delete {top}\n"
        f"cellname rename {top}_f {top}\n"
        "select top cell\n"
        f"extract path {extdir}\n"
        "ext2spice lvs\n"
        "extract all\n"
        f"ext2spice -p {extdir} -o {magdir / f'{top}_extracted.spice'}\n"
        "ext2spice cthresh 0.01\n"
        f"ext2spice -p {extdir} -o {magdir / f'{top}_pex_c.spice'}\n"
        # RC: hay que volver a extraer pidiendo resistencia y pasar por
        # ext2sim + extresist, que es lo que reparte los nodos de cada red por
        # tramos. No se puede sacar del mismo .ext que las capacidades.
        "extract do resistance\n"
        "extract all\n"
        "ext2sim labels on\n"
        f"ext2sim -p {extdir}\n"
        "extresist tolerance 10\n"
        "extresist all\n"
        "ext2spice extresist on\n"
        "ext2spice cthresh 0.01\n"
        f"ext2spice -p {extdir} -o {magdir / f'{top}_pex_rc.spice'}\n"
        "quit -noprompt\n",
        encoding="utf-8")
    try:
        r = subprocess.run(
            [MAGIC, "-dnull", "-noconsole", "-rcfile", MAGICRC, script.name],
            cwd=magdir, capture_output=True, text=True, timeout=600,
            env={"PATH": "/usr/bin:/bin", "PDK_ROOT": "/foss/pdks", "HOME": "/tmp"})
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"   AVISO: no se pudo generar el .mag ({exc})")
        return None
    finally:
        script.unlink(missing_ok=True)
        if plano is not None:
            plano.unlink(missing_ok=True)
        shutil.rmtree(extdir, ignore_errors=True)   # .ext: solo intermedios
    mag = magdir / f"{top}.mag"
    if not mag.exists():
        print(f"   AVISO: magic no escribio el .mag\n{r.stderr[-400:]}")
        return None
    for name in (f"{top}_extracted.spice", f"{top}_pex_c.spice", f"{top}_pex_rc.spice"):
        _tie_bulk(magdir / name)
        _hoja_resistencia(magdir / name, modelo_res)
    return mag


def _hoja_resistencia(path: Path, modelo: str | None) -> None:
    """Pone en el extraido el modelo de resistencia que pide el esquematico.

    magic reconoce la resistencia de alta hoja por su GEOMETRIA, que es la misma
    para 1k, 2k y 3k -- lo que las separa es una opcion de proceso, no el dibujo
    (§11.0.2) -- y su tech solo declara `ppolyf_u_1k` y `ppolyf_u_1k_6p0`. Asi
    que la extrae SIEMPRE como 1k, y simular eso da **382 kohm donde el circuito
    pide 1.15 Mohm**: la ganancia se iria a un tercio sin que nada avise.

    Es el mismo hueco que ya hubo que tapar en las otras dos herramientas: a
    KLayout se le pasa `-rd poly_res=3k` y a netgen un setup local que declara el
    dispositivo. Aqui se sustituye el nombre del modelo en el netlist extraido,
    que es donde se puede.
    """
    if not modelo or not path.exists():
        return
    txt = path.read_text(encoding="utf-8", errors="ignore")
    import re
    nuevo, n = re.subn(r"\bppolyf_u_1k\b", modelo, txt)
    if n:
        path.write_text(nuevo, encoding="utf-8")


_PFET_HINT, _NFET_HINT = "pfet", "nfet"


def _tie_bulk(path: Path) -> None:
    """Ata los nodos de bulk a VDD/VSS en el netlist extraido.

    magic no reconoce los taps de este layout y deja los pozos sueltos: el bulk
    de los PFET sale como 'w_...' (el nodo de nwell) y el de los NFET como
    'VSUBS' o 'w_...'. En la extraccion RC es peor, porque `extresist` parte cada
    pozo en decenas de sub-nodos ('w_x.t0', '.t1', ...). Todos ellos quedarian
    FLOTANDO al simular.

    La conexion **si existe en el layout** — el LVS de KLayout la ve y da
    `Circuits match uniquely` —, es magic quien no la extrae, asi que sustituir
    esos nodos por VDD/VSS reconstruye lo que el layout ya tiene. A que riel va
    cada uno se deduce del transistor: bulk de PFET -> pozo n -> VDD; bulk de
    NFET -> sustrato -> VSS.

    OJO: esto da por hecho que los taps estan bien. Si un layout futuro se
    quedara sin ellos, aqui no se notaria — **quien lo detecta es el LVS**, que
    hay que correr siempre.
    """
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()

    ports = []
    for ln in lines:
        if ln.lower().startswith(".subckt"):
            ports = ln.split()[2:]
            break
    vdd = next((p for p in ports if p.lower() in ("vdd", "vpwr", "vcc")), "VDD")
    vss = next((p for p in ports if p.lower() in ("vss", "vgnd", "gnd")), "VSS")

    # bulk = 4o nodo de cada linea de transistor
    tie: dict[str, str] = {"VSUBS": vss}
    for ln in lines:
        if not ln.startswith("X"):
            continue
        tok = ln.split()
        if len(tok) < 6:
            continue
        low = ln.lower()
        if _PFET_HINT in low:
            tie[tok[4]] = vdd
        elif _NFET_HINT in low:
            tie[tok[4]] = vss
    # `extresist` parte cada pozo en sub-nodos ('w_x.t0', 'w_x.n0', ...) que no
    # quedan unidos entre si: comprobado, ninguno alcanza el riel por resistencia.
    # Se ata la familia entera, o los que no son terminal de ningun transistor se
    # quedarian colgando con su resistencia de pozo al aire.
    fam = {k.split(".")[0]: v for k, v in tie.items() if k.startswith("w_")}
    for ln in lines:
        for tok in ln.split():
            base = tok.split(".")[0]
            if base in fam:
                tie[tok] = fam[base]

    tie = {k: v for k, v in tie.items() if k not in (vdd, vss)}
    if not tie:
        return

    out = []
    for ln in lines:
        if ln.startswith(("X", "C", "R", "c", "r")):
            tok = ln.split()
            ln = " ".join(tie.get(t, t) for t in tok)
        out.append(ln)

    n_nw = sum(1 for v in tie.values() if v == vdd)
    n_sub = len(tie) - n_nw
    head = (f"* Nodos de bulk atados: {n_nw} de pozo n -> {vdd}, "
            f"{n_sub} de sustrato -> {vss}.\n"
            "*   magic no extrae los taps de este layout y los dejaba flotando;\n"
            "*   la conexion si existe (el LVS de KLayout da 'match uniquely').\n"
            "*   Quien detecta un tap que falte de verdad es el LVS, no esto.\n")
    path.write_text(head + "\n".join(out) + "\n", encoding="utf-8")


def _mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def resolve_source(arg: str) -> Path:
    """Acepta el nombre del bloque ('WEIGHT_COMP') o una ruta al .spice."""
    p = Path(arg)
    if p.suffix == ".spice" and p.exists():
        return p
    cand = BLOCKS_DIR / f"{p.stem}.spice"
    if not cand.exists():
        raise SystemExit(f"no encuentro la netlist: {cand}")
    return cand


def build(src: Path, pdk: str = "gf180", v2: bool = False) -> dict:
    from coil_layout.flow import run_flow
    from coil_layout.placement import Opciones
    from flatten_spice import flatten

    name = src.stem
    out = (LAYOUTS_DIR_V2 if v2 else LAYOUTS_DIR) / name
    out.mkdir(parents=True, exist_ok=True)

    # La fuente de verdad es SIEMPRE el .spice de spice_blocks/. Todo lo que hay
    # en la carpeta de salida es derivado y se reescribe en cada corrida: no se
    # reutiliza nada de una anterior, porque el esquematico puede haber cambiado
    # y un derivado viejo daria un layout que ya no corresponde. Por eso se
    # anota de que fuente sale cada archivo.
    # Se resuelve el enlace: en spice_blocks/ las netlists suelen ser symlinks al
    # directorio de simulacion de Xschem, para que exportar desde el esquematico
    # baste y no haya que copiar nada. Interesa registrar el archivo REAL.
    real = src.resolve()
    raw = real.read_text()
    stamp = (f"* fuente: {real}\n"
             + (f"* leida via enlace: {src}\n" if real != src.absolute() else "")
             + f"* fecha de la fuente: {_mtime(real)}   sha1: {_sha1(raw)}\n"
             + "* generado por flatten_spice.py — NO editar a mano\n")
    flat_txt, lvs_txt, stats = flatten(raw)
    flat = out / f"{name}_flat.spice"
    lvs = out / f"{name}_lvs.spice"
    flat.write_text(stamp + flat_txt, encoding="utf-8")
    lvs.write_text(stamp + lvs_txt, encoding="utf-8")

    print(f">> {name}")
    print(f"   entrada:   {real}  ({_mtime(real)}, sha1 {_sha1(raw)})")
    if real != src.absolute():
        print(f"   (via enlace {src})")
    print(f"   top:       {stats['top']}  puertos: {' '.join(stats['ports'])}")
    print(f"   MOSFETs:   {stats['n_mos']}")
    if stats["merged"]:
        print("   nets fusionadas (V=0): "
              + ", ".join(f"{k}->{v}" for k, v in stats["merged"].items()))
    for f in stats["fingered"]:
        print(f"   FINGERS: {f}")
    for w in stats["warnings"]:
        print(f"   AVISO: {w}")

    res = run_flow(str(flat), pdk, str(out), opts=Opciones(v2=v2))
    lay = res["lay"]
    if lay.unlinked:
        # una net sin enlace entre canales queda partida en dos y el LVS lo canta
        print(f"   ERROR: sin enlace entre canales: {', '.join(lay.unlinked)}")
    if lay.power_taps:
        # Sin bajadas, el riel se queda en metal1 y quien coloque el bloque como
        # macro no tiene por donde engancharse: pdngen aborta con PDN-0232/0233.
        taps = ", ".join(f"y={y:g}: {n}" for y, n in sorted(lay.power_taps.items()))
        print(f"   power:     metal3 sobre los rieles ({taps} bajadas)")
        if any(n == 0 for n in lay.power_taps.values()):
            print("   ERROR: un riel se quedo sin ninguna bajada a metal3")
    if lay.signal_access:
        print(f"   senales:   metal3 sobre {len(lay.signal_access)} puertos de senal")
    for net in lay.signal_access_failed:
        # Sin plataforma, el router del top no puede bajarle una via a ese pin
        # sin tocar el metal del vecino: son los `Cut Short` del ruteo detallado.
        print(f"   ERROR: sin acceso en metal3 -> {net}")
    for c in lay.caps_placed:
        print(f"   cap:       {c}")
    for c in lay.caps_failed:
        # un condensador que falta NO lo ve ni el DRC ni el LVS: la netlist de
        # referencia sale del mismo aplanado, asi que los dos saldrian limpios
        print(f"   ERROR: condensador sin colocar: {c}")
    # Las resistencias, igual que los condensadores. Esto FALTABA: `res_placed` y
    # `res_failed` se rellenaban y no los leia nadie, asi que una resistencia que
    # no se colocaba desaparecia sin una sola linea de aviso -- y el DRC salia
    # limpio, porque lo que no se dibuja no viola ninguna regla. Paso de verdad:
    # se dio por bueno un OPAM_LIN_flat sin su resistencia de realimentacion.
    for nombre, n, largo, ancho in lay.res_placed:
        print(f"   res:       {nombre} {n} tramos de {largo:.3f} x {ancho:.2f} um")
    for r in lay.res_failed:
        print(f"   ERROR: resistencia sin colocar: {r[0]}: {r[1]}")
    pedidas = getattr(res["nl"], "resistors", None) or []
    if pedidas and not lay.res_placed and not lay.res_failed:
        print(f"   ERROR: la netlist trae {len(pedidas)} resistencia(s) y el layout no ha "
              f"colocado ni ha rechazado ninguna: place_resistors no llego a correr")
    for t in lay.tight:
        # La separacion que pide el router es conservadora (el caso 'mismo trunk'
        # pide 0.66 um aunque los dos stubs sean de la MISMA net, donde el metal
        # simplemente se fusiona), asi que esto no implica violacion: avisa de
        # donde mirar si el DRC saca una M1.2a o una V1.1. WEIGHT_COMP lo dispara
        # y sale limpio. Quien decide es el DRC.
        print(f"   AVISO: stubs justos, revisar M1.2a/V1.1 ahi -> {t}")
    print(f"   tamano:    {lay.component.dxsize:.2f} x {lay.component.dysize:.2f} um")
    print(f"   abutidas:  {sorted(lay.abutted_nets)}")
    print(f"   salida:    {out}")

    top = res["nl"].name
    gds = res["gds"]
    #  Modelo de resistencia que pide el esquematico, para corregirlo en el
    #  extraido de magic (ver `_hoja_resistencia`).
    _mod = None
    for _r in (getattr(res["nl"], "resistors", None) or []):
        _m = (_r.model or "").lower()
        if "ppolyf_u_" in _m:
            _mod = _m
            break
    mag = write_mag(Path(gds), top, out, modelo_res=_mod)
    if mag:
        print(f"   magic:     {mag}")
        res["mag"] = str(mag)
        for tag, name in (("sin parasitos ", f"{top}_extracted.spice"),
                          ("parasitos C  ", f"{top}_pex_c.spice"),
                          ("parasitos RC ", f"{top}_pex_rc.spice")):
            p = mag.parent / name
            if p.exists():
                print(f"   spice {tag}: {p}")
                res[name] = str(p)
    print("\n   Siguiente paso (DRC):")
    print(f"     python3 /foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py \\")
    print(f"       --path={gds} --variant=D --topcell={top} \\")
    print(f"       --run_dir={out}/drc --mp=4")
    res["flat"], res["lvs"], res["out_dir"] = str(flat), str(lvs), str(out)
    return res


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--v2"]
    v2 = "--v2" in sys.argv[1:]
    arg = args[0] if args else "WEIGHT_COMP"
    pdk = args[1] if len(args) > 1 else "gf180"
    build(resolve_source(arg), pdk, v2=v2)


if __name__ == "__main__":
    main()
