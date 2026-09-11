# Plan de pines y conexiones — nuestro cuarto

Todos los números salen de `flow/cuatro.tcl`. Ninguno está escrito a mano.

---

## La respuesta corta: no estamos cortos, sobra sitio

```
posiciones en el arco norte   21     (x 381 .. 1966, pads de 75 um apretados)
posiciones en el arco oeste   29     (y 2561 .. 4741)
total disponibles             50
usados ahora                  17     8 analógicos, 3 salidas, 6 de alimentación
LIBRES                        33
```

Usamos **un tercio** de lo que hay. Así que **no hay que quitar nada**, y de
hecho las salidas que proponías quitar ya están fuera: `XN`, `YN`, `ZN`, `X`,
`Y` y `Z` no tienen pad desde el primer diseño. Solo salen `XP`, `YP` y `ZP`.

---

## El ESD secundario no gasta ni un pin

Va **en serie entre el pad y el core**, no en paralelo con un pad propio. Cuesta
área y ruteo. Y el área es despreciable:

```
ESD_CDM        63.16 x 27.90 um = 1762 um2 cada uno
hacen falta    8, uno por entrada = 14 097 um2 = 0.0141 mm2
```

Contra los 3.23 mm² de core que nos tocan, es el **0.4 %**.

### Y caben exactamente donde deben

Entre el borde interior del padring y el techo del core quedan **66 µm**. El
`ESD_CDM` mide 27.9 de alto. Los ocho en fila ocupan 505.3 µm de ancho y sus
pads cubren 600.

**Caben en esa banda, cada uno debajo de su propio pad, sin entrar en el core.**
Que es además donde deben estar: un clamp secundario sirve para cortar el pico
*antes* de que llegue a la puerta, así que cuanto más cerca del pad, mejor.

### Por qué hacen falta, si el pad ya trae diodos

`gf180mcu_fd_io__asig_5p0` **sí** trae ESD primario, y bueno:

```
D2  DVSS -> ASIG5V   diode_nd2ps_06v0  m=4  area=150 pm2  pj=106 um
D3  ASIG5V -> DVDD   diode_pd2nw_06v0  m=4  area=150 pm2  pj=106 um
D0  DVSS -> DVDD     clamp de raíl,    m=4
X1  36 x cap_nmos_06v0 de 15 x 15 um   desacoplo
```

Lo que **no** trae es **resistencia serie ni clamp local**. Y nuestras ocho
entradas van directas a puertas de MOS — comprobado en el netlist,
`sub_diff_2_LIN`: `XM15`/`XM16` PMOS y `XM21`/`XM22` NMOS, con la señal en la
puerta y nada en serie. Una puerta desnuda sin resistencia delante es
exactamente el fallo por CDM: los diodos del pad son grandes y lentos, y el
pico llega a la puerta antes de que conduzcan.

`ESD_CDM` es la segunda etapa: ocho diodos más la resistencia serie. Es nuestra
celda, dibujada cuando la de los organizadores resultó traer un `MSLOT.1`
dentro, once veces.

Las tres salidas digitales **no** lo necesitan: `bi_24t` son 562 líneas de
netlist con su propio driver, receptor y protección completa.

---

## Por qué X, Y y Z conviene dejarlos fuera aunque sobren pines

Mirando cómo se instancia el búfer de salida:

```
.subckt COMP_OUT  VDD  OUT  IN  OUT_N  VSS
x8 VDD XN X XP VSS COMP_OUT
```

o sea `OUT = XN`, `IN = X`, `OUT_N = XP`. **`X` es la entrada**: el nodo crudo
del comparador, antes de los dos inversores. Sacarlo por un pad le colgaría la
capacidad del pad y del ESD **directamente a la salida del comparador**, que es
el nodo que decide. Es señal de observación, y observarla la cambia.

`XN` es `X` bufferizado y `XP` es su complemento, así que entre `XP` y `XN` no
hay información nueva. Los tres pads que usamos son los correctos.

---

## La distribución

### Arco norte — 13 de 21 posiciones

| posición | celda | señal | por qué ahí |
|---|---|---|---|
| 1–8 | `asig_5p0` | S1P S1N · S2N S2P · S3P S3N · S4N S4P | lo más a la izquierda que deja la esquina, o sea lo más cerca de los pines del bloque. El orden sigue el de los pines a lo largo de su borde, y **cada par en pads contiguos** |
| 9–11 | `bi_24t` | ZP YP XP | detrás, porque las digitales aguantan la pista larga |
| 12–13 | `dvss` `dvdd` | — | alimentación de la mitad norte del anillo |

### Arco oeste — 4 de 29 posiciones

| posición | celda | por qué ahí |
|---|---|---|
| las 4 más altas | `dvdd` `dvss` `dvdd` `dvss` | enfrente de las tetillas de alimentación del bloque, que están en `y 4342 .. 4669` |

Quedan **8 libres al norte y 25 al oeste**.

---

## Cómo se conecta cada cosa

### Las ocho entradas analógicas

```
pad asig_5p0 (ASIG5V)  →  ESD_CDM.PAD  →  ESD_CDM.CORE  →  bloque, borde superior
```

El ESD va en la banda de 66 µm, debajo de su pad. Del `CORE` del ESD al pin del
bloque, Metal2, bajando los pocos micrómetros que quedan hasta `y = 4680`.

Corriente: **cero DC**. Son puertas de MOS. Lo que manda es el apareo, y por eso
cada par va en pads contiguos: la diferencia dentro del par es de un paso de pad
para los cuatro, igual en todos, así que los cuatro puentes ven el mismo
desapareo y ninguno se sesga respecto a otro.

### Las tres salidas digitales

```
bloque, borde derecho (Metal3)  →  bi_24t.A     con OE = 1, IE = 0
```

Microamperios. Ancho mínimo sobra.

### La alimentación del bloque

```
pads dvdd/dvss del oeste  →  anillo propio del cuarto  →  Metal5, siete tetillas
                                                          del borde izquierdo
```

**El anillo tiene que ser nuestro, dentro del cuarto.** El anillo de core del
flujo rodea el core entero y cruzaría a los otros tres proyectos, que es justo
lo que dijimos que no. Cada proyecto se alimenta de sus propios pads.

Dimensionado: 31 mA de diseño (15.5 de pico medido). Los límites del tech-LEF
son 0.67 mA/µm en Metal1–4, 1.5 en Metal5 y **0.18 mA por corte de vía**:

* Anillo a **30 µm** en Metal3/Metal4 — el máximo sin ranurar: 20.1 mA por lado,
  40.2 en anillo cerrado.
* Las tetillas del bloque ya dan de sobra: 28.45 µm de Metal5 en VDD → 42.7 mA,
  37.07 en VSS → 55.6 mA.
* **Las vías son el cuello**: bajar 31 mA de Metal5 al anillo pide **≥ 173
  cortes**. Eso no lo pone `pdngen` solo; hay que declarar la matriz y contarla
  después.
* Reparto por pad: 3 de VDD y 3 de VSS → **10.3 mA cada uno**.

### La alimentación de los ESD — el punto que se olvida

Cada `ESD_CDM` tiene pines `VDD` y `VSS`, y **hay que atarlos al anillo**.

Esto ya nos pasó: en `B26_A` los once clamps se quedaron sin alimentar. Un ESD
secundario sin VDD ni VSS **no sujeta nada** — sus diodos no tienen a dónde
descargar. No lo dice el DRC, porque la geometría está perfectamente dibujada, y
el ruteo de señal tampoco, porque VDD y VSS son nets `special` y el router no
las toca. Lo cantó el LVS, y de una forma que hay que saber leer: doce nets del
layout con el cátodo del diodo y el pozo de la resistencia sin emparejar.

### DVDD y DVSS

Se reparten solos por **abutición** a lo largo del anillo de pads. Ojo con una
cosa que ya conocemos: `gf180mcu_fd_io__dvdd` no tiene pin `VDD` y `dvss` no
tiene `VSS`, así que el raíl se interrumpe en ellas. Es lo que hace fallar a
`connect_by_abutment` en el flujo de librelane con `PAD-0002`.

En la librería `fd` **`VDD` está cortocircuitado con `DVDD`** en `chip_top.sv`,
así que de hecho hay un solo dominio de alimentación.

---

## Lo que queda por decidir

1. **Dónde van exactamente los 8 `ESD_CDM`.** Caben en la banda; falta colocarlos
   y comprobar el DRC de esa zona, que es estrecha.
2. **El anillo propio del cuarto**: trazado, ancho y la matriz de vías.
3. **Si se aprovechan las 33 posiciones libres.** Con tanto margen se podría
   sacar `X`, `Y` y `Z` a pads de test — pero ver arriba por qué no conviene, y
   si se hace, con un búfer delante y no colgados del nodo.
4. **Si los otros tres proyectos aceptan el reparto** de 50 posiciones por
   esquina.
