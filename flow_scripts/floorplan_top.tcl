# -----------------------------------------------------------------------------
#  Floorplan of GRADIENT_NAV: place every macro and build the power grid.
#
#      openroad -no_init -exit scripts/floorplan_top.tcl
#
#  The design is nothing but hard macros (see verilog/top_macros.v), so there is
#  no placement to do beyond deciding where the blocks go, and no routing here at
#  all — only power. Signal routing is deliberately out of scope: the macro pins
#  are not on the 0.56 um routing grid.
#
#  Nothing below is a hard-coded coordinate. Sizes are read from the LEF through
#  the database, so the floorplan re-arranges itself when a block changes size.
# -----------------------------------------------------------------------------

#  Output directory. Defaults to `out`, which is the v1 top's.
#  `TOP_OUT` changes it so the top can be built with another version's cells
#  without stepping on the previous one: both have to coexist to be
#  compararlos.
set OUT [expr {[info exists env(TOP_OUT)] ? $env(TOP_OUT) : "out"}]
file mkdir $OUT

#  Name of the top cell. See scripts/load_design.tcl.
set TOPCELL [expr {[info exists env(TOP_CELL)] ? $env(TOP_CELL) : "GRADIENT_NAV"}]

source scripts/load_design.tcl

set block [ord::get_db_block]
set dbu   [[ord::get_db_tech] getDbUnitsPerMicron]

# --- geometry knobs ----------------------------------------------------------
#  Sized to land the whole chip inside 500 x 500 um. The channels have to stay
#  wide enough for a stripe pair plus clearance; 12 um fits 3 + 3 + 3 with room.
set HGAP     16.0   ;# gap between macros on a shelf: all the
                    ;# trafico vertical de Metal2, porque dentro de un macro esa
                    ;# layer is taken by the block's own routing.
set VGAP     12.0   ;# channel between shelves; a couple of straps must fit (9)
set MARGIN    9.0   ;# core a die
set STRIPE_W  3.0
set BUDGET  500.0   ;# lado maximo del die
set ASPECT    1.2   ;# proporcion maxima; dentro de eso se minimiza el AREA
set SNAP_PAD  3.0   ;# slack for snapping the core to the site grid
#  ELECTROMIGRACION. El bloque consume 15.50 mA de pico medidos, y se dimensiona
#  al DOBLE: 31 mA. Los limites son los del PDK, declarados en el tech-LEF como
#  DCCURRENTDENSITY AVERAGE -- Metal4 0.67 mA/um, Metal5 1.5, vias 0.18 por
#  corte. No estan en el DRC: esto no lo caza ninguna regla, hay que medirlo.
#
#      31 mA / 0.67 = 46.3 um de Metal4 vertical
#      31 mA / 1.5  = 20.7 um de Metal5 en el borde
#
#  Con straps de 3 um hacen falta ~16 parejas cruzando cualquier corte, contra
#  las 8 que salian antes. Y hay una segunda razon para repartirlas: cada macro
#  expone su alimentacion en una barra de Metal3 de 0.9 um, que aguanta 1.21 mA
#  contando el Metal1 en paralelo. Alimentado por UN punto, un COMP de 99.6 um
#  manda sus 0.83 mA de pico por la barra entera. Por dos, cada tramo lleva la
#  mitad. De ahi que se pueble cada banda libre en vez de poner un par centrado.
set SEP_PAIR  3.0      ;# hueco entre parejas contiguas de la misma banda
set MAXPAIR     4      ;# tope de parejas por banda, para no ahogar el ruteo
set PTS_MIN     2      ;# puntos de contacto minimos por macro y por rail
set I_OBJ    31.0      ;# mA que debe tragar el bloque: el doble del pico medido
set MA_UM_M4 0.67      ;# DCCURRENTDENSITY AVERAGE de Metal4, del tech-LEF
set CANAL_W  10.0      ;# ancho del strap de canal; ya no hay pareja que
                       ;# repartir, asi que se lleva todo el hueco
set PIN_GAP   5.0   ;# minimum spacing between top pins, in microns
set PIN_CORNER 10.0 ;# and how far they keep from the die corners

#: Everything handed to pdngen has to land on the 0.005 um manufacturing grid;
#: a band centred between two obstructions lands on 66.3875 as easily as not,
#: and `PDN-0191` aborts rather than rounding.
proc mfg {v} { return [expr {round($v / 0.005) * 0.005}] }

#: Macros are placed on the routing grid (0.56 pitch), not just on the
#: manufacturing grid. Their metal3 landing pads are already on-track inside the
#: block (see coil_layout/power.py); if the block does not land on a multiple of
#: alineacion se pierde al colocarlo y el router vuelve a aterrizar de refilon.
proc ontrack {v} { return [expr {round($v / 0.56) * 0.56}] }

#: EL `ORIGIN` DEL MACRO ENTRA EN LA CUENTA, y olvidarlo deshace lo anterior.
#: `place_macro -location` situa la esquina de la caja SIZE, que en coordenadas
#: del bloque esta en `-ORIGIN`. Asi que un pad que dentro del bloque vive en
#: `0.28 + k*0.56` acaba en el top en `location + ORIGIN + 0.28 + k*0.56`: si
#: `ORIGIN` no es multiplo del paso, toda la alineacion se pierde aunque
#: `location` si lo sea. `OPAM_LIN_flat` tiene `ORIGIN 1.260`, que es 0.14 fuera
#: de rejilla, y `WEIGHT_COMP` tiene `3.945 3.550`.
#:
#: Coste real: `[ERROR DRT-0073] No access point for x1_x1/INP`, que aborta el
#: ruteo entero. Y es el mismo razonamiento que ya hace `integrate_top.tcl` un
#: nivel mas arriba.
proc lef_origins {} {
    set out [dict create]
    foreach f [glob -nocomplain [file join [file dirname [info script]] .. lef *.lef]] {
        set mname [file rootname [file tail $f]]
        set fh [open $f r]; set txt [read $fh]; close $fh
        if {[regexp {\n\s*ORIGIN\s+([-\d.]+)\s+([-\d.]+)\s*;} $txt -> ox oy]} {
            dict set out $mname [list $ox $oy]
        } else {
            dict set out $mname [list 0.0 0.0]
        }
    }
    return $out
}

#: `location` tal que `location + origen` cae en la rejilla de ruteo.
#:
#: Redondea HACIA ARRIBA, no al mas cercano. Al mas cercano, la primera columna
#: se iba 0.14 um por debajo del borde del core y `MPL-0034` abortaba
#: (`Cannot place x1_x1 at (9.38, ...), outside of the core (9.52, ...)`).
#: Hacia arriba el macro nunca retrocede, y lo que se paga es como mucho un paso
#: de pista -- 0.56 um -- por fila y por columna, sobre un floorplan parametrico.
proc ontrack_org {v org} {
    set k [expr {ceil(($v + $org) / 0.56 - 1e-9)}]
    return [expr {$k * 0.56 - $org}]
}

#: `MIMTM.1` pide 1.2 um de la placa de un MIM a cualquier otro metal4. Evitar el
#: overlap is not enough: the power straps brushed past and 41
#: violations. The LEF already carries the layer spacing; this adds the rest.
set MIM_CLEAR 1.2

proc blocked_x {master dbu dx} {
    #: x ranges with Metal4 blocked, shifted to where the macro sits.
    #
    #  EL `ORIGIN` DEL LEF. Estos macros traen `ORIGIN 1.260 0.000`, y odb NO
    #  se lo aplica a la geometria: `getObstructions` devuelve las coordenadas
    #  tal cual estan en el fichero, mientras `getBBox` ya esta puesto donde va
    #  el macro. Sumar una cosa a la otra corria los bloqueos 1.26 um a la
    #  derecha, y con ellos las bandas libres: los straps de altura completa
    #  caian medio micron dentro de una placa MIM y pdngen los partia en
    #  trozos, dejando 15.9 um de Metal4 vertical donde este fichero informaba
    #  de 47.6.
    global MIM_CLEAR
    lassign [$master getOrigin] mox moy
    set mox [expr {$mox / double($dbu)}]
    set out {}
    foreach box [$master getObstructions] {
        if {[[$box getTechLayer] getName] ne "Metal4"} { continue }
        lappend out [list [expr {$dx + ([$box xMin] / double($dbu)) - $mox - $MIM_CLEAR}] \
                          [expr {$dx + ([$box xMax] / double($dbu)) - $mox + $MIM_CLEAR}]]
    }
    return $out
}

proc free_bands {blocked lo hi} {
    #: the complement of `blocked` inside [lo, hi], merged.
    set free [list [list $lo $hi]]
    foreach u [lsort -real -index 0 $blocked] {
        lassign $u ua ub
        set next {}
        foreach f $free {
            lassign $f fa fb
            if {$ub <= $fa || $ua >= $fb} { lappend next $f ; continue }
            if {$ua > $fa} { lappend next [list $fa $ua] }
            if {$ub < $fb} { lappend next [list $ub $fb] }
        }
        set free $next
    }
    return $free
}

proc solapa_x {ocupado lo hi} {
    #: cierto si [lo,hi) pisa alguno de los intervalos ya colocados.
    foreach o $ocupado {
        lassign $o a b
        if {$lo < $b && $a < $hi} { return 1 }
    }
    return 0
}

proc dim {block dbu name what} {
    set m [[$block findInst $name] getMaster]
    return [expr {[$m get$what] / double($dbu)}]
}

# --- gather the macros -------------------------------------------------------
#  Instances are grouped by the first field of their hierarchical name, which the
#  Verilog generator builds from the instance path: `x1_x4` is instance x4 inside
#  GRADIENT x1. So every group is one GRADIENT.
#  --- shelf packing ------------------------------------------------------------
#  The column grid is gone. It forced every column to be as wide as its widest
#  macro, and since every column mixed OPAM (87.44) with COMP (104.28), each
#  OPAM row threw away 16.84 um of width, twelve times over.
#
#  In its place, First-Fit-Decreasing-Height: macros are sorted tallest to
#  shortest and packed into shelves; each shelf height is set by the first one
#  in, which by that order is always the tallest. What is left at the end of a
#  shelf gets used by a shorter macro -- that is how the WEIGHT_COMPs end up in
#  the gap three COMPs leave.
#
#  Target widths are swept and the SMALLEST AREA is chosen among those keeping
#  the aspect below ASPECT and both sides below BUDGET. Nothing is padded to
#  even out the sides: an exact square is not needed, and that
#  padding would be wasted area.
set items {}
foreach inst [$block getInsts] {
    if {![[$inst getMaster] isBlock]} { continue }
    set m [$inst getMaster]
    lappend items [list [$inst getName] \
                        [expr {[$m getWidth] / double($dbu)}] \
                        [expr {[$m getHeight] / double($dbu)}] \
                        [$m getName]]
}
#  Order: by descending height, and within a height by instance name, which
#  groups `x1_*` with `x1_*`. Macros of the same GRADIENT then tend to land at
#  the same x on different shelves, which shortens the nets joining them.
set items [lsort -index 0 $items]
set items [lsort -real -decreasing -index 2 $items]

proc pack {items W hgap} {
    #: FFDH. Returns {shelves used_width total_height}, with shelves as a list of
    #: {tall  {{pin_name x w} ...}}.
    set shelves {}
    foreach it $items {
        lassign $it name w h
        set done 0
        for {set i 0} {$i < [llength $shelves]} {incr i} {
            lassign [lindex $shelves $i] sh smembers sused
            set nx [expr {$sused == 0 ? 0.0 : $sused + $hgap}]
            if {$nx + $w <= $W} {
                lappend smembers [list $name $nx $w]
                lset shelves $i [list $sh $smembers [expr {$nx + $w}]]
                set done 1
                break
            }
        }
        if {!$done} {
            if {$w > $W} { return {} }          ;# does not fit alone: bad width
            lappend shelves [list $h [list [list $name 0.0 $w]] $w]
        }
    }
    set used 0.0
    set tot  0.0
    foreach s $shelves {
        set used [expr {max($used, [lindex $s 2])}]
        set tot  [expr {$tot + [lindex $s 0]}]
    }
    return [list $shelves $used $tot]
}

set best {}
set widest 0.0
foreach it $items { set widest [expr {max($widest, [lindex $it 1])}] }
for {set W [expr {ceil($widest)}] } {$W <= $BUDGET - 2 * $MARGIN} {set W [expr {$W + 2.0}]} {
    set r [pack $items $W $HGAP]
    if {![llength $r]} { continue }
    lassign $r shelves used tot
    set n [llength $shelves]
    set w [expr {$used + 2 * $MARGIN}]
    set h [expr {$tot + ($n + 1) * $VGAP + 2 * $MARGIN}]
    if {$w > $BUDGET || $h > $BUDGET} { continue }
    set ratio [expr {max($w, $h) / min($w, $h)}]
    if {$ratio > $ASPECT} { continue }
    if {![llength $best] || $w * $h < [lindex $best 0]} {
        set best [list [expr {$w * $h}] $shelves $w $h $n]
    }
}
if {![llength $best]} {
    error "no width gives a die within $BUDGET um at aspect <= $ASPECT"
}
lassign $best best_area shelves die_w die_h nshelf

#  Un pelin de holgura: `initialize_floorplan` ajusta el core a la rejilla del
#  site and shrinks it by up to one site per side. Without this the first macro
#  por 0.52 um (`MPL-0034`).
set die_w [expr {$die_w + $SNAP_PAD}]
set die_h [expr {$die_h + $SNAP_PAD}]
set core_w [expr {$die_w - 2 * $MARGIN}]
set core_h [expr {$die_h - 2 * $MARGIN}]

initialize_floorplan \
    -die_area  "0 0 $die_w $die_h" \
    -core_area "$MARGIN $MARGIN [expr {$MARGIN + $core_w}] [expr {$MARGIN + $core_h}]" \
    -site      GF018hv5v_green_sc9

foreach layer {Metal1 Metal2 Metal3 Metal4} {
    make_tracks $layer -x_offset 0.28 -x_pitch 0.56 -y_offset 0.28 -y_pitch 0.56
}
make_tracks Metal5 -x_offset 0.45 -x_pitch 0.90 -y_offset 0.45 -y_pitch 0.90

# --- place -------------------------------------------------------------------
set core0   [$block getCoreArea]
set org_x   [expr {[$core0 xMin] / double($dbu)}]
set org_y   [expr {[$core0 yMin] / double($dbu)}]

set ORIGENES [lef_origins]
set masters [dict create]
set inst_of [dict create]
#  FILAS ESPEJADAS. Las estanterias pares van R0 y las impares MX, que es lo
#  que hace una fila de celdas estandar. Cada celda saca VSS por su borde de
#  abajo y VDD por el de arriba, asi que con todas en R0 cada canal entre
#  estanterias tenia el VDD de una enfrente del VSS de la otra: dos nets
#  distintos a dos micras, acoplo entre alimentacion y masa, y una pareja de
#  straps ocupando el hueco.
#
#  Espejando las alternas, los railes que se miran son del MISMO net:
#
#      estanteria k par   (R0)   VSS abajo   VDD arriba
#      estanteria k impar (MX)   VDD abajo   VSS arriba
#
#  y entonces el canal 0 (debajo de la primera) es de VSS, el 1 de VDD, el 2 de
#  VSS... Regla: **el carril i lleva VDD si i es impar y VSS si es par.**
#  `hlanes_net` la guarda para que la malla ponga un solo strap por canal.
set hlanes  {}
set hlanes_net {}
set y $VGAP
lappend hlanes [expr {$VGAP / 2.0}]
lappend hlanes_net VSS
set k 0
foreach s $shelves {
    lassign $s sh smembers
    set ori [expr {$k % 2 == 0 ? "R0" : "MX"}]
    foreach mem $smembers {
        lassign $mem name x w
        set mname0 [[[$block findInst $name] getMaster] getName]
        lassign [expr {[dict exists $ORIGENES $mname0] ?
                       [dict get $ORIGENES $mname0] : [list 0.0 0.0]}] mox moy
        #  Al espejar, el ORIGIN que hay que llevar a la rejilla es el del borde
        #  contrario: la geometria va de -ORIGIN a SIZE-ORIGIN, y MX la refleja.
        set moy_ef $moy
        if {$ori eq "MX"} {
            set mh [expr {[[[$block findInst $name] getMaster] getHeight] / double($dbu)}]
            set moy_ef [expr {$mh - $moy}]
        }
        place_macro -macro_name $name -orientation $ori \
            -location [list [ontrack_org [expr {$org_x + $x}] $mox] \
                            [ontrack_org [expr {$org_y + $y}] $moy_ef]]
        set mn [[[$block findInst $name] getMaster] getName]
        dict set masters $mn 1
        dict set inst_of $mn $name
    }
    set y [expr {$y + $sh + $VGAP}]
    lappend hlanes [expr {$y - $VGAP / 2.0}]
    lappend hlanes_net [expr {($k + 1) % 2 == 0 ? "VSS" : "VDD"}]
    incr k
}
#  LOS CARRILES, DE LA POSICION REAL Y NO DE LA NOMINAL.
#  `place_macro` pasa por `ontrack_org`, que AJUSTA A REJILLA, asi que un macro
#  no acaba exactamente en la `y` que se le calculo -- y con MX el ajuste es
#  distinto, porque el ORIGIN que hay que llevar a rejilla es el del otro borde.
#  Mientras los straps median 3 um sobraba holgura y no se noto. Con 10 um no:
#  un strap centrado en la `y` nominal se metia dentro del macro y aterrizaba
#  sobre sus placas MIM, cortando nets de senal. El DRC no lo ve --la geometria
#  es legal-- y el LVS lo canta como nets que desaparecen.
set ymin {} ; set ymax {}
foreach s $shelves {
    lassign $s sh smembers
    set lo 1e9 ; set hi -1e9
    foreach mem $smembers {
        lassign $mem name x w
        set bb [[$block findInst $name] getBBox]
        set a0 [expr {[$bb yMin] / double($dbu)}]
        set a1 [expr {[$bb yMax] / double($dbu)}]
        if {$a0 < $lo} { set lo $a0 }
        if {$a1 > $hi} { set hi $a1 }
    }
    lappend ymin $lo ; lappend ymax $hi
}
set hlanes {} ; set hlanes_w {}
lappend hlanes   [expr {[lindex $ymin 0] / 2.0}]
lappend hlanes_w [expr {[lindex $ymin 0] - 2.0}]
for {set i 1} {$i < [llength $shelves]} {incr i} {
    set g0 [lindex $ymax [expr {$i - 1}]]
    set g1 [lindex $ymin $i]
    lappend hlanes   [expr {($g0 + $g1) / 2.0}]
    lappend hlanes_w [expr {$g1 - $g0 - 2.0}]
}
set nsh [expr {[llength $shelves] - 1}]
lappend hlanes   [expr {[lindex $ymax $nsh] + 3.0}]
lappend hlanes_w 4.0

puts [format "  filas espejadas: %d estanterias, %d canales (VDD/VSS alternos)" \
          [llength $shelves] [llength $hlanes]]

#  ABUTICION MEDIDA, no supuesta. Un canal solo abuta donde hay rail arriba Y
#  abajo, y solo llegan al borde de su estanteria las celdas TAN ALTAS como
#  ella: en las estanterias mixtas (COMP 31.46 con DECODER 13.82) las bajitas
#  dejan hueco. Se mide la fraccion del ancho del core donde se tocan dos railes
#  del mismo net, que es lo unico que dice si el espejo sirvio de algo.
proc _intervalos_altos {block smembers sh dbu} {
    set out {}
    foreach mem $smembers {
        lassign $mem name x w
        set h [expr {[[[$block findInst $name] getMaster] getHeight] / double($dbu)}]
        #  media micra de tolerancia: alturas distintas, no ruido de redondeo
        if {abs($h - $sh) > 0.5} { continue }
        lappend out [list $x [expr {$x + $w}]]
    }
    return $out
}
proc _solape {a b} {
    set tot 0.0
    foreach ia $a {
        lassign $ia a0 a1
        foreach ib $b {
            lassign $ib b0 b1
            set lo [expr {$a0 > $b0 ? $a0 : $b0}]
            set hi [expr {$a1 < $b1 ? $a1 : $b1}]
            if {$hi > $lo} { set tot [expr {$tot + $hi - $lo}] }
        }
    }
    return $tot
}
set ancho_core [expr {([$core0 xMax] - [$core0 xMin]) / double($dbu)}]
puts "  abuticion por canal (railes del MISMO net enfrentados)"
set peor_ab 101.0
for {set i 1} {$i < [llength $hlanes]} {incr i} {
    lassign [lindex $shelves [expr {$i - 1}]] sh_lo mem_lo
    set ab 0.0
    if {$i < [llength $shelves]} {
        lassign [lindex $shelves $i] sh_hi mem_hi
        set ab [_solape [_intervalos_altos $block $mem_lo $sh_lo $dbu] \
                        [_intervalos_altos $block $mem_hi $sh_hi $dbu]]
    }
    set pct [expr {100.0 * $ab / $ancho_core}]
    if {$i < [llength $shelves] && $pct < $peor_ab} { set peor_ab $pct }
    #  El ultimo carril no esta ENTRE dos filas: es el borde de arriba, y por
    #  eso sale 0 -- no hay estanteria encima con la que abutar.
    set nota [expr {$i >= [llength $shelves] ? "  (borde, no hay fila encima)" : ""}]
    puts [format "    canal %d  %-3s  %6.1f um de %6.1f  = %5.1f %%%s" \
              $i [lindex $hlanes_net $i] $ab $ancho_core $pct $nota]
}
puts [format "    peor canal interior: %.1f %%" $peor_ab]

# --- power -------------------------------------------------------------------
#  Every block brings VDD and VSS up to a full-width Metal3 bar over its own
#  Metal1 rail (see coil_layout/power.py). That bar is the landing pad: a
#  vertical Metal4 stripe crossing the block hits it, and pdngen can drop a via.
add_global_connection -net VDD -inst_pattern {.*} -pin_pattern {VDD} -power
add_global_connection -net VSS -inst_pattern {.*} -pin_pattern {VSS} -ground
global_connect

set_voltage_domain -power VDD -ground VSS

#  The core is read back from the database rather than reused from what was asked
#  for: `initialize_floorplan` snaps it to the site grid, and a strap computed
#  against the requested size overflowed the real one by a couple of microns —
#  `PDN-0185 Insufficient width` aborts the run rather than clipping.
set core    [$block getCoreArea]
set core_x0 [expr {[$core xMin] / double($dbu)}]
set core_y0 [expr {[$core yMin] / double($dbu)}]
set real_w  [expr {([$core xMax] - [$core xMin]) / double($dbu)}]
set real_h  [expr {([$core yMax] - [$core yMin]) / double($dbu)}]

define_pdn_grid -name core -voltage_domains CORE

#  Metal4 (vertical) has to run OVER the blocks, not down the channels: that is
#  the only way it crosses their Metal3 bars. Where it may go is read from the
#  LEF obstructions rather than assumed — the MIM plates block Metal4 across the
#  middle of COMP and OPAM, and the free bands are not the same in the two.

#  Separacion DENTRO de la pareja VDD/VSS. Era igual al ancho del strap, y con
#  eso la pareja medía 9.0 um justos: las bandas libres del OPAM_LIN_flat miden
#  8.745 y se quedaban fuera por 0.255 um, dejando al amplificador con un solo
#  punto de contacto. El minimo del PDK para Metal4 es 0.28 um (M4.2), asi que
#  2.0 sigue siendo holgadisimo y hace que la pareja quepa.
set PAIR  2.0
set need  [expr {2 * $STRIPE_W + $PAIR}]

#  Metal5 (horizontal) stays in the channels between shelves: it only has to
#  meet Metal4, and above a macro it would land on the MIM plates.
#  `hlanes` viene de la colocacion, un carril por canal.
#  UN SOLO NET POR CANAL. Con las filas espejadas los dos railes que se miran
#  en un canal son del mismo net, asi que ahi no pinta nada el otro: se pone un
#  unico strap, de ese net, y se le da todo el ancho que antes se repartia entre
#  la pareja. Se acaba la adyacencia VDD/VSS en los canales, que es el acoplo
#  que habia que quitar.
set nlane 0
foreach c $hlanes {
    set net [lindex $hlanes_net $nlane]
    incr nlane
    #  Nunca mas ancho que el hueco REAL menos un micron por lado: si el strap
    #  se sale del canal aterriza sobre las placas MIM del macro y corta nets de
    #  senal. El DRC no lo ve, el LVS si.
    set w [lindex $hlanes_w [expr {$nlane - 1}]]
    if {$w > $CANAL_W} { set w $CANAL_W }
    #  pdngen exige que el ANCHO sea multiplo de 0.01 um, no de 0.005 como el
    #  resto de la geometria:  no vale aqui. Y se redondea hacia ABAJO para
    #  no volver a invadir el macro.
    set w [expr {floor($w * 100.0) / 100.0}]
    if {$w < 1.0} { continue }
    set off [mfg [expr {$c - $w / 2.0}]]
    if {$off < 0 || $off + $w > $real_h} { continue }
    #  El -pitch sigue siendo obligatorio aunque se pida un solo strap: se le
    #  da mas que el alto del core para que no repita.
    add_pdn_stripe -grid core -layer Metal5 -width $w -nets $net \
                   -number_of_straps 1 -pitch [expr {2 * $real_h}] -offset $off
}
add_pdn_connect -grid core -layers {Metal4 Metal5}

#  --- straps verticales que CRUZAN EL DIE ------------------------------------
#  LO QUE DE VERDAD LLEVA LA CORRIENTE, y lo que el informe de este fichero
#  llevaba contando mal. Un strap de Metal4 puesto en la banda libre de UN macro
#  lo parte pdngen en cuanto cruza el bloqueo de otro: sigue sirviendo como punto
#  de contacto, pero NO atraviesa el die. Medido sobre el DEF ruteado, la seccion
#  de cobre que cruza una linea horizontal bajaba a 24 um de VSS en la mitad
#  inferior -- 16 mA contra los 31 pedidos -- mientras aqui se sumaban las 27
#  parejas como si todas llegaran de arriba abajo.
#
#  Asi que antes que nada se buscan las bandas de x que NINGUN macro bloquea a
#  NINGUNA altura. Un strap ahi va entero de un borde al otro, y es el unico que
#  cuenta para el limite de electromigracion.
set todos {}
foreach inst [$block getInsts] {
    if {![[$inst getMaster] isBlock]} { continue }
    set ix [expr {[[$inst getBBox] xMin] / double($dbu)}]
    foreach b [blocked_x [$inst getMaster] $dbu $ix] { lappend todos $b }
}
set libres_glob [free_bands $todos $core_x0 [expr {$core_x0 + $real_w}]]

#: Cuanto Metal4 hace falta por net, del limite del PDK. 31 / 0.67 = 46.3 um.
set W_OBJ [expr {$I_OBJ / $MA_UM_M4}]
#: Margen a los lados de la banda. El borde de la banda es el bloqueo de un MIM,
#: y `blocked_x` ya le sumo MIM_CLEAR; esto es holgura contra la regla de
#: espaciado de metal ancho, que en Metal4 crece con el ancho.
set BANDA_M   1.0
#: Tope por strap. Mas ancho no hace falta -- lo que sobra del objetivo es cobre
#: tirado -- y una losa muy ancha se come el ruteo del canal. Con 6.0 los dos
#: nets se quedaban en 26.7 y 25.2 mA: las dos bandas anchas (24.5 y 20.6 um)
#: desperdiciaban la mitad de su hueco contra el tope.
set MAX_STRAP 8.0
#: Separacion entre dos straps de altura completa de la MISMA banda. Es menor
#: que SEP_PAIR porque aqui cada micra de hueco sale del cobre: con 3.0 los dos
#: nets no llegaban a los 46.3 um que pide el limite. El minimo del PDK para
#: Metal4 es 0.28 um (M4.2), asi que 2.0 sigue siendo holgado.
set SEP_FULL 2.0

#  Se recorren las bandas de la mas ancha a la mas estrecha y cada una se le da
#  al net que va MAS ATRASADO. Asi los dos llegan al objetivo a la vez en vez de
#  quedarse uno corto, que es exactamente lo que paso al espejar las filas: VDD
#  acabo con 18 straps y VSS con 15 sin que nadie lo decidiera.
set anchas {}
foreach band $libres_glob {
    lassign $band lo hi
    lappend anchas [list [expr {$hi - $lo}] $lo $hi]
}
set anchas [lsort -real -decreasing -index 0 $anchas]

set full_w  [dict create VDD 0.0 VSS 0.0]
set full_n  [dict create VDD 0   VSS 0]
set seen    {}
set completos {}
foreach a $anchas {
    lassign $a ancho lo hi
    set lo [expr {$lo + $BANDA_M}]
    set hi [expr {$hi - $BANDA_M}]
    set ancho [expr {$hi - $lo}]
    if {$ancho < 1.0} { continue }
    #  Se llena la banda a lo ancho, strap tras strap separados SEP_FULL, hasta
    #  que no quepa mas. Repartir la banda en un numero fijo de straps salia
    #  peor: cada strap de mas cuesta un hueco de SEP_FULL, asi que lo que
    #  maximiza el cobre es poner los MAS ANCHOS que el tope permita.
    set x $lo
    while {$hi - $x >= 1.0} {
        set w [expr {$hi - $x}]
        if {$w > $MAX_STRAP} { set w $MAX_STRAP }
        #  Y lo que deja la cota rara de pdngen -- coloca por el eje pero
        #  comprueba `offset + ancho` -- que en la ultima banda pide
        #  x + 1.5*ancho <= borde del core. Se ESTRECHA el strap en vez de
        #  saltarselo: saltandoselo, VSS se quedaba en 28.81 mA.
        set wmax [expr {($real_w + $core_x0 - $x) / 1.5}]
        if {$w > $wmax} { set w $wmax }
        #  pdngen exige el ancho en multiplos de 0.01 um, y se redondea HACIA
        #  ABAJO para no volver a comerse el margen contra el bloqueo.
        set w [expr {floor($w * 100.0) / 100.0}]
        if {$w < 1.0} { break }
        #  al net mas atrasado
        set net [expr {[dict get $full_w VDD] <= [dict get $full_w VSS] ? "VDD" : "VSS"}]
        if {[dict get $full_w $net] >= $W_OBJ} {
            #  ese ya llego; si el otro tambien, se para de gastar cobre
            set otro [expr {$net eq "VDD" ? "VSS" : "VDD"}]
            if {[dict get $full_w $otro] >= $W_OBJ} { break }
            set net $otro
        }
        #  EL `-offset` DE pdngen ES EL EJE DEL STRAP, no su borde izquierdo.
        #  Medido: se pidio un strap de 8 um en 108.29 y el DEF lo escribio en
        #  104.29..112.29 -- corrido media anchura. Con straps de 3 um daba
        #  igual, 1.5 um de holgura los absorbia la banda; con los de 8 el
        #  strap se salia por la izquierda, pisaba la placa MIM de al lado y
        #  pdngen lo partia. De ahi los 1.29 um de VDD vertical.
        set off [mfg [expr {$x + $w / 2.0 - $core_x0}]]
        #  Y LAS DOS COTAS. pdngen COLOCA por el eje pero COMPRUEBA los limites
        #  como si el offset fuera el borde izquierdo: con la banda de la
        #  derecha, offset + ancho se salia del core y abortaba con PDN-0185.
        if {$off - $w / 2.0 >= 0 && $off + $w <= $real_w} {
            add_pdn_stripe -grid core -layer Metal4 -width $w -nets $net \
                           -number_of_straps 1 -pitch [expr {2 * $real_w}] -offset $off
            dict incr full_n $net
            dict set full_w $net [expr {[dict get $full_w $net] + $w}]
            lappend seen [list [expr {$off - $w / 2.0}] [expr {$off + $w / 2.0}]]
            lappend completos [list [expr {$off + $core_x0 - $w / 2.0}] \
                                    [expr {$off + $core_x0 + $w / 2.0}] $net]
        }
        set x [expr {$x + $w + $SEP_FULL}]
    }
    if {[dict get $full_w VDD] >= $W_OBJ && [dict get $full_w VSS] >= $W_OBJ} { break }
}
foreach net {VDD VSS} {
    set um [dict get $full_w $net]
    puts [format "  Metal4 de altura completa %s: %d straps, %.2f um -> %.2f mA (pide %.2f)  %s" \
              $net [dict get $full_n $net] $um [expr {$um * $MA_UM_M4}] $I_OBJ \
              [expr {$um * $MA_UM_M4 >= $I_OBJ ? "OK" : "CORTO"}]]
}

#  The Metal4 straps go on the CORE grid and are computed **per instance**, not
#  per column: for each macro we look at the bands where ITS LEF leaves Metal4
#  free, map them into core coordinates with its placed position, and ask for a
#  strap there. That the strap gets blocked passing over another macro does not
#  matter -- pdngen clips it into pieces and it still serves the macros where it is free.
#
#  The apparent alternative, a `-macro` grid with its own per-instance straps,
#  does NOT work: it comes out empty (`PDN-0232`) because its straps have no core
#  grid to climb to, and pdngen discards them and aborts the run.
set base [expr {$MARGIN - $core_x0}]
set nstripe 0
foreach inst [$block getInsts] {
    if {![[$inst getMaster] isBlock]} { continue }
    set m  [$inst getMaster]
    set ix [expr {[[$inst getBBox] xMin] / double($dbu)}]
    set iw [expr {[$m getWidth] / double($dbu)}]
    set puntos 0
    foreach band [free_bands [blocked_x $m $dbu $ix] $ix [expr {$ix + $iw}]] {
        lassign $band lo hi
        set ancho [expr {$hi - $lo}]
        if {$ancho < $need} { continue }
        #  Cuantas parejas caben separadas SEP_PAIR, y repartidas a lo ancho de
        #  la banda en vez de una sola en el centro.
        set n [expr {int(($ancho + $SEP_PAIR) / ($need + $SEP_PAIR))}]
        if {$n > $MAXPAIR} { set n $MAXPAIR }
        if {$n < 1} { continue }
        set hueco [expr {($ancho - $n * $need) / double($n + 1)}]
        for {set k 0} {$k < $n} {incr k} {
            set lo_k [expr {$lo + $hueco * ($k + 1) + $need * $k}]
            #  Mismo criterio: `-offset` es el eje del PRIMER strap de la
            #  pareja, no el borde izquierdo de la banda que ocupa.
            set off  [mfg [expr {$lo_k + $STRIPE_W / 2.0 - $core_x0}]]
            if {$off - $STRIPE_W / 2.0 < 0 || \
                $off - $STRIPE_W / 2.0 + $need > $real_w} { continue }
            #  SOLAPE, no igualdad. Antes se comparaba el offset exacto, y eso
            #  bastaba mientras todos los straps median lo mismo; los de altura
            #  completa no, asi que dos parejas podian pisarse por un lado.
            if {[solapa_x $seen [expr {$off - $STRIPE_W / 2.0}] \
                                [expr {$off - $STRIPE_W / 2.0 + $need}]]} { continue }
            lappend seen [list [expr {$off - $STRIPE_W / 2.0}] \
                               [expr {$off - $STRIPE_W / 2.0 + $need}]]
            add_pdn_stripe -grid core -layer Metal4 -width $STRIPE_W -spacing $PAIR \
                           -pitch [expr {2 * $real_w}] -offset $off
            incr nstripe
            incr puntos
        }
    }
}

#  CUANTOS PUNTOS DE CONTACTO TIENE CADA MACRO DE VERDAD.
#  No los que el macro pidio: los que le pasan por encima. Un strap vertical
#  recorre el die entero, asi que sirve a todos los macros cuyo rango de x
#  cruza, los pidieran ellos o un vecino. Contarlo de la otra manera daba
#  ceros donde habia contacto de sobra.
set peor 9999
set peor_inst ""
foreach inst [$block getInsts] {
    if {![[$inst getMaster] isBlock]} { continue }
    set m  [$inst getMaster]
    set ix [expr {[[$inst getBBox] xMin] / double($dbu)}]
    set iw [expr {[$m getWidth] / double($dbu)}]
    set libre [free_bands [blocked_x $m $dbu $ix] $ix [expr {$ix + $iw}]]
    set n 0
    foreach o $seen {
        #  `o` esta en coordenadas de core; el strap ocupa [a, b).
        lassign $o a b
        set sx [expr {$a + $core_x0}]
        set sb [expr {$b + $core_x0}]
        foreach band $libre {
            lassign $band lo hi
            if {$sx >= $lo && $sb <= $hi} { incr n ; break }
        }
    }
    if {$n < $peor} { set peor $n ; set peor_inst [$inst getName] }
    if {$n < $PTS_MIN} {
        puts [format "  AVISO: %s (%s) tiene %d punto(s) de contacto; se piden %d" \
                  [$inst getName] [$m getName] $n $PTS_MIN]
    }
}
puts [format "  contacto por macro: peor caso %d (%s), minimo pedido %d" \
          $peor $peor_inst $PTS_MIN]
#  El total de Metal4 vertical NO es el que cuenta para electromigracion -- de
#  estos straps solo cruzan el die enteros los de altura completa, y esos ya se
#  reportaron arriba. Este numero es cuanto cobre vertical hay en total, que es
#  otra cosa y sirve para ver cuanto ruteo se esta ocupando.
set um_tot 0.0
foreach o $seen { lassign $o a b ; set um_tot [expr {$um_tot + $b - $a}] }
puts [format "  Metal4 vertical en total: %d tramos, %.1f um de cobre \
(de ellos %.2f um VDD y %.2f um VSS llegan de borde a borde)" \
          [llength $seen] $um_tot [dict get $full_w VDD] [dict get $full_w VSS]]

#  And the macro grid, which is what ties each block: Metal3 (the bar the block
#  exposes over its rail) against Metal4 (the straps above).
define_pdn_grid -macro -name macro -cells [lsort [dict keys $masters]] -halo {0 0}
add_pdn_connect -grid macro -layers {Metal3 Metal4}

pdngen

# --- coser los straps de altura completa -------------------------------------
#  pdngen PARTE un strap en los tramos donde no le pone via, y lo hace en
#  silencio: no hay aviso ninguno. Con las filas espejadas eso es fatal para la
#  malla vertical, porque entre dos canales del MISMO net hay dos estanterias
#  enteras cuyos railes son del OTRO -- no hay donde bajar una via, asi que el
#  tramo del medio se queda sin ninguna y desaparece. Medido sobre el DEF
#  ruteado: de los 47.08 um de VDD vertical que se pidieron cruzaban el die
#  1.29.
#
#  Aqui se vuelven a unir. Solo las columnas de `completos`, que son las que se
#  colocaron sobre bandas libres de bloqueo Metal4 EN TODA LA ALTURA -- coser
#  las demas metria cobre por encima de una placa MIM. Las vias que pdngen ya
#  puso siguen donde estaban; lo que cambia es que el metal entre ellas deja de
#  faltar.
#  Hasta donde tiene que llegar cada net: su carril mas bajo y su carril mas
#  alto. Mas alla no hay nada suyo que alimentar.
set lane_lo [dict create] ; set lane_hi [dict create]
for {set i 0} {$i < [llength $hlanes]} {incr i} {
    set n [lindex $hlanes_net $i]
    set c [expr {round([lindex $hlanes $i] * $dbu)}]
    if {![dict exists $lane_lo $n] || $c < [dict get $lane_lo $n]} { dict set lane_lo $n $c }
    if {![dict exists $lane_hi $n] || $c > [dict get $lane_hi $n]} { dict set lane_hi $n $c }
}

set cosidos 0
foreach net [list [$block findNet VDD] [$block findNet VSS]] {
    if {$net eq "NULL" || $net eq ""} { continue }
    set nname [$net getName]
    foreach swire [$net getSWires] {
        #  Por columna: las cajas de Metal4 de esta net cuyo x coincide con el
        #  de un strap de altura completa suyo.
        set porcol [dict create]
        foreach caja [$swire getWires] {
            if {[$caja isVia]} { continue }
            if {[[$caja getTechLayer] getName] ne "Metal4"} { continue }
            set x0 [expr {[$caja xMin] / double($dbu)}]
            set x1 [expr {[$caja xMax] / double($dbu)}]
            #  LA CONDICION SE MIDE SOBRE LA GEOMETRIA, no sobre lo que se
            #  pidio. pdngen no coloca los straps donde dice el `-offset` -- el
            #  DEF los escribe por su eje, y ademas los estrecha para cumplir
            #  sus propias reglas -- asi que cotejar la caja contra el offset
            #  pedido no casaba ni una. Lo que hay que comprobar es lo unico
            #  que importa: que la columna caiga entera dentro de una banda
            #  libre de bloqueo Metal4 a TODA altura. Si es asi, coserla no
            #  puede aterrizar sobre una placa MIM.
            set suya 0
            foreach band $libres_glob {
                lassign $band bl bh
                if {$x0 >= $bl - 0.01 && $x1 <= $bh + 0.01} { set suya 1 ; break }
            }
            if {!$suya} { continue }
            dict lappend porcol [list [$caja xMin] [$caja xMax]] $caja
        }
        dict for {col cajas} $porcol {
            lassign $col x0 x1
            #  Hasta los carriles EXTREMOS de esta net, no solo hasta donde
            #  llegaban los trozos. Una columna a la que pdngen no le puso via
            #  en el carril de abajo empezaba 100 um mas arriba, y con ella se
            #  perdian 5.9 um de VSS justo en el corte peor. La columna esta en
            #  una banda libre a toda altura, asi que alargarla no pisa nada.
            set y0 [dict get $lane_lo $nname]
            set y1 [dict get $lane_hi $nname]
            set tipo ""
            foreach caja $cajas {
                if {[$caja yMin] < $y0} { set y0 [$caja yMin] }
                if {[$caja yMax] > $y1} { set y1 [$caja yMax] }
                set tipo [$caja getWireShapeType]
            }
            if {[llength $cajas] == 1} {
                set c [lindex $cajas 0]
                if {[$c yMin] <= $y0 && [$c yMax] >= $y1} { continue }
            }
            foreach caja $cajas { odb::dbSBox_destroy $caja }
            odb::dbSBox_create $swire [[ord::get_db_tech] findLayer Metal4] \
                $x0 $y0 $x1 $y1 $tipo
            incr cosidos
        }
    }
}
puts "  straps verticales cosidos: $cosidos columnas"

# --- halo de los MIM ---------------------------------------------------------
#  `MIMTM.1` pide 1.2 um de la placa de un MIM a cualquier otro metal4, y esa
#  distance is measured **outside** the macro too. Growing the LEF obstruction
#  does not help: OpenROAD clips it to the macro outline, so the router ran
#  Metal4 0.51 um from a plate through the channel next door. What it does
#  respect is a blockage declared on the top, and that is what goes here: each
#  instance's Metal4 geometry, grown, in die coordinates.
set nblock 0
foreach inst [$block getInsts] {
    if {![[$inst getMaster] isBlock]} { continue }
    #  Mismo `ORIGIN` que en `blocked_x`, y ademas el ESPEJO: con las filas
    #  alternas en MX la placa esta a `alto - y`, no a `y`. Sin las dos
    #  correcciones el halo se dibujaba corrido 1.26 um en x y en la mitad de
    #  las filas encima de otra cosa.
    set m  [$inst getMaster]
    set bb [$inst getBBox]
    lassign [$m getOrigin] mox moy
    set ox [expr {[$bb xMin] - $mox}]
    #  Solo MX/FS, que son las dos que usa el floorplan y significan lo mismo:
    #  espejo respecto al eje X. MY y R180 tambien voltean la x y aqui no se
    #  usan; listarlas como si solo voltearan la y seria mentira.
    set esp [expr {[$inst getOrient] in {MX FS}}]
    set halo [expr {round($MIM_CLEAR * $dbu)}]
    foreach box [$m getObstructions] {
        if {[[$box getTechLayer] getName] ne "Metal4"} { continue }
        if {$esp} {
            set y0 [expr {[$bb yMax] - ([$box yMax] - $moy)}]
            set y1 [expr {[$bb yMax] - ([$box yMin] - $moy)}]
        } else {
            set y0 [expr {[$bb yMin] + [$box yMin] - $moy}]
            set y1 [expr {[$bb yMin] + [$box yMax] - $moy}]
        }
        odb::dbObstruction_create $block [$box getTechLayer] \
            [expr {$ox + [$box xMin] - $halo}] [expr {$y0 - $halo}] \
            [expr {$ox + [$box xMax] + $halo}] [expr {$y1 + $halo}]
        incr nblock
    }
}
puts "Metal4 blockages around the MIMs: $nblock"

# --- pines del top -----------------------------------------------------------
#  The 19 ports have no physical pin: today they are just names in the Verilog.
#  Without this the nets going to them have nowhere to end and the router cannot
#  close them. Metal3 is horizontal and Metal2 vertical, so the left and right
#  ones come out on Metal3 and the top and bottom ones on Metal2.
#  `-min_distance` in microns. Without it, `place_pins` packed them to the grid
#  pitch and they came out **1.12 um** apart (S1N/S1P at the bottom, and the six
#  on the left). Not illegal, but it leaves the padframe integrator opening the
#  abanico desde un paso de pista; 5 um es holgado y siguen cabiendo de sobra.
place_pins -hor_layers Metal3 -ver_layers Metal2 -min_distance $PIN_GAP \
           -corner_avoidance $PIN_CORNER

#  ...but the TWO power ones have to be placed by hand, over their own Metal5
#  strap. `place_pins` treats them like any other signal and leaves them on the
#  die edge, on a Metal2/Metal3 pad that never touches the grid: they end up
#  FLOTANDO. No lo ve el DRC (un abierto no viola ninguna regla) ni
#  `check_connectivity.py` (which only looks at macro terminals, not the top
#  pins), and the router does not close them either, because it skips POWER/GROUND nets.
#
#  Where it does show is in LVS, and it was the last thing left on the top:
#  daba `Netlists match with 144 symmetries` con 880 nets y 1389 dispositivos
#  identical on each side, and it failed only on pin matching -- the power
#  real power came out unnamed (`w_1904_7964#` the well,
#  `a_2082_4860#` the substrate) and the `VDD` and `VSS` ports came out loose.
#
#  The pin goes onto the strap, not the strap onto the pin: the grid is already
#  y tocarla es rehacer el reparto entero.
proc strap_of {block pin_name layer} {
    set net [$block findNet $pin_name]
    if {$net eq "NULL" || $net eq ""} { return {} }
    foreach sw [$net getSWires] {
        foreach box [$sw getWires] {
            if {[$box isVia]} { continue }
            set l [$box getTechLayer]
            if {$l eq "NULL" || [$l getName] ne $layer} { continue }
            return [list [$box xMin] [$box yMin] [$box xMax] [$box yMax]]
        }
    }
    return {}
}

set dbu_pin [[ord::get_db_tech] getDbUnitsPerMicron]

#: Extends the strap to the LEFT edge of the die and returns the new box.
#:
#: Without this the Metal5 strap stops ~20 um from the edge and the pin lands
#: **inside** the die: a padframe connecting by abutment cannot reach. A port is
#: precisely what does have to touch the outline -- the rest of the
#: geometry keeps clear of it (see `decap_fill.BORDE_DIE` and
#: `fill_density.BORDE_DIE`).
proc extend_all_to_edge {block pin_name layer} {
    #  TODOS los straps de esa net, no el primero. Antes se estiraba uno solo y
    #  el pin salia un cuadrado de 3x3 um: 4.5 mA de capacidad contra los 31 que
    #  pide el bloque, un factor de casi siete. Cada strap que llega al borde
    #  suma su ancho, y son gratis -- Metal5 no la usa ninguna senal, el ruteo
    #  va por Metal2-Metal4.
    set net [$block findNet $pin_name]
    if {$net eq "NULL" || $net eq ""} { return {} }
    #  PRIMERO SE MIRA, LUEGO SE ESCRIBE. Creando la caja dentro del mismo
    #  `foreach` que recorre los hilos, el recorrido se encuentra lo que acaba
    #  de insertar y lo vuelve a estirar: VDD salia con 7 puertos de los que
    #  solo 3 eran distintos, y el informe sumaba los 7 -- 104.77 mA de
    #  capacidad de pin que no existian. Se anota, se sale del bucle, y
    #  entonces se dibuja.
    set quiero {}
    foreach sw [$net getSWires] {
        set aqui {}
        foreach box [$sw getWires] {
            if {[$box isVia]} { continue }
            set l [$box getTechLayer]
            if {$l eq "NULL" || [$l getName] ne $layer} { continue }
            #  Horizontal y con algo de recorrido: un trozo vertical o un
            #  cuadradito de conexion no sirve de puerto.
            if {[expr {[$box xMax] - [$box xMin]}] <= [expr {[$box yMax] - [$box yMin]}]} { continue }
            #  Y uno por carril: si un carril ya trajo su strap partido en
            #  varios trozos, todos darian el mismo puerto.
            set clave [list [$box yMin] [$box yMax]]
            if {[lsearch -exact $aqui $clave] >= 0} { continue }
            lappend aqui $clave
            lappend quiero [list $sw $l [$box yMin] [$box xMax] [$box yMax]]
        }
    }
    set cajas {}
    foreach q $quiero {
        lassign $q sw l y0 x1 y1
        odb::dbSBox_create $sw $l 0 $y0 $x1 $y1 "STRIPE"
        lappend cajas [list 0 $y0 $x1 $y1]
    }
    return $cajas
}

#: mA por um de ancho, DC, del tech-LEF del PDK (DCCURRENTDENSITY AVERAGE).
set DC_M5 1.5

set m5 [[ord::get_db_tech] findLayer Metal5]
foreach pin_name {VDD VSS} {
    set cajas [extend_all_to_edge $block $pin_name Metal5]
    if {[llength $cajas] == 0} {
        puts "  WARNING: $pin_name has no Metal5 strap; the pin stays where it was"
        continue
    }
    set net [$block findNet $pin_name]
    set bt  [$block findBTerm $pin_name]
    if {$bt eq "NULL" || $bt eq ""} { set bt [odb::dbBTerm_create $net $pin_name] }
    #  Fuera los puertos que hubiera: se redibujan todos.
    foreach bp [$bt getBPins] { odb::dbBPin_destroy $bp }

    set ancho_total 0.0
    foreach caja $cajas {
        lassign $caja x0 y0 x1 y1
        set bp [odb::dbBPin_create $bt]
        odb::dbBox_create $bp $m5 $x0 $y0 [expr {$x0 + int($STRIPE_W * $dbu_pin)}] $y1
        $bp setPlacementStatus PLACED
        set ancho_total [expr {$ancho_total + ($y1 - $y0) / double($dbu_pin)}]
    }
    #  Y declarados como lo que son. `place_pins` los deja `USE SIGNAL`, y el
    #  integrador del padframe distingue las alimentaciones por ahi.
    $bt setSigType [expr {$pin_name eq "VDD" ? "POWER" : "GROUND"}]

    set cap [expr {$ancho_total * $DC_M5}]
    puts [format "  pin %-3s  %2d puertos de Metal5 en el borde, %6.2f um en total\
 -> %6.2f mA  (pide %.1f)  %s" \
              $pin_name [llength $cajas] $ancho_total $cap $I_OBJ \
              [expr {$cap >= $I_OBJ ? "OK" : "CORTO"}]]
}

# --- output ------------------------------------------------------------------
file mkdir out
write_def $OUT/$TOPCELL.def

puts "--------------------------------------------------------------"
puts [format "Die       %.2f x %.2f um   (budget %.0f)" $die_w $die_h $BUDGET]
puts [format "Area      %.0f um2   aspect %.3f" \
          [expr {$die_w * $die_h}] [expr {max($die_w,$die_h)/min($die_w,$die_h)}]]
puts [format "Shelves   %d" $nshelf]
foreach s $shelves {
    puts [format "   tall %5.2f um : %s" [lindex $s 0] \
              [join [lmap m [lindex $s 1] {lindex $m 0}] " "]]
}
report_design_area
puts "DEF written to $OUT/$TOPCELL.def"
puts "--------------------------------------------------------------"
