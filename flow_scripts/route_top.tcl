# -----------------------------------------------------------------------------
#  Signal routing for the top.
#
#      openroad -no_init -exit scripts/route_top.tcl
#
#  Runs AFTER the floorplan: it reads the DEF that left behind (macros placed,
#  power grids and top pins already in place) and routes the signal nets. It is
#  split from the floorplan on purpose, because detailed routing takes a while
#  and there is no need to repeat it every time a macro moves.
# -----------------------------------------------------------------------------

#  The floorplan is redone instead of reading its DEF. `read_def -incremental`
#  on a freshly linked block brings no track structure and the router dies with
#  `ODB-0139 Missing track structure for layer Metal1`; rehacerlo cuesta segundos
#  and leaves the database complete.
#  Output directory. Defaults to `out`, which is the v1 top's.
#  `TOP_OUT` changes it so the top can be built with another version's cells
#  without stepping on the previous one: both have to coexist to be
#  compararlos.
set OUT [expr {[info exists env(TOP_OUT)] ? $env(TOP_OUT) : "out"}]
file mkdir $OUT

#  Name of the top cell. See scripts/load_design.tcl.
set TOPCELL [expr {[info exists env(TOP_CELL)] ? $env(TOP_CELL) : "GRADIENT_NAV"}]

source scripts/floorplan_top.tcl

set block [ord::get_db_block]

#  Layer split: signal runs on Metal2 (vertical), Metal3 (horizontal) and
#  Metal4 (vertical); Metal5 is kept whole for power.
#
#  Metal1 stays out: that is where the rails and the blocks' internal routing live.
#
#  Metal4 is needed even though it is the MIM layer. With only Metal2 and Metal3
#  the router ended with 667 overflow on Metal3 and **46 demand on Metal2 out of
#  23190 resource**: over a macro it cannot drop to Metal2 -- that layer is taken
#  by the block's own routing, so via2 is blocked -- so all the vertical traffic
#  had to escape into the channel.
#  Metal4 gives it vertical corridors above the blocks; the `MIMTM.1` margin
#  already comes in the LEF obstructions.
set_routing_layers -signal Metal2-Metal4

#  Non-standard rule: 0.38 wires on the three signal layers, not the 0.28
#  minimum. That is what matches the wire width to the via enclosure, which is
#  0.38 x 0.28. With 0.28 there was a 0.05 step at the junction -- hence the
#  `M3.1` and the 0.04..0.08 `M2.2a` brushes -- and a loose 0.38 x 0.28 pad is
#  0.1064 um2 when `Mn.3` asks 0.1444, which is where `M3.3` came from.
#  A 0.38 wire covers both: no step and no short area.
create_ndr -name ANCHO -width {Metal2 0.38 Metal3 0.38 Metal4 0.38} \
                       -spacing {Metal2 0.28 Metal3 0.28 Metal4 0.28}
foreach net [$block getNets] {
    if {[$net getSigType] in {POWER GROUND}} { continue }
    assign_ndr -ndr ANCHO -net [$net getName]
}

set n 0
foreach net [$block getNets] {
    if {[$net getSigType] in {POWER GROUND}} { continue }
    incr n
}
puts "--------------------------------------------------------------"
puts "Nets de senal a rutear: $n"
puts "--------------------------------------------------------------"

file mkdir out
#  `-allow_congestion`: global routing is left with a handful of overflowed
#  GCells over a 2.3% total occupancy -- a local jam getting into some pin, not
#  a lack of resource; neither widening channels nor multiplying the port
#  platforms brought it down. Global overflow is an estimate on a coarse grid:
#  what decides is DETAILED routing, and its DRC report
#  (`$OUT/route_drc.rpt`) plus KLayout's sign-off DRC are what to look at.
#  If detailed routing did not close, it would show there.
#  Spots the sign-off DRC marked on an earlier pass and that the router is
#  forbidden to use again (see `scripts/drc_blockages.py`). The file may not
#  exist: the first pass runs with nothing.
set bloqueos $OUT/drc_blockages.txt
if {[file exists $bloqueos]} {
  set blk  [ord::get_db_block]
  set tech [ord::get_db_tech]
  set dbu  [$tech getDbUnitsPerMicron]
  set nb 0
  set fh [open $bloqueos r]
  while {[gets $fh linea] >= 0} {
    if {[string trim $linea] eq ""} { continue }
    lassign $linea capa x0 y0 x1 y1
    set l [$tech findLayer $capa]
    if {$l eq "NULL" || $l eq ""} { continue }
    odb::dbObstruction_create $blk $l \
        [expr {int($x0*$dbu)}] [expr {int($y0*$dbu)}] \
        [expr {int($x1*$dbu)}] [expr {int($y1*$dbu)}]
    incr nb
  }
  close $fh
  puts "  $nb DRC blockages read from $bloqueos"
}

global_route -guide_file $OUT/route.guide -allow_congestion -verbose
#  `-disable_via_gen`: without this the router builds its own vias from the
#  techlef `VIARULE ... GENERATE`, which give a 0.38 x 0.28 pad -- below minimum
#  area and with a 0.05 step against a 0.28 wire, which is where `M3.3`, `M3.1`
#  and the little `M3.2a`/`M2.2a` brushes came from. With the flag it uses the
#  vias cuadradas de `lef/vias.lef`.
detailed_route -disable_via_gen \
               -output_drc $OUT/route_drc.rpt \
               -output_maze $OUT/route_maze.log \
               -droute_end_iter 5 -verbose 1

write_def $OUT/${TOPCELL}_routed.def
puts "--------------------------------------------------------------"
report_design_area
puts "DEF ruteado en $OUT/${TOPCELL}_routed.def"
puts "router DRC report in $OUT/route_drc.rpt"
puts "--------------------------------------------------------------"
