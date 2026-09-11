# GRADIENT_NAV2_V3 en el slot quarter de wafer.space

Qué es esto: la plantilla `wafer-space/gf180mcu-project-template` con el bloque
`GRADIENT_NAV2_V3` dentro, en la esquina superior izquierda del core del slot
**0.5×0.5 (quarter)**. La plantilla original está intacta en `UPSTREAM.txt`
(commit `0de7e394`, 2026-07-21); todo lo que hemos cambiado se lista abajo.

**Estado: no cierra el flujo entero en este contenedor, y no por nuestro
diseño.** Ver «El muro de las herramientas» al final. Lo que sí está
comprobado, corriendo de verdad, llega hasta la generación del padring.

---

## Los números del vendedor, que no se tocan

```
DIE_AREA   [0, 0, 1936, 2531]         1936 x 2531 um
CORE_AREA  [442, 442, 1494, 2089]     1052 x 1647 um
sello 26 um por lado, padring 350 um de alto
```

El core real, tras ajustarse OpenROAD a la rejilla de sitios, va de
`x 442.400 .. 1493.520` y `y 442.960 .. 2085.440`: 419 filas de 3.92 um. El
`CORE_AREA` declarado sigue siendo el de arriba y es contra ese que se colocan
los macros y el anillo.

El reparto de pads son **56 posiciones: 11 sur, 17 este, 11 norte, 17 oeste**,
48 de señal y 8 de alimentación. Se conserva, y hay que conservarlo, porque
`pad_cfg.tcl` reparte cada fila **por cuenta**: divide el hueco sobrante entre
el número de pads más uno. Cambiar un contador mueve todos los pads de ese
lado. Confirmado en el log del propio OpenROAD:

```
norte  hueco 1174 um, 825 de celdas, 349 de relleno, 29.0 entre pads
este   hueco 1769 um, 1275 de celdas, 494 de relleno, 27.4 entre pads
```

Lo que sí es nuestro es **qué celda va en cada posición de señal**, y eso sale
gratis: todas las celdas de señal de `gf180mcu_fd_io` miden **75 × 350 um**
—`bi_24t`, `asig_5p0`, `in_c`, `dvdd`, `dvss`, las mismas—, así que cambiar una
por otra no mueve nada.

## El macro

```
instancia    i_chip_core.u_nav
location     [442, 1702.01]
orientation  FS
```

`location` es la esquina inferior izquierda de la caja **ya orientada**;
comprobado contra odb, no supuesto, porque para un macro espejado la diferencia
es una altura entera de celda. Con eso el bloque ocupa

```
x  442.00 .. 902.90        y  1702.01 .. 2089.00
```

es decir, pegado al techo y al costado izquierdo del core.

**FS, espejo vertical, y esa es la decisión que hace funcionar la esquina.** Tal
como está dibujado, las ocho entradas analógicas salen por el borde INFERIOR;
para llegar a los pads del norte tendrían que bajar 387 um, rodear un bloque que
es obstrucción maciza en los cinco metales, y volver a subir. Espejado salen por
el borde superior, en `y = 2089.00` exacto, a 66 um del padring. La alimentación
se queda en el borde izquierdo mirando al oeste; las salidas, a la derecha,
hacia dentro del core.

Posiciones reales de los pines tras el espejo, leídas de odb:

```
S1P 467.5  S1N 472.5  S2N 477.6  S2P 482.6      y = 2088.48 .. 2089.00
S3P 578.4  S3N 583.4  S4N 588.4  S4P 593.5
ZP  y 1781.3   YP  y 1831.7   XP  y 1872.0      x = 902.38 .. 902.90
VDD, VSS   siete tetillas de Metal5             x = 442.00 .. 445.00
```

## El padring

| lado | qué lleva |
|---|---|
| **norte** (11) | 8 `asig_5p0` (S1P S1N · S2N S2P · S3P S3N · S4N S4P), los 2 de alimentación en su sitio del vendedor, 1 bidir libre |
| **este** (17) | 3 `bi_24t` en salida (ZP, YP, XP, de abajo arriba), 2 de alimentación, 12 bidir libres |
| **norte/este** | el orden sigue el de los pines a lo largo del borde del macro, que es lo que evita que las pistas se crucen |
| **oeste** (17) | intacto: el par VDD/VSS de core y las cuatro entradas donde los pone el vendedor |
| **sur** (11) | intacto: reloj, reset, un par de alimentación y siete bidir libres |

Distancias resultantes, pad a pin:

```
S1P  19.5    S1N  79.5    S2N 386.4    S2P 485.4
S3P 493.6    S3N 592.6    S4N 691.6    S4P 790.5      um
ZP   98.6    YP  150.6    XP  212.7
```

**Las analógicas salen largas y hay que decirlo.** Los pads del norte van a
104 um de paso y cubren 1176 um; los pines del macro se apiñan en 126 um. No se
puede arreglar sin mover pads, que es justo lo que el vendedor fija. Lo que sí
está cuidado es lo que de verdad importa en un puente diferencial: **los dos
extremos de cada par van en pads contiguos**, así que la diferencia dentro del
par es de ~99 um en tres pares y 60 um en el primero, no de 700. Y esa
diferencia no produce offset: las ocho entradas van directas a puertas de MOS
(`sub_diff_2_LIN`, `XM15`/`XM16` P y `XM21` N), sin resistencia de entrada, así
que la corriente por esas pistas es de fuga. Lo que queda es desapareo de
capacidad y acoplo, que afecta al establecimiento y al ruido, no a la exactitud.

**Solo salen XP, YP y ZP.** `X`, `XN`, `Y`, `YN`, `Z` y `ZN` se quedan al aire.
XN es el complemento exacto de XP —el chip no saca signo—, así que su pad no
añade información, y son seis pads y seis pistas cruzando el core para nada.

## Corriente, conexión por conexión

Los límites salen del tech-LEF (`DCCURRENTDENSITY AVERAGE`), no del DRC:
**Metal1–4 = 0.67 mA/um, Metal5 = 1.5 mA/um, vía = 0.18 mA/corte.**

| qué | corriente | cómo queda |
|---|---|---|
| VDD/VSS del macro | 31 mA de diseño (pico medido 15.5) | 28.45 um de Metal5 en VDD → 42.7 mA; 37.07 um en VSS → 55.6 mA |
| anillo de core | los mismos 31 mA | subido de 25 a **30 um**, el máximo sin ranurar: 20.1 mA por lado, 40.2 en anillo cerrado |
| pads de alimentación | 31 mA repartidos | **4 pads de VDD y 4 de VSS**, no uno: en `gf180mcu_fd_io` la celda `vdd` ES una `dvdd` y `chip_top.sv` cortocircuita `VDD = DVDD`. 7.75 mA por pad |
| S1P…S4N | cero DC | puertas de MOS. Manda el apareo, no la electromigración |
| XP, YP, ZP | uA | entran a la puerta de un `bi_24t` |

Las bandas de Metal5 que atacan las siete tetillas **se generan desde el LEF**
(`openroad/scripts/waferspace_collateral.py` → `librelane/pdn/pdn_nav.tcl`), no
se escriben a mano: si el bloque se vuelve a endurecer y las tetillas se mueven,
las bandas se mueven con ellas. Son bandas del grid del core, no del grid del
macro, a propósito: pdngen recorta el grid del core en el halo del macro, así
que cada una entra desde el anillo oeste, se para en el bloque y aterriza en su
tetilla. Una banda del grid del macro se dibujaría **atravesándolo**, y el
bloque es obstrucción maciza en los cinco metales con su propia malla de Metal5
debajo.

Su paso no puede ser regular: las tetillas están a 43 um unas de otras abajo y a
65 arriba, porque vienen de estanterías de distinta altura.

Falta un número: **cuánta corriente admite un pad `dvdd`/`dvss`**. Es el único
hueco de la tabla y es pregunta para wafer.space.

---

## Todo lo que se cambió de la plantilla

| fichero | qué |
|---|---|
| `src/slot_defines.svh` | `NUM_ANALOG_PADS` 4 → **8**, `NUM_BIDIR_PADS` 38 → **34**. El total de señal sigue siendo 48 |
| `src/chip_top.sv` | `(* keep *)` en `clk_pad` y `rst_n_pad` — ver abajo |
| `src/chip_core.sv` | reescrito: instancia el macro y ata los pads. Sin lógica, sin SRAM |
| `librelane/slots/slot_0p5x0p5.yaml` | el padring de arriba |
| `librelane/macros/macros_5v.yaml` | fuera las dos SRAM de demostración, dentro el macro |
| `librelane/pdn/pdn_cfg.tcl` | en vez de las SRAM, `pdn_nav.tcl` |
| `librelane/pdn/pdn_nav.tcl` | **generado**, no editar |
| `librelane/config.yaml` | anillo a 30 um, `GRADIENT_NAV2_V3` en `IGNORE_DISCONNECTED_MODULES`, y el bloque de compatibilidad de PDK |
| `Makefile` | `PDK_ROOT` incondicional, slot por defecto `0p5x0p5`, `MACROS` fijado a `5v` |
| `ip/gradient_nav2_v3/` | GDS y LEF **enlazados** a `openroad/`, nunca copiados; `.lib` y `.v` generados |

### `(* keep *)` en el reloj y el reset

Todos los pads de `chip_top.sv` lo llevan menos esos dos, que se instancian
sueltos. En la plantilla sobreviven porque su core usa `clk` y `rst_n`. Este
core es un bloque analógico y no usa ninguno, así que yosys borró las dos
celdas — y no se vio hasta tres etapas después, como
`add_global_connections failed to make any connections for 'clk_pad/DVDD'`.
Borrarlos no era opción: son dos de las 11 posiciones de la fila sur, y el
contador de la fila es lo que fija dónde cae cada pad de ese lado.

### El `.lib` del bloque

No existía: `build_collateral.py` solo había generado vistas de las hojas, nunca
del top. Ahora lo genera `waferspace_collateral.py`, que comprueba además que
**el LEF y el netlist de xschem declaran los mismos 19 puertos** antes de
escribir nada. Y se le añadieron a `write_lib` los umbrales de conmutación:
OpenSTA rechaza una librería sin ellos —«Library GRADIENT_NAV2_V3 is missing one
or more thresholds»— y rechazarla es tumbar el run entero. Los valores están
copiados de `gf180mcu_fd_sc_mcu7t5v0`, no inventados.

---

## El padring dibujado, sin librelane

El flujo de librelane no cierra en este contenedor (siguiente seccion), pero el
padring **si** se puede montar, y con GDS que se abre. Todo esta en `flow/`, y
sale en `out/`:

```
flow/floorplan.tcl    el marco del vendedor, los 56 pads y el bloque
flow/gds.py           DEF -> GDS con la geometria real dentro
flow/render.py        GDS -> PNG
flow/figura.py        el diagrama de ocupacion
flow/cuatro.tcl       el die completo partido en cuatro
flow/figura4.py       su diagrama
flow/collateral.py    .lib y .v del bloque, y pdn_nav.tcl
flow/pad_sites.lef    los dos sitios del anillo

out/quarter.def       589 instancias: 56 pads, 4 esquinas, relleno y el bloque
out/quarter.gds       24 MB de geometria real
out/quarter_layout.png
```

Se monta con **`make_io_sites` + `place_pad` + `place_corners` +
`place_io_fill`**, que es el generador de padrings de OpenROAD y el mismo que
usa por dentro el flujo del fabricante. Orienta cada fila el solo, que no es un
detalle: el bond pad de la celda esta en su base (`RECT 7.5 2.0 67.5 62.0` en
Metal5, con las senales de core arriba en y = 264..350), asi que al sur le vale
`R0` y al norte `MX`, pero al este **ninguna rotacion pura** sirve — hace falta
un espejo. Orientarlas a mano salio mal a la primera.

**Lo que NO se llama es `connect_by_abutment`.** Aqui solo se quiere la
geometria, y esa llamada es exactamente la que revienta en librelane
(`PAD-0002`). Saltandosela se obtiene el anillo dibujado sin tropezar con un
fallo que no es nuestro.

Tres cosas que costaron una corrida cada una, por si alguien las repite:

* **`fillnc` es imprescindible en la lista de rellenos.** Los de 10, 5 y 1 um no
  cubren los 29.5 um que el reparto deja contra la esquina: falta el medio
  micrometro. `fillnc` mide 0.1 um. Sin el, `PAD-0030`.
* **Los sitios del anillo no estan en el LEF.** Las celdas referencian
  `GF_IO_Site` y `GF_COR_Site` y nadie los define; `flow/pad_sites.lef` los
  crea con las medidas que librelane usa en `PAD_FAKE_SITES`.
* **La comprobacion mide el bond pad, no la caja del terminal.** La envolvente
  de un `asig_5p0` incluye la tira de Metal2 que sube al core, y la de un
  `dvdd` el rail que cruza la celda; midiendo eso, la mitad de los pads salian
  "mal orientados" estando bien.

`out/` no sube al repositorio de herramientas: es salida, y `flow/` la rehace
desde el DEF en segundos.

---

## El muro de las herramientas

La plantilla sigue la rama **`dev`** de librelane, con toda la cadena fijada por
nix. En este contenedor no hay nix, y ninguna combinación disponible cierra:

| combinación | dónde se rompe |
|---|---|
| librelane `dev` (3.1.0.dev3) | su script de síntesis llama al paso de yosys `arith_tree`; el contenedor tiene yosys **0.64**, que no lo tiene |
| librelane 3.0.14 | `corner.tcl` llama a `set_scene_cmd`; el OpenROAD del contenedor (26Q2) tiene `set_scene`, no eso. Es *más nueva* que su OpenSTA |
| librelane 3.0.2 (la del contenedor) | llega hasta el padring y muere en `connect_by_abutment` |

Con la 3.0.2 hicieron falta cuatro variables de compatibilidad, todas anotadas
en `config.yaml`, porque este PDK usa nombres que solo `dev` lee: `LIB` (el PDK
declara `CELL_LIBS`, que la 3.0.2 no conoce, y sin eso yosys no tiene ni celdas
que mapear ni definición de ningún pad), `EXTRA_VERILOG_MODELS`,
`DEFAULT_CORNER`/`SYNTH_CORNER` (el PDK pone el prefijo `nom_`, no el nombre
completo) y `PAD_LIBS: {}` (la 3.0.2 recorre el diccionario como lista plana e
intenta abrir la clave como fichero).

Con eso el flujo llega a la **etapa 17 de 83** y falla así:

```
[PAD-0002] IO_FILL_IO_NORTH_2_270/VSS (VSS) and
           IO_FILL_IO_NORTH_2_280/VSS (DVSS) are touching,
           but are connected to different nets
```

**No es nuestro diseño.** La plantilla sin modificar, con el mismo PDK y las
mismas variables, falla en el mismo punto con los mismos nombres de celda —
está en `../waferspace_baseline/`, montado justo para poder decir esto. La
causa está a la vista en el log del paso anterior: de 56 pads, 56 reciben
`DVDD→DVDD` y `DVSS→DVSS` pero solo **53** reciben `VDD→VDD` y `VSS→VSS`. Las
celdas `gf180mcu_fd_io__dvdd` no tienen pin `VDD` y las `dvss` no tienen `VSS`,
así que el raíl se interrumpe en ellas y este OpenROAD considera la
discontinuidad un error en vez de un corte deliberado.

Para cerrarlo hace falta la cadena que la plantilla fija: yosys > 0.64 junto con
librelane `dev`. Lo que no se ha hecho es forzarlo desde aquí cambiando el
cableado de alimentación de los pads: sería tocar la alimentación de un chip que
va a fábrica para rodear un fallo que no es suyo.

## Cómo se corre

```bash
cd waferspace
make clone-pdk     # una vez; 4 GB, dentro del proyecto, ya en .gitignore
make librelane
```

`PDK_ROOT` está fijado **incondicionalmente** al del proyecto. Tiene que estarlo:
en este contenedor `.designinit` ya exporta `PDK_ROOT=/foss/designs/pdks`, y con
el `?=` de la plantilla este flujo instalaría en el PDK del Chipathon y
cambiaría con `ciel enable` cuál es la versión activa. Además la versión que hay
instalada allí (`7b70722e`) no trae
`libs.tech/librelane/gf180mcu_fd_io/config.tcl`, o sea que no tiene
`PAD_SITE_NAME` y con ella el padring no arranca siquiera.

Y si se toca el LEF del bloque, antes de nada:

```bash
cd ../openroad && python3 scripts/waferspace_collateral.py
```

## Lo que hay que preguntar a wafer.space

* Si el reparto de 56 pads es **obligatorio** para su encapsulado y su test, o
  si es solo la configuración por defecto. Todo esto asume lo segundo: conserva
  la geometría y cambia los tipos.
* Cuánta corriente admite un pad `dvdd`/`dvss` de `gf180mcu_fd_io`.
* Con qué versión exacta de librelane y de yosys validan ellos las entregas.
