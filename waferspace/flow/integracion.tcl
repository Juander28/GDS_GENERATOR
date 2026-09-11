#  La integracion completa en el slot QUARTER de wafer.space.
#
#  El die y el reparto de pads son los del fabricante, sin tocar: 1936 x 2531,
#  core [442, 442, 1494, 2089], 56 posiciones repartidas 11/17/11/17. Lo nuestro
#  es que celda va en cada posicion de senal, y eso sale gratis porque todas
#  miden 75 x 350 um.
#
#  Aqui el die entero es nuestro, asi que -- al contrario que en `cuatro.tcl`,
#  que estudia el die completo partido entre cuatro proyectos -- el anillo de
#  alimentacion puede rodear el core entero y aprovechar los ocho pads de
#  alimentacion de los cuatro lados.
#
#  Uso:  openroad -exit flow/integracion.tcl

set AQUI     [file dirname [file normalize [info script]]]
set WS       [file dirname $AQUI]
set PROYECTO [file dirname $WS]
set OPENROAD $PROYECTO/openroad
set SALIDA   $WS/out_integracion
file mkdir $SALIDA

set PDK $WS/gf180mcu/gf180mcuD
set SC  gf180mcu_fd_sc_mcu7t5v0
set IO  gf180mcu_fd_io

set DIE    {0 0 1936 2531}
set CORE   {442 442 1494 2089}
set SELLO  26.0
set PADH   350.0
set CORNER 355.0
set PADW   75.0
set SITIO  0.1

set MACRO GRADIENT_NAV2_V3
set M_OR  MX
set ANALOG  {S1P S1N S2N S2P S3P S3N S4N S4P}
set SALIDAS {ZP YP XP}

set I_OBJ  31.0 ; set MA_M4 0.67 ; set MA_M5 1.5 ; set MA_VIA 0.18

read_lef $PDK/libs.ref/$SC/techlef/${SC}__nom.tlef
read_lef $PDK/libs.ref/$SC/lef/$SC.lef
foreach f [glob $PDK/libs.ref/$IO/lef/*.lef] { read_lef $f }
read_lef $AQUI/pad_sites.lef
read_lef $OPENROAD/lef/$MACRO.lef
read_lef $OPENROAD/lef/ESD_CDM.lef
read_lef $OPENROAD/lef/vias.lef

set db [ord::get_db] ; set dbu 2000
proc maestro {n} {
    foreach lib [[ord::get_db] getLibs] {
        set m [$lib findMaster $n] ; if {$m != "NULL"} { return $m }
    }
    error "no encuentro $n"
}
proc um {v} { expr {$v / 2000.0} }
#  Micrometros -> dbu en la REJILLA DE FABRICACION (10 dbu = 5 nm). Con `int()`
#  a secas, `int(505.16*2000)` da 1010319 y no 1010320 -- coma flotante -- y ese
#  medio nanometro, sumado al ORIGIN de una celda, saca un pin de la rejilla y
#  tumba el ruteo detallado con DRT-0416 tres pasos mas tarde.
proc rejilla {v} { expr {int(round(round($v*2000.0)/10.0)*10)} }

lassign $DIE  dx0 dy0 dx1 dy1
lassign $CORE cx0 cy0 cx1 cy1
set HX0 [expr {$SELLO+$CORNER}] ; set HX1 [expr {$dx1-$SELLO-$CORNER}]
set VY0 [expr {$SELLO+$CORNER}] ; set VY1 [expr {$dy1-$SELLO-$CORNER}]
set PAD_IN_N [expr {$dy1-$SELLO-$PADH}]
set PAD_IN_S [expr {$SELLO+$PADH}]
set PAD_IN_O [expr {$SELLO+$PADH}]
set PAD_IN_E [expr {$dx1-$SELLO-$PADH}]

set chip [odb::dbChip_create $db [$db getTech]]
set blk  [odb::dbBlock_create $chip "B26_waferspace_quarter"]
$blk setDefUnits $dbu
set caja [odb::Rect]
$caja init [rejilla $dx0] [rejilla $dy0] [rejilla $dx1] [rejilla $dy1]
$blk setDieArea $caja
puts "\n=== el marco del fabricante ==="
puts [format "  die  %.0f x %.0f um    core %.0f %.0f .. %.0f %.0f" \
          $dx1 $dy1 $cx0 $cy0 $cx1 $cy1]

# ---------------------------------------------------------------------------
#  1. El padring: 11/17/11/17, con el reparto de pad_cfg.tcl
# ---------------------------------------------------------------------------
set FILA(sur)   {in_s in_c dvss dvdd bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t}
set FILA(este)  {bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t dvss dvdd
                 bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t}
set FILA(norte) {asig_5p0 asig_5p0 dvss dvdd asig_5p0 asig_5p0 asig_5p0 asig_5p0
                 asig_5p0 asig_5p0 bi_24t}
set FILA(oeste) {bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t bi_24t
                 bi_24t bi_24t in_c in_c dvss dvdd in_c in_c}
#  Nuestras senales, en el orden de los pines a lo largo del borde del bloque.
set SENAL(norte) [list S1P S1N . . S2N S2P S3P S3N S4N S4P .]
set SENAL(este)  [list . . . . . . . . . . . . . . ZP YP XP]
set SENAL(sur)   [list . . . . . . . . . . .]
set SENAL(oeste) [list . . . . . . . . . . . . . . . . .]

make_io_sites -horizontal_site GF_IO_Site -vertical_site GF_IO_Site \
              -corner_site GF_COR_Site -offset $SELLO
set ROW [dict create sur IO_SOUTH este IO_EAST norte IO_NORTH oeste IO_WEST]
array set PADDE {} ; array set PADX {}
foreach lado {sur este norte oeste} {
    set n [llength $FILA($lado)]
    set ancho 0.0
    foreach m $FILA($lado) { set ancho [expr {$ancho + [um [[maestro ${IO}__$m] getWidth]]}] }
    set largo [expr {($lado eq "sur" || $lado eq "norte") ? $HX1-$HX0 : $VY1-$VY0}]
    set relleno [expr {$largo - $ancho}]
    set entre   [expr {floor(($relleno/($n+1))/$SITIO)*$SITIO}]
    set cur     [expr {($lado eq "sur" || $lado eq "norte") ? $HX0 : $VY0}]
    set cur     [expr {$cur + ($relleno - $entre*($n-1))/2.0}]
    set k 0
    foreach m $FILA($lado) s $SENAL($lado) {
        set nom [expr {$s eq "." ? "pad_${lado}_$k" : "pad_$s"}]
        place_pad -row [dict get $ROW $lado] -location $cur -master ${IO}__$m $nom
        if {$s ne "."} { set PADDE($s) $nom ; set PADX($s) [expr {$cur+$PADW/2.0}] }
        set cur [expr {$cur + $entre + $PADW}]
        incr k
    }
}
place_corners ${IO}__cor
foreach fila {IO_NORTH IO_SOUTH IO_WEST IO_EAST} {
    place_io_fill -row $fila ${IO}__fill10 ${IO}__fill5 ${IO}__fill1 ${IO}__fillnc
}
remove_io_rows
puts "\n=== padring ==="
puts "  56 pads del fabricante: 8 analogicos al norte, 3 salidas al este"

# ---------------------------------------------------------------------------
#  2. El bloque, en la esquina superior izquierda del core
# ---------------------------------------------------------------------------
set mst [maestro $MACRO]
set MW [um [$mst getWidth]] ; set MH [um [$mst getHeight]]
set M_X $cx0 ; set M_Y [expr {$cy1-$MH}]
set nav [odb::dbInst_create $blk $mst "u_nav"]
$nav setOrient $M_OR
$nav setLocation [rejilla $M_X] [rejilla $M_Y]
$nav setPlacementStatus FIRM
set bb [$nav getBBox]
set mx0 [um [$bb xMin]] ; set my0 [um [$bb yMin]]
set mx1 [um [$bb xMax]] ; set my1 [um [$bb yMax]]
puts "\n=== el bloque ==="
puts [format "  %s  x %.2f .. %.2f   y %.2f .. %.2f  (%s)" $MACRO $mx0 $mx1 $my0 $my1 $M_OR]

# ---------------------------------------------------------------------------
#  3. Los ocho ESD, cada uno DEBAJO DE SU PROPIO PAD
# ---------------------------------------------------------------------------
#  Aqui los pads analogicos no van apretados: el reparto del fabricante los
#  separa 104 um a lo largo de toda la fila norte. Asi que los ESD tampoco van
#  en fila pegada, sino cada uno bajo el suyo, que es el camino mas corto y deja
#  el pico donde tiene que quedarse.
set esd_m [maestro ESD_CDM]
set EW [um [$esd_m getWidth]] ; set EH [um [$esd_m getHeight]]
set banda [expr {$PAD_IN_N - $cy1}]
set STRAP_W 12.0
set VSS_SY [expr {$cy1 + 2.0}]
set ESD_Y  [expr {$VSS_SY + $STRAP_W + 2.0}]
set VDD_SY [expr {$ESD_Y + $EH + 2.0}]
if {$VDD_SY + $STRAP_W + 2.0 > $PAD_IN_N} {
    error "no caben las dos tiradas y el ESD en los $banda um de banda"
}
array set ESDDE {}
foreach s $ANALOG {
    set e [odb::dbInst_create $blk $esd_m "esd_$s"]
    $e setOrient R0
    #  Centrado bajo su pad, pero SIN salirse del core. El pad de S1P esta en
    #  x = 448 y el core empieza en 442: centrado, su ESD arrancaria en 416, o
    #  sea dentro del anillo de VDD, que va de 410 a 440. El router lo canto
    #  como un corto de verdad -- `net:VDD net:S1P_pad` en Metal3 -- y es
    #  exactamente el tipo de cosa que no se ve mirando el dibujo.
    set ex [expr {min(max($PADX($s)-$EW/2.0, $cx0), $cx1-$EW)}]
    $e setLocation [rejilla $ex] [rejilla $ESD_Y]
    $e setPlacementStatus FIRM
    set ESDDE($s) $e
}
puts "\n=== ESD secundario ==="
puts [format "  8 x ESD_CDM de %.2f x %.2f um en la banda de %.0f um" $EW $EH $banda]
puts [format "  tira VSS y %.1f .. %.1f | ESD y %.1f .. %.1f | tira VDD y %.1f .. %.1f" \
          $VSS_SY [expr {$VSS_SY+$STRAP_W}] $ESD_Y [expr {$ESD_Y+$EH}] \
          $VDD_SY [expr {$VDD_SY+$STRAP_W}]]
puts "  cada uno debajo de su propio pad, no en fila apretada: aqui el reparto"
puts "  del fabricante separa los pads 104 um y el camino corto es ese."

# ---------------------------------------------------------------------------
#  4. Los nets
# ---------------------------------------------------------------------------
proc net {blk n {tipo SIGNAL}} {
    set x [$blk findNet $n]
    if {$x eq "NULL" || $x eq ""} {
        set x [odb::dbNet_create $blk $n]
        if {$tipo ne "SIGNAL"} { $x setSpecial ; $x setSigType $tipo }
    }
    return $x
}
proc ata {inst pin red} {
    set it [$inst findITerm $pin]
    if {$it eq "NULL" || $it eq ""} { error "[$inst getName] no tiene pin $pin" }
    odb::dbITerm_connect $it $red
}
#  Un solo dominio: en `gf180mcu_fd_io` la celda `vdd` de core ES una `dvdd`, y
#  `chip_top.sv` escribe `assign VDD = DVDD`.
set nVDD [net $blk VDD POWER] ; set nVSS [net $blk VSS GROUND]
set n_ali 0
foreach inst [$blk getInsts] {
    foreach {pin red} [list VDD $nVDD VSS $nVSS DVDD $nVDD DVSS $nVSS] {
        set it [$inst findITerm $pin]
        if {$it ne "NULL" && $it ne ""} { odb::dbITerm_connect $it $red ; incr n_ali }
    }
}
#  Las analogicas van en DOS tramos con el ESD en medio. Si fueran un solo net,
#  el clamp quedaria en paralelo y no protegeria nada.
foreach s $ANALOG {
    set pad [$blk findInst $PADDE($s)] ; set e $ESDDE($s)
    set a [net $blk "${s}_pad"] ; set b [net $blk $s]
    ata $pad ASIG5V $a ; ata $e PAD $a ; ata $e CORE $b ; ata $nav $s $b
}
foreach s $SALIDAS {
    set pad [$blk findInst $PADDE($s)] ; set r [net $blk $s]
    ata $nav $s $r ; ata $pad A $r ; ata $pad OE $nVDD
    foreach c {IE CS SL PU PD Y} { ata $pad $c $nVSS }
}
puts "\n=== nets ==="
puts "  $n_ali terminales de alimentacion, [llength $ANALOG] analogicas en dos tramos,\
 [llength $SALIDAS] salidas"

# ---------------------------------------------------------------------------
#  5. El anillo de alimentacion, alimentado por los CUATRO lados
# ---------------------------------------------------------------------------
#  El die entero es nuestro, asi que el anillo rodea el core completo. Y el
#  reparto del fabricante deja un par dvdd/dvss en CADA lado, o sea que el
#  anillo se alimenta por cuatro puntos: la corriente se reparte sola y la caida
#  sale simetrica. No hace falta que todo pase por un camino.
#
#  Dos anillos concentricos en los 66 um que hay entre el core y el padring:
#  VDD por dentro (pegado al core, que es donde estan las tetillas del bloque) y
#  VSS por fuera. Metal4 + Metal3 apilados: 30 um de cada uno son 40.2 mA, y con
#  Metal4 a solas serian 20.1 contra los 31 que pide el bloque.
set BUS_W 30.0 ; set SEP 2.0
set VDD_O [expr {$cx0 - $SEP - $BUS_W}]              ;# oeste, x
set VSS_O [expr {$VDD_O - $SEP - $BUS_W}]
set VDD_E [expr {$cx1 + $SEP}]                       ;# este
set VSS_E [expr {$VDD_E + $SEP + $BUS_W}]
set VDD_S [expr {$cy0 - $SEP - $BUS_W}]              ;# sur, y
set VSS_S [expr {$VDD_S - $SEP - $BUS_W}]
if {$VSS_O < $PAD_IN_O || $VSS_S < $PAD_IN_S || $VSS_E+$BUS_W > $PAD_IN_E} {
    error "el anillo no cabe entre el core y el padring"
}

set tech [$db getTech]
foreach c {Metal1 Metal2 Metal3 Metal4 Metal5} { set L($c) [$tech findLayer $c] }
proc caja {red capa x0 y0 x1 y1} {
    set sw [odb::dbSWire_create $red ROUTED]
    odb::dbSBox_create $sw $capa [rejilla $x0] [rejilla $y0] \
        [rejilla $x1] [rejilla $y1] STRIPE
}
proc matriz {red nombre x0 y0 x1 y1} {
    set v [[[ord::get_db] getTech] findVia $nombre]
    if {$v eq "NULL" || $v eq ""} { error "no existe la via $nombre" }
    set sw [odb::dbSWire_create $red ROUTED] ; set P 0.90 ; set n 0
    for {set x [expr {$x0+$P/2}]} {$x < $x1-$P/4} {set x [expr {$x+$P}]} {
        for {set y [expr {$y0+$P/2}]} {$y < $y1-$P/4} {set y [expr {$y+$P}]} {
            odb::dbSBox_create $sw $v [rejilla $x] [rejilla $y] STRIPE ; incr n
        }
    }
    return $n
}

#  Los tres lados que estan libres. El norte lo lleva la banda de los ESD, mas
#  abajo, porque ahi no cabe un anillo de 30 um: ya estan los clamps.
set n_cos 0
foreach {red xo xe ys} [list $nVDD $VDD_O $VDD_E $VDD_S  $nVSS $VSS_O $VSS_E $VSS_S] {
    foreach capa [list $L(Metal4) $L(Metal3)] {
        caja $red $capa $xo $ys [expr {$xo+$BUS_W}] $VDD_SY      ;# oeste, hasta la banda
        caja $red $capa $xe $ys [expr {$xe+$BUS_W}] $VDD_SY      ;# este
        caja $red $capa $xo $ys [expr {$xe+$BUS_W}] [expr {$ys+$BUS_W}]  ;# sur
    }
    #  la costura entre las dos capas, repartida en parches
    for {set j 0} {$j < 5} {incr j} {
        set yy [expr {$ys + 40 + $j*($VDD_SY-$ys-80)/4.0}]
        incr n_cos [matriz $red Via3_SQ [expr {$xo+0.2}] $yy [expr {$xo+$BUS_W-0.2}] [expr {$yy+20}]]
        incr n_cos [matriz $red Via3_SQ [expr {$xe+0.2}] $yy [expr {$xe+$BUS_W-0.2}] [expr {$yy+20}]]
    }
    for {set j 0} {$j < 6} {incr j} {
        set xx [expr {$xo + 40 + $j*($xe-$xo-80)/5.0}]
        incr n_cos [matriz $red Via3_SQ $xx [expr {$ys+0.2}] [expr {$xx+20}] [expr {$ys+$BUS_W-0.2}]]
    }
}

#  La banda del norte: dos tiradas de Metal5 que son a la vez el lado norte del
#  anillo y la alimentacion de los ocho ESD. Metal5 puede pasar por encima de
#  ellos: `ESD_CDM` solo obstruye Metal1, Metal2 y los pozos.
set n_ani 0
foreach {red sy xo} [list $nVSS $VSS_SY $VSS_O  $nVDD $VDD_SY $VDD_O] {
    caja $red $L(Metal5) $xo $sy [expr {$cx1+$SEP+$BUS_W}] [expr {$sy+$STRAP_W}]
    #  baja al anillo en los dos extremos
    foreach xx [list $xo [expr {$cx1+$SEP}]] {
        incr n_ani [matriz $red Via4_SQ [expr {$xx+0.2}] $sy \
                           [expr {$xx+$BUS_W-0.2}] [expr {$sy+$STRAP_W}]]
    }
}
puts "\n=== alimentacion ==="
puts [format "  anillo de %.0f um en Metal4 + Metal3 -> %.1f mA, por oeste, sur y este" \
          $BUS_W [expr {2*$BUS_W*$MA_M4}]]
puts [format "  norte: 2 tiradas de Metal5 de %.0f um -> %.1f mA cada una" \
          $STRAP_W [expr {$STRAP_W*$MA_M5}]]
puts "  $n_cos cortes de via3 cosen Metal3 con Metal4; $n_ani de via4 cierran el norte"

#  Los pads de alimentacion de los cuatro lados, cada uno a su anillo.
set n_tap 0 ; set um_tap 0.0
foreach inst [$blk getInsts] {
    set nom [$inst getName]
    set m [[$inst getMaster] getName]
    if {![string match "*__dvdd" $m] && ![string match "*__dvss" $m]} { continue }
    set es_vdd [string match "*__dvdd" $m]
    set red [expr {$es_vdd ? "$nVDD" : "$nVSS"}]
    set pin [expr {$es_vdd ? "DVDD" : "DVSS"}]
    set b [$inst getBBox]
    set px0 [um [$b xMin]] ; set py0 [um [$b yMin]]
    set px1 [um [$b xMax]] ; set py1 [um [$b yMax]]
    #  de que lado es, y hasta donde hay que tirar
    if {$py1 <= $PAD_IN_S+1} {                               ;# sur
        caja $red $L(Metal4) [expr {$px0+5}] $py1 [expr {$px1-5}] \
             [expr {$es_vdd ? $VDD_S+$BUS_W : $VSS_S+$BUS_W}]
        set um_tap [expr {$um_tap+$px1-$px0-10}]
    } elseif {$py0 >= $PAD_IN_N-1} {                          ;# norte
        caja $red $L(Metal5) [expr {$px0+5}] \
             [expr {$es_vdd ? $VDD_SY : $VSS_SY}] [expr {$px1-5}] $py0
        set um_tap [expr {$um_tap+$px1-$px0-10}]
    } elseif {$px1 <= $PAD_IN_O+1} {                          ;# oeste
        caja $red $L(Metal4) $px1 [expr {$py0+5}] \
             [expr {$es_vdd ? $VDD_O+$BUS_W : $VSS_O+$BUS_W}] [expr {$py1-5}]
        set um_tap [expr {$um_tap+$py1-$py0-10}]
    } else {                                                  ;# este
        caja $red $L(Metal4) [expr {$es_vdd ? $VDD_E : $VSS_E}] [expr {$py0+5}] \
             $px0 [expr {$py1-5}]
        set um_tap [expr {$um_tap+$py1-$py0-10}]
    }
    incr n_tap
}
puts [format "  %d pads de alimentacion enganchados, %.0f um de cobre en total" $n_tap $um_tap]

#  Las tetillas del bloque al anillo de VDD/VSS del oeste.
set n_v4 0 ; array set UM {VDD 0.0 VSS 0.0}
foreach {p red x0} [list VDD $nVDD $VDD_O VSS $nVSS $VSS_O] {
    set it [$nav findITerm $p]
    foreach par [$it getGeometries] {
        lassign $par capa b
        if {[$capa getName] ne "Metal5"} { continue }
        set y0 [um [$b yMin]] ; set y1 [um [$b yMax]] ; set xr [um [$b xMax]]
        caja $red $L(Metal5) [expr {$x0+0.35}] $y0 $xr $y1
        caja $red $L(Metal4) [expr {$x0+0.20}] $y0 [expr {$x0+$BUS_W-0.20}] $y1
        incr n_v4 [matriz $red Via4_SQ [expr {$x0+0.20}] $y0 [expr {$x0+$BUS_W-0.20}] $y1]
        set UM($p) [expr {$UM($p)+$y1-$y0}]
    }
}
foreach p {VDD VSS} {
    puts [format "  %s del bloque: %.2f um de Metal5 -> %.1f mA" $p $UM($p) [expr {$UM($p)*$MA_M5}]]
}
puts [format "  %d cortes de via4 del bloque al anillo -> %.1f mA" $n_v4 [expr {$n_v4*$MA_VIA}]]

#  Y los ESD a sus tiradas. SIN ESTO NO SUJETAN NADA: un clamp secundario sin
#  VDD ni VSS no tiene a donde descargar. El DRC no dice palabra -- la geometria
#  esta perfecta -- y el ruteo de senal tampoco, porque son nets `special`.
set n_esd 0
foreach s $ANALOG {
    set e $ESDDE($s)
    foreach {p red sy} [list VSS $nVSS $VSS_SY  VDD $nVDD $VDD_SY] {
        set it [$e findITerm $p]
        foreach par [$it getGeometries] {
            lassign $par capa b
            if {[$capa getName] ne "Metal3"} { continue }
            set y0 [um [$b yMin]] ; set y1 [um [$b yMax]]
            if {$y1-$y0 > 2.0 || [um [$b xMax]]-[um [$b xMin]] < 20} { continue }
            set a [expr {min($y0,$sy)}] ; set c [expr {max($y1,$sy+$STRAP_W)}]
            set xm [expr {[um [$b xMin]]+8}] ; set xM [expr {$xm+20}]
            caja $red $L(Metal4) $xm $a $xM $c
            incr n_esd [matriz $red Via3_SQ $xm $y0 $xM $y1]
            incr n_esd [matriz $red Via4_SQ $xm $sy $xM [expr {$sy+$STRAP_W}]]
            break
        }
    }
}
puts "  $n_esd cortes de via llevan VDD y VSS a los ocho ESD"

# ---------------------------------------------------------------------------
#  6. Las once senales
# ---------------------------------------------------------------------------
foreach c {Metal1 Metal2 Metal3 Metal4} {
    make_tracks $c -x_offset 0.28 -x_pitch 0.56 -y_offset 0.28 -y_pitch 0.56
}
make_tracks Metal5 -x_offset 0.45 -x_pitch 0.90 -y_offset 0.45 -y_pitch 0.90
set_routing_layers -signal Metal2-Metal4
puts "\n=== ruteo ==="
if {[catch {global_route -congestion_iterations 30} err]} {
    puts "  el ruteo global se quejo: $err"
} else {
    if {[catch {detailed_route -output_drc $SALIDA/route_drc.rpt -droute_end_iter 5 \
                               -verbose 0} err2]} {
        puts "  el ruteo detallado se quejo: $err2"
    } else {
        set n [file size $SALIDA/route_drc.rpt]
        puts "  ruteado; route_drc.rpt de $n bytes\
 ([expr {$n == 0 ? {sin violaciones} : {CON violaciones}}])"
    }
}

# ---------------------------------------------------------------------------
#  7. Comprobaciones
# ---------------------------------------------------------------------------
#  Que cada senal llegue de verdad de punta a punta. Un net con terminales y sin
#  ruta no lo caza el DRC -- no hay geometria que pueda romper una regla -- y en
#  el GDS se ve como un bloque colocado y perfecto sin una sola conexion.
set sueltos {}
foreach s [concat $ANALOG $SALIDAS] {
    foreach n [list $s "${s}_pad"] {
        set red [$blk findNet $n]
        if {$red eq "NULL" || $red eq ""} { continue }
        set w [$red getWire]
        if {$w eq "NULL" || $w eq ""} { lappend sueltos $n }
    }
}
puts "\n=== que todo esta conectado ==="
if {[llength $sueltos] == 0} {
    puts "  las [expr {2*[llength $ANALOG]+[llength $SALIDAS]}] rutas de senal tienen geometria"
} else {
    puts "  SIN RUTA: $sueltos"
}

#  Y que nada se sale del die util, por dentro del sello.
set fuera 0
foreach inst [$blk getInsts] {
    set b [$inst getBBox]
    if {[um [$b xMin]] < $SELLO-0.001 || [um [$b yMin]] < $SELLO-0.001 ||
        [um [$b xMax]] > $dx1-$SELLO+0.001 || [um [$b yMax]] > $dy1-$SELLO+0.001} {
        puts "  FUERA DEL SELLO: [$inst getName]" ; incr fuera
    }
}
puts [format "  %d celdas revisadas contra el anillo de sellado, %d fuera" \
          [llength [$blk getInsts]] $fuera]
if {$fuera} { error "$fuera celdas pisan el sello" }

write_def $SALIDA/integracion.def
puts "\n  DEF -> $SALIDA/integracion.def"
puts [format "  %d instancias" [llength [$blk getInsts]]]
