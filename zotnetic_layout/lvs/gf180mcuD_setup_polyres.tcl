#---------------------------------------------------------------
# Setup de netgen para gf180mcuD + las resistencias de poly de 2k y 3k
#
# El setup del PDK (`gf180mcuD_setup.tcl`) declara en su lista `devices` solo
# `ppolyf_u_1k` y `ppolyf_u_1k_6p0`. Esa lista NO decide que dispositivos
# existen -- eso lo decide el deck de extraccion, que si tiene rama para 1k, 2k
# y 3k (`res_extraction.lvs`, `case POLY_RES`). Lo que decide es como los
# compara:
#
#   * `permute 1 2`          -- una resistencia no distingue sus dos extremos
#   * `series enable`        -- N tramos en serie se juntan en uno, sumando
#                               r_length y exigiendo el mismo r_width
#   * `parallel enable`      -- lo simetrico
#   * `property delete par1 pm par r`
#
# La reduccion en SERIE es la que hace falta aqui y la que faltaba: el serpentin
# se extrae como `s` tramos encadenados por metal1, mientras que la referencia
# trae un solo dispositivo con `S=5`. Sin ella netgen ve 5 dispositivos contra 1
# y no casa, sin decir que el problema es de plegado.
#
# Se hace desde fuera y no tocando el PDK: `source` del setup original y se
# repite su bloque `foreach` con los nombres que le faltan. Si el PDK anade
# algun dia esos dispositivos a su lista, esto se vuelve inofensivo (repetir
# `permute`/`property` sobre el mismo dispositivo no rompe nada) y este fichero
# se puede borrar.
#---------------------------------------------------------------

source /foss/pdks/gf180mcuD/libs.tech/netgen/gf180mcuD_setup.tcl

#  `cells1` y `cells2` los deja puestos el setup del PDK, pero se recogen otra
#  vez por si esto se llega a usar suelto.
set cells1 [cells list -all -circuit1]
set cells2 [cells list -all -circuit2]

set devices {}
lappend devices ppolyf_u_2k
lappend devices ppolyf_u_3k
lappend devices ppolyf_u_2k_6p0
lappend devices ppolyf_u_3k_6p0

foreach dev $devices {
    if {[lsearch $cells1 $dev] >= 0} {
	permute "-circuit1 $dev" 1 2
	property "-circuit1 $dev" series enable
	property "-circuit1 $dev" series {r_width critical}
	property "-circuit1 $dev" series {r_length add}
	property "-circuit1 $dev" parallel enable
	property "-circuit1 $dev" parallel {r_length critical}
	property "-circuit1 $dev" parallel {r_width add}
	property "-circuit1 $dev" tolerance {r_length 0.01} {r_width 0.01}
	# Ignore these properties
	property "-circuit1 $dev" delete par1 pm par r
    }
    if {[lsearch $cells2 $dev] >= 0} {
	permute "-circuit2 $dev" 1 2
	property "-circuit2 $dev" series enable
	property "-circuit2 $dev" series {r_width critical}
	property "-circuit2 $dev" series {r_length add}
	property "-circuit2 $dev" parallel enable
	property "-circuit2 $dev" parallel {r_length critical}
	property "-circuit2 $dev" parallel {r_width add}
	property "-circuit2 $dev" tolerance {r_length 0.01} {r_width 0.01}
	# Ignore these properties
	property "-circuit2 $dev" delete par1 pm par r
    }
}
