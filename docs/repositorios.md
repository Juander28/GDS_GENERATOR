# Los dos repositorios, y qué va en cada uno

Anotado el 2026-09-08. Son **dos**, con dueños distintos y con reglas distintas,
y confundirlos es fácil porque el árbol de trabajo no es un repositorio de
ninguno de los dos.

| | Diseño | Herramientas y documentación |
|---|---|---|
| **URL** | `git@github.com:AnBuiUCI/sscs-2026-zotnetic.git` | `git@github.com:Juander28/GDS_GENERATOR.git` |
| **HTTPS** | `https://github.com/AnBuiUCI/sscs-2026-zotnetic.git` | `https://github.com/Juander28/GDS_GENERATOR.git` |
| **Dueño** | An Bui — se escribe como colaborador | `Juander28`, la clave de esta máquina |
| **Qué lleva** | todo `a_zonetic2026/`, dentro de `FINAL/` | `zotnetic_layout/`, `flow_scripts/`, `docs/` |
| **Qué NO lleva** | nada fuera de `FINAL/` | ningún artefacto generado: ni GDS, ni `.lyrdb`, ni extracciones |
| **Ramas** | `main`, `add-pads`, `glayout` | `main` |

La clave SSH de esta máquina autentica como `Juander28` (comprobado 2026-09-08:
`ssh -T git@github.com` responde `Hi Juander28!`). En el repo de diseño eso da
escritura **sólo mientras se sea colaborador**; el repositorio no es suyo. No
existe una copia de este proyecto bajo `Juander28` — comprobado el 2026-08-29.

## El árbol de trabajo NO es un repositorio, y así se queda

`/foss/designs/a_zonetic2026` (en el host,
`~/Documents/DOCKER2026/designs/a_zonetic2026`) no tiene `.git` y **no se le
hace `git init` nunca**. Git no sabe empujar un repositorio local dentro de un
subdirectorio de un remoto, así que el `init` no serviría de nada y además
dejaría un `.git` suelto en medio del diseño. Se clona en un scratchpad y se
copia dentro.

## Subir el diseño

```bash
cd <scratchpad>
git clone git@github.com:AnBuiUCI/sscs-2026-zotnetic.git repo
git -C repo config user.name  "Juander28"
git -C repo config user.email "jdsanch4@uci.edu"

#  /bin/cp a propósito: `cp` está aliasado a `cp -i` y en un bucle se queda
#  esperando una respuesta que nadie teclea.
/bin/cp -a /foss/designs/a_zonetic2026/. repo/FINAL/

git -C repo add -A
git -C repo diff --cached --name-only --diff-filter=D    # TIENE que salir vacío
git -C repo diff --cached --name-only | grep -v '^FINAL/' # TIENE que salir vacío
git -C repo commit -m "..."
git -C repo push origin main
```

Cuatro cosas que muerden:

1. **`FINAL/` ya existe** (desde `d018403`). Se ACTUALIZA, no se recrea: de ahí
   `cp -a` y no `rsync --delete`, y de ahí la comprobación `--diff-filter=D`.
2. **Nada fuera de `FINAL/`.** Hay dos ramas más con trabajo de otra gente.
3. **Los enlaces de `spice_blocks/` se rompen en cada copia.** En el árbol de
   trabajo son absolutos a `/foss/designs/...`; en el repo se guardan
   **relativos** (`../XSCHEM/...`), que es la única forma que funciona en el
   clon de otra persona. `cp -a` los preserva absolutos, así que hay que
   restaurarlos antes de commitear:
   `git -C repo checkout -- FINAL/spice_blocks/`.
   Y la comprobación **no** es `find FINAL -xtype l`: en esta máquina el destino
   absoluto existe y no parece roto. La que vale es

       find FINAL -type l -lname '/*'      # tiene que salir vacío

4. **Nunca `--force`, nunca reescribir historia.**

Se verifica clonando en limpio, no mirando la copia de trabajo:

```bash
git clone git@github.com:AnBuiUCI/sscs-2026-zotnetic.git verify
cd verify && find FINAL -type l -lname '/*'
python3 -c "print(open('FINAL/openroad/out_integration/B26_A_filled4.gds','rb').read(4).hex())"
# 00060002 = cabecera GDSII válida
```

`B26_A_filled4.gds` es el entregable desde el 2026-09-07: el área integrada con
`GRADIENT_NAV2_V3` dentro, sha256 `543d31ff7536b791…`. Es a lo que apuntan
`lvs_config.json → LAYOUT_FILE` e `info.yaml`.

## Subir las herramientas

```bash
cd <scratchpad>
git clone git@github.com:Juander28/GDS_GENERATOR.git gen
for b in $(ls gen/flow_scripts); do
    src=/foss/designs/a_zonetic2026/openroad/scripts/$b
    [ -f "$src" ] && { cmp -s "gen/flow_scripts/$b" "$src" || echo "DIFF $b"; }
done
```

Es una **copia**, así que se queda vieja en silencio: cada vez que cambia un
script del flujo o un módulo del generador hay que sincronizarlo a mano.

**Ningún artefacto generado va aquí**: pesan cientos de megas, los rehace el
flujo, y uno viejo es exactamente cómo un DRC y un LVS acaban pasando contra el
circuito equivocado. Los entregables viven en el repositorio de diseño.

LFS no hace falta: el fichero más grande es `B26_A_filled4.gds`, ~14 MB, muy por
debajo del límite de 100 MB de GitHub. `FINAL/.gitattributes` declara
`*.gds binary` y `*.gds.gz binary`.
