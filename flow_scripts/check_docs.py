#!/usr/bin/env python3
"""Comprueba que lo que dicen los documentos sigue siendo verdad.

    python3 scripts/check_docs.py

POR QUE EXISTE. Este arbol lleva unos 8.000 renglones de `.md` y de docstrings
que afirman cosas medibles: que el entregable se llama de tal manera, que tiene
tal sha, que el LVS casa sobre tantos dispositivos, que el bloque mide tanto.
Nada de eso se revalida solo. Un fichero se renombra, se rehace una tanda, y el
documento sigue ahi diciendo lo de la semana pasada con la misma seguridad que
el primer dia -- que es exactamente igual de peligroso que un LVS corrido contra
un netlist viejo, y mas dificil de ver, porque un documento no falla.

QUE COMPRUEBA. Solo lo que se puede contrastar contra un fichero de verdad:

  * el entregable que nombran `lvs_config.json` e `info.yaml` EXISTE, y los dos
    nombran el mismo;
  * su sha256 es el que dice el archivo de `integration/gds/`;
  * los ficheros y directorios que citan los documentos existen;
  * los recuentos del LVS que citan los documentos son los de los `.rpt`;
  * el tamano del bloque que citan es el de su DEF;
  * ningun documento nombra un entregable que ya no es el entregable.

QUE NO COMPRUEBA. La prosa. Que una explicacion sea buena, o que un razonamiento
siga en pie, no lo dice ningun script: eso se lee. Esto solo caza la clase de
error que se cuela sin que nadie mienta -- el numero que era verdad y dejo de
serlo.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # .../openroad
PROY = ROOT.parent                                 # .../a_zonetic2026

#: Los documentos que se auditan. Los de `copia*` no: son fotos de un momento y
#: se supone que estan viejos.
DOCS = [p for p in PROY.rglob("*.md")
        if "copia" not in str(p) and "__pycache__" not in str(p)]

fallos: list[str] = []
avisos: list[str] = []


def mal(m: str) -> None:
    fallos.append(m)


def ojo(m: str) -> None:
    avisos.append(m)


def entregable() -> str | None:
    """El GDS que se entrega, segun los DOS ficheros de interfaz, que tienen
    que coincidir. Si no coinciden no hay una respuesta, hay un problema."""
    cfg = PROY / "lvs_config.json"
    inf = PROY / "info.yaml"
    n_cfg = n_inf = None
    if cfg.exists():
        d = json.loads(cfg.read_text())
        m = re.search(r"([A-Za-z0-9_]+\.gds)", d.get("LAYOUT_FILE", ""))
        n_cfg = m.group(1) if m else None
    if inf.exists():
        m = re.search(r"^#\s*GDS:\s+\S*?([A-Za-z0-9_]+\.gds)", inf.read_text(), re.M)
        n_inf = m.group(1) if m else None
    if n_cfg is None:
        mal("lvs_config.json no nombra ningun LAYOUT_FILE")
    if n_inf is None:
        ojo("info.yaml no nombra el GDS en su cabecera")
    elif n_cfg and n_cfg != n_inf:
        mal(f"lvs_config.json dice {n_cfg} e info.yaml dice {n_inf}: "
            f"dos fuentes de verdad que ya no coinciden")
    return n_cfg


def sha_del_archivo(nombre: str) -> str | None:
    """El sha256 que apunto `archivar_integracion.py` para ese fichero."""
    arch = PROY / "integration" / "gds"
    if not arch.is_dir():
        return None
    for d in sorted(arch.iterdir(), reverse=True):
        notas = d / "NOTAS.txt"
        if not notas.is_file():
            continue
        t = notas.read_text()
        if nombre in t.splitlines()[0]:
            m = re.search(r"sha256\s+([0-9a-f]{64})", t)
            return m.group(1) if m else None
    return None


def recuentos_lvs(rpt: Path) -> tuple[int, int] | None:
    """(dispositivos, nets) del ultimo bloque de un informe de netgen."""
    if not rpt.is_file():
        return None
    t = rpt.read_text()
    d = re.findall(r"Number of devices:\s+(\d+)\s+\|Number of devices:\s+(\d+)", t)
    n = re.findall(r"Number of nets:\s+(\d+)\s+\|Number of nets:\s+(\d+)", t)
    if not d or not n:
        return None
    if d[-1][0] != d[-1][1] or n[-1][0] != n[-1][1]:
        mal(f"{rpt.name}: los recuentos no cuadran, {d[-1]} y {n[-1]}")
    return int(d[-1][0]), int(n[-1][0])


def main() -> int:
    print("  documentos auditados:", len(DOCS))

    #  --- 1. el entregable ---------------------------------------------------
    ent = entregable()
    if ent:
        gds = ROOT / "out_integration" / ent
        print(f"  entregable: {ent}")
        if not gds.is_file():
            mal(f"el entregable {ent} no existe en out_integration/")
        else:
            if gds.open("rb").read(4) != b"\x00\x06\x00\x02":
                mal(f"{ent} no empieza por una cabecera GDSII")
            sha = hashlib.sha256(gds.read_bytes()).hexdigest()
            esperado = sha_del_archivo(ent)
            if esperado is None:
                ojo(f"{ent} no esta archivado en integration/gds/ -- "
                    f"corre archivar_integracion.py")
            elif esperado != sha:
                mal(f"{ent} tiene sha {sha[:8]}… y el archivo dice "
                    f"{esperado[:8]}…: uno de los dos es de otra tanda")
            else:
                print(f"  sha256 coincide con el archivo: {sha[:8]}…")

        #  Ningun documento debe nombrar un entregable ANTERIOR como si fuera
        #  el de ahora. Los `_filledN` anteriores se citan como historia, y eso
        #  se distingue por que la frase los presenta como pasados.
        viejos = {p.name for p in (ROOT / "out_integration").glob("B26_A_filled*.gds")
                  if p.name != ent}
        for doc in DOCS:
            t = doc.read_text(errors="replace")
            for v in viejos:
                #  CON FRONTERA. `B26_A_filled` es prefijo de
                #  `B26_A_filled4`, asi que un `in` suelto marcaba como
                #  obsoleta cada linea que nombra el entregable de ahora. La
                #  primera version de este script lo hacia, y saco cuatro
                #  fallos que no existian: un comprobador que se equivoca es
                #  peor que no tenerlo.
                raiz = re.escape(v.replace(".gds", ""))
                for ln in t.splitlines():
                    if not re.search(raiz + r"(?![0-9])", ln):
                        continue
                    if re.search(r"THE DELIVERABLE|el entregable es|LAYOUT_FILE|"
                                 r"el fichero que se entrega|the file that ships",
                                 ln, re.I):
                        mal(f"{doc.relative_to(PROY)}: presenta {v} como el "
                            f"entregable, y el entregable es {ent}")

    #  --- 2. los recuentos del LVS -------------------------------------------
    citados = {}
    for doc in DOCS:
        for m in re.finditer(r"(\d{3,5})\s*=\s*\1\b", doc.read_text(errors="replace")):
            citados.setdefault(int(m.group(1)), set()).add(doc.relative_to(PROY))
    reales = set()
    for rpt, etiq in ((ROOT / "out_integration/lvs_netgen_B26_A.rpt", "B26_A"),
                      (ROOT / "out_v2_GRADIENT_NAV2_V3/lvs_netgen_GRADIENT_NAV2_V3.rpt",
                       "GRADIENT_NAV2_V3")):
        r = recuentos_lvs(rpt)
        if r:
            print(f"  LVS {etiq}: {r[0]} dispositivos, {r[1]} nets")
            reales |= set(r)
    #  El bloque tiene DOS recuentos validos -- con y sin desacoplo-- y el
    #  informe solo guarda el ultimo, asi que el otro se acepta si esta a dos
    #  dispositivos, que son los dos que anaden los desacoplos al colapsarse.
    reales |= {n - 2 for n in reales} | {n + 2 for n in reales}
    for n, docs in sorted(citados.items()):
        if n not in reales:
            ojo(f"los documentos citan «{n} = {n}» y ningun informe da esa "
                f"cifra: {', '.join(str(d) for d in sorted(docs))}")

    #  --- 3. el tamano del bloque --------------------------------------------
    dep = ROOT / "out_v2_GRADIENT_NAV2_V3/GRADIENT_NAV2_V3_routed.def"
    if dep.is_file():
        m = re.search(r"UNITS DISTANCE MICRONS (\d+)", dep.read_text())
        u = int(m.group(1))
        da = re.search(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
                       r"\(\s*(-?\d+)\s+(-?\d+)\s*\)", dep.read_text())
        w = (int(da.group(3)) - int(da.group(1))) / u
        h = (int(da.group(4)) - int(da.group(2))) / u
        print(f"  bloque: {w:.2f} x {h:.2f} um")
        for doc in DOCS:
            for mm in re.finditer(r"(\d{3}\.\d{2})\s*[x×]\s*(\d{3}\.\d{2})",
                                  doc.read_text(errors="replace")):
                a, b = float(mm.group(1)), float(mm.group(2))
                if abs(a - w) > 0.01 and abs(a - 1110) > 0.01 and a > 300:
                    ojo(f"{doc.relative_to(PROY)}: cita {a} x {b} um y el "
                        f"bloque mide {w:.2f} x {h:.2f}")
                    break

    #  --- 4. los ficheros que citan existen ----------------------------------
    #  Solo rutas dentro del arbol y con extension conocida, para no perseguir
    #  cada palabra con un punto.
    patron = re.compile(r"`((?:openroad/|scripts/|XSCHEM[^`]*?/|layouts_v2/|docs/|"
                        r"reportes/|integration/)[A-Za-z0-9_./-]+"
                        r"\.(?:py|tcl|sh|md|json|yaml|def|gds|lef|spice|sch|sym|txt))`")
    #  `README_GDS_GENERATOR.md` describe el OTRO repositorio, no este arbol:
    #  alli la documentacion vive en `docs/` -- `subir.sh` la copia ahi-- y en
    #  el arbol de trabajo `HANDOFF.md` esta en la raiz. Sus rutas son
    #  relativas a aquel, asi que se cotejan contra el clon de las
    #  herramientas si existe, y si no se dejan pasar. Marcarlas como rotas
    #  seria pedirle a ese fichero que mintiera sobre su propio repositorio.
    GEN = Path.home() / "Documents/DOCKER2026/repos/gen"
    faltan: dict[str, set] = {}
    for doc in DOCS:
        otro = doc.name == "README_GDS_GENERATOR.md"
        bases = (GEN,) if otro and GEN.is_dir() else (PROY, ROOT, PROY.parent)
        if otro and not GEN.is_dir():
            continue
        for m in patron.finditer(doc.read_text(errors="replace")):
            r = m.group(1)
            for base in bases:
                if (base / r).exists():
                    break
            else:
                faltan.setdefault(r, set()).add(doc.relative_to(PROY))
    for r, docs in sorted(faltan.items()):
        ojo(f"citado y no existe: {r}  ({', '.join(str(d) for d in sorted(docs))})")

    #  --- 5. documentos duplicados -------------------------------------------
    #  Dos ficheros con el mismo contenido no son dos fuentes: son una que se
    #  va a separar de la otra el dia que alguien edite una sola.
    por_hash: dict[str, list] = {}
    for doc in DOCS:
        por_hash.setdefault(hashlib.md5(doc.read_bytes()).hexdigest(),
                            []).append(doc.relative_to(PROY))
    for h, ds in por_hash.items():
        if len(ds) > 1:
            ojo("mismo contenido en " + " y ".join(str(d) for d in ds))

    print()
    for a in avisos:
        print(f"  AVISO  {a}")
    for f in fallos:
        print(f"  FALLA  {f}")
    if not fallos and not avisos:
        print("  todo lo comprobable cuadra")
    elif not fallos:
        print(f"\n  {len(avisos)} aviso(s), ningun fallo")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
