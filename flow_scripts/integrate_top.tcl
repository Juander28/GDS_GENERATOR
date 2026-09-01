# -----------------------------------------------------------------------------
#  Fills the padring's user area: our block, the routing to the 73 pins, and the
#  programming of the six digital pads.
#
#      openroad -no_init -exit scripts/integrate_top.tcl
#
#  `padframe/B26_A.def` is 1110 x 1110 um with 73 pins on its west and north
#  edges and NO COMPONENTS, and `B26_A_padring.v` does not instantiate our block
#  either. So this area is ours to fill, and that is what this writes.
#
#  Nothing here is typed by hand. `scripts/integrate_padframe.py` derives the
#  Verilog, the pin boxes and the macro origin from the organisers' own files
#  and from info.yaml, and writes them into verilog/B26_A.v and
#  constraints/B26_A_pins.tcl. Change the pad programming in the PROGRAMMING
#  table of that script and everything below follows.
# -----------------------------------------------------------------------------

set CELL   B26_A
set MACRO  GRADIENT_NAV2
set OUT    out_integration
file mkdir $OUT

read_lef lef/techlef_patched.tlef
read_lef lef/vias.lef
read_lef lef/$MACRO.lef
#  El ESD secundario es un macro mas, y va AQUI y no dentro del bloque: la red
#  tiene que estar junto al pad, porque lo que quede por delante de la sujecion
#  no lo protege nada. Es la celda de los organizadores tal cual.
read_lef lef/ESD_CDM.lef

read_verilog verilog/$CELL.v
link_design $CELL

source constraints/${CELL}_pins.tcl

lassign $MACRO_ORIGIN ox oy
lassign $MACRO_SIZE   mw mh

#  The die is the user area, exactly. The core is the die minus the channel the
#  block keeps from the edges, which is where the routing to the pads goes.
set SIDE   1110.0
set MARGIN 5.0
initialize_floorplan \
    -die_area  "0 0 $SIDE $SIDE" \
    -core_area "$MARGIN $MARGIN [expr {$SIDE - $MARGIN}] [expr {$SIDE - $MARGIN}]" \
    -site      GF018hv5v_green_sc9

foreach layer {Metal1 Metal2 Metal3 Metal4} {
    make_tracks $layer -x_offset 0.28 -x_pitch 0.56 -y_offset 0.28 -y_pitch 0.56
}
make_tracks Metal5 -x_offset 0.45 -x_pitch 0.90 -y_offset 0.45 -y_pitch 0.90

#  `initialize_floorplan` snaps the core to the site grid and can shrink it by
#  up to one site per side, so the origin asked for lands just outside and
#  `MPL-0034` aborts. The core is read back and the origin clamped into it, and
#  then put on the 0.56 um routing grid: the macro's own landing pads are
#  already on-track inside the block, and that alignment is lost if it does not
#  land on a multiple.
#  The site is 0.56 x 5.04 um and 5.04 is exactly nine routing pitches, so a
#  ROW boundary is always on the routing grid too. Snapping the origin to a row
#  therefore satisfies both at once; snapping only to the pitch does not, and
#  `place_macro` then moves it to the nearest row and takes the alignment with
#  it -- measured, 3 of the macro's 17 pins ended up on-track instead of all.
proc onrow {v origin pitch} {
    return [expr {$origin + round(($v - $origin) / $pitch) * $pitch}]
}
set blk   [ord::get_db_block]
set dbu   [[ord::get_db_tech] getDbUnitsPerMicron]
set core  [$blk getCoreArea]
set cx0   [expr {[$core xMin] / double($dbu)}]
set cy0   [expr {[$core yMin] / double($dbu)}]
set row [[lindex [$blk getRows] 0] getSite]
set rw  [expr {[$row getWidth]  / double($dbu)}]
set rh  [expr {[$row getHeight] / double($dbu)}]
set ox [onrow [expr {max($ox, $cx0)}] $cx0 $rw]
set oy [onrow [expr {max($oy, $cy0)}] $cy0 $rh]
puts [format "  site %.2f x %.2f um; origin snapped to a row at (%.3f, %.3f)" \
          $rw $rh $ox $oy]

#  `place_macro` places the CELL ORIGIN, and magic writes a non-zero ORIGIN into
#  the LEF, so the bounding box comes out shifted by it: asked for y=559.440 and
#  the block landed at 559.605, which is 0.165 off the row and takes the macro's
#  pins off the routing grid with it. The offset is read from the master and
#  subtracted, so what lands on the row is the OUTLINE.
set mst [[$blk findInst x_core] getMaster]
lassign [$mst getOrigin] gxi gyi
set gx  [expr {$gxi / double($dbu)}]
set gy  [expr {$gyi / double($dbu)}]
if {$gx != 0 || $gy != 0} {
    puts [format "  LEF ORIGIN (%.3f, %.3f) compensated" $gx $gy]
}
place_macro -macro_name x_core -orientation R0 \
            -location [list [expr {$ox - $gx}] [expr {$oy - $gy}]]
puts [format "  %s at (%.1f, %.1f), %.2f x %.2f um inside %.0f x %.0f" \
          $MACRO $ox $oy $mw $mh $SIDE $SIDE]

# --- los clamps de ESD secundario, uno por pad analogico ---------------------
#  Sus sitios los calcula `integrate_padframe.py` a partir de la posicion de
#  cada pad en el DEF del anillo; aqui solo se colocan. Como con el nucleo, se
#  compensa el ORIGIN del LEF y se lleva la esquina a una fila, que es lo que
#  mantiene los pines del macro sobre la rejilla de ruteo.
if {[info exists ESD_PINS]} {
    set nesd 0
    foreach s $ESD_PINS {
        set inst x_esd_$s
        if {[$blk findInst $inst] eq "NULL"} {
            puts "  AVISO: $inst no esta en el verilog; me lo salto"
            continue
        }
        lassign $ESD($s) ex ey
        set em [[$blk findInst $inst] getMaster]
        lassign [$em getOrigin] exi eyi
        set egx [expr {$exi / double($dbu)}]
        set egy [expr {$eyi / double($dbu)}]
        set exs [onrow [expr {max($ex, $cx0)}] $cx0 $rw]
        set eys [onrow [expr {max($ey, $cy0)}] $cy0 $rh]
        place_macro -macro_name $inst -orientation R0 \
                    -location [list [expr {$exs - $egx}] [expr {$eys - $egy}]]
        incr nesd
    }
    puts "  $nesd clamps de ESD secundario colocados junto a su pad"
}

# --- the pins ----------------------------------------------------------------
#  NOT `place_pin`. That snaps to the routing track and to the manufacturing
#  grid, and it moved pins by up to 0.63 um -- measured, `PPL-0070` says so for
#  each one. These pins have to sit EXACTLY where the padring put them or they
#  do not abut the pads, so the boxes are written straight into the database.
#
#  The padring DEF counts 200 dbu per micron and this block counts what the tech
#  LEF says, so the boxes are scaled rather than copied.
set PAD_DBU 200.0
set ESC [expr {$dbu / $PAD_DBU}]
set tech [ord::get_db_tech]
set n 0
foreach p $PIN_ORDER {
    set bt [$blk findBTerm $p]
    if {$bt eq "NULL" || $bt eq ""} { error "no BTerm for pin $p" }
    foreach bp [$bt getBPins] { odb::dbBPin_destroy $bp }
    set bp [odb::dbBPin_create $bt]
    foreach r $PIN($p) {
        lassign $r layer x0 y0 x1 y1
        odb::dbBox_create $bp [$tech findLayer $layer] \
            [expr {int(round($x0 * $ESC))}] [expr {int(round($y0 * $ESC))}] \
            [expr {int(round($x1 * $ESC))}] [expr {int(round($y1 * $ESC))}]
        incr n
    }
    $bp setPlacementStatus FIRM
}
puts "  $n pins written at the padring's own coordinates, unsnapped"

#  And check it, because a pin that is 0.02 um off looks right in every viewer
#  and does not connect.
set malos 0
foreach p $PIN_ORDER {
    set esperado {}
    foreach r $PIN($p) {
        lassign $r layer x0 y0 x1 y1
        lappend esperado [list [expr {int(round($x0*$ESC))}] [expr {int(round($y0*$ESC))}] \
                               [expr {int(round($x1*$ESC))}] [expr {int(round($y1*$ESC))}]]
    }
    set visto {}
    foreach bp [[$blk findBTerm $p] getBPins] {
        foreach b [$bp getBoxes] {
            lappend visto [list [$b xMin] [$b yMin] [$b xMax] [$b yMax]]
        }
    }
    foreach e $esperado {
        if {[lsearch -exact $visto $e] < 0} {
            puts "    $p: box $e is not in the design"
            incr malos
        }
    }
}
if {$malos} { error "$malos pins are not where the padring put them" }
puts "  verified: every pin box matches padframe/B26_A.def exactly"


# --- the power buses and the 48 tie-offs --------------------------------------
#  The 48 control pins of the six digital pads are inputs the padring expects
#  the core to supply, and the PROGRAMMING table of integrate_padframe.py says
#  what each one is: OE to VDD, the other seven to VSS. Here that becomes metal.
#
#  ONE BUS PER SUPPLY, per edge, because the pins alternate between the two: a
#  stub going to the far bus simply CROSSES the near one, Metal2 over Metal4,
#  and only drops a via at its own. No detour, no divergence.
#
#  HOW WIDE THE RING HAS TO BE. Not a guess: the block draws 14.81 mA at 5 V,
#  measured on the RC-extracted layout, and the PDK's maximum line current
#  density (Integration README, from the design manual) is
#
#      Metal1..Metal4  unidirectional   2.09 / 1.00 / 0.67 mA/um at 85/110/125 C
#      Via 0.26 um     unidirectional   0.58 / 0.28 / 0.18 mA per cut
#
#  so 14.81 mA needs 7.1 um at 85 C, 14.8 at 110 and 22.1 at 125. It started at
#  2.5 um, which carries 5.2 mA at 85 C -- short by a factor of three at the
#  most generous temperature there is. That is electromigration, not style.
#
#  Sized for 125 C, the column that assumes nothing about where this runs. It
#  costs nothing here: the area is 1110 um across and the block is 418.
set BUS_W    24.0     ;# 22.1 um needed at 125 C, plus margin
set VSS_OFF  2.0      ;# from the edge to the outer ring
set VDD_OFF  28.0     ;# ... and to the inner one, 2 um of clearance between
set VIA_P    0.90     ;# via pitch of the arrays; 82 cuts are needed at 125 C
set PAD_V    0.44     ;# via landing pad
set VIA_S    0.26     ;# the cut
set SIDE_UM  1110.0
#  The two via columns for the tie-offs. They are staggered because the control
#  pins come at a 0.73 um pitch and a 0.44 um pad at that pitch leaves 0.29 um
#  against M2.2a's 0.28 -- one hundredth is not a margin. With a 24 um bus there
#  is room to space them properly.
set COL_A    3.0
set COL_B    6.0

proc um {v} { return [expr {int(round($v * 2000))}] }

set L(m2) [$tech findLayer Metal2]
set L(m3) [$tech findLayer Metal3]
set L(m4) [$tech findLayer Metal4]
set L(v2) [$tech findLayer Via2]
set L(v3) [$tech findLayer Via3]
set L(m5) [$tech findLayer Metal5]
set L(v4) [$tech findLayer Via4]

proc caja {net layer x0 y0 x1 y1} {
    set sw [odb::dbSWire_create $net "ROUTED"]
    odb::dbSBox_create $sw $layer [um $x0] [um $y0] [um $x1] [um $y1] "STRIPE"
}

#  A VIA INSTANCE, not a rectangle on the cut layer. This is what cost the
#  connectivity: `gf180mcu.map`, which `def_to_gds.py` hands to KLayout, gives
#  the metals the purposes NET,SPNET,PIN,VIA but gives the via layers only VIA
#  -- meaning geometry that arrives as a via INSTANCE. Cuts drawn as loose
#  rectangles on Via2/Via3/Via4 simply never reached the GDS, so the buses and
#  the stubs were all drawn and NOTHING was connected vertically. And nothing
#  complained: DRC had no cuts to find fault with.
#
#  `lef/vias.lef` already defines the four square vias this flow uses.
proc via {net nombre x y} {
    global blk tech
    #  A LEF `VIA ... DEFAULT` lands in the TECH, not in the block.
    set v [$tech findVia $nombre]
    if {$v eq "NULL" || $v eq ""} { set v [$blk findVia $nombre] }
    if {$v eq "NULL" || $v eq ""} { error "via $nombre is not defined" }
    set sw [odb::dbSWire_create $net "ROUTED"]
    odb::dbSBox_create $sw $v [um $x] [um $y] "STRIPE"
}

#  A grid of vias covering a rectangle. The supply paths need 82 cuts at 125 C
#  and a corner of 24 x 24 um at a 0.9 um pitch gives hundreds, so the count
#  stops being the thing to worry about.
#  EVERY array lands on ONE global lattice, k * VIA_P from the origin, and not
#  on a lattice of its own starting at its own corner. Two arrays that overlap
#  with different origins interleave: the corner array and the supply-pin grid
#  ended up 0.14 um apart in y and 546 Via3 cuts MERGED into 0.26 x 0.40, which
#  breaks V3.1's "min/max via size is 0.26".
#
#  `evitar` is a list of coordinates a tie-off already put a via on: a north
#  tie-off drops its via inside the corner array's own rectangle, and two cuts
#  0.257 um apart break V4.2a.
#  MARGIN. The cut is 0.26 but the via carries its own metal: 0.4 across for
#  Via2_SQ/Via3_SQ and 0.6 for Via4_SQ. Placing by the centre alone put the top
#  row's Metal5 0.1 um PROUD of the ring, and the 0.3 um gaps between those
#  fingers broke MT.2a 125 times. Half of the widest enclosure, plus a little.
proc matriz {net nombre x0 y0 x1 y1 {evitar {}} {marg 0.35}} {
    global VIA_P
    set x0 [expr {$x0 + $marg}] ; set x1 [expr {$x1 - $marg}]
    set y0 [expr {$y0 + $marg}] ; set y1 [expr {$y1 - $marg}]
    set n 0
    for {set i [expr {int(ceil($x0 / $VIA_P))}]} {$i * $VIA_P <= $x1} {incr i} {
        set x [expr {$i * $VIA_P}]
        set salta 0
        foreach e $evitar { if {abs($x - $e) < 1.2} { set salta 1 ; break } }
        if {$salta} { continue }
        for {set j [expr {int(ceil($y0 / $VIA_P))}]} {$j * $VIA_P <= $y1} {incr j} {
            via $net $nombre $x [expr {$j * $VIA_P}] ; incr n
        }
    }
    return $n
}

#  A stack from Metal2 up to `hasta`. The tie-offs on the west edge climb to the
#  Metal4 side ring; on the north edge they climb to their own horizontal ring,
#  which is Metal3 for VSS and Metal5 for VDD.
proc pila {net x y {hasta m4}} {
    global L PAD_V
    set h [expr {$PAD_V / 2.0}]
    set orden {m2 m3 m4 m5}
    set n [lsearch -exact $orden $hasta]
    foreach lay [lrange $orden 0 $n] {
        caja $net $L($lay) [expr {$x-$h}] [expr {$y-$h}] [expr {$x+$h}] [expr {$y+$h}]
    }
    foreach v [lrange {Via2_SQ Via3_SQ Via4_SQ} 0 [expr {$n - 1}]] {
        via $net $v $x $y
    }
}

set nVDD [$blk findNet VDD]
set nVSS [$blk findNet VSS]
if {$nVDD eq "NULL" || $nVSS eq "NULL"} { error "no VDD/VSS net in the design" }
#  Marked SPECIAL, or the bus geometry never reaches the DEF: `dbSWire` is only
#  written out for a net that says it is one, and the file came out with 25 nets
#  and not a single rectangle -- silently.
$nVDD setSpecial ; $nVDD setSigType POWER
$nVSS setSpecial ; $nVSS setSigType GROUND

#  A CLOSED RING PER SUPPLY, and the two are separated BY LAYER, not just by
#  position. That is what makes the wide ring possible at all.
#
#  With both rings on the same pair of layers, a tie-off's via stack lands a
#  Metal3 and a Metal4 pad, and at 24 um wide the horizontal rings reach y=1108
#  while the west pins reach y=1076.6 -- so a stack for one supply lands inside
#  the other's ring and shorts them. Measured: it did, and both nets came out
#  with the same 50 pins.
#
#      VSS   vertical Metal4 (west, east)   horizontal METAL3 (north, south)
#      VDD   vertical Metal4 (west, east)   horizontal METAL5 (north, south)
#
#  Now a west stack (Metal2-3-4) can never meet a horizontal ring of the other
#  supply: VSS's is Metal3, but it sits at a y no VDD west pin reaches, and
#  VDD's is Metal5, which no west stack touches. And a north stack reaches only
#  as high as its own ring needs. No guard, no skipped tie-off.
#
#  Metal5 carries this comfortably: 1.5 mA/um at 125 C over 24 um is 36 mA
#  against the 14.81 that flow.
foreach {net off cap} [list $nVSS $VSS_OFF m3 $nVDD $VDD_OFF m5] {
    set a $off ; set b [expr {$off + $BUS_W}]
    set c [expr {$SIDE_UM - $b}] ; set d [expr {$SIDE_UM - $a}]
    caja $net $L(m4)    $a 0.0 $b $SIDE_UM        ;# west
    caja $net $L(m4)    $c 0.0 $d $SIDE_UM        ;# east
    caja $net $L($cap) 0.0 $c $SIDE_UM $d         ;# north
    caja $net $L($cap) 0.0 $a $SIDE_UM $b         ;# south
}
puts "  a closed ring per supply: Metal4 on the sides, Metal3 for VSS and Metal5 for VDD across"

#  --- the 48 tie-offs ---------------------------------------------------------
#  Sorted along the edge so the via column alternates between neighbours: at a
#  0.73 um pitch two 0.44 um pads at the same x would leave 0.29 um against
#  M2.2a's 0.28, and one hundredth of a micron is not a margin.
set oeste {} ; set norte {}
foreach p $TIEOFFS {
    lassign [lindex $PIN($p) 0] layer x0 y0 x1 y1
    if {$x0 == 0} {
        lappend oeste [list [expr {($y0+$y1)/2.0/$PAD_DBU}] $p]
    } else {
        lappend norte [list [expr {($x0+$x1)/2.0/$PAD_DBU}] $p]
    }
}
set oeste [lsort -real -index 0 $oeste]
set norte [lsort -real -index 0 $norte]

#  THE FOUR CORNERS. Metal4 against Metal3 is a via3; against Metal5 it is a
#  via3 and a via4 with a Metal4 pad in between -- which the ring already is.
#  where the north tie-offs put their own vias, so the corner arrays keep clear
set xnorte {}
foreach par $norte { lappend xnorte [lindex $par 0] }

set ncorner 0
foreach {net off nombre} [list $nVSS $VSS_OFF Via3_SQ $nVDD $VDD_OFF Via4_SQ] {
    set a $off ; set b [expr {$off + $BUS_W}]
    set c [expr {$SIDE_UM - $b}] ; set d [expr {$SIDE_UM - $a}]
    foreach {px qx} [list $a $b $c $d] {
        foreach {py qy} [list $a $b $c $d] {
            incr ncorner [matriz $net $nombre $px $py $qx $qy $xnorte]
        }
    }
}
puts "  four corners per supply, $ncorner cuts in all (82 needed at 125 C)"

set n 0
foreach lado {oeste norte} {
    set i 0
    foreach par [set $lado] {
        lassign $par pos p
        lassign [lindex $PIN($p) 0] layer x0 y0 x1 y1
        set net [expr {$RAIL($p) eq "VDD" ? $nVDD : $nVSS}]
        set off [expr {$RAIL($p) eq "VDD" ? $VDD_OFF : $VSS_OFF}]
        set col [expr {$i % 2 ? $COL_B : $COL_A}]
        if {$lado eq "oeste"} {
            set vx [expr {$off + $col}]
            #  the stub: Metal2 from the very edge to just past its via
            caja $net $L(m2) 0.0 [expr {$y0/$PAD_DBU}] [expr {$vx + $PAD_V/2.0}] \
                                 [expr {$y1/$PAD_DBU}]
            #  the side rings are Metal4 for both supplies, at different x
            pila $net $vx $pos m4
        } else {
            #  the horizontal rings are NOT the same layer: Metal3 for VSS and
            #  Metal5 for VDD, which is what keeps the two apart up here.
            set vy [expr {$SIDE_UM - $off - $col}]
            caja $net $L(m2) [expr {$x0/$PAD_DBU}] [expr {$vy - $PAD_V/2.0}] \
                             [expr {$x1/$PAD_DBU}] $SIDE_UM
            pila $net $pos $vy [expr {$net eq $nVSS ? "m3" : "m5"}]
        }
        incr i ; incr n
    }
}
puts "  $n tie-offs wired to their bus, vias staggered in two columns"

#  --- the two supply pins of the user area ------------------------------------
#  VSS comes in on the west edge and VDD on the north, and each has to reach its
#  own bus. Their pads are 9.5 um tall, so these get a COLUMN of via stacks
#  rather than the single one the tie-offs use: this is the current path of the
#  whole block, not a gate held at a rail.
foreach {p net off} [list VSS $nVSS $VSS_OFF VDD $nVDD $VDD_OFF] {
    #  a supply pad is a comb of six rectangles; what is wanted is its extent
    set layer "" ; set x0 "" ; set y0 "" ; set x1 "" ; set y1 ""
    foreach r $PIN($p) {
        lassign $r l a b c d
        set layer $l
        if {$x0 eq "" || $a < $x0} { set x0 $a }
        if {$y0 eq "" || $b < $y0} { set y0 $b }
        if {$x1 eq "" || $c > $x1} { set x1 $c }
        if {$y1 eq "" || $d > $y1} { set y1 $d }
    }
    set a [expr {$x0/$PAD_DBU}] ; set b [expr {$y0/$PAD_DBU}]
    set c [expr {$x1/$PAD_DBU}] ; set d [expr {$y1/$PAD_DBU}]
    if {$x0 == 0} {
        caja $net $L(m2) 0.0 $b [expr {$off + $BUS_W}] $d
        #  A GRID, not a column: 82 cuts are needed at 125 C and a single column
        #  down a 9.5 um pad gives ten. The pad's whole height by the whole bus
        #  width gives hundreds. The rows that fall inside the other supply's
        #  ring are skipped, which is why `libre` exists.
        #  One sheet of Metal3 over the overlap and two via arrays on it, rather
        #  than a landing pad per cut: fewer shapes and, more to the point, both
        #  arrays on the global lattice.
        caja $net $L(m3) $off $b [expr {$off + $BUS_W}] $d
        set puestas [matriz $net Via2_SQ $off $b [expr {$off + $BUS_W}] $d]
        incr puestas [matriz $net Via3_SQ $off $b [expr {$off + $BUS_W}] $d]
    } else {
        caja $net $L(m2) $a [expr {$SIDE_UM - $off - $BUS_W}] $c $SIDE_UM
        set lo [expr {$SIDE_UM - $off - $BUS_W}] ; set hi [expr {$SIDE_UM - $off}]
        caja $net $L(m3) $a $lo $c $hi
        set puestas [matriz $net Via2_SQ $a $lo $c $hi]
        incr puestas [matriz $net Via3_SQ $a $lo $c $hi]
        if {$net ne $nVSS} {
            caja $net $L(m4) $a $lo $c $hi
            incr puestas [matriz $net Via4_SQ $a $lo $c $hi]
        }
    }
    puts "  supply pin $p tied to its bus with $puestas via stacks"
}

#  --- the block's own supplies ------------------------------------------------
#  In the abstract these two are a 3 x 3 um METAL5 pad on the block's west edge,
#  sitting over the Metal5 strap of its internal grid -- that is what
#  `floorplan_top.tcl` puts there and what `macro_lef.py` copies out of the
#  routed DEF. The buses here are Metal4, so each pad gets a Metal5 run west to
#  over its bus and a via4 down.
set inst [$blk findInst x_core]
lassign [$inst getLocation] ix iy
foreach {p net off} [list VSS $nVSS $VSS_OFF VDD $nVDD $VDD_OFF] {
    set it [$inst findITerm $p]
    if {$it eq "NULL" || $it eq ""} { error "the macro has no $p terminal" }
    set best {}
    foreach mp [[$it getMTerm] getMPins] {
        foreach b [$mp getGeometry] {
            if {[[$b getTechLayer] getName] ne "Metal5"} { continue }
            set box [list [expr {[$b xMin]+$ix}] [expr {[$b yMin]+$iy}] \
                          [expr {[$b xMax]+$ix}] [expr {[$b yMax]+$iy}]]
            if {$best eq "" || [lindex $box 0] < [lindex $best 0]} { set best $box }
        }
    }
    if {$best eq ""} { error "the macro has no Metal5 pad for $p" }
    lassign $best bx0 by0 bx1 by1
    set px0 [expr {$bx0/double($dbu)}] ; set py0 [expr {$by0/double($dbu)}]
    set px1 [expr {$bx1/double($dbu)}] ; set py1 [expr {$by1/double($dbu)}]
    set cy  [expr {($py0 + $py1)/2.0}]
    #  The run has to start LEFT OF THE FIRST VIA, not at the middle of the bus:
    #  the via4 column begins at off+0.7 and the run began at off+1.25, so the
    #  first via's Metal5 pad was left orphaned -- 0.36 um2 against MT.4's
    #  0.5625, and 0.25 um from the run against MT.2a's 0.38.
    set bx  [expr {$off + 0.35}]
    caja $net $L(m5) $bx $py0 $px1 $py1
    #  Metal4 under the whole run, and via4 everywhere it overlaps the bus.
    caja $net $L(m4) [expr {$off + 0.2}] $py0 [expr {$off + $BUS_W - 0.2}] $py1
    set nv [matriz $net Via4_SQ [expr {$off + 0.2}] $py0 \
                   [expr {$off + $BUS_W - 0.2}] $py1]
    puts [format "  block %s: Metal5 pad %.2f um tall, %d via4 to the bus" \
              $p [expr {$py1 - $py0}] $nv]
}

# --- alimentacion de los clamps de ESD ---------------------------------------
#  SIN ESTO LOS ONCE CLAMPS QUEDAN SIN ALIMENTAR, y un ESD secundario sin VDD ni
#  VSS no sujeta nada: sus diodos no tienen a donde descargar. No lo dice el DRC
#  -- la geometria esta perfectamente dibujada -- y el ruteo de senal tampoco,
#  porque VDD y VSS son nets `special` y el router no las toca.
#
#  Lo canto el LVS de `B26_A`, y de una forma que hay que saber leer: doce nets
#  del layout con `diode_pd2nw/cathode` y `ppolyf_u/3` --el catodo del diodo y el
#  BULK de la resistencia, o sea el pozo-- que no emparejaban con nada. Ese pozo
#  tendria que estar en VDD; flotando, sale como net propia.
#
#  Cada clamp saca VDD y VSS en un pad de METAL3 (se lo pone `esd_jacket.py`),
#  asi que la conexion se hace en metal3 hasta el anillo que le toca:
#
#    los cinco del OESTE  VSS -> metal3 al oeste + via3 al Metal4 de x[2,26]
#                         VDD -> metal3 al oeste + via3 al Metal4 de x[28,52]
#    los seis del NORTE   VSS -> metal3 al norte, que ES metal3 en y[1084,1108]
#                         VDD -> metal3 al norte + pila hasta el Metal5 de y[1058,1082]
#
#  Los cruces no cortocircuitan porque los dos anillos van en capas distintas
#  donde se cruzan: el metal3 de VDD pasa por encima del Metal4 de VSS y por
#  debajo del Metal5 de VDD sin tocarlos.
proc pad_m3 {inst term ix iy dbu} {
    set it [$inst findITerm $term]
    if {$it eq "NULL" || $it eq ""} { return {} }
    foreach mp [[$it getMTerm] getMPins] {
        foreach b [$mp getGeometry] {
            if {[[$b getTechLayer] getName] ne "Metal3"} { continue }
            return [list [expr {([$b xMin]+$ix)/double($dbu)}] \
                         [expr {([$b yMin]+$iy)/double($dbu)}] \
                         [expr {([$b xMax]+$ix)/double($dbu)}] \
                         [expr {([$b yMax]+$iy)/double($dbu)}]]
        }
    }
    return {}
}

if {[info exists ESD_PINS]} {
    set nlig 0
    foreach s $ESD_PINS {
        set inst [$blk findInst x_esd_$s]
        if {$inst eq "NULL"} { continue }
        lassign [$inst getLocation] ix iy
        set norte [expr {[lindex $ESD($s) 1] > $SIDE_UM / 2.0}]
        foreach {term net off} [list VSS $nVSS $VSS_OFF VDD $nVDD $VDD_OFF] {
            set b [pad_m3 $inst $term $ix $iy $dbu]
            if {$b eq {}} {
                puts "  AVISO: x_esd_$s no expone $term en Metal3"
                continue
            }
            lassign $b px0 py0 px1 py1
            #  UNA COLUMNA ESTRECHA, no el pad entero. `ESD_CDM` saca sus rieles
            #  como BARRAS DE METAL3 A TODO LO ANCHO de la celda -- es el
            #  interfaz que exporta cualquier bloque nuestro -- y tomarlas
            #  enteras hacia el anillo dibuja dos planchas que comparten toda la
            #  x: VDD y VSS acaban en la misma net. Con la celda de los
            #  organizadores no pasaba porque sus pads son cuadrados sueltos.
            #
            #  Cada suministro coge ademas una columna DISTINTA, para que sus dos
            #  tramos no compartan ni la x.
            set anc [expr {$px1 - $px0}]
            if {$anc > 3.0} {
                #  0.8 de ancho y 1.8 entre centros: deja 1.0 um entre las dos
                #  columnas. Con 1.2 de ancho y 1.4 entre centros quedaban a
                #  0.20 y salian 7 `M4.2a`, que pide 0.28.
                set cxx [expr {$px0 + ($term eq "VDD" ? 1.0 : 2.8)}]
                set px0 [expr {$cxx - 0.4}]
                set px1 [expr {$cxx + 0.4}]
            }
            #  EL TRAMO VA EN METAL4, NO EN METAL3. El pad esta en metal3, pero
            #  el camino hasta el anillo cruza la celda entera -- el pad de VDD
            #  vive en el borde derecho y el anillo esta al oeste -- y en metal3
            #  pasa justo por encima de los pads `ASIG5V` y `to_gate` del propio
            #  clamp: los une, y con ellos unidos la resistencia en serie queda
            #  PUENTEADA. Medido: netgen paso de 894 nets a 883, once menos,
            #  exactamente las once `<PIN>_I` fundidas con su pad.
            #
            #  El clamp no tiene ni una forma en Metal4 ni en Metal5 (medido:
            #  metal3 4 formas, metal4 0, metal5 0), asi que por ahi se cruza sin
            #  tocar nada. Una via3 sobre el pad sube, y otra baja en el anillo.
            set cx [expr {($px0 + $px1) / 2.0}]
            set cy [expr {($py0 + $py1) / 2.0}]
            via $net Via3_SQ $cx $cy
            caja $net $L(m4) $px0 $py0 $px1 $py1
            if {$norte} {
                set ay [expr {$SIDE_UM - $off - $BUS_W / 2.0}]
                caja $net $L(m4) $px0 $py0 $px1 $ay
                if {$term eq "VDD"} {
                    via $net Via4_SQ $cx $ay          ;# Metal4 -> Metal5 del anillo
                    caja $net $L(m5) $px0 [expr {$ay - 0.6}] $px1 [expr {$ay + 0.6}]
                } else {
                    via $net Via3_SQ $cx $ay          ;# Metal4 -> Metal3 del anillo
                }
            } else {
                set ax [expr {$off + $BUS_W / 2.0}]
                if {$term eq "VSS"} {
                    #  VSS VA EN METAL3, NO EN METAL4. Su anillo esta en
                    #  x[2,26] y el de VDD en x[28,52], y LOS DOS son Metal4:
                    #  un tramo de VSS en Metal4 desde el clamp hasta su anillo
                    #  cruza por fuerza el de VDD y los une. Medido: VDD y VSS
                    #  salian como UNA sola net en el layout, y el sintoma en
                    #  netgen es `(no matching net) | Net: VDD` con la net de
                    #  VSS cargando ademas los 643 `pfet/4`.
                    #
                    #  En Metal3 el cruce es inocuo, y aqui se puede porque el
                    #  pad de VSS esta en el borde OESTE del clamp y el tramo se
                    #  va hacia afuera: no pasa por encima de la celda, que es lo
                    #  que puentearia su resistencia en serie.
                    caja $net $L(m3) $ax $py0 $px1 $py1
                    via $net Via3_SQ $ax $cy
                } else {
                    caja $net $L(m4) $ax $py0 $px1 $py1
                }
            }
            incr nlig
        }
    }
    puts "  $nlig conexiones de alimentacion a los clamps de ESD"
}

#  --- an escape for each signal pin -------------------------------------------
#  The router came out with five SHORTS, all of them at the west edge between a
#  signal and a neighbouring tie-off. The cause is geometric: the tie-off stubs
#  fill their pin's full height and run across the channel, and the signal pins
#  sit 0.35 um from them, so the router has nowhere to turn.
#
#  So every signal pin gets a straight escape of its own, drawn here as a SECOND
#  BOX on the same pin: parallel to all the others at the same 0.73 um pitch,
#  which clears M2.2a's 0.28 comfortably. The router then starts past the buses,
#  in open space. The pin's original box is untouched, so the check against the
#  padring still compares like with like.
#  The escape has to END ON A ROUTING TRACK. Ending at a round 10.0 um left the
#  router's wire meeting it slightly off and the join came out with a 0.07 um
#  notch -- one `Metal Spacing` on S4P, and the kind that no viewer shows.
proc pista {v} { return [expr {0.28 + round(($v - 0.28) / 0.56) * 0.56}] }
#  PAST BOTH BUSES, not just past the first. The tie-off stubs run in Metal2
#  from the edge all the way to their ring, so up to x = 52 the channel is a
#  comb of them at a 0.73 um pitch. A 0.84 um router wire does not fit between
#  two of those -- 7 `Metal Spacing` between VDD and the six digital outputs,
#  0.07 um apart. Past the buses the area is empty and the wire can be as wide
#  as it likes.
set ESCAPE_X [pista [expr {$VDD_OFF + $BUS_W + 4.0}]]
set ESCAPE_Y [pista [expr {$SIDE_UM - $VDD_OFF - $BUS_W - 4.0}]]
set n 0
#  A PLATE, OR A COMB. `MSLOT.1` forbids metal wider than 30 um in BOTH
#  directions without slotting it, and the escape is 54.7 um long by
#  construction -- it has to clear both buses. So on a pin whose own height is
#  also over 30 um the solid plate is a violation, and it was: the eleven
#  analogue pads are eight teeth spanning 44.32 um, and covering them with one
#  box gave a 55.7 x 44.3 um plate. Eleven of them, one per analogue pad, and
#  nothing in the flow saw it for weeks because the PDK's `mslot` table crashes
#  in split-table mode (see `drc_klayout.mslot1_local` and `docs/drc-full-deck`).
#
#  The narrow pins keep the plate -- a digital pin is 0.38 um tall and the rule
#  cannot touch it. The wide ones get a COMB instead: one finger per tooth,
#  2.54 um wide, plus a spine at the far end that ties the fingers together.
#
#  The comb is a strict SUBSET of the plate it replaces, so no spacing to
#  anything outside can get worse. What it adds are its own internal gaps, and
#  those are the pad's own 3.14 and 5.16 um -- ten times `M2.2a`.
#
#  The spine is what keeps this ONE polygon. Eight loose fingers would be eight
#  disjoint shapes carrying the same pin label, and the extractor would come out
#  with the net split eight ways; LVS would fail on geometry that conducts
#  perfectly well through the padring. It also gives the router a 44 um landing
#  edge instead of asking it to hit a 2.54 um finger.
#
#  Erosion checks out both ways: 15 um off each side vertically leaves nothing
#  of a 2.54 um finger, and what survives on the spine is 2 um wide, which the
#  horizontal erosion then takes.
set SPINE_W  2.0      ;# the rib that ties the fingers into one polygon
set PLATE_MAX 29.0    ;# over this, comb instead of plate. `MSLOT.1` is 30.
set ncomb 0
foreach p $SIGNALS {
    if {$p eq "VDD" || $p eq "VSS"} { continue }
    set lo {} ; set hi {} ; set a {} ; set b {}
    foreach r $PIN($p) {
        lassign $r layer x0 y0 x1 y1
        if {$lo eq "" || $y0 < $lo} { set lo $y0 }
        if {$hi eq "" || $y1 > $hi} { set hi $y1 }
        if {$a  eq "" || $x0 < $a}  { set a  $x0 }
        if {$b  eq "" || $x1 > $b}  { set b  $x1 }
    }
    lassign [lindex $PIN($p) 0] layer x0 y0 x1 y1
    set bt [$blk findBTerm $p]
    set bp [lindex [$bt getBPins] 0]
    if {$x0 == 0} {
        #  west edge: the escape runs in +x, so the pin's HEIGHT is what the
        #  rule measures across.
        set ancho [expr {($hi - $lo) / $PAD_DBU}]
        if {$ancho <= $PLATE_MAX} {
            odb::dbBox_create $bp $L(m2) [um [expr {$x1/$PAD_DBU}]] [um [expr {$lo/$PAD_DBU}]] \
                                         [um $ESCAPE_X]              [um [expr {$hi/$PAD_DBU}]]
        } else {
            foreach r $PIN($p) {
                lassign $r layer rx0 ry0 rx1 ry1
                odb::dbBox_create $bp $L(m2) [um [expr {$rx1/$PAD_DBU}]] [um [expr {$ry0/$PAD_DBU}]] \
                                             [um $ESCAPE_X]               [um [expr {$ry1/$PAD_DBU}]]
            }
            odb::dbBox_create $bp $L(m2) [um [expr {$ESCAPE_X - $SPINE_W}]] [um [expr {$lo/$PAD_DBU}]] \
                                         [um $ESCAPE_X]                     [um [expr {$hi/$PAD_DBU}]]
            incr ncomb
        }
    } else {
        #  north edge: the escape runs in -y, so the pin's WIDTH is the one
        #  measured across.
        set ancho [expr {($b - $a) / $PAD_DBU}]
        if {$ancho <= $PLATE_MAX} {
            odb::dbBox_create $bp $L(m2) [um [expr {$a/$PAD_DBU}]] [um $ESCAPE_Y] \
                                         [um [expr {$b/$PAD_DBU}]] [um [expr {$y0/$PAD_DBU}]]
        } else {
            foreach r $PIN($p) {
                lassign $r layer rx0 ry0 rx1 ry1
                odb::dbBox_create $bp $L(m2) [um [expr {$rx0/$PAD_DBU}]] [um $ESCAPE_Y] \
                                             [um [expr {$rx1/$PAD_DBU}]] [um [expr {$ry0/$PAD_DBU}]]
            }
            odb::dbBox_create $bp $L(m2) [um [expr {$a/$PAD_DBU}]] [um [expr {$ESCAPE_Y}]] \
                                         [um [expr {$b/$PAD_DBU}]] [um [expr {$ESCAPE_Y + $SPINE_W}]]
            incr ncomb
        }
    }
    incr n
}
puts "  $n signal pins given a straight escape past the buses ($ncomb as a comb, for MSLOT.1)"

# --- routing the 17 signals --------------------------------------------------
#  Only Metal2 to Metal4 for signals: Metal5 is where the power runs to the
#  block's own pads, and the six digital pads sit on Metal2.
set_routing_layers -signal Metal2-Metal4

#  A WIDER WIRE FOR THE SIGNALS. They carry next to no current -- eight drive
#  MOS gates and six drive a pad's data input -- so this is margin, not
#  electromigration. The minimum is 0.28 um and the flow's own rule is 0.38.
#
#  METAL2 STAYS AT 0.38 AND THAT IS NOT A CHOICE. It is the layer the pins are
#  on, and they come at a 0.73 um pitch: with a 0.84 um wire there is 0.07 um
#  left to the neighbour against M2.2a's 0.28, and the router put seven of those
#  in. The widest that fits is 0.45, and 0.38 keeps a real margin.
#
#  Metal3 and Metal4 never go near that comb, so they get 0.84 -- three times
#  the minimum, and free in an area this empty.
create_ndr -name ANCHO_INT \
           -width  {Metal2 0.38 Metal3 0.84 Metal4 0.84} \
           -spacing {Metal2 0.28 Metal3 0.28 Metal4 0.28}
foreach net [$blk getNets] {
    if {[$net isSpecial]} { continue }
    if {[llength [$net getITerms]] == 0} { continue }
    assign_ndr -ndr ANCHO_INT -net [$net getName]
}

global_route -guide_file $OUT/route.guide -allow_congestion -verbose
#  `-disable_via_gen` for the same reason as in route_top.tcl: without it the
#  router builds vias from the techlef's VIARULE GENERATE, 0.38 x 0.28, which is
#  below minimum area and brushes M3.1/M3.2a. With the flag it uses the square
#  vias of lef/vias.lef.
detailed_route -disable_via_gen \
               -output_drc $OUT/route_drc.rpt \
               -droute_end_iter 5 -verbose 1

write_def $OUT/${CELL}_routed.def
puts "  routed DEF -> $OUT/${CELL}_routed.def"
puts "  router DRC -> $OUT/route_drc.rpt"

write_def $OUT/$CELL.def
puts "  DEF written to $OUT/$CELL.def"
