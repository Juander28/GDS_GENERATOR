# -----------------------------------------------------------------------------
#  Read the PDK and the analog macros, then link the top level.
#
#  Run from the openroad/ directory:
#      openroad -no_init -exit scripts/load_design.tcl
#
#  This is the smoke test for the whole collateral: if the LEF, the Liberty and
#  the Verilog disagree about a pin, link_design is where it shows up.
# -----------------------------------------------------------------------------

set PDK      /foss/pdks/gf180mcuD
set SC_LIB   gf180mcu_fd_sc_mcu9t5v0
set SC_REF   $PDK/libs.ref/$SC_LIB
set CORNER   nom

#: The design OpenROAD places. `verilog/<TOP>_macros.v` is generated from the
#: xschem netlist and contains nothing but hard macros. `verilog/top.v` is the
#: hand-written template from before there was a real netlist-derived top; it is
#: kept for reference and is not read by anything.
#:
#: `TOP_CELL` picks which top gets built. `GRADIENT_NAV` builds four GRADIENT
#: blocks, with the 98 dB OPAM; `GRADIENT_NAV2` is the same schematic with
#: GRADIENT2, that is with the linear amplifier. Each has its own Verilog and
#: output directory, so both can coexist and be compared.
if {![info exists DESIGN_TOP]} {
    set DESIGN_TOP [expr {[info exists env(TOP_CELL)] ? $env(TOP_CELL) : "GRADIENT_NAV"}]
}
if {![info exists DESIGN_V]}   { set DESIGN_V verilog/${DESIGN_TOP}_macros.v }

# --- technology --------------------------------------------------------------
#  The techlef is PATCHED: the PDK `VIARULE ... GENERATE` leave a via pad of
#  0.38 x 0.28, below minimum area and with a 0.05 step against the wire.
#  See scripts/patch_techlef.py.
read_lef lef/techlef_patched.tlef
read_lef $SC_REF/lef/$SC_LIB.lef

#  Our own vias, with enough enclosure for the metal minimum area: the techlef
#  ones leave a 0.1064 um2 pad and `Mn.3` asks for 0.1444 (see lef/vias.lef).
read_lef lef/vias.lef

# --- analog macros -----------------------------------------------------------
#  Globbed, not listed: a block with no layout yet has no LEF, and hard-coding
#  the names would fail here instead of where the missing block actually is —
#  link_design, which names the instance it cannot bind.
#  AND NOT THE ABSTRACT OF THE TOP ITSELF. `scripts/macro_lef.py` writes
#  lef/<TOP>.lef so the padring integration can place this design as a macro.
#  Reading it back in while BUILDING that same design is worse than useless:
#  OpenROAD binds every instance to the LEF MACRO of the same name, so the top
#  would bind to a leaf cell of itself. It also has no lib/<TOP>.lib, which is
#  how it announced itself -- "cannot read file lib/GRADIENT_NAV2.lib".
foreach lef [lsort [glob -nocomplain lef/*.lef]] {
    if {[file tail $lef] eq "vias.lef"} { continue }   ;# ya leido arriba
    set macro [file rootname [file tail $lef]]
    if {$macro eq $DESIGN_TOP} { continue }
    read_lef     $lef
    read_liberty lib/$macro.lib
}

# --- standard cell timing ----------------------------------------------------
read_liberty $SC_REF/lib/${SC_LIB}__tt_025C_5v00.lib

# --- design ------------------------------------------------------------------
#  ONLY the top level is read here. The black-box files verilog/COMP.v,
#  verilog/OPAM.v ... are for *synthesis* (yosys): giving them to OpenROAD is
#  actively harmful, because it elaborates them as empty hierarchical modules and
#  the instances disappear — link_design succeeds and the block ends up with 0
#  instances. OpenROAD binds each instance to the LEF MACRO of the same name.
read_verilog $DESIGN_V
link_design $DESIGN_TOP

read_sdc constraints/top.sdc

set n 0
set kinds [dict create]
foreach inst [[ord::get_db_block] getInsts] {
    if {[[$inst getMaster] isBlock]} {
        incr n
        dict incr kinds [[$inst getMaster] getName]
    }
}
puts "--------------------------------------------------------------"
puts "$DESIGN_TOP linked: $n macro instances"
foreach macro [lsort [dict keys $kinds]] {
    puts [format "  %-14s x%d" $macro [dict get $kinds $macro]]
}
puts "--------------------------------------------------------------"
