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
    global MIM_CLEAR
    set out {}
    foreach box [$master getObstructions] {
        if {[[$box getTechLayer] getName] ne "Metal4"} { continue }
        lappend out [list [expr {$dx + [$box xMin] / double($dbu) - $MIM_CLEAR}] \
                          [expr {$dx + [$box xMax] / double($dbu) + $MIM_CLEAR}]]
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
set hlanes  {}
set y $VGAP
lappend hlanes [expr {$VGAP / 2.0}]
foreach s $shelves {
    lassign $s sh smembers
    foreach mem $smembers {
        lassign $mem name x w
        set mname0 [[[$block findInst $name] getMaster] getName]
        lassign [expr {[dict exists $ORIGENES $mname0] ?
                       [dict get $ORIGENES $mname0] : [list 0.0 0.0]}] mox moy
        place_macro -macro_name $name -orientation R0 \
            -location [list [ontrack_org [expr {$org_x + $x}] $mox] \
                            [ontrack_org [expr {$org_y + $y}] $moy]]
        set mn [[[$block findInst $name] getMaster] getName]
        dict set masters $mn 1
        dict set inst_of $mn $name
    }
    set y [expr {$y + $sh + $VGAP}]
    lappend hlanes [expr {$y - $VGAP / 2.0}]
}

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

set PAIR  [expr {$STRIPE_W}]
set need  [expr {2 * $STRIPE_W + $PAIR}]

#  Metal5 (horizontal) stays in the channels between shelves: it only has to
#  meet Metal4, and above a macro it would land on the MIM plates.
#  `hlanes` viene de la colocacion, un carril por canal.
set extent [expr {2 * $STRIPE_W + $PAIR}]
foreach c $hlanes {
    set off [mfg [expr {$c - $extent / 2.0}]]
    if {$off < 0 || $off + $extent > $real_h} { continue }
    add_pdn_stripe -grid core -layer Metal5 -width $STRIPE_W -spacing $STRIPE_W \
                   -pitch [expr {2 * $real_h}] -offset $off
}
add_pdn_connect -grid core -layers {Metal4 Metal5}

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
set seen {}
foreach inst [$block getInsts] {
    if {![[$inst getMaster] isBlock]} { continue }
    set m  [$inst getMaster]
    set ix [expr {[[$inst getBBox] xMin] / double($dbu)}]
    set iw [expr {[$m getWidth] / double($dbu)}]
    foreach band [free_bands [blocked_x $m $dbu $ix] $ix [expr {$ix + $iw}]] {
        lassign $band lo hi
        if {$hi - $lo < $need} { continue }
        set off [mfg [expr {$lo - $core_x0 + ($hi - $lo - $need) / 2.0}]]
        if {$off < 0 || $off + $need > $real_w} { continue }
        if {[lsearch -exact $seen $off] >= 0} { continue }
        lappend seen $off
        add_pdn_stripe -grid core -layer Metal4 -width $STRIPE_W -spacing $PAIR \
                       -pitch [expr {2 * $real_w}] -offset $off
        incr nstripe
    }
}

#  And the macro grid, which is what ties each block: Metal3 (the bar the block
#  exposes over its rail) against Metal4 (the straps above).
define_pdn_grid -macro -name macro -cells [lsort [dict keys $masters]] -halo {0 0}
add_pdn_connect -grid macro -layers {Metal3 Metal4}

pdngen

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
    set bb [$inst getBBox]
    set ox [$bb xMin] ; set oy [$bb yMin]
    set halo [expr {round($MIM_CLEAR * $dbu)}]
    foreach box [[$inst getMaster] getObstructions] {
        if {[[$box getTechLayer] getName] ne "Metal4"} { continue }
        odb::dbObstruction_create $block [$box getTechLayer] \
            [expr {$ox + [$box xMin] - $halo}] [expr {$oy + [$box yMin] - $halo}] \
            [expr {$ox + [$box xMax] + $halo}] [expr {$oy + [$box yMax] + $halo}]
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
proc extend_to_edge {block pin_name layer} {
    set net [$block findNet $pin_name]
    if {$net eq "NULL" || $net eq ""} { return {} }
    foreach sw [$net getSWires] {
        foreach box [$sw getWires] {
            if {[$box isVia]} { continue }
            set l [$box getTechLayer]
            if {$l eq "NULL" || [$l getName] ne $layer} { continue }
            odb::dbSBox_create $sw $l 0 [$box yMin] [$box xMax] [$box yMax] "STRIPE"
            return [list 0 [$box yMin] [$box xMax] [$box yMax]]
        }
    }
    return {}
}

foreach pin_name {VDD VSS} {
    set box [extend_to_edge $block $pin_name Metal5]
    if {[llength $box] != 4} {
        puts "  WARNING: $pin_name has no Metal5 strap; the pin stays where it was"
        continue
    }
    lassign $box x0 y0 x1 y1
    set tall  [expr {($y1 - $y0) / double($dbu_pin)}]
    set wide $tall
    #  Flush with the left die edge, over the already extended strap.
    set cx [expr {$wide / 2.0}]
    set cy [expr {(($y0 + $y1) / 2.0) / $dbu_pin}]
    place_pin -pin_name $pin_name -layer Metal5 \
              -location [list $cx $cy] -pin_size [list $wide $tall]
    #  And declared as what they are. `place_pins` leaves them `USE SIGNAL`, and
    #  the padframe integrator tells the supplies apart by that.
    set bt [$block findBTerm $pin_name]
    if {$bt ne "NULL" && $bt ne ""} {
        $bt setSigType [expr {$pin_name eq "VDD" ? "POWER" : "GROUND"}]
    }
    puts [format "  pin %s on the die edge, over its Metal5 strap: (%.3f, %.3f), %.3f x %.3f" \
              $pin_name $cx $cy $wide $tall]
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
