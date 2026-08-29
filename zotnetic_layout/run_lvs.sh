#!/bin/bash
# LVS de un bloque (o de todos) con las DOS herramientas, guardando los logs.
#
#   ./run_lvs.sh                 todos los bloques
#   ./run_lvs.sh OPAM_LIN_flat   uno solo
#
# Por que dos. No comprueban lo mismo y ya se ha visto discrepar a las dos:
#
#   * KLayout extrae del GDS y compara con SUS reglas de conexion, que incluyen
#     las de MIM (`mimcap_connections.lvs`). Es el que sabe de verdad si las dos
#     placas del condensador caen en su net -- magic no resuelve el terminal de
#     placa superior (§11) y netgen depende de lo que le den.
#   * netgen compara topologia y ademas PROPIEDADES (W, L, area), asi que pilla
#     un transistor del tamano equivocado que a KLayout le cuadraria igual.
#
# Todo lo que sale se queda en `layouts/<BLOQUE>/lvs/`:
#
#   <BLOQUE>_flat_gf180.cir     netlist extraida del GDS   (KLayout)
#   <BLOQUE>_flat_gf180.lvsdb   base de datos de LVS       (KLayout)
#   lvs_run_*.log               log de la extraccion       (KLayout)
#   netgen.out                  comparacion detallada      (netgen)
#   netgen.log                  lo que netgen escribio por consola
#   RESUMEN.txt                 el veredicto de los dos, en tres lineas
#
# OJO con `--top_lvl_pins`: sin el, netgen no recibe los pines del top y da un
# emparejamiento que no significa nada (§12.0).

set -uo pipefail

#  `--v2` mira la otra carpeta. La netlist de referencia es la MISMA en las dos
#  versiones -- sale del mismo aplanado -- asi que un `Netlists match` en la v2 es
#  la prueba de que no ha cambiado el circuito, solo el dibujo.
RAIZ=/foss/designs/a_zonetic2026/layouts
if [ "${1:-}" = "--v2" ]; then RAIZ=/foss/designs/a_zonetic2026/layouts_v2; shift; fi
PDK=/foss/pdks/gf180mcuD/libs.tech
export PATH=/foss/tools/klayout:$PATH

BLOQUES=${*:-"WEIGHT_COMP DECODER COMP OPAM OPAM_LIN_flat"}
FALLOS=0

for B in $BLOQUES; do
    D=$RAIZ/$B
    GDS=$D/${B}_flat_gf180.gds
    REF=$D/${B}_lvs.spice
    echo "=============================================================="
    echo "  $B"
    echo "=============================================================="
    if [ ! -s "$GDS" ] || [ ! -s "$REF" ]; then
        echo "  SALTADO: falta el GDS o la netlist de referencia"
        echo "     $GDS"
        echo "     $REF"
        FALLOS=$((FALLOS + 1)); continue
    fi

    #  El sustrato TIENE que llamarse como en la netlist o queda como nodo
    #  suelto y el LVS no significa nada. Se lee del .subckt en vez de fijarlo:
    #  era GND con el esquematico viejo y es VSS con el nuevo.
    SUB=$(grep -m1 -i "^\.subckt" "$REF" \
          | tr ' ' '\n' | grep -ixE "VSS|VGND|GND" | head -1)
    SUB=${SUB:-VSS}
    echo "  sustrato: $SUB"

    mkdir -p "$D/lvs"
    rm -f "$D/lvs/netgen.out" "$D/lvs/netgen.log" "$D/lvs/RESUMEN.txt"

    #  La hoja de la resistencia de poly, leida de la propia netlist. 1k/2k/3k no
    #  es algo que se dibuje distinto -- es la MISMA capa (`ppolyf_u_h_sub`) y lo
    #  que cambia es una opcion de proceso -- asi que la unica forma de que la
    #  extraccion ponga el valor bueno es decirselo.
    HOJA=$(grep -om1 -iE "ppolyf_u_[123]k" "$REF" | grep -oE "[123]k")
    if [ -n "$HOJA" ]; then echo "  hoja de poly: $HOJA"; fi

    echo "  --> 1/2  extraccion y LVS con KLayout"
    if [ -z "$HOJA" ] || [ "$HOJA" = "1k" ]; then
        timeout 3000 python3 "$PDK/klayout/tech/lvs/run_lvs.py" \
            --layout="$GDS" --netlist="$REF" \
            --variant=D --topcell="$B" --run_dir="$D/lvs" \
            --lvs_sub="$SUB" --top_lvl_pins > "$D/lvs/klayout_stdout.log" 2>&1
    else
        #  `run_lvs.py` FIJA `poly_res=1k` en su tabla de variantes (A, B, C y D,
        #  las cuatro) y no ofrece manera de cambiarlo. El deck si lo admite:
        #  `gf180mcu.lvs` hace `POLY_RES = $poly_res || '1k'` y
        #  `res_extraction.lvs` tiene rama completa para 2k y 3k. Asi que para
        #  esos dos se llama al deck directamente, con la misma bateria de
        #  switches que montaria `generate_klayout_switches()` para la variante D
        #  y `--top_lvl_pins`.
        #
        #  OJO: esta lista DUPLICA la tabla del PDK (`run_lvs.py`, variante D:
        #  metal_top=11K, mim_option=B, metal_level=5LM, mim_cap=2). Si se cambia
        #  de variante o el PDK cambia la tabla, hay que revisarla aqui. Es el
        #  precio de poder fijar `poly_res`; se prefiere eso a extraer con una
        #  hoja que no es la del circuito.
        timeout 3000 klayout -b -r "$PDK/klayout/tech/lvs/gf180mcu.lvs" \
            -rd input="$GDS" \
            -rd schematic="$REF" \
            -rd report="$D/lvs/${B}_flat_gf180.lvsdb" \
            -rd target_netlist="$D/lvs/${B}_flat_gf180.cir" \
            -rd topcell="$B" \
            -rd lvs_sub="$SUB" \
            -rd thr=2 \
            -rd run_mode=deep \
            -rd metal_top=11K \
            -rd mim_option=B \
            -rd metal_level=5LM \
            -rd mim_cap=2 \
            -rd poly_res="$HOJA" \
            -rd top_lvl_pins=true \
            -rd verbose=false \
            -rd spice_net_names=true \
            -rd spice_comments=false \
            -rd scale=false \
            -rd schematic_simplify=false \
            -rd net_only=false \
            -rd combine=false \
            -rd purge=false \
            -rd purge_nets=false > "$D/lvs/klayout_stdout.log" 2>&1
    fi
    KL=$?
    CIR=$D/lvs/${B}_flat_gf180.cir

    #  Setup de netgen: el del PDK solo declara `ppolyf_u_1k`, y sin el
    #  dispositivo en su lista no hay REDUCCION EN SERIE -- que es justo lo que
    #  hace falta para casar `s` tramos extraidos contra un dispositivo de la
    #  referencia. El local anade 2k y 3k sin tocar el PDK.
    SETUP=$PDK/netgen/gf180mcuD_setup.tcl
    case "$HOJA" in
        2k|3k) SETUP=$(dirname "$0")/lvs/gf180mcuD_setup_polyres.tcl ;;
    esac

    echo "  --> 2/2  comparacion con netgen"
    if [ -s "$CIR" ]; then
        #  netgen devuelve 0 aunque los circuitos NO casen, asi que su codigo de
        #  salida no sirve de veredicto: hay que leer el fichero de comparacion.
        timeout 3000 netgen -batch lvs \
            "$CIR $B" "$REF $B" \
            "$SETUP" \
            "$D/lvs/netgen.out" > "$D/lvs/netgen.log" 2>&1
    else
        echo "  netgen SALTADO: KLayout no dejo $CIR" > "$D/lvs/netgen.log"
    fi

    #  ---- veredicto -------------------------------------------------------
    #  Cada herramienta se juzga por lo que ESCRIBE, no por su codigo de salida.
    #  Esto valia para netgen desde el principio y para KLayout NO: se juzgaba
    #  por `$KL`, y `run_lvs.py` devuelve 0 aunque las netlists no casen. El
    #  resultado fue un LIMPIO falso en OPAM_LIN_flat, con el log diciendo
    #  `ERROR : Netlists don't match` en la misma corrida. Es el tercer caso de
    #  la misma familia (§12.5): la comprobacion no fallaba cuando debia.
    if grep -qi "ERROR : Netlists don't match" "$D/lvs/klayout_stdout.log" 2>/dev/null; then
        V_KL="NO CASAN"
    elif grep -qi "Congratulations! Netlists match" "$D/lvs/klayout_stdout.log" 2>/dev/null; then
        V_KL="LIMPIO"
    else
        V_KL="SIN VEREDICTO -- mira klayout_stdout.log"
    fi
    #  El codigo de salida deja de ser el veredicto, pero se conserva como dato:
    #  distingue "no caso" de "ni siquiera arranco".
    [ "$KL" -eq 0 ] || V_KL="$V_KL (codigo $KL)"
    if grep -qi "Netlists do not match" "$D/lvs/netgen.out" 2>/dev/null; then
        V_NG="NO CASAN"
    elif grep -qiE "Circuits match uniquely|Netlists match" "$D/lvs/netgen.out" 2>/dev/null; then
        V_NG="CASAN"
        grep -qi "property.*mismatch\|Property errors" "$D/lvs/netgen.out" \
            && V_NG="CASAN (con avisos de propiedad)"
    else
        V_NG="SIN VEREDICTO -- mira netgen.log"
    fi

    { echo "bloque : $B"
      echo "fecha  : $(date '+%Y-%m-%d %H:%M:%S')"
      echo "GDS    : $GDS"
      echo "ref    : $REF"
      echo "sustrato: $SUB"
      echo "hoja poly: ${HOJA:-n/a}"
      echo "setup netgen: $SETUP"
      echo "KLayout: $V_KL"
      echo "netgen : $V_NG"
    } > "$D/lvs/RESUMEN.txt"

    printf "  KLayout: %-18s netgen: %s\n" "$V_KL" "$V_NG"
    echo "  logs en $D/lvs/"
    case "$V_KL$V_NG" in
        LIMPIOCASAN*) ;;
        *) FALLOS=$((FALLOS + 1)) ;;
    esac
done

echo
echo "=============================================================="
printf "  %-16s %-20s %s\n" BLOQUE KLAYOUT NETGEN
for B in $BLOQUES; do
    R=$RAIZ/$B/lvs/RESUMEN.txt
    [ -s "$R" ] || { printf "  %-16s %s\n" "$B" "sin resultado"; continue; }
    printf "  %-16s %-20s %s\n" "$B" \
        "$(sed -n 's/^KLayout: //p' "$R")" "$(sed -n 's/^netgen : //p' "$R")"
done
echo "=============================================================="
[ "$FALLOS" -eq 0 ] || echo "  $FALLOS bloque(s) sin LVS limpio"
exit 0
