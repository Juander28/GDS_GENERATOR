#  El die COMPLETO (1x1) partido en cuatro proyectos, y el nuestro en el cuarto
#  de arriba a la izquierda.
#
#  La regla que manda aqui, y que se comprueba al final en vez de suponerse:
#  NADA nuestro sale del cuarto. Ni el bloque, ni sus pads, ni las pistas que
#  los unen. El die se parte por la mitad en las dos direcciones y ese es el
#  contrato con los otros tres proyectos.
#
#  El reparto de pads del fabricante NO se usa: en el quarter mandaba porque el
#  vendedor documenta ese pinout, pero aqui el die se comparte entre cuatro y el
#  pinout es cosa nuestra. Eso permite lo que en el quarter no se podia:
#  APRETAR los ocho pads analogicos justo encima de los pines del bloque en vez
#  de repartirlos por toda la fila. En el quarter la pista mas larga eran 790
#  um; aqui se vera cuanto.
#
#  Uso:  openroad -exit scripts/waferspace_cuatro.tcl

#  Rutas desde donde esta ESTE fichero, no desde el directorio de trabajo: el
#  guion se corre desde donde sea y tiene que encontrar lo suyo igual.
set AQUI     [file dirname [file normalize [info script]]]
set WS       [file dirname $AQUI]
set PROYECTO [file dirname $WS]
set OPENROAD $PROYECTO/openroad
set SALIDA   $WS/out
file mkdir $SALIDA

set PDK $WS/gf180mcu/gf180mcuD
set SC  gf180mcu_fd_sc_mcu7t5v0
set IO  gf180mcu_fd_io

#  --- el marco, de waferspace/librelane/slots/slot_1x1.yaml
set DIE   {0 0 3932 5122}
set CORE  {442 442 3490 4680}
set SELLO 26.0
set PADH  350.0
set CORNER 355.0

set MACRO GRADIENT_NAV2_V3
set M_OR  MX          ;# FS en nombres LEF

read_lef $PDK/libs.ref/$SC/techlef/${SC}__nom.tlef
read_lef $PDK/libs.ref/$SC/lef/$SC.lef
foreach f [glob $PDK/libs.ref/$IO/lef/*.lef] { read_lef $f }
read_lef $OPENROAD/lef/$MACRO.lef

set db [ord::get_db] ; set dbu 2000
proc maestro {n} {
    foreach lib [[ord::get_db] getLibs] {
        set m [$lib findMaster $n] ; if {$m != "NULL"} { return $m }
    }
    error "no encuentro $n"
}
proc um {v} { expr {$v / 2000.0} }

lassign $DIE  dx0 dy0 dx1 dy1
lassign $CORE cx0 cy0 cx1 cy1

#  --- la frontera de los cuartos -----------------------------------------------
set QX [expr {($dx0 + $dx1) / 2.0}]
set QY [expr {($dy0 + $dy1) / 2.0}]

#  Tramo util de cada fila: entre las celdas de esquina.
set HX0 [expr {$SELLO + $CORNER}] ; set HX1 [expr {$dx1 - $SELLO - $CORNER}]
set VY0 [expr {$SELLO + $CORNER}] ; set VY1 [expr {$dy1 - $SELLO - $CORNER}]
set PADW 75.0

puts "\n=== el die partido en cuatro ==="
puts [format "  die            %.0f x %.0f um" $dx1 $dy1]
puts [format "  frontera       x = %.0f   y = %.0f" $QX $QY]
puts [format "  nuestro cuarto x %.0f .. %.0f   y %.0f .. %.0f" $dx0 $QX $QY $dy1]
puts [format "  arco norte-oeste  x %.1f .. %.1f  = %.1f um  (%d pads de 75)" \
          $HX0 $QX [expr {$QX-$HX0}] [expr {int(($QX-$HX0)/$PADW)}]]
puts [format "  arco oeste-norte  y %.1f .. %.1f  = %.1f um  (%d pads de 75)" \
          $QY $VY1 [expr {$VY1-$QY}] [expr {int(($VY1-$QY)/$PADW)}]]

#  --- el bloque, arriba a la izquierda del core ---------------------------------
set chip [odb::dbChip_create $db [$db getTech]]
set blk  [odb::dbBlock_create $chip "cuatro_proyectos"]
$blk setDefUnits $dbu
set caja [odb::Rect] ; $caja init [expr {int($dx0*$dbu)}] [expr {int($dy0*$dbu)}] \
                                  [expr {int($dx1*$dbu)}] [expr {int($dy1*$dbu)}]
$blk setDieArea $caja

set mst [maestro $MACRO]
set MH  [um [$mst getHeight]] ; set MW [um [$mst getWidth]]
set M_X $cx0
set M_Y [expr {$cy1 - $MH}]
set inst [odb::dbInst_create $blk $mst "u_nav"]
$inst setOrient $M_OR
$inst setLocation [expr {int($M_X*$dbu)}] [expr {int(round($M_Y*$dbu))}]
$inst setPlacementStatus FIRM
set bb [$inst getBBox]
set mx0 [um [$bb xMin]] ; set my0 [um [$bb yMin]]
set mx1 [um [$bb xMax]] ; set my1 [um [$bb yMax]]

#  --- NUESTROS pads -------------------------------------------------------------
#  Apretados, no repartidos. Los ocho analogicos van pegados unos a otros y lo
#  mas a la izquierda que deja la celda de esquina, que es lo mas cerca que
#  pueden estar de los pines del bloque. Detras las tres salidas, y detras el
#  par de alimentacion de IO.
set HUECO 25.0
set ANALOG {S1P S1N S2N S2P S3P S3N S4N S4P}
set SALIDA {ZP YP XP}

set MIO {}
set x $HX0
foreach s $ANALOG { lappend MIO [list norte asig_5p0 $x [expr {$x+$PADW}] $s] ; set x [expr {$x+$PADW}] }
set x [expr {$x + $HUECO}]
foreach s $SALIDA { lappend MIO [list norte bi_24t $x [expr {$x+$PADW}] $s] ; set x [expr {$x+$PADW}] }
set x [expr {$x + $HUECO}]
foreach m {dvss dvdd} { lappend MIO [list norte $m $x [expr {$x+$PADW}] .] ; set x [expr {$x+$PADW}] }
set FIN_NORTE $x

#  La alimentacion del bloque sale por su costado IZQUIERDO, asi que sus pads van
#  en lo mas alto del arco oeste, enfrente de las tetillas.
set y $VY1
set MIO_O {}
foreach m {dvdd dvss dvdd dvss} {
    lappend MIO_O [list oeste $m [expr {$y-$PADW}] $y .] ; set y [expr {$y-$PADW}]
}
set FIN_OESTE $y
foreach p $MIO_O { lappend MIO $p }

#  --- los otros tres cuartos, a paso uniforme -----------------------------------
#  Lo que lleven da igual: son bidir y un par de alimentacion cada uno. Estan
#  para que el anillo quede completo y para poder ver que no nos pisamos.
set OTROS {}
proc arco {lado a b n} {
    set paso [expr {($b - $a) / double($n)}]
    set r {}
    for {set i 0} {$i < $n} {incr i} {
        set p [expr {$a + $i*$paso}]
        set m [expr {($i == 2) ? "dvss" : (($i == 3) ? "dvdd" : "bi_24t")}]
        lappend r [list $lado $m $p [expr {$p + 75.0}] .]
    }
    return $r
}
foreach {lado a b n} [list norte $QX $HX1 13 \
                           este  $QY $VY1 14 \
                           este  $VY0 $QY 14 \
                           sur   $QX $HX1 13 \
                           sur   $HX0 $QX 13 \
                           oeste $VY0 $QY 14] {
    foreach p [arco $lado $a $b $n] { lappend OTROS $p }
}

#  --- se comprueba, no se supone ------------------------------------------------
puts "\n=== el bloque ==="
puts [format "  %s  x %.2f .. %.2f   y %.2f .. %.2f  (%s)" $MACRO $mx0 $mx1 $my0 $my1 $M_OR]

puts "\n=== nuestros pads ==="
foreach p $MIO {
    lassign $p lado m a b s
    puts [format "  %-6s %-9s %8.1f .. %8.1f   %s" $lado $m $a $b $s]
}
puts [format "  el arco norte acaba en x = %.1f, con %.1f um de sobra hasta la frontera" \
          $FIN_NORTE [expr {$QX - $FIN_NORTE}]]
puts [format "  el arco oeste baja hasta y = %.1f, con %.1f um de sobra" \
          $FIN_OESTE [expr {$FIN_OESTE - $QY}]]

#  --- de cada pin a su pad, y por donde va la pista -------------------------------
set PADY [expr {$dy1 - $SELLO - $PADH}]   ;# borde interior del padring norte
set PADX [expr {$SELLO + $PADH}]          ;# borde interior del padring oeste
puts "\n=== de cada pin del bloque a su pad ==="
set peor 0.0 ; set fuera {}
foreach p $MIO {
    lassign $p lado m a b s
    if {$s eq "."} { continue }
    set it [$inst findITerm $s] ; set pb [$it getBBox]
    set c [expr {($a+$b)/2.0}]
    set px [um [$pb xMin]] ; set py [um [$pb yMin]]
    set d [expr {abs($c - $px) + ($PADY - [um [$pb yMax]])}]
    puts [format "  %-4s pad %8.1f   pin %8.2f   pista %7.1f um" $s $c $px $d]
    if {$d > $peor} { set peor $d }
    #  la caja que ocupa esa pista: del pin al pad, en L
    set lo [expr {min($c,$px)-1}] ; set hi [expr {max($c,$px)+1}]
    if {$hi > $QX} { lappend fuera "pista de $s llega a x=$hi" }
}
puts [format "  la peor pista mide %.1f um  (en el quarter del fabricante eran 790.7)" $peor]

puts "\n=== que nada nuestro sale del cuarto ==="
set malo 0
foreach {que x0 y0 x1 y1} [list bloque $mx0 $my0 $mx1 $my1] {
    if {$x1 > $QX || $y0 < $QY} { puts "  FUERA: $que"; incr malo }
}
foreach p $MIO {
    lassign $p lado m a b s
    if {$lado eq "norte" && $b > $QX} { puts "  FUERA: pad $m/$s en x=$b" ; incr malo }
    if {$lado eq "oeste" && $a < $QY} { puts "  FUERA: pad $m/$s en y=$a" ; incr malo }
}
foreach f $fuera { puts "  FUERA: $f" ; incr malo }
if {$malo == 0} {
    puts [format "  bloque, %d pads y %d pistas, todo dentro de x < %.0f e y > %.0f" \
              [llength $MIO] [expr {[llength $ANALOG]+[llength $SALIDA]}] $QX $QY]
} else {
    error "$malo cosas se salen del cuarto"
}

#  --- presupuesto de pines de NUESTRO cuarto -------------------------------------
#  La pregunta es si los pines dan de si, contando el ESD secundario. Se mide,
#  no se estima.
set PADW 75.0
set cab_n [expr {int(($QX - $HX0) / $PADW)}]
set cab_o [expr {int(($VY1 - $QY) / $PADW)}]
set usados [llength $MIO]
puts "\n=== presupuesto de pines ==="
puts [format "  posiciones en el arco norte  %2d  (x %.0f .. %.0f, apretados)" \
          $cab_n $HX0 $QX]
puts [format "  posiciones en el arco oeste  %2d  (y %.0f .. %.0f)" \
          $cab_o $QY $VY1]
puts [format "  total disponibles            %2d" [expr {$cab_n + $cab_o}]]
puts [format "  usados ahora mismo           %2d  (%d analogicos, %d salidas, %d de alimentacion)" \
          $usados [llength $ANALOG] [llength $SALIDA] \
          [expr {$usados - [llength $ANALOG] - [llength $SALIDA]}]]
puts [format "  LIBRES                       %2d" [expr {$cab_n + $cab_o - $usados}]]

#  --- el ESD secundario de las ocho entradas analogicas -------------------------
#  `ESD_CDM` es nuestra celda, la que se dibujo cuando la de los organizadores
#  resulto traer un MSLOT.1 dentro. Va EN SERIE entre el pad y el core, asi que
#  no gasta ningun pin: gasta sitio y ruteo.
#
#  El sitio natural es la banda que queda entre el borde interior del padring y
#  el techo del core. Se comprueba que caben ahi, debajo de sus propios pads,
#  en vez de suponerlo.
read_lef $OPENROAD/lef/ESD_CDM.lef
set esd [maestro ESD_CDM]
set ew [um [$esd getWidth]] ; set eh [um [$esd getHeight]]
set banda [expr {($dy1 - $SELLO - $PADH) - $cy1}]
set ancho_an 0.0 ; set an_x0 1e9 ; set an_x1 0
foreach p $MIO {
    lassign $p lado m a b s
    if {$m ne "asig_5p0"} { continue }
    if {$a < $an_x0} { set an_x0 $a }
    if {$b > $an_x1} { set an_x1 $b }
}
puts "\n=== ESD secundario de las entradas analogicas ==="
puts [format "  ESD_CDM             %.2f x %.2f um  = %.0f um2 cada uno" $ew $eh [expr {$ew*$eh}]]
puts [format "  hacen falta         %d, uno por entrada = %.0f um2 = %.4f mm2" \
          [llength $ANALOG] [expr {[llength $ANALOG]*$ew*$eh}] \
          [expr {[llength $ANALOG]*$ew*$eh/1e6}]]
puts [format "  banda entre padring y core   %.1f um de alto; el ESD mide %.1f" $banda $eh]
puts [format "  los %d en fila ocupan         %.1f um de ancho; sus pads cubren %.1f" \
          [llength $ANALOG] [expr {[llength $ANALOG]*$ew}] [expr {$an_x1-$an_x0}]]
if {$eh < $banda && [llength $ANALOG]*$ew < $QX - $HX0} {
    puts "  CABEN en la banda, debajo de sus propios pads, sin entrar en el core"
} else {
    puts "  NO caben en la banda: hay que meterlos dentro del core"
}

#  --- cuanto core toca por proyecto ------------------------------------------
#  El dato que decide si esto merece la pena frente a comprar un quarter suelto.
set qcx1 [expr {min($cx1, $QX)}] ; set qcy0 [expr {max($cy0, $QY)}]
set qw [expr {$qcx1 - $cx0}] ; set qh [expr {$cy1 - $qcy0}]
puts "\n=== cuanto core toca por proyecto ==="
puts [format "  nuestro trozo de core   x %.0f .. %.0f   y %.0f .. %.0f" \
          $cx0 $qcx1 $qcy0 $cy1]
puts [format "  son %.0f x %.0f um = %.2f mm2" $qw $qh [expr {$qw*$qh/1e6}]]
puts [format "  el core entero del slot quarter son 1052 x 1647 = 1.73 mm2"]
puts [format "  o sea %.2f veces mas sitio, y el die completo cuesta 7000 \$ entre" [expr {$qw*$qh/1.733e6}]]
puts        "  cuatro = 1750 \$ por proyecto, contra 2000 \$ el quarter suelto."
puts [format "  caben %d bloques como el nuestro en nuestro trozo (canal 20 um)" \
          [expr {int(($qw+20)/($MW+20)) * int(($qh+20)/($MH+20))}]]

#  --- json para la figura --------------------------------------------------------
set j [open $SALIDA/cuatro.json w]
puts $j "{"
puts $j "  \"die\": \[$dx0, $dy0, $dx1, $dy1\],"
puts $j "  \"core\": \[$cx0, $cy0, $cx1, $cy1\],"
puts $j "  \"sello\": $SELLO, \"padh\": $PADH, \"corner\": $CORNER,"
puts $j "  \"frontera\": \[$QX, $QY\],"
puts $j "  \"macro\": {\"nombre\": \"$MACRO\", \"caja\": \[$mx0, $my0, $mx1, $my1\], \"orient\": \"$M_OR\"},"
set e {}
foreach p [concat $MIO $OTROS] {
    lassign $p lado m a b s
    set mio [expr {[lsearch -exact $MIO $p] >= 0 ? 1 : 0}]
    lappend e "    \[\"$lado\", \"$m\", $a, $b, \"$s\", $mio\]"
}
puts $j "  \"pads\": \[\n[join $e ",\n"]\n  \],"
set e {}
foreach s [concat $ANALOG $SALIDA {VDD VSS}] {
    set pb [[$inst findITerm $s] getBBox]
    lappend e "    \"$s\": \[[um [$pb xMin]], [um [$pb yMin]], [um [$pb xMax]], [um [$pb yMax]]\]"
}
puts $j "  \"pines\": {\n[join $e ",\n"]\n  }"
puts $j "}"
close $j
puts "\n  JSON -> $SALIDA/cuatro.json"
