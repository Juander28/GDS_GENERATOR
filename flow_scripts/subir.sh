#!/usr/bin/env bash
#  Sube el arbol de trabajo a los dos repositorios, con las comprobaciones que
#  hay que hacer SIEMPRE y que es facil saltarse.
#
#      scripts/subir.sh                    prepara y ENSENA lo que iria; no empuja
#      scripts/subir.sh --push  "mensaje"  lo empuja de verdad
#      scripts/subir.sh --solo diseno|gen  uno de los dos nada mas
#
#  POR QUE UN SCRIPT. El arbol de trabajo no es un repositorio de ninguno de los
#  dos y no se le hace `git init` -- git no empuja un repo local dentro de un
#  subdirectorio de un remoto. Asi que cada subida es una copia, y una copia
#  pierde tres cosas que no son el contenido de los ficheros: el destino de los
#  enlaces, los bits de permiso y, si se hace con `rsync --delete`, ficheros que
#  nadie queria borrar. Las tres estan comprobadas aqui.
#
#  Ver docs/repositorios.md para el porque de cada comprobacion.
set -euo pipefail

ARBOL=${ARBOL:-/foss/designs/a_zonetic2026}
[ -d "$ARBOL" ] || ARBOL=$HOME/Documents/DOCKER2026/designs/a_zonetic2026
CLONES=${CLONES:-$(cd "$ARBOL/../.." 2>/dev/null && pwd)/repos}
[ -d "$CLONES" ] || CLONES=$HOME/Documents/DOCKER2026/repos

DISENO=$CLONES/repo          # AnBuiUCI/sscs-2026-zotnetic  -- todo va en FINAL/
GEN=$CLONES/gen              # Juander28/GDS_GENERATOR      -- herramientas y docs

PUSH=0 ; SOLO=ambos ; MENSAJE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --push) PUSH=1 ; MENSAJE=${2:-} ; shift 2 ;;
        --solo) SOLO=$2 ; shift 2 ;;
        *) echo "no entiendo '$1'" >&2 ; exit 2 ;;
    esac
done

falta() { echo "  FALTA $1 -- clona con: git clone $2 $1" >&2 ; exit 1 ; }
[ -d "$DISENO/.git" ] || falta "$DISENO" git@github.com:AnBuiUCI/sscs-2026-zotnetic.git
[ -d "$GEN/.git" ]    || falta "$GEN"    git@github.com:Juander28/GDS_GENERATOR.git

#  --- el diseno --------------------------------------------------------------
diseno() {
    echo "== diseno: $DISENO"
    git -C "$DISENO" checkout -q main
    git -C "$DISENO" pull -q --ff-only origin main

    #  /bin/cp a proposito: `cp` esta aliasado a `cp -i` y en un bucle se queda
    #  esperando una respuesta que nadie teclea. Y `cp -a`, no `rsync --delete`:
    #  FINAL/ se ACTUALIZA, no se recrea.
    /bin/cp -a "$ARBOL/." "$DISENO/FINAL/"
    #  Y fuera los ficheros de bloqueo que deja abierta una presentacion.
    #  `cp -a` los copia como cualquier otro y uno se colo en el commit
    #  c4c8610: 165 bytes de basura en el repositorio del diseño.
    find "$DISENO/FINAL" \( -name '~$*' -o -name '.~lock.*' \) -delete

    #  Los enlaces de spice_blocks/ se guardan RELATIVOS en el repo; `cp -a` los
    #  trae absolutos a /foss/designs/... y en el clon de otra persona no
    #  resuelven. Y no vale `find -xtype l`: aqui el destino absoluto existe.
    git -C "$DISENO" checkout -- FINAL/spice_blocks/ 2>/dev/null || true
    if [ -n "$(cd "$DISENO" && find FINAL -type l -lname '/*')" ]; then
        echo "  ABORTA: quedan enlaces absolutos en FINAL/" >&2
        (cd "$DISENO" && find FINAL -type l -lname '/*') >&2
        exit 1
    fi

    #  El bit de ejecucion, que una copia entre maquinas se come.
    if [ -n "$(cd "$DISENO" && find FINAL -name '*.sh' ! -perm -u+x)" ]; then
        echo "  aviso: .sh sin permiso de ejecucion, se lo pongo"
        (cd "$DISENO" && find FINAL -name '*.sh' ! -perm -u+x -exec chmod +x {} +)
    fi

    git -C "$DISENO" add -A
    #  Nada borrado, y nada fuera de FINAL/ salvo los dos ficheros de interfaz
    #  del chipathon, que viven en la RAIZ y solo ahi.
    local borrados fuera
    borrados=$(git -C "$DISENO" diff --cached --name-only --diff-filter=D)
    fuera=$(git -C "$DISENO" diff --cached --name-only \
            | grep -v '^FINAL/' | grep -vE '^(info\.yaml|lvs_config\.json)$' || true)
    [ -z "$borrados" ] || { echo "  ABORTA: borraria ficheros:" >&2 ; echo "$borrados" >&2 ; exit 1 ; }
    [ -z "$fuera" ]    || { echo "  ABORTA: toca cosas fuera de FINAL/:" >&2 ; echo "$fuera" >&2 ; exit 1 ; }

    echo "  ficheros que cambian: $(git -C "$DISENO" diff --cached --name-only | wc -l)"
    git -C "$DISENO" diff --cached --stat | tail -12
}

#  --- las herramientas y la documentacion -------------------------------------
#  Es una COPIA de lo que vive en el arbol, asi que se queda vieja en silencio.
gen() {
    echo "== herramientas: $GEN"
    git -C "$GEN" checkout -q main
    git -C "$GEN" pull -q --ff-only origin main

    #  TODO `openroad/scripts/`, no solo lo que ya estaba. Recorriendo el
    #  destino, un script NUEVO no llegaba nunca: la copia solo refrescaba los
    #  que ya existian alli, y eso es justo como una copia se queda vieja sin
    #  que nadie lo note.
    rsync -a --exclude '__pycache__/' --exclude '*.pyc' \
          "$ARBOL/openroad/scripts/" "$GEN/flow_scripts/"
    [ -f "$ARBOL/openroad/Makefile" ] && /bin/cp -a "$ARBOL/openroad/Makefile" "$GEN/flow_scripts/"

    #  Los .md del arbol: en el repo de diseno estan ignorados a proposito, aqui
    #  es donde viven.
    for m in "$ARBOL"/docs/*.md "$ARBOL/HANDOFF.md"; do
        [ -f "$m" ] && /bin/cp -a "$m" "$GEN/docs/"
    done
    #  El generador, SIN sus directorios de trabajo. `lvs_run/` es la
    #  extraccion de una celda -- .ext, .lvsdb, logs con fecha en el nombre --
    #  y ninguno de esos tres es conocimiento: son el resultado de correr la
    #  herramienta una vez. `.gitignore` de este repo ya para los .gds y los
    #  .lyrdb, pero no los directorios de run, asi que se excluyen aqui.
    [ -d "$ARBOL/../zotnetic_layout" ] && \
        rsync -a --delete \
              --exclude '__pycache__/' --exclude '*.pyc' --exclude '.venv*/' \
              --exclude 'lvs_run/' --exclude 'drc_run/' --exclude 'drc_run_*/' \
              --exclude 'out/' --exclude 'work_*/' \
              --exclude '*.lvsdb' --exclude '*.ext' --exclude '*.log' \
              "$ARBOL/../zotnetic_layout/" "$GEN/zotnetic_layout/"

    #  NINGUN artefacto generado aqui: pesan cientos de megas, los rehace el
    #  flujo, y uno viejo es como un DRC y un LVS acaban pasando contra el
    #  circuito equivocado. Los `.spice` NO entran en esa lista: los de
    #  `zotnetic_layout/` son ejemplos y celdas de referencia, y llevan en el
    #  repositorio desde el principio.
    local malo
    #  `-uall`: sin el, git resume un directorio nuevo entero en una linea y
    #  el filtro por extension no ve ni uno de los ficheros de dentro.
    malo=$(cd "$GEN" && git status --porcelain -uall | awk '{print $2}' \
           | grep -E '\.(gds|gds\.gz|lyrdb|ext)$' || true)
    [ -z "$malo" ] || { echo "  ABORTA: artefactos generados:" >&2 ; echo "$malo" >&2 ; exit 1 ; }

    git -C "$GEN" add -A
    echo "  ficheros que cambian: $(git -C "$GEN" diff --cached --name-only | wc -l)"
    git -C "$GEN" diff --cached --stat | tail -12
}

[ "$SOLO" = gen ]    || diseno
[ "$SOLO" = diseno ] || gen

if [ "$PUSH" = 1 ]; then
    [ -n "$MENSAJE" ] || { echo "  --push necesita un mensaje" >&2 ; exit 2 ; }
    #  Nunca --force, nunca reescribir historia.
    [ "$SOLO" = gen ] || { git -C "$DISENO" diff --cached --quiet || \
        { git -C "$DISENO" commit -qm "$MENSAJE" && git -C "$DISENO" push origin main ; } ; }
    [ "$SOLO" = diseno ] || { git -C "$GEN" diff --cached --quiet || \
        { git -C "$GEN" commit -qm "$MENSAJE" && git -C "$GEN" push origin main ; } ; }
    echo "== subido"
else
    echo
    echo "== NO se ha empujado nada. Para hacerlo:"
    echo "   scripts/subir.sh --push \"mensaje del commit\""
fi
