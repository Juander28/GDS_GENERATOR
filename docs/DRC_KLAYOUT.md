# DRC con KLayout en IIC-OSIC-TOOLS — bitácora viva

Documento operativo **y** registro acumulativo del ciclo SPICE → GDS → DRC para los
layouts generados con `coil_layout` sobre GF180MCU.

> **Estado:** iteración #40 completada — hay **dos versiones del layout**, las dos
> verificadas. La **v2** (`build_block.py <BLOQUE> --v2`, salida a `layouts_v2/`) baja el
> área un **7.3 %** en total —`DECODER` −17 %, `OPAM` −9.1 %— con DRC 0 y LVS limpio en las
> dos herramientas, comparada contra la **misma** netlist de referencia que la v1. Ver
> §13. Los bancos instancian las dos al lado del esquemático (§14), y el **top**
> se puede armar con cualquiera de las dos (`make top V=v2`): sale un **6.9 %**
> más pequeño, con DRC de firma limpio y **LVS que casa** (§15).
>
> **Hay un tercer top**, `GRADIENT_NAV2`, que es el navegador montado con `GRADIENT2`
> —el de la cadena lineal— en vez de con `GRADIENT`: **418.24 × 413.53 µm = 0.1730 mm²**,
> DRC de firma limpio y **55/55 nets con 0 cortos** (§15.4). Construirlo destapó un fallo
> que llevaba escondido desde que existe `OPAM_LIN_flat`: **magic traza los puertos a
> través del cuerpo de una resistencia de poly**, así que su LEF declaraba como `OUT`
> metal de los dos lados de la realimentación y el router aterrizaba en el equivocado
> (§15.5). Arreglado en `build_collateral.py`.
>
> `GRADIENT_NAV2` lleva ahora **229 transistores de desacople metidos en los huecos entre
> macros** —36 baldosas, 22 407 µm² de los 25 183 útiles (89 %), **~5.11 pF**— y **los
> mismos transistores en su esquemático**, escritos por el generador (§15.6). Los tres
> ficheros del top (pelado, con desacople y con relleno de densidad) están con **DRC de
> firma limpio**, el de relleno además con **las reglas de densidad limpias**, y el LVS
> **casa en las dos herramientas**.
>
> Ese LVS **nunca se había corrido** antes de esta iteración, y al correrlo salieron **dos
> fallos reales de las propias herramientas de verificación**, no del layout: `align_ports`
> no plegaba las continuaciones `+` del `.subckt` —así que al top extraído le faltaba el
> puerto `VSS`— y ni netgen ni KLayout sabían de la hoja de **3 kΩ/□** en el top, que es lo
> que el esquemático pide y lo que magic no puede distinguir (§15.7).
>
> **El top está listo para un padring.** Es una sola celda plana y autocontenida, sus 19
> puertos llevan texto en las capas de etiqueta, `VDD` y `VSS` salen **al borde del die** y
> declarados `POWER`/`GROUND`, los pines van a **5.04 µm** unos de otros y nada más que los
> puertos toca el contorno: el relleno y el desacople se apartan **2 µm** (§15.8). Están
> escritos `info.yaml` y `lvs_config.json` en la raíz del proyecto.
>
> Y hay banco para el top: `XSCHEM/TEST_TOTAL/test_NAV2.sch` compara el esquemático contra
> el navegador **rehecho con los 31 bloques extraídos del layout con parásitos RC**. A
> fondo de escala difieren en **14° de 360**, todos en el canto de los escalones; en la
> ventana fina, en **0°**, con 1.9 mV de diferencia máxima (§16).
>
> **Lo único abierto en verificación:** magic ve **24 `MIMTM.8a`** en `GRADIENT_NAV2` —dos
> por cada `OPAM_LIN_flat`—, que **son anteriores a todo esto** y que KLayout no ve porque
> su versión de la regla mide área (25 µm²) donde la de magic mide **ancho de placa
> superior (5 µm)**. El bloque suelto da 222 con magic. Está en §17.
>
> Lo que sigue describe la **v1**, que no ha cambiado y hace de control.
>
> **Estado de la v1:** iteración #29 completada — **DRC 0 y LVS LIMPIO EN LAS DOS
> HERRAMIENTAS, en los CINCO bloques**, `OPAM_LIN_flat` incluido y con su
> resistencia de realimentación dentro y conectada. KLayout dice
> `Congratulations! Netlists match.` en los cinco y netgen empareja los cinco
> (`COMP`, `OPAM` y `OPAM_LIN_flat` con avisos de propiedad, que son el choque de
> convenios `A`/`P` contra `W`/`L` de los MIM — §11.1, no una diferencia de
> circuito).
> `WEIGHT_COMP` mide **37.17 × 25.00 µm = 929 µm²**, `DECODER` **37.89 × 15.84 µm**,
> `COMP` **104.28 × 31.46 µm**, `OPAM` **88.27 × 31.46 µm** y `OPAM_LIN_flat`
> **98.22 × 46.57 µm**. Floorplan de **tres filas (P / N1 / N2)**, dos
> canales de ruteo y **9 puertos** etiquetados. Se exporta también a `.mag` y a **tres**
> netlists extraídas (sin parásitos, con C y con RC — §5.1.2). La netlist de entrada es un
> **enlace simbólico** al netlist de Xschem (§5.1).
>
> **Novedad de esta iteración:** el generador soporta **resistencias de poly**
> (`coil_layout/resistors.py`): serpentín metido en el canal de ruteo entre las filas P y
> N, que cuesta ~5 % de área en vez del ~94 % que costaba una banda lateral. La primera
> integración completa sacó **1222 violaciones en 48 reglas** y se cerró en seis pasos
> (iteraciones #19-#24); las causas están destiladas en §41-§46. **Una de esas seis fue un
> falso limpio**: la resistencia desapareció del layout sin avisar y el DRC bajó igual
> (§46). La comprobación que lo cierra es medir el área del marcador `res_mk`, que tiene
> que dar `s·L·W` exactos (§5.6.6).
>
> **`OPAM_LIN_flat` cerrado** (iteración #29). Lo que quedaba no era un problema de
> floorplan, como se había leído, sino **cinco fallos distintos que sólo veía el LVS** y
> que el DRC daba por buenos: la resistencia salía atada al sustrato por su propia toma de
> cuerpo (§11.0.3), `term1` apuntaba a un nodo interno en vez de al extremo libre (§11.0.4),
> el ruteo cortocircuitaba `G_OUT_P` con `OUT` por un giro que no compensaba (§11.0.5), una
> placa MIM encima del terminal impedía que la extracción lo conectara (§11.0.6), y la
> longitud del cuerpo que pedía el esquemático no era dibujable en rejilla (§11.0.7).
> Además, `run_lvs.sh` había dado un **LIMPIO falso**: juzgaba a KLayout por su código de
> salida (§12.5) y la netlist de referencia **no llevaba la resistencia** (§11.0.8).
>
> **`ppolyf_u_3k` sí se puede verificar** — lo que decía §11.0.2 era incompleto. El deck de
> KLayout tiene rama para 1k, 2k y 3k y lee `$poly_res`; quien fija 1k es sólo la tabla de
> variantes de `run_lvs.py`. Llamando al deck directamente con `-rd poly_res=3k` la
> extracción sale con `POLY_RES Selected is 3k` y 229 350 Ω por tramo (§11.0.2).
>
> Los **otros cuatro** bloques mantienen su tamaño **al milímetro** tras todos estos
> cambios, con DRC 0 y LVS limpio en las dos herramientas.
> Ver [Bitácora](#8-bitácora-de-iteraciones) y [LVS](#12-lvs).

---

## 0. Protocolo de actualización (leer antes de escribir aquí)

Este archivo está pensado para **crecer**. Reglas:

1. **Después de cada corrida de DRC** se añade una fila a la [Bitácora](#8-bitácora-de-iteraciones).
   Nunca se sobrescribe una fila anterior: el valor del documento está en poder comparar
   iteración N contra N-1.
2. **Nunca se borra una entrada.** Si un hallazgo se resuelve, se marca `RESUELTO` con la
   fecha y el commit/cambio que lo arregló; se queda como historia.
3. **Si un hallazgo aparece dos veces**, sube de la bitácora a
   [Lecciones aprendidas](#9-lecciones-aprendidas) redactado como regla general, no como
   anécdota. Ahí es donde el documento realmente "aprende".
4. **Las hipótesis se marcan como tales.** Nada se escribe como causa confirmada sin
   haberlo verificado contra el `.lyrdb`. Se usa `HIPÓTESIS` / `CONFIRMADO`.
5. **Los comandos que se peguen aquí deben haberse ejecutado tal cual.** Si un comando
   falló y hubo que corregirlo, se documenta el fallo en
   [Trampas conocidas](#10-trampas-conocidas-del-entorno) — ahorra repetir el error.
6. Al cerrar una sesión de trabajo, actualizar la línea **Estado** de arriba y
   [Pendientes](#11-pendientes).

---

## 1. Por qué hace falta el contenedor

El `klayout` que instala `pip` (`klayout==0.29.12`, el que usa el venv de Windows) es
**solo la API de Python**: `klayout.db`, `klayout.rdb`. Los *rule decks* `.drc` están
escritos en el DSL de KLayout, que se interpreta en **Ruby dentro del binario completo**.
Ese binario no está en el entorno de Windows, y por eso el flujo nunca pudo verificarse
—el README del generador advierte "el ruteo es best-effort, no garantiza DRC limpio".

El contenedor sí trae el binario completo (KLayout 0.30.8) y los decks del PDK.

---

## 2. Entorno (verificado el 2026-08-01)

| Dato | Valor |
|---|---|
| Contenedor | `iic-osic-tools_chipathon_xvnc` |
| Imagen | `hpretl/iic-osic-tools:chipathon26` |
| KLayout | 0.30.8 (binario en `/foss/tools/klayout/`) |
| `PDK_ROOT` | `/foss/pdks` — `gf180mcuD`, `sky130A`, `ihp-sg13g2` |
| Deck GF180 | `/foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/gf180mcu.drc` |
| Runner oficial | `/foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py` |
| Helper JKU | `/foss/tools/sak/sak-drc.sh -k <cell>` (alias `iic-drc.sh`) |
| Volumen | `C:\Users\juand\Documents\GitHub\sscs-2026-zotnetic\designs` → `/foss/designs` (RW) |
| Proyecto (generador) | `/foss/designs/zotnetic_layout/` (= esta carpeta) |
| venv del proyecto | `/headless/.venvs/zotnetic` (dentro del contenedor) |
| **Netlists de entrada** | `/foss/designs/a_zonetic2026/spice_blocks/<BLOQUE>.spice` |
| **Layouts generados** | `/foss/designs/a_zonetic2026/layouts/<BLOQUE>/` |

**El volumen es un espejo.** Lo que edites en Windows aparece al instante en el
contenedor y viceversa. No hay que copiar nada entre iteraciones.

**Entrada y salida separadas** (desde la iteración #5). El código del generador se queda
en `zotnetic_layout/`; las netlists que exporta Xschem viven en `a_zonetic2026/spice_blocks/`
y todo lo generado va a una carpeta por bloque bajo `a_zonetic2026/layouts/`. Las netlists
derivadas (`_flat`, `_lvs`) se escriben en la carpeta de **salida** a propósito:
`spice_blocks/` es entrada del usuario y no debe ensuciarse con artefactos.

---

## 3. Setup (una sola vez, o si se recrea el contenedor)

El Python del sistema del contenedor trae **gdsfactory 9.44 / kfactory 2.5 / pydantic 2.12**,
pero el proyecto está clavado a **9.2.2 / 1.2.2 / 2.9.2** (salto *major* en kfactory).
Por eso se usa un venv aislado, **no** el Python del sistema:

```bash
docker exec iic-osic-tools_chipathon_xvnc bash -c '
  python3 -m venv /headless/.venvs/zotnetic &&
  /headless/.venvs/zotnetic/bin/pip install -r /foss/designs/zotnetic_layout/requirements.txt'
```

Instala las versiones exactas del `requirements.txt`, incluido `gf180==0.1.1`
(que **no** viene en la imagen). Tarda ~2 min.

El venv vive **dentro** del contenedor a propósito: sobre el bind-mount de Windows la
instalación de decenas de miles de archivos es lentísima. El precio es que hay que
repetir este comando si se recrea el contenedor — el código, que sí está en el volumen,
no se pierde nunca.

Verificación:

```bash
docker exec iic-osic-tools_chipathon_xvnc \
  /headless/.venvs/zotnetic/bin/python -c "import gdsfactory,kfactory;print(gdsfactory.__version__,kfactory.__version__)"
# -> 9.2.2 1.2.2
```

---

## 4. Archivos que viven aquí

**Copiados desde `C:\Users\juand\Desktop\gds factory`:**

| Ruta | Rol |
|---|---|
| `coil_layout/` | generador: `spice_parser`, `device_map`, `pdk_manager`, `placement`, `routing`, `caps` (MIM), **`resistors`** (poly, §5.6), `power`, `flow`, `gui` |
| `flatten_spice.py` | aplana jerarquía Xschem → `.subckt` plano de MOSFETs |
| `test_flow.py` | flujo headless parse→place→route→export |
| `app.py` | GUI Tkinter (opcional; funciona por VNC) |
| `requirements.txt` | versiones clavadas — **es lo que hace reproducible el venv** |
| `zonetic/spice/` | `WEIGHT_COMP.spice` (jerárquico) y `WEIGHT_COMP_flat.spice` |
| `examples/` | netlists de prueba |

**Deliberadamente NO copiados:** `.venv/`, `.venv-glayout/` (binarios Windows, inservibles
en Linux), `out/`, `zonetic/gds/*` (se regenera), `DESIGNS/`, `docs/`.

**Generado, ignorado por git** (ver `.gitignore`): `zonetic/gds/*.gds|png`, `drc_run/`, `__pycache__/`.

---

## 5. Ciclo de trabajo

Los cuatro pasos, con los comandos **tal como se ejecutaron**:

### 5.1 Generar el layout (aplanar + colocar + rutear + exportar)

Desde la iteración #5 los dos primeros pasos van juntos en `build_block.py`, que lee de
`spice_blocks/` y escribe en `layouts/<BLOQUE>/`:

```bash
docker exec iic-osic-tools_chipathon_xvnc bash -c \
 'cd /foss/designs/zotnetic_layout && env -u PYTHONPATH \
  /headless/.venvs/zotnetic/bin/python build_block.py WEIGHT_COMP'
```

> **La fuente de verdad es siempre el `.spice` de `spice_blocks/`, y ahí son enlaces
> simbólicos al netlist que escribe Xschem:**
>
> ```
> spice_blocks/WEIGHT_COMP.spice
>   -> XSCHEM/WEIGTH/simulation/WEIGHT_COMP.sch/WEIGHT_COMP.spice
> ```
>
> Así basta con exportar desde el esquemático: no hay que copiar nada y **no puede quedarse
> una copia vieja**, que era el riesgo real. Ojo con el nombre: `WEIGHT_COMP.sch` ahí es un
> **directorio** —Xschem crea uno por esquemático—, no el `.sch`.
> `build_block.py` resuelve el enlace y anota el archivo real en la cabecera de las
> netlists derivadas, no el enlace.
>
> Todo lo que hay en la carpeta de salida es derivado y `build_block.py` lo reescribe en
> cada corrida; no reutiliza nada de una anterior. Trabajar sobre un derivado viejo daría un layout que ya
> no corresponde al circuito — y encima **un DRC y un LVS que pasan**, porque serían
> coherentes entre sí pero con la netlist equivocada, que es el peor fallo posible: no se
> nota. Las netlists derivadas llevan en la cabecera la fecha y el `sha1` de la fuente:
>
> ```
> * fuente: .../XSCHEM/WEIGTH/simulation/WEIGHT_COMP.sch/WEIGHT_COMP.spice
> * leida via enlace: /foss/designs/a_zonetic2026/spice_blocks/WEIGHT_COMP.spice
> * fecha de la fuente: 2026-08-03 06:34   sha1: 295db9ef2b
> ```
>
> Si ese `sha1` no coincide con el de la fuente actual, lo que hay en la carpeta está
> obsoleto. Para regenerar, **usar siempre `build_block.py`**: `test_flow.py` parte de una
> netlist ya aplanada y se salta el paso que recoge los cambios del esquemático.

### 5.1.1 Qué archivo genera quién

Los nombres despistan, porque hay dos netlists con `flat` y **no las escribe el mismo
programa**. Quién produce cada cosa:

| Archivo | Lo escribe | Qué es |
|---|---|---|
| `WEIGHT_COMP_flat.spice` | **`flatten_spice.py`** (nuestro) | La netlist de Xschem aplanada a un solo `.subckt` de MOSFETs, con `nf`. Es la **entrada** del generador |
| `WEIGHT_COMP_lvs.spice` | **`flatten_spice.py`** (nuestro) | Lo mismo con los dedos en paralelo, para netgen (§12.1). Tambien **entrada** |
| `WEIGHT_COMP_flat_gf180.gds` | **`coil_layout`** (nuestro) | El layout. El `_flat_gf180` sale de `flow.run_flow`, que nombra la salida como `<stem del spice de entrada>_<pdk>` |
| `WEIGHT_COMP_flat_gf180.png` / `_report.txt` | **`coil_layout`** (nuestro) | Render y reporte |
| `lvs/WEIGHT_COMP_flat_gf180.cir` | **KLayout** (`run_lvs.py` del PDK) | La netlist **extraida del GDS**. Hereda el nombre del `.gds` |
| `mag/*.mag` | **magic** | El layout en formato magic |
| `mag/WEIGHT_COMP_extracted.spice` | **magic** | Netlist extraida del layout, **sin parasitos** |
| `mag/WEIGHT_COMP_pex_c.spice` | **magic** | La misma **con capacidades (C)** |
| `mag/WEIGHT_COMP_pex_rc.spice` | **magic** | La misma **con capacidades y resistencias (RC)** |

Regla para no perderse: lo que esta en la **raiz** de la carpeta lo genera nuestro flujo;
lo que esta en `lvs/` lo genera KLayout y lo que esta en `mag/` lo genera magic. El `flat`
del nombre significa "netlist plana de Xschem", no "extraida del layout".

### 5.1.2 Netlists extraidas del layout

**Herramienta: `magic`** (`/foss/tools/bin/magic`), lanzado una sola vez por
`build_block.write_mag()` con los comandos que usa `sak-pex.sh`. Las tres van a `mag/`:

| Archivo | Parasitos | Comandos de magic |
|---|---|---|
| `mag/<BLOQUE>_extracted.spice` | **ninguno** | `ext2spice lvs` (preset que los apaga) + `extract all` |
| `mag/<BLOQUE>_pex_c.spice` | **C** | lo anterior + `ext2spice cthresh 0.01` |
| `mag/<BLOQUE>_pex_rc.spice` | **R y C** | `extract do resistance` + `extract all` + `ext2sim` + `extresist tolerance 10` + `extresist all` + `ext2spice extresist on` |

La RC **no sale del mismo `.ext`** que las capacidades: hay que volver a extraer pidiendo
resistencia y pasar por `ext2sim`/`extresist`, que es lo que parte cada red en tramos y
reparte los nodos. Por eso el guion extrae dos veces.

Referencia de lo que produce cada una en `WEIGHT_COMP` (33 transistores):

| | dispositivos | C | R |
|---|---:|---:|---:|
| `_extracted` | 33 | 0 | 0 |
| `_pex_c` | 33 | 86 | 0 |
| `_pex_rc` | 33 | 180 | 177 |

Los intermedios (`.ext`, `.sim`, `.nodes`) se escriben en `mag/.ext/` y se borran al
terminar: solo interesan las netlists.

> **No confundir con la extraccion del LVS.** Esa la hace **KLayout** (`run_lvs.py` del
> PDK) y va a `lvs/<BLOQUE>_flat_gf180.cir`. Son dos extractores distintos y no coinciden
> en todo: KLayout ata bien los pozos y magic no. Para LVS manda la de KLayout; para
> simular, las de magic.

### 5.1.3 Como instanciar la netlist extraida (y dos trampas)

El orden de puertos de las tres es el mismo, y **no** es el del esquematico:

```spice
.subckt WEIGHT_COMP VSS VDD WE OUT OUT_N VA VB VC VD
```

En el testbench:

```spice
.include .../mag/WEIGHT_COMP_pex_rc.spice
Xextrc  GND VDD WE2 OUT2 OUT_N2 va va va va  WEIGHT_COMP
```

**Trampa 1: el nombre de la instancia tiene que empezar por `X`.** Con `extrc ...` SPICE
lee una **fuente de tension controlada** (`E`), no una llamada a subcircuito; ngspice
intenta montar una fuente polinomica, la implementa como dispositivo XSPICE y falla con

```
MIF-ERROR - model: a$poly$extrc - Bad real value
```

que no menciona ni el subcircuito ni la linea original. Cualquier nombre que empiece por
una letra de dispositivo SPICE (`e`, `r`, `c`, `v`, `i`...) da un error igual de opaco.

**Trampa 2: los nodos de bulk.** magic no extrae los taps de este layout y dejaba el bulk
de los PFET en `w_...` y el de los NFET en `VSUBS`; con `extresist` es peor, porque parte
cada pozo en **decenas** de sub-nodos (`w_x.t0`, `.n0`, ...) que **no se conectan entre si**
—comprobado: ninguno alcanza el riel por resistencia—. Todos quedaban flotando.
`build_block._tie_bulk()` los sustituye por VDD/VSS al generar (el riel se deduce del
transistor: bulk de PFET → pozo n → VDD; de NFET → sustrato → VSS) y lo deja anotado en la
cabecera del archivo. **Eso da por hecho que los taps estan bien: quien detecta uno que
falte de verdad es el LVS**, no la simulacion.

> **Los nodos de bulk salen sueltos.** magic no reconoce los taps de este layout (§12.2):
> el bulk de los PFET aparece como `w_...#` y el de los NFET como `VSUBS`, en vez de VDD y
> VSS. **La conexion si existe** — el LVS de KLayout la ve y da `Circuits match uniquely` —,
> es magic quien no la extrae. Los dos archivos llevan el aviso en la cabecera; para
> simular hay que atarlos en el testbench.

Deja en `/foss/designs/a_zonetic2026/layouts/WEIGHT_COMP/`:
`WEIGHT_COMP_flat.spice` (netlist plana con `nf`, la que consume el layout),
`WEIGHT_COMP_lvs.spice` (dedos en paralelo, para el LVS — ver §12.1), el `.gds`, el `.png`,
el reporte, `mag/WEIGHT_COMP.mag` para abrirlo en magic y las dos netlists extraidas. Al
terminar imprime el comando de DRC ya con las rutas puestas.

> **El `.mag` va con toda su jerarquía en `mag/`.** Se genera con `writeall force`, que
> guarda la celda top *y sus ~90 subceldas*: guardando solo la top, el `.mag` queda con
> ~180 `use` apuntando a celdas que no existen en disco y magic no puede abrirlo. Aplanar
> antes daría un único archivo, pero el `flatten` de magic sobre esta jerarquía **no
> termina** (probado, >10 min). Para abrirlo:
> `magic -rcfile $PDK_ROOT/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc mag/WEIGHT_COMP`

> `env -u PYTHONPATH` no es opcional — sin él se ignora el venv (§10).

Los pasos sueltos siguen existiendo (`flatten_spice.py` y `test_flow.py`) y sirven para
depurar o para regenerar el netlist viejo de `zonetic/spice/`, que sigue soportado.

### 5.3 Correr el DRC

```bash
docker exec iic-osic-tools_chipathon_xvnc bash -c \
 'export PATH=/foss/tools/klayout:$PATH
  cd /foss/designs/a_zonetic2026/layouts/WEIGHT_COMP
  python3 /foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py \
    --path=$PWD/WEIGHT_COMP_flat_gf180.gds \
    --variant=D --topcell=WEIGHT_COMP \
    --run_dir=$PWD/drc --mp=4'
```

- `--variant=D` = metal_top 11K, mim_option B, **5 niveles de metal** — coincide con el
  stack que declara `pdk_manager.GF180` (metal1..metal5).
- `--topcell` es obligatorio. Desde la iteración #4 la celda se llama **`WEIGHT_COMP`**
  (antes `WEIGHT_COMP_layout`); se renombró para que el LVS de KLayout la reconozca.
- Opciones útiles: `--density` (reglas de densidad, apagadas por defecto), `--antenna`,
  `--no_connectivity` (más rápido), `--run_mode=deep` (jerárquico).
- Usa el **`python3` del sistema**, no el venv: `run_drc.py` solo orquesta y llama al
  binario de KLayout.

### 5.4 Leer el reporte

`run_drc.py` escribe **un `.lyrdb` por sección del deck** (≈70 archivos), no uno solo.
Para el conteo agregado por regla:

```bash
docker exec iic-osic-tools_chipathon_xvnc python3 -c "
import glob,collections,xml.etree.ElementTree as ET
c=collections.Counter()
for f in glob.glob('/foss/designs/zotnetic_layout/drc_run/*.lyrdb'):
    for it in ET.parse(f).getroot().iter('item'):
        cat=it.findtext('category','').strip().strip(chr(39))
        if cat: c[cat]+=1
print('TOTAL:',sum(c.values()),' reglas:',len(c))
for r,n in c.most_common(): print(f'{n:6d}  {r}')
"
```

Y para ver las descripciones de las reglas violadas, misma idea iterando sobre
`<category>` en vez de `<item>` y leyendo `name`/`description`.

**Inspección visual:** abrir la GUI de KLayout por VNC (el contenedor ya expone noVNC),
cargar el `.gds` y luego *Tools → Marker Browser → Load* con el `.lyrdb` de la regla que
interese: resalta cada violación sobre el layout.

---

## 5.5 El floorplan (desde la iteración #9)

```
  VPWR  ================================   riel
        [ fila P  ]                         straps hacia ARRIBA
  ------ canal A -------------------------  trunks de las nets con pines en P o N1
        [ fila N1 ]                         straps hacia ABAJO
  VGND  ================================   riel COMPARTIDO + taps p+
        [ fila N2 ]                         straps hacia ARRIBA
  ------ canal B -------------------------  trunks de las nets con pines en N2
```

**Por qué tres filas.** Hay muchos más NFET que PFET (18 contra 5 en `WEIGHT_COMP`, suma
de anchos 27.6 vs 11.5 µm): en dos filas la N marcaba el ancho de la celda y la P se
quedaba a menos de la mitad, desperdiciando todo su lado. Partiendo la N el ancho baja de
67.5 a 37.2 µm.

**Por qué un solo riel VGND.** Va entre N1 y N2 y lo comparten las dos filas (una alimenta
hacia abajo y la otra hacia arriba). Así ninguna fila cruza un canal para llegar a su
alimentación —que es lo que estropearía el ruteo— y sobra una tira de taps: los del riel
quedan a menos de 6 µm de cualquier NFET, de sobra para `DF.14_MV` (15 µm).

**Consecuencia para el ruteo.** Un pin de N1 no puede bajar al canal B porque tendría que
cruzar el riel: los pines de P y N1 usan solo el canal A y los de N2 solo el B. Una net con
pines a los dos lados necesita trunk en los dos canales y un **enlace vertical** que los
una (§12.2).

---

## 5.6 Resistencias de poly (desde la iteración #18)

`coil_layout/resistors.py`. Se estrenó con `RFB` de `OPAM_LIN_flat`: `ppolyf_u_3k` de
1 µm × 76.4536 µm con `s=5`, o sea **1.2 MΩ**.

### 5.6.1 Dónde va: en el canal, no en una banda

Una tira de 382 µm de largo no cabe recta en una celda de 100. Se pliega en **serpentín**,
y el serpentín se mete **dentro del canal de ruteo** entre la fila P y la N, no en una
banda lateral propia. La diferencia es grande:

| dónde | área de la celda |
|---|---|
| banda lateral | 5387 µm² (**+94 %**) |
| dentro del canal | 2914 µm² (**+5 %**) |

El canal ya existe y solo hay que engordarlo, que es lo que hace `extra_channel` en
`placement.build_layout`: `flow` calcula `altura_necesaria(nl.resistors, …)` **antes** de
la primera colocación y la pasa como suelo del alto del canal A.

Por eso el serpentín se pliega **ancho y plano** y no alto y estrecho (`_plan`): lo que
hay que gastar es ancho, que la celda ya tiene, y no alto, que es lo caro.

### 5.6.2 El número de tramos lo manda el esquemático

`s` en el modelo del PDK es un multiplicador **en serie** (`par` sería en paralelo), y el
layout usa **exactamente** esos tramos. No es cosmético: el modelo aplica la corrección de
extremo (`r_dl`) una vez **por tramo**, así que cinco tramos de 76.45 µm y uno de 382 µm no
son la misma resistencia. Que esquemático y silicio coincidan depende de respetarlo.

### 5.6.3 Cuándo se coloca: el último

Después de rutear **y después de los condensadores**. El orden importa y está medido: a la
resistencia le basta un punto de vía en el trunk, mientras que un MIM necesita 20 µm
seguidos. Colocando la resistencia primero se quedaban sin sitio los dos MIM y dos puertos.

### 5.6.4 Las seis trampas, todas de integración

El serpentín se había verificado **suelto** y salía limpio; integrado en el bloque dio
**1222 violaciones**. Las seis causas, en el orden en que aparecieron —y la sexta no daba
ninguna violación, que es lo que la hacía peligrosa:

| # | síntoma | causa | dónde se arregló |
|---|---|---|---|
| 1 | 1222 violaciones en 48 reglas (`SB`, `HRES`, `LRES`, `PL`, `CO`, `NP`, `PP`) | `channel_y` es el **centro** del canal; el serpentín colgaba hacia abajo y se metía en la fila N1. El `res_mk` sobre poly de puerta reclasifica los transistores como resistencias | `Layout.channel_h` + `techo`/`suelo` en `place_resistors` (§41) |
| 2 | 90 `*_OFFGRID` | el PCell dibuja la tira **centrada en el origen**: un `l_res` múltiplo impar de 5 nm deja los bordes a 2.5 nm | `resistors.snap2()`, que redondea a 0.01 µm (§42) |
| 3 | 44 `M2.2a` | el salto del terminal al trunk iba en metal2 horizontal y cruzaba todos los stubs verticales del canal | cruce por **metal3** (§43) |
| 4 | `M2.1`, `M2.2a`, `V1.2a` | el terminal aterrizaba sobre un stub ya existente, y **deslizarlo en x no sirve**: los trunks son barras horizontales | búsqueda en x **e y** con `BUSQUEDA_Y` de canal reservado (§44) |
| 5 | `DF.13_MV` | una sola columna de taps a la derecha de todo el grupo `span`, que se ensanchó | columnas repartidas por los huecos del grupo (§45) |
| 6 | **ninguno — el DRC salía limpio** | la resistencia no se colocaba y `res_placed`/`res_failed` no los leía nadie | `build_block.py` los imprime y falla (§46) |

### 5.6.5 Lo que nunca se calla

Una resistencia que **no se coloca** no la ve ni el DRC ni el LVS: la netlist de referencia
sale del mismo aplanado, así que las dos comprobaciones saldrían limpias describiendo un
circuito que no es el del esquemático. Por eso todo fallo de colocación va a
`lay.res_failed` con su motivo y el flujo lo imprime como `ERROR`. Lo mismo pasó una vez
con `flatten_spice.py`, que se comía la resistencia en silencio: layout DRC-limpio y
eléctricamente equivocado.

### 5.6.6 Cómo comprobar que está y está bien puesta

```bash
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python -c "
import klayout.db as kdb
ly=kdb.Layout(); ly.read('.../OPAM_LIN_flat_flat_gf180.gds')
t=ly.top_cell()
res =kdb.Region(t.begin_shapes_rec(ly.layer(110,5)))   # res_mk
comp=kdb.Region(t.begin_shapes_rec(ly.layer(22,0)))    # difusion
print('area res_mk      ', res.area()/1e6, 'um2')      # = s * L * W
print('solape con difus.', (res & comp).area()/1e6)    # tiene que ser 0.00
"
```

El área del `res_mk` tiene que dar `s · L · W` (aquí 5 × 76.45 × 1.0 = **382.25 µm²**, y
sale clavado): si da **0.00** la resistencia no está en el layout, y si da otra cosa no es
la que pide el esquemático. El solape con difusión tiene que ser **exactamente cero**.

**Esta comprobación no es opcional.** Un DRC limpio no prueba que la resistencia esté: lo
que no se dibuja no viola ninguna regla, y el LVS tampoco lo nota porque compara contra una
referencia salida del mismo aplanado. Ya pasó una vez y me lo tragué (§46). El flujo lo
avisa ahora por su cuenta —`build_block.py` imprime `res: XRFB 5 tramos de 76.450 x 1.00
um` y saca `ERROR` si falta— pero medir el área es la comprobación independiente.

### 5.6.7 `BUSQUEDA_Y`: lo que se reserva a ojo se paga en alto (iteración #31)

`BUSQUEDA_Y` es el margen vertical que se le da al serpentín **por encima de lo que mide**,
para que pueda deslizarse buscando dónde bajar sus terminales. Estaba en **5.0 µm**, puesto
a ojo, y cada micra reservada es una micra de alto de celda.

Medido, barriendo el valor y mirando **cuánto baja de verdad**:

| `BUSQUEDA_Y` | 3.0 | 2.5 | 2.0 | 1.5 | 1.0 | 0.5 | 0.0 |
|---|---|---|---|---|---|---|---|
| lo que baja | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 |
| alto de celda | 47.57 | 47.07 | 46.57 | 46.07 | 45.57 | 45.07 | 44.57 |

**Siempre 0.40 µm**, y la resistencia se coloca en los siete casos con `res_mk` exacto y sin
dejar puertos sin acceso. O sea que de los 5.0 sobraban 4.6.

No es que la reserva fuera absurda cuando se puso: entonces el terminal tenía que **ir a
buscar un hueco entre trunks**, porque el router repartía sus pistas por todo el canal
(§11.0.1b). Desde que el canal se dimensiona como trunks **más** serpentín y cada uno se
queda con su parte, la banda del serpentín nace limpia y no hay nada que buscar. **La
reserva sobrevivió a su motivo**, que es lo fácil que pasa con una constante puesta a ojo.

Se deja en **2.0**, no en 0.4: lo que hay que cubrir no es lo que baja hoy sino lo que
podría tener que bajar otra geometría, y el peor caso realista es esquivar la banda
prohibida de un puerto de señal, que mide 1.7 µm (`BANDA_PUERTO` a cada lado). 2.0 la cubre
entera; 1.0 no. **Resultado: 49.57 → 46.57 µm de alto**, y de paso desaparece el medio
micrón de ancho que el MIM tumbado se había llevado (§5.7.1), porque con el canal más bajo
vuelve a caber sin asomarse.

---

## 5.7 Condensadores MIM: tumbados, no de pie (desde la iteración #25)

`coil_layout/caps.py`. El MIM vive en metal4/metaltop y se monta **encima** del array ya
ruteado, así que en principio no cuesta área. Pero la **placa sí tiene orientación**, y
puesta de pie sí cuesta:

```
                 celda 103.85 x 43.20            celda 103.85 x 36.37
   fusetop     x 28.34..32.34  y 17.59..42.59  |  x 32.34..57.34  y 17.59..21.59
               4 ancho x 25 ALTO               |  25 ancho x 4 alto
   metal4      llega a y = 43.20  <- el techo  |  llega a y = 22.20
```

De pie, los 25 µm de la placa se comían 25 de los 43 de alto y **su metal4 llegaba justo al
borde superior**: el condensador era lo que fijaba la altura de la celda. Tumbado, esos
25 µm caben de sobra en los 103.85 de ancho. **El área no cambia, o sea que la capacidad
tampoco** — solo cambia el dibujo.

`_candidates()` genera ahora las colocaciones en las dos orientaciones, **tumbada primero**
y de pie solo como respaldo, con presupuesto de ramas (`_BRANCH`) independiente para cada
una: compartido, la segunda no llegaba a probarse nunca.

**Resultado: 43.20 → 36.37 µm de alto (−16 %)**, con los dos MIM y la resistencia dentro y
DRC limpio.

Regla general: cuando algo se monta sobre capas libres se suele razonar como si fuera
gratis, y no lo es del todo — hay que mirar **en qué dirección** crece contra la dimensión
que está apretada. Aquí la celda es 2.9 veces más ancha que alta, así que la orientación
correcta era la evidente en cuanto se miran los dos números juntos.

### 5.7.1 Preferir tumbado no basta: hay que IMPONERLO (iteración #30)

La preferencia de §5.7 es **local** — dentro del generador de UN condensador — y el que va
primero se lleva el sitio. Al vetar la zona del terminal de la resistencia (§11.0.6), `XC3`
cogió hueco tumbado, `XC1` se quedó sin sitio y acabó **de pie**: sus 25 µm en vertical, su
metal4 llegando a `y = 55.16` y la celda otra vez con el condensador fijando el alto.
Volvía el problema que §5.7 daba por cerrado.

Cuatro cosas, y hacen falta las cuatro:

1. **Dos pasadas en `place_caps`**: la primera prohíbe las placas de pie por completo. Así
   o entran los dos tumbados, o se ha intentado de verdad antes de rendirse.
2. **La placa también HACIA ABAJO del punto de agarre.** Solo se construía hacia arriba, y
   ésa es la razón de fondo de que una placa de pie fijara la altura: anclada en un trunk a
   `y=28.66`, sus 25 µm se iban a `29.5..54.5`. Hacia abajo caen sobre las filas de
   transistores, que es **donde tiene que estar un MIM** —en metal4 y metal5, por encima
   del array— y no cuestan ni una micra. `_FUSE_CLEAR` (MIMTM.10) es simétrico, así que la
   construcción vale igual por los dos lados.
3. **Puntos de agarre repartidos** (`_AGARRE_SEP` = 2.0). `_free_points` barre el trunk cada
   0.1 µm, así que las 40 alternativas de un condensador se iban en **1.3 µm** de trunk
   moviendo la placa de décima en décima. Medido: 40 candidatos, **14 posiciones distintas**.
   Para el siguiente condensador eso es *una* alternativa.
4. **Varias rutas de metal5 por pareja de puntos** (`_M5_ALT`) y los extremos del trunk de
   P2 ofrecidos además del más cercano. Los dos MIM de `OPAM_LIN_flat` cruzan el bloque en
   sentidos opuestos —uno va de `net10` (izquierda) a `OUT` (derecha) y el otro de `OUT` a
   `net9`— y con una sola ruta por pareja el primero levantaba **un muro**: se midió su
   metal5 como una barra de `x 12.4` a `x 72.2` a una sola altura, y el segundo tenía que
   bajar atravesándola.

**Resultado en `OPAM_LIN_flat`: 98.22 × 55.16 → 98.75 × 49.57 µm.** 5.59 µm menos de alto
por 0.53 más de ancho: **523 µm² menos, un 9.7 %**. `COMP` y `OPAM` conservan su tamaño
exacto y sus cuatro placas siguen tumbadas.

> **Ojo con el presupuesto de ramas.** Ofrecer la placa arriba y abajo **duplica** los
> candidatos por punto, así que con `_BRANCH = 40` se exploraba la mitad de puntos que
> antes y `OPAM` se quedó sin colocar sus dos MIM. Subido a 90. Y no cuesta tiempo *porque*
> los puntos van adelgazados: con 90 ramas y sin `_AGARRE_SEP`, `OPAM` tarda **cuatro
> minutos**; con las dos cosas, **11 segundos**. Las dos medidas van juntas.

---

## 6. Interpretación de la iteración #1

629 violaciones, pero **no son 629 problemas distintos**. Agrupadas por causa raíz:

| Causa raíz | Reglas | Nº | Estado |
|---|---|---:|---|
| **Vías mal construidas** por `routing.py` | V1.1, V1.3a, V1.4a, V1.2a | **348** | CONFIRMADO |
| **Contactos vs poly** en/entre dispositivos | CO.7, CO.2a, CO.4, CO.10 | **215** | HIPÓTESIS |
| **Ruteo best-effort**: ancho/espaciado de metal | M1.2a, M2.2a, M1.1 | **32** | CONFIRMADO |
| **Marcadores nplus/nwell** en `placement.py` | NP.5di | **15** | HIPÓTESIS |
| **Falta de taps de sustrato** (`bulk="None"`) | DF.14_MV | **8** | CONFIRMADO |
| **L=0.5 µm en dispositivos 6 V** (error de esquemático) | PL.2_MV, DF.2a_MV, DF.6_MV | **11** | CONFIRMADO |

### 6.1 Vías (55 % de todo) — el arreglo de mayor impacto

```
V1.1  : Min/max Via1 size : 0.26 µm      → 256
V1.3a : metal1 overlap of via1 >= 0.0    →  62
V1.4a : metal2 overlap of via1 >= 0.01   →  28
V1.2a : min. via1 spacing : 0.26 µm      →   2
```

Via1 en GF180 tiene tamaño **exacto** 0.26 µm (no es un mínimo, es min *y* max) y exige
*enclosure* de metal1 y metal2. `routing.py` claramente dibuja las vías con otra medida
—muy probablemente reutiliza los 0.22 µm del contacto— y sin el enclosure. Arreglar solo
esto elimina más de la mitad de las violaciones.

### 6.2 `L=0.5u` en los inversores — esto es un bug del esquemático, no del layout

`PL.2_MV` (Gate Width / Channel Length) dispara en los 3 PFET de la cadena de inversores
de `comp._out`: están declarados `pfet_06v0 L=0.5u`, por debajo de la longitud mínima de
canal de los dispositivos de media tensión (los NFET hermanos sí usan `L=0.6u`).

**Esto no se arregla en el generador: hay que corregirlo en Xschem y re-exportar.**

### 6.4 `CO.7` — no era el generador, era el PCell (añadido 2026-08-02)

`CO.7` (0.15 µm entre un contacto de COMP y el poly de gate) resultó ser **dos bugs
distintos de `gf180==0.1.1`**, confirmados midiendo el PCell aislado:

1. **Contactos inter-finger.** Con el `inter_sd_l` por defecto (0.24 µm) el hueco entre
   gates es de 0.24 y el PCell mete ahí un contacto de 0.22 centrado: quedan **0.01 µm**
   por lado. A ese paso no hay arreglo posible — hacen falta `0.22 + 2×0.15 = 0.52`.
   Se pasa `inter_sd_l=0.52`.
2. **Contactos S/D externos.** El PCell deja el contacto a 0.07 del borde de la difusión
   intrínseca y el poly empieza otros 0.07 dentro → **0.14**. Tampoco basta con mover el
   contacto: entre el enclosure de COMP (0.07, `CO.4`) y el poly (0.15, `CO.7`) la ventana
   legal mide **0.21** y `CO.1` obliga a que el contacto mida **exactamente 0.22**. Hay que
   ensanchar COMP: se corre el contacto 0.01 hacia fuera y se extienden COMP y el implante
   esa misma cantidad (`device_map._fix_pcell_co7_gf180`).

Como efecto secundario, el **abutment** también era ilegal: el bloque S/D compartido tiene
gate a ambos lados y necesitaría los mismos 0.52 midiendo 0.36. Pero no necesita contacto
—el criterio de abutment exige que la net tenga exactamente 2 pines, así que el nodo es
interno al par y la difusión compartida **es** la conexión—, así que se borran contacto y
pad (`device_map.strip_abutted_sd_gf180`).

### 6.3 Taps de sustrato — predicción confirmada

`DF.14_MV` (distancia máxima de un tap de sustrato: 15 µm) confirma lo que ya se
sospechaba: `device_map.py` instancia los PCells con `bulk="None"` para conseguir el
estilo celda-lógica sin guard rings, y `placement.py` no añade taps propios en cantidad
suficiente. Un layout sin taps es *latch-up* garantizado, así que esto hay que resolverlo
sí o sí antes de cualquier tape-out.

---

## 7. Reglas violadas — referencia rápida

### 7.1 Estado actual (iteración #23)

**Ninguna**, en los **cinco** bloques, todos regenerados y reverificados el 2026-08-18
después de tocar `resistors.py`, `placement.py`, `routing.py`, `caps.py`, `device_map.py`
y `flow.py` (`--variant=D`, con su `--topcell`). Y esta vez con **el LVS al lado**, que es
lo que faltaba: un 0 de DRC ya se ha demostrado compatible con la salida cortada a masa.

| bloque | tamaño | errores de flujo | DRC | KLayout LVS | netgen |
|---|---|---:|---:|---|---|
| `WEIGHT_COMP` | 37.17 × 25.00 µm | 0 | **0** | `Netlists match` | casan |
| `DECODER` | 37.89 × 15.84 µm | 0 | **0** | `Netlists match` | casan |
| `COMP` | 104.28 × 31.46 µm | 0 | **0** | `Netlists match` | casan (avisos de propiedad) |
| `OPAM` | 88.27 × 31.46 µm | 0 | **0** | `Netlists match` | casan (avisos de propiedad) |
| `OPAM_LIN_flat` | 98.22 × 46.57 µm | 0 | **0** | `Netlists match` | casan (avisos de propiedad) |

Los avisos de propiedad son el choque de convenios de los MIM (`A`/`P` contra `W`/`L`
contra `c_width`/`c_length`), documentado en §11.1: los números cuadran, lo que no cuadra
son los nombres.

Los cuatro primeros dan **exactamente** el mismo tamaño que antes de tocar `resistors.py`,
`placement.py` y `build_block.py`: las columnas de tap extra, `snap2` y la búsqueda del
serpentín solo actúan donde hay grupo `span` ancho o resistencia, así que no tocan a quien
no las usa. Que las cinco corridas den 0 **no** es prueba de que el cambio sea inocuo —lo
que lo prueba es que los tamaños no se muevan ni un nanómetro—, y en `OPAM_LIN_flat` un 0
tampoco basta por sí solo: hay que medir el `res_mk` (§5.6.6, §46).

El circuito tampoco cambia: `./run_opam_g100.sh dc` sigue dando **103.4 V/V de pico, 103.2
entre 1 y 4 V, INL 0.12 %, offset +24.0 mV y 2.550 mW**.

Quedan por habilitar las reglas de densidad y antena, apagadas por defecto
(ver [Pendientes](#11-pendientes)).

#### 7.1.1 Lo que costó `OPAM_LIN_flat` (para no repetirlo)

Es el bloque que más caro ha salido: **1222 violaciones en 48 reglas** en la primera
integración, todas provocadas por la resistencia de poly. Vale la pena quedarse con la
forma del diagnóstico, más que con las reglas concretas:

1. **La distribución de las violaciones dice más que la lista de reglas.** 48 reglas
   distintas, sin relación aparente entre ellas, pero **todas** en la banda `y = 1.65..13.84`
   de una celda de 41.77 de alto. Un conjunto heterogéneo de reglas concentrado en una zona
   pequeña casi nunca son 48 problemas: es uno.
2. **La causa se confirma midiendo, no leyendo el layout.** Una línea —
   `(res_mk & comp).area()` = 42.08 µm² — lo cerró. Marcadores y capas de dispositivo son
   `kdb.Region`; su intersección es la prueba.
3. **Las capas de marcador reclasifican, no solo solapan.** El `res_mk` sobre poly de
   puerta convierte transistores en resistencias a ojos del deck, y por eso salían `HRES`,
   `LRES`, `SB`, `PL`, `CO`, `NP` y `PP` a la vez (§41).
4. **Verificar un componente suelto no verifica su integración.** El serpentín se había
   dado por limpio probándolo **fuera** del bloque. Las cinco causas que aparecieron
   después —canal, rejilla, cruce del canal, hueco del terminal y cobertura de taps— son
   todas de interacción con lo que ya había alrededor.

### 7.2 Histórico — iteración #1 (629 violaciones)

Se conserva como referencia de cómo se veía el punto de partida.

| Regla | Descripción (del PDK) | Nº |
|---|---|---:|
| `V1.1` | Min/max Via1 size: 0.26 µm | 256 |
| `CO.7` | Space from COMP contact to Poly2 on COMP: 0.15 µm | 208 |
| `V1.3a` | metal1 overlap of via1 >= 0.0 | 62 |
| `V1.4a` | metal2 overlap of via1 >= 0.01 µm | 28 |
| `M1.2a` | min. metal1 spacing: 0.23 µm | 25 |
| `NP.5di` | Nwell overlap of Nplus < 0.4 (fuera de DNWELL, dentro de Nwell) | 15 |
| `DF.14_MV` | Max. distancia de tap de sustrato: 15 µm | 8 |
| `M2.2a` | min. metal2 spacing: 0.28 µm | 6 |
| `PL.2_MV` | Gate Width (Channel Length) | 6 |
| `DF.2a_MV` | Min. Channel Width: 0.3 µm | 3 |
| `CO.2a` | min. contact spacing: 0.25 µm | 3 |
| `DF.6_MV` | Min. COMP extend beyond gate (overhang S/D): 0.4 µm | 2 |
| `CO.4` | COMP overlap of contact: 0.07 µm | 2 |
| `CO.10` | Contacto sobre Poly2 gate encima de COMP: prohibido | 2 |
| `V1.2a` | min. via1 spacing: 0.26 µm | 2 |
| `M1.1` | min. metal1 width: 0.23 µm | 1 |

---

## 8. Bitácora de iteraciones

| # | Fecha | GDS | Violaciones | Reglas | Cambio respecto a la anterior | Resultado |
|---|---|---|---:|---:|---|---|
| 0 | 2026-08-01 | `WEIGHT_COMP_flat_gf180.gds` (generado en Windows) | — | — | Estado inicial: sin DRC posible (`klayout` de pip no corre decks) | Punto de partida |
| 1 | 2026-08-01 | `WEIGHT_COMP_flat_gf180.gds` (regenerado en contenedor) | **629** | **16** | Primer DRC real. Layout idéntico al de Windows (30 transistores, 766 polígonos, 73.00 × 17.16 µm) → reproducibilidad confirmada | `V1.1`×256 y `CO.7`×208 dominan; ver §6 |
| 2 | 2026-08-02 | `WEIGHT_COMP_flat_gf180.gds` | **485** | **9** | **`m` → fingers**: `flatten_spice.py` convierte `m` a `nf=nf·m` (antes copias paralelas); `device_map.py` soporta `nf>1` (straps S/D en metal2 con via1 de 0.26 exacto, barras+riser de gate, risers laterales de S/D, parche del poly de `draw_pfet`); `placement.py` excluye multi-finger del abutment y baja los taps p+ sobre el riel (DV.3/PL.5) | 30→23 MOSFETs, ancho 73.0→63.8 µm (−13 %). Desaparecen `CO.4/CO.10/DF.2a_MV/DF.6_MV`; las 9 reglas restantes son todas de causas preexistentes: vias del router (`V1.1`×172, `V1.3a`×42, `V1.4a`×20), `CO.7`×206, espaciados router (`M1.2a`×15, `M2.2a`×6), taps (`NP.5di`×12, `DF.14_MV`×6) y `PL.2_MV`×6 (esquemático) |
| 3 | 2026-08-02 | `WEIGHT_COMP_flat_gf180.gds` | **256** | **5** | **Vías del router** (pendiente #1): `routing.py` dibujaba via1 de 0.22 µm sin enclosure. Ahora 0.26 µm exacto con pad de aterrizaje de 0.34 en metal1 **y** metal2 | Las **234** violaciones `V1.*` → **0**. Efecto colateral: los pads de 0.34 subieron `M1.2a` de 15 a 26 |
| 4 | 2026-08-02 | `WEIGHT_COMP_flat_gf180.gds` | **12** | **2** | **Contactos** (`CO.7`, dos bugs del PCell: `inter_sd_l` 0.24→0.52 e íntegro desplazamiento de 0.01 de los contactos externos + ensanche de COMP/implante); abutment sin contacto en el bloque compartido; **taps** (implante 0.15→0.18, tira p+ a lo ancho de la celda, tap 0.6→0.48 por `DF.9`, reposicionamiento en los huecos entre dispositivos); **M1.2a** (pista S/D corrida para librar el pad de gate, pads internos retranqueados 0.02, reparto de stubs en x); **OFFGRID** (cajas insertadas sin pasar por el caché de `rectangle`); celda top renombrada a `WEIGHT_COMP`; puertos etiquetados en (34,0) y (34,10) | `CO.7` 206→**0**, `NP.5di`/`DF.14_MV`→**0**, `M1.2a` 26→**6**. Quedan 6 `M1.2a` (congestión del canal) y 6 `PL.2_MV` (esquemático, fuera de alcance). 68.00 × 17.29 µm |

| 5 | 2026-08-03 | `layouts/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` | **6** | **1** | Netlist re-exportada a `a_zonetic2026/spice_blocks/` con los inversores en **05v0**. `flatten_spice.py` aprende el formato nuevo de Xschem (top con `**.subckt` comentado, MOSFET `XM*` con el modelo al final, tokenizado que respeta comillas, filtrado a `L/W/nf/m`); nuevo `build_block.py` que escribe en `layouts/<bloque>/` | **`PL.2_MV` 6 → 0** sin tocar el generador: los 6 marcadores `v5_xtor` aparecen sobre los inversores y pasan a regirse por los mínimos de 5 V. **No** apareció ninguna regla de frontera 5 V/6 V (era el riesgo del plan). Queda solo `M1.2a`×6. LVS sin cambios: 23 vs 23 dispositivos y el mismo corto `x1_net6`↔`WE` |

| 6 | 2026-08-03 | `layouts/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` | **0** | **0** | **Router de canal** (pendiente #1). Dos causas independientes: (a) el canal tenía alto fijo de 4.0 µm → 2.74 µm útiles para 10 trunks que pedían 6.82, así que se desbordaban dentro de las filas; ahora `placement` lo dimensiona (`nets_to_route()` × `TRUNK_PITCH`). (b) los trunks se asignaban por número de pines, sin respetar la **restricción vertical** del ruteo de canales; `routing._order_trunks()` la implementa con orden topológico | **DRC 6 → 0** y **el corto `x1_net6`↔`WE` desaparece**: netgen pasa de 19 vs 20 nets a **20 vs 20** y da `Circuits match uniquely`. Alto 17.29 → 20.91 µm, que es lo que costaba que los trunks cupieran de verdad |

| 7 | 2026-08-03 | `layouts/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` | **0** | **0** | **Left-edge con restricciones** (`routing._assign_tracks`): las nets cuyos trunks no se solapan en x comparten pista, sin romper el orden vertical. `flow.run_flow` hace una segunda pasada con el número real de pistas (el canal se dimensiona antes de rutear, cuando aún no se sabe). Añadida exportación a `.mag` en `build_block.write_mag` | 10 nets → **7 pistas**; alto 20.91 → **19.05 µm** (−8.9 %). DRC y LVS siguen limpios. El empaquetado está en su límite con esta colocación: 6 de las 10 nets cruzan casi toda la celda (spans de 45-60 µm) y no pueden compartir con nadie; solo las 4 cortas se agrupan |

| 8 | 2026-08-03 | `layouts/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` | **0** | **0** | **Alinear las filas**: `placement._barycenter_targets()` centra cada cadena de la fila corta sobre sus vecinos de la larga, en vez de empaquetarla a la izquierda | **1295 → 1168 µm² (−10 %)** y **7 → 4 pistas**, que es la cota inferior (densidad máxima del canal = 4). `net1` pasa de 47.0 a 3.6 µm de span y `net2` de 44.1 a 0.7 |
| 9 | 2026-08-03 | `layouts/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` | **0** | **0** | **Floorplan de tres filas P / N1 / N2** con dos canales: 18 NFET contra 5 PFET dejaban la fila P a menos de la mitad. Un solo riel VGND compartido (N1 alimenta hacia abajo, N2 hacia arriba). Router por canal + enlaces verticales metal1/metal2/metal1 por columnas libres (`_plan_links`/`_draw_links`) | **1168 → 1064 µm² (−9 %)**; el **ancho baja de 67.5 a 37.2 µm (−45 %)** a cambio de altura. DRC y LVS siguen limpios |

| 10 | 2026-08-03 | igual (sin cambios de layout) | **0** | **0** | Extracción con magic en `build_block.write_mag`: mismo lanzamiento que ya escribía los `.mag` produce ahora `mag/*_extracted.spice` (sin parásitos) y `mag/*_pex.spice` (con capacidades) | 30 dispositivos en las dos, 88 capacidades en la de parásitos. DRC y LVS sin tocar |

| 11 | 2026-08-04 | `layouts/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` | **0** | **0** | **Re-export del esquemático**: `XM2` pasa de `W=4u m=3` a `W=2u m=6` (mismo ancho total, otra disposición) y el formato vuelve al estilo `M...`. `spice_blocks/` pasa a ser **enlace simbólico** al netlist de Xschem. El cambio destapó dos bugs latentes del router: dos pines de la misma net en el mismo trunk fusionaban sus `via1` (`V1.1`), y la barra que las une dejaba un escalón (`M1.1`). Arreglados con `_via_groups()` y `_required_sep()` | Salieron 10 violaciones nuevas de un cambio que no altera el circuito; con los dos arreglos vuelve a **0**. LVS sigue `Circuits match uniquely`. Alto 28.63 → **26.63 µm** (990 µm²): con 6 dedos de 2 µm la fila P es más baja que con 3 de 4 µm |

| 12 | 2026-08-04 | `layouts/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` | **0** | **0** | **Transistores pegados al tap**: los límites de fila salen de la extensión REAL de los dispositivos (`extent()`) en vez de `max(W)+1.5`, y la separación fila-riel pasa a `RAIL_CLEAR`, **medido por barrido** (0.35 limpio, 0.30 dispara `DV.3`). Añadida la extracción **RC** (`_pex_rc.spice`) junto a la de C | Alto 26.63 → **25.00 µm** (929 µm²). La fila N2 estaba a **1.72 µm** del tap por culpa de la cuenta aproximada; ahora las dos filas quedan simétricas a **0.56 µm** del COMP del tap. Camino de sustrato más corto (latch-up) |

| 13 | 2026-08-04 | `layouts/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` | **0** | **0** | Re-export declarando `OUT` y `OUT_N` como puertos del `.subckt`: el top pasa de 7 a **9 puertos**. **Sin cambios en el generador** | Las 9 etiquetas aparecen en el GDS y el `.SUBCKT` extraído sale con los 9 puertos. DRC 0 y `Circuits match uniquely`; tamaño igual (37.17 × 25.00 µm) porque `net1`/`net2` ya se ruteaban, solo les faltaba el pin |

| 14 | 2026-08-04 | `layouts/COMP/COMP_flat_gf180.gds` | **0** | **0** | **Segundo bloque: `COMP`** (`XSCHEM/OPAM/simulation/COMP.sch`, enlazado en `spice_blocks/`). 50 MOSFET, jerarquía de dos niveles (`bias` + `sub_diff`). Primera pasada: **2 `M1.2a`**, de dos causas distintas. (a) `_spread_stubs()` era un solo barrido voraz que **solo empuja a la derecha**: un stub ya en su `x_hi` no podía ceder y el roce se quedaba mudo → reescrito como solución exacta del sistema de **restricciones de diferencia** (mínimo viable hacia la derecha, luego acercar al pin hacia la izquierda). (b) `_free_x()` se rendía al agotar su presupuesto de 3 µm y devolvía la x que **chocaba**; con PFET de 10 µm el primer hueco cae más lejos → busca por toda la tira y, si no hay, se salta el tap. Además: los transistores conservan el **nombre del esquemático** y se etiquetan en la capa VTEXT (63/63) | **2 → 0**. 104.28 × 41.34 µm. KLayout LVS `Netlists match`; netgen 50 vs 50 dispositivos y 37 vs 37 nets, `Device classes are equivalent`, pero **falla el emparejamiento de pines**: el puerto se llama `IN-` y KLayout lo escapa como `IN\x2d` — es el nombre en el esquemático, no el layout (§11). Sin regresión en WEIGHT_COMP (DRC 0, `Circuits match uniquely`) |

| 15 | 2026-08-04 | `layouts/COMP/COMP_flat_gf180.gds` | **0** | **0** | **La fila N se parte solo si está desequilibrada** (`SPLIT_RATIO = 1.5` en `placement.py`). Partir siempre solo tenía sentido para `WEIGHT_COMP`; medido el ancho horizontal real de cada fila, `COMP` da N/P = **0.92** y `WEIGHT_COMP` **2.63**. Sin fila N2 el riel VGND baja al fondo de la celda | `COMP` **41.34 → 31.46 µm de alto** (4310 → 3281 µm², −24 %), mismo ancho. `WEIGHT_COMP` **no cambia** (sigue con dos filas). DRC 0 y LVS limpio en los dos |

| 16 | 2026-08-04 | `layouts/COMP/COMP_flat_gf180.gds` | **0** | **0** | **Condensadores MIM** (`coil_layout/caps.py`, nuevo). Se colocan **después de rutear**, encima del array: el MIM vive en metal4/metal5 y esas capas estaban vacías, así que no hace falta mover nada ni realimentar el floorplan. Cada terminal baja al trunk de su net con una pila metal2→via2→metal3→via3→metal4[→via4→metal5]. `flatten_spice.py` deja de ignorarlos y escribe **dos formas distintas**: `X…` con `c_width`/`c_length` para el layout y **`C…` con `W`/`L`** para el LVS (§12.3). Hubo que renunciar a los PCells `cap_mim` y `via_stack` del PDK, los dos rotos | **2 → 0** en tres iteraciones (`V4.1`×2804, `MIMTM.9/10`, `MT.1`, `M2.2a`, `M3.2a`, `V4.2a`). **El área no crece**: 104.28 × 31.46 µm, igual que sin condensadores. KLayout LVS `Netlists match` con los dos extraídos como `cap_mim_2f0fF` A=200P; netgen 52 vs 52 dispositivos y `Netlists match with 6 symmetries`, con errores de propiedad (A/P contra W/L, §12.3) |

| 17 | 2026-08-05 | `layouts/COMP/COMP_flat_gf180.gds` | **0** | **0** | **Intento de más abutment con D y S intercambiables.** `_order_row()` pasa de un encadenado voraz `A.drain == B.source` a un **recubrimiento por caminos de Euler** (nets = nodos, dispositivos `nf=1` = aristas), que acepta pares D-D y S-S reflejando el dispositivo (`dmirror_x`) y no depende del orden de la netlist. Destapó dos bugs reales del router: `_sd_track_x()` y la dirección del `slack` decidían de qué lado estaba la puerta por el **nombre del terminal**, que el espejo invierte. Añadidos los pads de gate como obstáculos fijos del reparto de stubs y realimentación al placement (`need_gap`) | **Área sin cambio: 104.28 × 31.46.** El abutment extra **no es viable**: un bloque S/D compartido tiene puerta a los dos lados por definición, así que un stub vertical de metal1 que salga de él cruza a la fuerza el pad de gate del vecino (medido: 0.155 µm entre centros donde hacen falta 0.845). La unión queda restringida a nets que no tienen que salir, y ahí el máximo son los **7 por fila que el voraz ya conseguía**. Se conservan los arreglos del router y el solver de cadenas. DRC 0 y LVS limpio en los dos bloques |

| 18 | 2026-08-17 | `layouts/OPAM_LIN_flat/OPAM_LIN_flat_flat_gf180.gds` | **1222** | **48** | **Cuarto bloque: `OPAM_LIN_flat`**, el primero con **resistencia de poly** (`RFB`, `ppolyf_u_3k`, 1 µm × 76.4536 µm, `s=5` → 1.2 MΩ). Primera corrida del serpentín integrado en el flujo completo (`coil_layout/resistors.py` + `extra_channel` en `placement`). Antes solo se había verificado **suelto**, fuera del bloque | Explosión de reglas heterogéneas: `SB.4`×174, `SB.8`×140, `HRES.8`×126, `PL.6`×96, `LRES.5`×88, `LRES.7`×86, `CO.3`×44, `NP.10`×44… Todas en la banda `y = 1.65..13.84` de una celda de 41.77 de alto. **CONFIRMADO** midiendo `(res_mk & comp).area()` = **42.08 µm²**: el serpentín estaba montado sobre la fila N1 |
| 19 | 2026-08-17 | igual | **148** | **10** | **`channel_h` en `Layout`** y serpentín centrado en el canal. `channel_y` era el **centro** del canal, no su borde, y `place_resistors` colgaba el serpentín hacia abajo desde ahí: sus 11 µm atravesaban la mitad inferior y se metían en la fila. Ahora se apila desde el techo del canal (`techo`/`suelo`) y **el que no quepa no se coloca** — va a `res_failed`, porque una resistencia que falta no la ven ni el DRC ni el LVS (la referencia sale del mismo aplanado). Ver §41 | **1222 → 148.** Solape con difusión **42.08 → 0.00 µm²**; el `res_mk` sube de `y=3.44` a `y=9.66`. Desaparecen las 6 familias de resistencia. Quedan `M2.2a`×44 y 90 `*_OFFGRID` |
| 20 | 2026-08-17 | igual | **48** | **4** | **`snap2()`**: las dimensiones que el PCell parte por la mitad se redondean a **0.01 µm**, el doble de la rejilla. El PCell dibuja la tira centrada en el origen, así que un `l_res` múltiplo impar de 5 nm deja los bordes a 2.5 nm. Verificado midiendo el PCell suelto: `l_res=76.455` descuadra seis capas, `76.450` sale limpio. Ver §42 | **90 `*_OFFGRID` → 0** (`contact`, `pplus`, `poly2`, `sab`, `resistor`, `res_mk`). `L` efectiva 76.4536 → 76.450 µm: **−0.0047 % de resistencia**, muy por debajo de la tolerancia del proceso |
| 21 | 2026-08-17 | igual | **6** | **4** | **Salto al trunk por metal3.** El terminal de la resistencia llegaba al trunk con un cable **horizontal de metal2** a su misma altura, y el canal está lleno de stubs verticales de metal2 que lo cruzan. Ahora sube `metal1→metal3` en el terminal, cruza por metal3 —vacío en este flujo— y baja `metal3→metal2` sobre el trunk. Ver §43 | **`M2.2a` 44 → 2.** Las 44 estaban en las dos líneas de `y` de los dos terminales, exactamente donde el cable los cruzaba |
| 22 | 2026-08-17 | igual | **1** | **1** | **INTENTO FALLIDO, y peor: dio un falso limpio.** Se añadió una búsqueda de hueco **solo en x** para el serpentín. Las 905 posiciones fallaron, así que la resistencia **no se colocó** — y como nadie leía `res_placed`/`res_failed`, no salió ni una línea de aviso. Las violaciones bajaron de 6 a 1 y **lo di por bueno**: no era la búsqueda funcionando, era la resistencia desapareciendo | Lección §46. Lo que quedó de útil: `build_block.py` **ahora sí** imprime las resistencias colocadas y falla con `ERROR` si alguna no se coloca o si `place_resistors` no llegó a correr |
| 23 | 2026-08-17 | igual | **1** | **1** | **Columnas de tap repartidas por el grupo `span`.** El pozo en L llevaba una sola columna a la derecha de todo el grupo; con `XM43` partido en cuatro copias el grupo mide ~20 µm y su difusión más a la izquierda quedaba a 18.7 µm, cuando `DF.13_MV` permite 15. Ahora se añaden columnas en los huecos entre dispositivos hasta cubrirlos todos. Ver §45. **Independiente de la resistencia** — es geometría de los PMOS — así que este arreglo sí es válido | `DF.13_MV` 1 → 0 |
| 24 | 2026-08-17 | igual | **0** | **0** | **Búsqueda en x E y, con margen vertical reservado.** Medido con instrumentación: `term0` quedaba aprisionado entre metal2 a `y=9.58` y a `y=10.085`, un hueco de **0.505 µm** donde su pad necesita `0.40 + 2×0.28 = 0.96`. Los trunks son barras **horizontales**, así que moverse de lado no libera nada: había que moverse en **y**. `BUSQUEDA_Y = 2.5 µm` de canal extra en `altura_necesaria` da sitio para saltar de carril (paso de trunk 0.835). Ver §44 | **DRC LIMPIO (0) y esta vez con la resistencia DENTRO**, verificado midiendo: `res_mk` = **382.25 µm² exactos** (= `s·L·W` = 5 × 76.45 × 1.0) y solape con difusión **0.00**. Se colocan además **los dos** condensadores. Queda **un** error de flujo (`INN` sin acceso en metal3). Celda **103.85 × 43.20 µm**: los 2.5 µm de margen de búsqueda cuestan 1.43 de alto |


| 25 | 2026-08-17 | igual | **0** | **0** | **MIM tumbados** (`caps._candidates`): la placa se prueba primero con el lado largo en x. De pie, los 25 µm se comían 25 de los 43 de alto y su metal4 llegaba a `y=43.20`, el techo — **el condensador era lo que fijaba la altura**. El presupuesto de ramas pasa a ser por orientación: compartido, la segunda no llegaba a probarse. Ver §5.7 | **43.20 → 36.37 µm de alto (−16 %)** con los dos MIM, la resistencia y DRC 0. El área de la placa no cambia, así que la capacidad tampoco |
| 26 | 2026-08-17 | igual | **0** | **0** | **`INN` sin acceso en metal3, resuelto.** Tres cosas: (a) el mensaje de error ahora dice la causa — `19 hueco(s) en el trunk pero ninguno sirve` — en vez de solo que falló (§48); (b) el cruce de metal3 de la resistencia respeta una banda de **`BANDA_PUERTO` = 0.85 µm** alrededor del trunk de cada puerto de señal, con el desglose escrito al lado (§47); (c) **bug de cuentas**: la holgura vertical de la búsqueda usaba `dy`, que es un desplazamiento, como si fuera coordenada — daba 0 y la búsqueda en `y` no se hacía (§49). `BUSQUEDA_Y` 2.5 → 5.0, porque al acortarse la celda el canal quedó más apretado | **CERO errores de flujo y DRC 0.** `103.85 × 38.87 µm`, con `res_mk` = **382.25 µm² exactos**, solape con difusión **0.00**, las dos placas MIM de 25 × 4 y todos los puertos con plataforma |

| 27 | 2026-08-17 | `layouts/OPAM_LIN_flat/OPAM_LIN_flat_flat_gf180.gds` | **0** | **0** | **El LVS encuentra un cortocircuito que el DRC no ve.** `OUT` fundido con `VSS` (77 ocurrencias de `OUT|VSS`). Localizado en tres medidas — no era la netlist, bisección sin resistencia (77 → 0) y resta de GDS, que dio las **4 formas de metal1, 5.00 µm²**, en las cabezas izquierdas del serpentín. Causa: `place_resistors` miraba metal2/via1 solo alrededor de los terminales y dibujaba a ciegas los 76 µm de metal1 del serpentín, con 67 straps verticales cruzando el canal. Ver §11.0.1 y §50 | **DRC seguía dando 0 con la salida cortada contra masa.** Arreglado comprobando la huella de metal1 entera (+0.23 de `M1.2a`): contacto **5.00 → 0.00 µm²**, verificado por la misma resta |
| 28 | 2026-08-17 | igual | — | — | **El serpentín deja de caber: límite de floorplan, no fallo.** Al respetar metal1 y pozo, `XRFB` no encuentra sitio. El mensaje de error pasa a traer el **reparto de rechazos en cascada** (banda 1096 / terminal 9783 / metal1 571 / pozo 45 / ok 0), que es lo que permitió leer el problema en una sola corrida en vez de a ciegas. Cuentas: marcador de **78.53 µm** contra un brazo de nwell que ocupa `x 80.82..102.59` → **1.69 µm de ventana**. Se probó ensanchar el brazo a 2 µm y **se revirtió**: la regla penaliza que el marcador CRUCE el borde y el trozo hereda el 1 µm del cuerpo, así que ensanchar no cambia nada (mismos 45 rechazos) | **`OPAM_LIN_flat` no es entregable.** La salida es `s=10` (tiras de 38.2 µm en vez de 76.45), que es cambio de esquemático, y está **bloqueado a la espera de decidir la hoja** (§11.0.2): con 1 kΩ/cuadro el poly pasa de 382 a 1146 µm y hay que replantear los pliegues. Los otros cuatro bloques siguen con DRC 0 y LVS limpio |

| 29 | 2026-08-18 | los cinco `*_flat_gf180.gds` | **0** | **0** | **`OPAM_LIN_flat` cerrado: cinco fallos que sólo veía el LVS, más dos silencios en las propias comprobaciones.** (a) `run_lvs.sh` juzgaba a KLayout por su **código de salida**, que es siempre 0: decía `LIMPIO` con `ERROR : Netlists don't match` en el log (§12.5). (b) `flatten_spice.build_lvs_netlist()` **no emitía las resistencias**, así que la referencia no tenía realimentación (§11.0.8). (c) El PCell trae una **toma de sustrato** que la envolvente de metal1 se tragaba: los cinco tramos con un extremo en `VSS` (§11.0.3, §54). (d) `term1` apuntaba a un **nodo interno** por una paridad invertida (§11.0.4). (e) El giro de `XM43` ahorraba **0.30 µm** y a cambio cortocircuitaba `G_OUT_P` con `OUT`: `_ROT_MIN_RATIO = 3.0` (§11.0.5, §52). (f) Una **placa MIM encima del terminal** impedía que la extracción lo conectara — probado borrando sólo esas capas del mismo GDS (§11.0.6, §55). (g) `L=76.4536 µm` **no es dibujable** en rejilla: corregido en el esquemático a 76.45 (§11.0.7, §56). Y el canal se dimensionaba como `max` en vez de **suma** de trunks y serpentín, que era lo que dejaba al terminal sin banda (§11.0.1b, §53) | **DRC 0 y LVS limpio en las DOS herramientas, en los cinco bloques.** `OPAM_LIN_flat` **98.75 × 49.57 µm**, `res_mk` = **382.25 µm² exactos**, solape con difusión y con pozo **0.00**, cadena extraída de `G_OUT_P` a `OUT` con los cinco tramos. Los otros cuatro **no cambian de tamaño ni un nanómetro**. `ppolyf_u_3k` **sí es verificable**: `POLY_RES Selected is 3k`, 229 350 Ω por tramo (§11.0.2). Circuito comprobado tras el cambio de `L`: 103.4 V/V, INL 0.12 %, 2.550 mW, margen de fase 73.9°, offset +24.0 → **+23.8 mV** |

| 30 | 2026-08-18 | los cinco `*_flat_gf180.gds` | **0** | **0** | **Los dos MIM, tumbados de verdad.** El veto del terminal de la resistencia (§11.0.6) había dejado a `XC1` **de pie**, con sus 25 µm en vertical fijando otra vez la altura de la celda — el problema que §5.7 daba por cerrado. Preferir tumbado no basta porque es una preferencia local y el primero se lleva el sitio. Cuatro cambios en `caps.py`, y hacen falta los cuatro (§5.7.1): pasada previa que **prohíbe** las placas de pie; la placa se construye también **hacia abajo** del punto de agarre (solo iba hacia arriba, y ésa era la causa de fondo); puntos de agarre **repartidos** (`_AGARRE_SEP`), porque las 40 alternativas se iban en 1.3 µm de trunk; y **varias rutas de metal5** por pareja, porque el primer MIM levantaba una barra de `x 12.4` a `x 72.2` a una sola altura y el segundo tenía que bajar atravesándola. `_BRANCH` 40 → 90, que hizo falta al duplicarse los candidatos | **`OPAM_LIN_flat` 98.22 × 55.16 → 98.75 × 49.57 µm**: 5.59 menos de alto por 0.53 más de ancho, **523 µm² (−9.7 %)**. Las **seis** placas de los tres bloques con MIM quedan tumbadas. `COMP` y `OPAM` **no cambian de tamaño**. DRC 0 y LVS limpio en las dos herramientas, en los cinco |

| 31 | 2026-08-18 | los cinco `*_flat_gf180.gds` | **0** | **0** | **`BUSQUEDA_Y` 5.0 → 2.0, medido en vez de a ojo** (§5.6.7). Barrido de 3.0 a 0.0 mirando cuánto baja el serpentín de verdad: **0.40 µm siempre**, con la resistencia colocada y `res_mk` exacto en los siete casos. La reserva **había sobrevivido a su motivo**: se puso cuando el terminal tenía que buscar hueco entre trunks, y desde que el canal se reparte (§11.0.1b) la banda del serpentín nace limpia. Se deja en 2.0 y no en 0.4 para cubrir el peor caso realista, esquivar la banda prohibida de un puerto (1.7 µm) | **`OPAM_LIN_flat` 98.75 × 49.57 → 98.22 × 46.57 µm**: 3.00 µm menos de alto, y devuelve las 0.53 de ancho que se había llevado el MIM tumbado. **321 µm² (−6.6 %)**. Total del bloque en las tres últimas iteraciones: **5418 → 4574 µm², un 16 %**. Los otros cuatro no se mueven; DRC 0 y LVS limpio en las dos herramientas, en los cinco |

| 32 | 2026-08-18 | `layouts_v2/*_flat_gf180.gds` | **0** | **0** | **v2 del generador, con interruptor** (`--v2`, §13). Cuatro cambios: un solo contacto de puerta (`gate_con_pos` por fila, solo `nf=1`); cada fila pegada a su riel (el hueco a VPWR iba de 0.35 a **8.35** en `COMP` y a **9.85** en `OPAM_LIN_flat`); y el **salto del stub por metal2** sobre el pad de gate, que desbloquea el abutment de nets que salen del par —14 → 24 en `OPAM` y `OPAM_LIN_flat`—. Los trunks en metal3 **no** se hicieron, y §13.3 explica con la cuenta por que intercalarlos en el canal gana cero. De paso salieron dos bugs latentes de la v1: `_hbar` y el nwell usaban `gf.components.rectangle`, que cachea por tamano y dejaba los rieles en x = **−0.999** | **−7.3 % de area en total**: `DECODER` −17.0 %, `OPAM` −9.1 %, `OPAM_LIN_flat` −8.7 %, `COMP` −4.3 %. Los cinco bloques de la v2 con **DRC 0 y LVS limpio en las dos herramientas**, contra la MISMA netlist de referencia que la v1. Y la v1 **no se mueve ni un nanometro**, que es el control |\n
| 33 | 2026-08-18 | `layouts/` y `layouts_v2/` | **0** | **0** | **Los bancos con el layout dentro, y por que magic no extraia la resistencia.** Los siete bancos pasan a tres columnas (esquematico, v1 RC, v2 RC). Dos cosas hubo que resolver: **magic emite los puertos en el orden en que los encuentra**, y ese orden cambia con el layout —`OPAM_LIN_flat` v1 `... INP OUT INN` contra v2 `... INP INN OUT`—, asi que cablear las dos igual ponia la salida en la entrada negativa **sin dar ningun error**; y **magic no extraia la resistencia de poly** porque deriva el dispositivo como una AND de cuatro capas y la evalua celda a celda, mientras gdsfactory escribe cada rectangulo en su propia celda (§14.1). Se aplana el GDS con KLayout **antes** de dárselo, y solo donde hay resistencias: aplanar cuesta caro —`WEIGHT_COMP` pasa de 9 s a **mas de 10 minutos**— y solo un bloque la necesita | **El layout no rompe el circuito**: `OPAM_LIN` da 102.9 de ganancia contra 103.1, misma INL (0.12 %), mismo offset (+23.8 mV) y mismo consumo. Lo que cuesta son **8.7 grados de margen de fase** (73.9 → 65.3) y un 10 % de slew. **La v2 se comporta como la v1** (65.1 contra 65.3 gr) ocupando un 8.7 % menos. El RC salio barato: el banco mas lento son **5.8 s** |\n
| 34 | 2026-08-18 | `openroad/out_v2/GRADIENT_NAV.gds` | **0** | **0** | **El top armado con las celdas de la v2** (§15). Interruptor de version que recorre el flujo entero: `usar_version.sh` reapunta los enlaces de `gds/`, `TOP_OUT` separa la salida y `lef/.version` impide construir con un collateral de la otra version. De paso destapo un defecto **mio** de la v2: al dejar que la placa MIM creciera hacia abajo (§5.7.1) se salia de la celda y tapaba el riel VGND, y `pdngen` abortaba con `PDN-0006`. Arreglado obligandola a quedarse **entre los dos rieles** (§15.3) | **die 371.70 × 408.52 → 378.08 × 374.10 µm**, o sea 0.1518 → **0.1414 mm² (−6.9 %)**, con DRC del router 0, DRC de firma limpio (con y sin relleno) y las 7 reglas de densidad cumplidas. **PERO el LVS del top NO casa** (944 nets contra 880, fallo de emparejamiento de pines) mientras el de la v1 si: queda ABIERTO y documentado con lo ya descartado (§15.2). `OPAM` v2 baja ademas a 31.42 µm de alto |\n
| 35 | 2026-08-19 | `openroad/out/` y `out_v2/` | **0** | **0** | **Cerrado el LVS del top de la v2**, que quedo abierto en #34. No era ni el layout ni la extraccion: al parametrizar el `Makefile` por version le pase a `def_to_gds.py` el DEF del **floorplan** en vez del **ruteado**, asi que el GDS salia con los macros colocados y **sin una sola conexion**. Pasa el DRC —no hay nada que pueda violar una regla— y pasa el relleno; solo lo vio el LVS. La medida que lo cerro: **formas por net de pin, 41..125 en la v1 contra 1 en los 17 pines de la v2** (§15.2). De paso, el top de la v1 que habia en disco era de una corrida vieja y hubo que rehacerlo entero, porque DEF, LEF y GDS tienen que venir de la misma (§15.2.1) | **Los dos tops verificados y comparables**: `Circuits match uniquely` (880 = 880 nets), **55/55 nets conectadas y 0 cortos** en ambos, DRC de firma limpio con y sin relleno, y las 7 reglas de densidad. v1 **0.1518 mm²** contra v2 **0.1414 mm² (−6.9 %)** |\n
| 36 | 2026-08-19 | `layouts_v2/*_flat_gf180.gds` | **0** | **0** | **Trunks en metal3 POR ENCIMA de las filas: escrito, medido y APAGADO** (§13.3). Mecanismo entero en `routing.py` (`_nets_a_metal3`, `_banda_m3`, `_via2_patch`, `_Access.en_m3`/`y_hop`) mas `Layout.cap_nets`/`res_nets` en `placement.py`. Sube **solo la net que no necesita nadie mas**: se quedan abajo las de puerto, condensador y resistencia, que son las tres familias que `caps`, `resistors` y `power` leen de `lay.trunks` dando por hecho metal2 — asi los trunks de metal3 no se apuntan y **no hubo que tocar ninguno de los tres modulos**. Lo que **no** esta resuelto: **39 violaciones**, 21 `M2.2a` con pares de aristas a **0.135 µm** donde la regla pide 0.28; estrechar el vertical de 0.38 a 0.28 las subio a **72**, o sea que la causa no es el ancho sino que `_spread_stubs` reparte en x contando solo el **metal1**. Y magic pasa de segundos a **mas de 10 min** (su tiempo limite) con metal3 sobre las filas | **Medido: el canal de `COMP` pasa de 13 pistas a 3** y la celda de `99.75 × 31.46` (3138 µm²) a `105.88 × 25.42` (**2690 µm², −14 %**); `OPAM` y `OPAM_LIN_flat` 13 → 4, `WEIGHT_COMP` 11 → 4, `DECODER` 6 → 4. **Se deja detras de `Opciones.trunks_m3 = False`** y se verifica la reversion: los cinco bloques de la v2 vuelven a su tamano exacto, con **DRC 0 y LVS limpio en las dos herramientas**. Un entregable verificado no se cambia por algo a medias |
| 37 | 2026-08-20 | `openroad/out_v2_GRADIENT_NAV2/` | **0** | **0** | **Tercer top: `GRADIENT_NAV2`**, el navegador con la cadena lineal. El flujo pasa a estar parametrizado por top (`make top T=GRADIENT_NAV2 V=v2`) igual que ya lo estaba por version: `TOP_CELL` recorre `load_design.tcl`, los dos `.tcl` de floorplan y ruteo y los seis guiones de verificacion, y cada combinacion escribe en su propio directorio. Se anade `OPAM_LIN_flat` al collateral —no estaba, y **tampoco estaba en las listas de DRC ni de LVS** desde que se creo— con el alias `OPAM_LIN` → `OPAM_LIN_flat` en `spice_to_verilog.py`, porque el esquematico y el layout llaman distinto a la misma celda. La primera corrida dio **43/55 nets**: las 12 abiertas eran las salidas de los amplificadores, y la causa esta en §15.5 | **418.24 × 413.53 µm = 0.1730 mm²** (+22 % sobre el top con `OPAM`, que es lo que cuesta el amplificador lineal: 4178 µm² contra 2427), **31 macros**, DRC del router 0, **DRC de firma limpio** y **55/55 nets con 0 cortos** |
| 38 | 2026-08-20 | `openroad/scripts/decap_fill.py` | **4** | **1** | **Relleno de desacople: transistores en los huecos del top** (§15.6). Medido primero: de los **80 382 µm² libres** solo son alcanzables **18 523** (23 %), porque un relleno solo se ata a VDD y VSS **por abutment de metal1** si tiene al lado un macro con los rieles a su misma altura. Cuatro cosas resueltas por el camino, todas medidas: el **anillo de guarda del PCell no es limpio a 6 V** (`grw=0.22` contra los 0.30 de `DF.1a_MV`: 768 `CO.4` + 348 `CO.7` + 184 `CO.6`); llamar al PCell **en crudo** deja 220 `CO.7` porque falta `_fix_pcell_co7_gf180`, que `map_device` ya aplica; los **taps van EN los huecos entre dispositivos** y el hueco tiene que medir `TAP_W + 2·CLR` o no cabe ninguno (`DF.14_MV`); y la barra VSS de cierre arrancaba pisando el carril de VDD, o sea **cortocircuitando las dos alimentaciones** — que el DRC solo asomaba como cuatro `M1.2a` y se vio **extrayendo las nets** | De **930 violaciones a 4**, todas `M1.2a` de 0.07 µm y **una por dispositivo**. Los dos rieles salen como **nets separadas**, comprobado por extraccion. **Sin integrar en el top**: el `GRADIENT_NAV2` verificado no se toca hasta que la baldosa este limpia |

<!-- Plantilla para la siguiente fila:
| 39 | 2026-08-21 | `openroad/out_v2_GRADIENT_NAV2/*_decap.gds` y `*_filled.gds` | **0** | **0** | **El desacople, dentro del top; y el primer LVS de `GRADIENT_NAV2`** (§15.6, §15.7). Cinco fallos por el camino, todos medidos: (1) la puerta se cogia como `cajas[0]` en el PMOS cuando los dos dispositivos se construyen con `gate_con="top"` — se estiraba la **placa de puerta** hasta el riel contrario, de ahi las cuatro `M1.2a` que quedaban, y el PMOS acababa **cortado y sin capacidad**; (2) las cajas del PCell se pasaban a micras con el dbu del layout **de destino** (0.0005) en vez del suyo (0.001), o sea dispositivos a **mitad de tamano**: 1180 `M1.1` + 886 `M1.2a`; (3) los rieles de los macros **no llegan a sus dos bordes** — por la izquierda empiezan 0.26 µm dentro — asi que una baldosa de borde a borde queda **abierta** y el DRC no se entera; (4) `alcance` tomaba un **dedo de transistor** de `WEIGHT_COMP` por un riel y cortocircuitaba `net5`/`net6` de tres WEIGHT contra VSS: **DRC limpio, 877 nets contra 880 en el LVS**; (5) los estantes **se solapan en `y`** (WEIGHT_COMP dentro del hueco de las filas de COMP) y se colocaban baldosas encima de baldosas. Y en las herramientas: `align_ports` sin plegar continuaciones y la hoja de poly de 3 kΩ/□ ausente en los dos LVS del top | **36 baldosas, 229 transistores** (119 N + 110 P) de hasta **18 µm** de canal —una sola fila de N y una de P por hueco, con tap arriba y abajo para que `DF.13_MV`/`DF.14_MV` los dejen crecer—, 22 407 de 25 183 µm² utiles (**89 %**), **~5.11 pF**. `_decap` y `_filled` con **DRC de firma 0**, `_filled` con **densidad 0** en las 7 reglas, **netgen `Circuits match uniquely`** en los dos y **KLayout `MATCH`** (851 nets, 0 dispositivos, 0 pines) en `_decap` |
| 40 | 2026-08-21 | `openroad/` + `XSCHEM/TEST_TOTAL/` | **0** | **0** | **El top, listo para padring; y banco del top contra su layout con RC** (§15.8, §16). Cuatro cosas del contorno: (1) `VDD`/`VSS` estaban **dentro** del die, a 23 µm de la esquina y declarados `USE SIGNAL` -- ahora su tira de Metal5 se prolonga hasta el borde y los pines salen ahi, como `POWER` y `GROUND`; (2) el metal1 del desacople y el relleno de COMP llegaban a **0.000 y 0.005 µm** del contorno -- margen de guarda de **2 µm** en `decap_fill` y en `fill_density`, y en los huecos de borde el pozo se aparta solo 0.2 porque `NW.2b_MV` no aplica contra la nada; (3) los pines estaban a **1.12 µm** unos de otros, ahora a 5.04 (`place_pins -min_distance`); (4) escritos `info.yaml` con los 19 pines en orden horario y `lvs_config.json`. Y el banco `test_NAV2.sch`, con `comprobar_nav2.py` verificando que el navegador rehecho a mano es el MISMO grafo que el esquematico -- probado a la contra con un nodo cambiado y con el cruce VB/VC del `WEIGHT_COMP`, que los caza los dos | Router DRC **0**; DRC de firma y densidad **0** en `_decap` y `_filled`; **netgen `Circuits match uniquely`** en los dos y **KLayout `MATCH`** (852 nets, 0/0/0). **224 transistores de desacople, ~4.93 pF**. Banco: Vcm 2.500000 clavado, y esquematico contra layout RC **14° de 360 a fondo de escala y 0° en la ventana fina** |
| 41 | AAAA-MM-DD | archivo.gds | NNN | NN | qué se cambió y en qué archivo | reglas top / qué mejoró |
-->

---

## 9. Lecciones aprendidas

Reglas generales destiladas de los errores ya cometidos. Orden: de más a menos costoso.

0. **Una comprobación que no puede fallar no está comprobando nada.** Antes de creerte un
   «limpio», rompe el layout a propósito y mira si salta: `make probar` en
   `a_zonetic2026/openroad`. Aquí han aparecido **tres** comprobaciones que no fallaban
   nunca —el `net.name` vacío, el DRC que daba «limpio» sin haber arrancado, y el lector
   de pines que solo miraba `PLACED`—, y las tres tenían el mismo síntoma: silencio.
   Detalle en §12.5. *(La regla más cara del proyecto.)*
1. **El `klayout` de pip no puede correr DRC.** Solo expone la API de Python; el DSL de
   los decks `.drc` se interpreta en Ruby dentro del binario completo. Cualquier
   verificación real exige el contenedor. *(Origen del documento.)*
2. **La netlist de Xschem hay que aplanarla antes de hacer layout.** `spice_parser.py`
   solo entiende un `.subckt` plano de MOSFETs; `flatten_spice.py` expande la jerarquía
   (`WEIGHT` → `comp._out` → `INV_1`) prefijando nets e instancias.
3. **Las fuentes `V` de 0 V son cortos, no dispositivos.** Los `Vmeas` de Xschem deben
   fusionar sus dos nets (`x1_net10..13 → GND`); si se ignoran, esos *sources* quedan
   flotando y el layout resultante no corresponde al esquemático.
4. **El multiplicador `m` se estaba perdiendo.** `device_map.py`/`placement.py` no lo
   soportan: un `m=3` se dibujaba como un único transistor. `flatten_spice.py` lo expande
   a copias paralelas explícitas. No se mapea a `nf` porque el wrapper de puertos de
   `device_map.py` asume `nf=1` (con *fingers* pares el pad de drain caería sobre
   difusión de source).
   **ACTUALIZADO 2026-08-02:** ahora `m` sí se mapea a `nf` (iteración #2). El wrapper
   multi-finger une las regiones S/D con straps de metal2 (via1 de 0.26 exacto) y los
   dos grupos de contactos de gate alternados con barras+riser de metal1; los puertos
   S/D quedan en risers laterales de altura completa, así que el problema de los
   *fingers* pares desaparece. Solo si `W<1.2` o `L<0.8` (no caben los straps) se
   mantiene la expansión a copias.
5. **Un DRC con centenares de violaciones suele ser un puñado de bugs.** 629 violaciones
   = 6 causas raíz, y una sola (las vías) explica el 55 %. Agrupar por causa antes de
   tocar código; nunca atacar la lista regla por regla.
6. **El DRC también encuentra errores de esquemático, no solo de layout.** `PL.2_MV`
   destapó `L=0.5u` en PFETs de 6 V, que viene del `.spice` original. Antes de "arreglar
   el generador", comprobar si la violación nace en la netlist.
7. **Versiones clavadas ≠ versiones del contenedor.** La imagen trae gdsfactory 9.44 /
   kfactory 2.5; el proyecto exige 9.2.2 / 1.2.2. Usar siempre el venv aislado; el Python
   del sistema del contenedor rompería el generador en silencio.
   **CORREGIDO 2026-08-02:** el venv por sí solo no basta — ver la trampa del `PYTHONPATH`
   en §10. Durante meses se creyó estar usando 9.2.2 y en realidad corría 9.44.
8. **El PCell del PDK también viola DRC.** `gf180==0.1.1` trae dos bugs de `CO.7` (§6.4)
   y uno de poly en `draw_pfet`. Antes de culpar al generador, **medir el PCell aislado**:
   instanciarlo suelto, escribirlo a GDS y comprobar las distancias a mano. Eso separa en
   un minuto "el generador lo coloca mal" de "el PCell viene mal".
9. **Arreglar una regla puede romper otra; medir siempre después.** Los pads de vía de
   0.34 µm limpiaron las 234 violaciones `V1.*` y crearon 11 `M1.2a` nuevas. Achicar ese
   pad a 0.26 para descongestionar disparó 43 `V1.3d`. Separar más los dispositivos
   (`DEVICE_GAP` 1.0→1.4) subió `M1.2a` de 9 a 11 y ensanchó la celda 5.7 µm. Ninguna de
   las tres se podía predecir leyendo el deck: hay que correr el DRC.
10. **Los tamaños "redondos" no garantizan estar en rejilla.** `gf.components.rectangle`
    devuelve celdas cacheadas por tamaño y reutilizaba la misma celda para alturas que
    diferían menos de 1 nm, así que la caja dibujada no medía lo pedido → `*_OFFGRID`.
    Para geometría cuyo tamaño se calcula, insertar la caja directamente
    (`c.shapes(...).insert(kdb.DBox(...))`) en vez de usar el componente cacheado.
11. **El DRC no ve los cortos; el LVS sí.** El layout pasó de 629 a 12 violaciones con un
    cortocircuito entre dos nets todavía dentro. Un DRC limpio no dice nada sobre si el
    circuito es el que se dibujó: hay que correr LVS.
12. **Una violación de DRC puede ser un dispositivo mal elegido, no una geometría mal
    dibujada.** Las 6 `PL.2_MV` no venían de un `L` equivocado: el inversor usaba las
    medidas exactas de la celda estándar `gf180mcu_fd_sc_mcu9t5v0__inv_1`
    (PFET 0.5/1.83, NFET 0.6/1.32) pero declaradas como `*_06v0`. El deck separa las dos
    familias por el marcador **`v5_xtor` (112,1)** —`ngate_5v = ngate_56v.and(v5_xtor)`,
    `ngate_6v = …not(v5_xtor)`— y los mínimos de canal son 0.55/0.7 en 6 V pero **0.5/0.6
    en 5 V**, justo lo que usaba. Cambiar el modelo a `*_05v0` en el esquemático las
    eliminó las 6 sin tocar una línea del generador. Antes de reescribir geometría,
    comprobar **qué dispositivo cree el deck que estás dibujando**.
13. **Un canal de ruteo necesita alto suficiente, y eso se calcula, no se elige.** El
    canal tenía 4.0 µm fijos: 2.74 µm útiles para 10 trunks que necesitaban 6.82. Los
    trunks sobrantes se dibujaban *dentro* de las filas de dispositivos, chocando con su
    metal. Se veía como violaciones de espaciado dispersas y parecía congestión local,
    cuando era falta de sitio. Antes de retocar separaciones, **comprobar que la capacidad
    del canal da para las nets que hay** (`nets_to_route()` × `TRUNK_PITCH`).
14. **La restricción vertical del ruteo de canales no es opcional.** Si la net A tiene un
    pin abajo (su stub sube) y la net B uno arriba (su stub baja) casi en la misma x, los
    stubs comparten columna y solo dejan de pisarse si el trunk de A va **por debajo** del
    de B. Asignar los trunks por número de pines lo ignoraba y producía el corto
    `x1_net6`↔`WE`. La solución es un orden topológico sobre esas restricciones
    (`routing._order_trunks`), no empujar los stubs en x: los pines S/D no tienen holgura
    porque su x la fija el pad de gate del propio dispositivo.
    Ojo con las medias tintas: ordenar por *altura media de los pines* parecía capturar la
    misma idea y **empeoraba** (22 dispositivos y un corto extra). La restricción es por
    pares de pines, no un promedio.
15. **Para acortar las nets, alinear las filas importa mucho más que reordenarlas.** Se
    probó ordenar los dispositivos (encadenado voraz por nets compartidas, orden por
    baricentro) y **los dos empeoran**: 7→8 y 7→5 pistas. El orden de la netlist ya es
    bueno porque el esquemático agrupa por función. Lo que sobraba era otra cosa: la fila
    P se empaquetaba a la izquierda (22 µm) mientras la N llegaba a 68, así que **toda net
    que cruzaba pagaba la diferencia de largos**. Centrando cada cadena de la fila corta
    sobre sus vecinos (`_barycenter_targets`) se pasa a **4 pistas, que es la cota
    inferior** (la densidad máxima del canal es 4). Antes de tocar el orden, mirar si las
    filas están alineadas.
16. **Al alinear una fila hay que devolverla al origen.** El empaquetado con objetivos
    solo empuja a la derecha, así que la primera cadena arrastra la fila entera: N2
    arrancaba en x=12.6 y regalaba ese ancho por la izquierda (47.6 µm en vez de 37.2).
    Se corre la fila completa al origen, que conserva el estirado interno —que es lo que
    acorta las nets— sin pagar ancho.
17. **Un enlace entre canales se planifica antes de repartir pistas, no después.** Tres
    intentos fallidos seguidos, cada uno con su síntoma en el LVS:
    (a) acabar los tramos justo en el cambio de capa deja cada via1 con metal1 solo por
    debajo y metal2 solo por encima → no conecta (nets **de más**);
    (b) elegir la columna después de dibujar los trunks hace que la via caiga fuera del
    metal2 del trunk → tampoco conecta;
    (c) estirar el trunk hasta la columna después de repartir pistas hace que dos trunks
    de la misma pista se solapen → **corto** (nets de menos).
    El orden correcto: elegir columna → meterla en el span → repartir pistas → dibujar,
    con cada tramo solapando el cambio de capa.
18. **Bloquear el bounding box entero es demasiado.** Al cruzar una fila la columna va en
    metal2 y ahí solo le estorba el metal2: los straps de S/D de los multi-finger. Los
    dispositivos de un dedo no llevan metal2 y se puede pasar por encima. Bloqueando el
    bbox completo, 5 de 6 enlaces se quedaban sin sitio.
19. **Un pad de vía suelto tiene que cumplir el área mínima.** `M1.3`/`M2.3` piden
    0.1444 µm², o sea 0.38 de lado. En metal1 da igual porque el pad siempre se fusiona
    con su stub, pero en metal2 un trunk corto o el pad de un enlace quedan aislados: con
    0.34 violaban área. De ahí que el pad de metal2 sea 0.38 y el de metal1 se quede en
    0.34, que en el canal el espacio en x es justo lo que escasea.
20. **Los avisos silenciados esconden fallos de conectividad.** `build_block.py` hace
    `warnings.filterwarnings("ignore")`, así que los `warnings.warn` del router no se
    veían y un enlace que no se colocaba pasaba desapercibido hasta el LVS. Lo que rompe
    la conectividad se reporta por un canal propio (`Layout.unlinked`) y se imprime.
21. **Los formatos de export de Xschem no son uno solo.** El mismo bloque, re-exportado,
    pasó de `.subckt` + líneas `M...` a top con la cabecera **comentada** (`**.subckt`),
    MOSFET como `XM...` con el modelo en la última posición y parámetros con expresiones
    entre comillas *con espacios dentro*. Los tres rompen un parser hecho a base de
    `split()`. Al tocar el parser, probar **siempre contra los dos formatos**: la
    compatibilidad hacia atrás es parte del entregable.

22. **Dos pines de la misma net pueden pedir una sola vía, no dos.** Si caen en el mismo
    trunk y cerca en x —lo típico: uno en cada fila—, sus dos `via1` se fusionan en una de
    0.46 µm y `V1.1` exige **0.26 exactos** (es min *y* max). Separarlas no vale: los pines
    S/D casi no tienen holgura porque su x la fija el pad de gate. La salida es unirlos en
    metal1 y poner **una sola vía** por grupo (`_via_groups`). Ojo con la barra de unión:
    si va de centro a centro deja un escalón de medio stub donde uno termina y eso lo
    cuenta `M1.1` como ancho por debajo del mínimo — tiene que cubrir los stubs de punta
    a punta.
23. **`_required_sep` no puede mirar solo el solape vertical.** Dos stubs que salen en
    direcciones opuestas desde el mismo trunk no comparten franja vertical, así que la
    comprobación de solape los daba por buenos; pero sus **pads de vía están a la misma
    altura** y se pisan igual. Hay que tratar aparte el caso "mismo trunk".
24. **Un cambio de esquemático destapa bugs latentes del generador.** Pasar `XM2` de
    `W=4u m=3` a `W=2u m=6` no cambia el ancho total, pero reorganiza la geometría lo
    justo para sacar los dos fallos de arriba, que llevaban ahí desde el principio sin
    manifestarse. Tras cada re-export, **volver a correr DRC y LVS**: que el circuito sea
    equivalente no garantiza que el layout salga igual de limpio.
25. **Los altos de fila se miden, no se estiman.** `max(W) + 1.5` parecía razonable pero
    ignora cuánto sobresale el envoltorio (pads de gate, dualgate) y **cuánto varía entre
    filas**: dejaba la fila N2 a 1.72 µm del tap mientras N1 estaba a 0.25. Usando la
    extensión real (`component.dymin/dymax`) las dos quedan simétricas. Acercar los
    transistores al tap no es solo área: acorta el camino de sustrato y aleja el latch-up.
26. **En SPICE la primera letra del nombre ES el tipo de dispositivo.** Instanciar un
    subcircuito con `extrc ... WEIGHT_COMP` no llama a nada: la `e` inicial lo convierte
    en fuente de tensión controlada, y ngspice acaba fallando con
    `MIF-ERROR - model: a$poly$extrc - Bad real value`, un mensaje que no menciona ni el
    subcircuito ni la línea original. Ante un error de ngspice que habla de modelos XSPICE
    o de "bad real value" sin venir a cuento, **mirar la primera letra de los nombres de
    instancia**.
27. **Los márgenes al límite se buscan barriendo, no razonando.** Deducir el mínimo de
    las reglas es traicionero porque suele mandar una que no habías considerado: aquí el
    cálculo por `DV.3` (0.24) daba margen de sobra a 0.30, pero el DRC lo rechaza y el
    mínimo real es **0.35**. Barrer el parámetro y quedarse con el último valor limpio
    cuesta cinco corridas y da el dato, no la conjetura.
28. **Un heurístico voraz que solo empuja en un sentido falla en silencio.** El reparto
    de stubs recorría el canal de izquierda a derecha empujando cada uno lo justo; el que
    ya estaba en el borde de su pad no podía ceder y el roce se quedaba sin arreglar y sin
    aviso. Relajar después tirando del vecino tampoco sirve: **oscila**, porque arreglar
    un par rompe el siguiente. Cuando el problema es un sistema de restricciones
    (aquí, diferencias en 1-D: `x_j - x_i >= s_ij` con cada `x_i` dentro de su pad),
    **resolverlo, no aproximarlo** — sale más corto que el heurístico y da la respuesta
    exacta, incluyendo el "no hay solución".
29. **Un fallback que "acepta un roce" deja de ser aceptable al cambiar de bloque.**
    `_free_x` se rendía tras 3 µm de búsqueda y devolvía la posición que chocaba, con el
    argumento de que perder el tap era peor. Con los PFET de 10 µm de `COMP` ese caso pasó
    de raro a sistemático. Un fallback que produce geometría inválida **a propósito** hay
    que revisarlo en cuanto cambian las dimensiones típicas del diseño.
30. **Al aplanar, poner el prefijo de jerarquía solo donde hay choque de verdad.**
    Renombrar `M4` a `Mx1_M4` siempre hace imposible seguir un transistor del esquemático
    al layout, y en la mayoría de diseños los nombres ya son únicos (en `COMP`, los 50).
    Un GDS además **no guarda nombres de instancia**, así que hace falta escribirlos como
    texto: la capa `VTEXT` (63/63) del PDK sirve, está mapeada en magic y ninguna regla
    del deck la lee.
31. **Un `-` o un `+` en el nombre de un puerto rompe el LVS con netgen.** KLayout los
    escapa al extraer (`IN-` → `IN\x2d`) y netgen compara la cadena cruda: la topología
    casa (`Device classes are equivalent`) pero el resultado final es
    `Top level cell failed pin matching`. Se arregla **en el esquemático** (`INN`/`INP`);
    no es un problema del layout, y además un `-` en un nodo de SPICE da guerra aguas
    abajo (se puede leer como signo).
32. **Una optimización buena para un bloque puede ser mala para el siguiente.** Partir la
    fila N en dos bajó `WEIGHT_COMP` un 9 % porque tenía 2.6 veces más N que P. Aplicada a
    `COMP`, que está equilibrado (0.92), *sube* el área: dos medias filas bajo una P que
    sigue marcando el ancho, más un canal y un riel de alto. La decisión hay que ligarla a
    **la medida que la justificaba**, no dejarla clavada.
33. **Antes de dibujar sobre una capa nueva, mirar qué reglas despierta.** Meter el MIM
    activó de golpe metal3/4/5, via2/3/4 y las `MIMTM.*`, todas en 0 hasta entonces porque
    las capas estaban vacías. Tres sorpresas que no se deducían de lo obvio: `MIMTM.10`
    prohíbe via3 donde el metal4 se solapa con el `fusetop` (los contactos van **fuera** de
    la placa); `MIMTM.1` pide 1.2 µm de la placa a cualquier otro metal4, y por eso la
    placa se dibuja como **rectángulo** hasta el contacto y no como placa + brazo (un
    convexo no puede violar la separación consigo mismo, una escotadura sí); y con 5LM
    **metal5 ES el metal top**, así que le aplican `MT.*` (0.44 de ancho mínimo) y no
    `M5.*` (0.28).
34. **El área mínima de metal está clavada en el cuadrado del pad "obvio".** `M3.3`/`M4.3`
    piden 0.1444 µm², que es 0.38² exacto — justo el pad que sale de sumar la vía (0.26) y
    dos enclosures de 0.06. Trabajar en la igualdad es pedir problemas: 0.40 cuesta lo
    mismo y deja margen en área, ancho y enclosure a la vez.
35. **Contar polígonos vecinos no sustituye a correr la regla.** Para decidir si un pad
    cabía sobre un trunk se miraba que solo tocase un polígono de metal2. Falla: el trunk y
    sus pads de vía están fusionados en uno solo, así que el pad podía caer a 0.01 µm de
    otro pad **de su misma net** y dejar una escotadura, que `M2.2a` sí mira. Lo fiable es
    recortar una ventana, añadir la forma nueva y correr `space_check`/`width_check` ahí
    mismo: es la propia regla, y sobre una ventana pequeña sale gratis.
36. **Los PCells del PDK hay que verificarlos siempre.** `gf180.via_stack` está roto sin
    remedio (usa `m_enc` como float en una línea y lo indexa como tupla en la siguiente, así
    que falla se le pase lo que se le pase) y `gf180.cap_mim` genera las vías de **0.22**
    cuando `V4.1` exige 0.26 exactos: 2804 violaciones de una tacada. Van tres veces, con
    los dos bugs de `fet.py` y `CO.7`. Sale más barato dibujar la geometría a mano.
37. **Una difusión compartida solo sirve para nets que no tienen que salir.** Es tentador
    abutir más pares —en `COMP`, `VDD` y `VSS` tienen 8 fuentes por fila— pero el bloque
    S/D compartido tiene **puerta a los dos lados por definición**, así que queda
    encajonado: el pad de contacto de gate sobresale de la difusión justo por donde el
    stub tendría que cruzar, y un stub vertical de metal1 se le pone a 0.155 µm cuando
    `M1.2a` pide 0.845 entre centros. El problema **no es el contacto** (ensanchar el
    bloque a 0.52 y ponerle uno propio pasa `CO.7` sin problema), es el camino de salida.
    Para abutir nets ruteables el stub tendría que saltar el pad de gate por metal2.
38. **Decidir por el nombre del terminal lo que en realidad decide la geometría.**
    `_sd_track_x()` daba por hecho «source = bloque izquierdo, drain = bloque derecho»,
    y la holgura del stub se orientaba igual. En cuanto un dispositivo se refleja para
    intercambiar S y D, las dos cosas apuntan al lado contrario: el stub se salía de su
    propio pad —pin **flotante**, que el DRC no ve— y rozaba al vecino. Cuando un atributo
    se puede leer de la geometría colocada, leerlo de ahí.
39. **Un solver exacto no puede mover lo que no es suyo.** Al meter los pads de gate como
    obstáculos en el reparto de stubs, el paso de asignación los movía como a un stub más,
    porque eran objetos del mismo tipo. Sus posiciones falsas inflaban el límite de todos
    los de su derecha y el reparto salía peor que sin obstáculos. Lo fijo hay que anclarlo
    explícitamente, no confiar en que `x_lo == x_hi` lo impida.
40. **Un óptimo bajo la restricción equivocada no es una mejora.** El recubrimiento por
    caminos encuentra 13 abutments por fila donde el voraz encontraba 7 — pero 6 de esos
    13 son ilegales (§37). Bajo la restricción correcta los dos dan 7, o sea que **el
    heurístico que se quería mejorar ya era óptimo**. Antes de sustituir un heurístico,
    comprobar que la cota que lo supera se calcula con las mismas restricciones.
41. **Un marcador de dispositivo sobre geometría ajena no es un solape, es una
    reclasificación.** `place_resistors` colgaba el serpentín de `channel_y` hacia abajo,
    pero `channel_y` es el **centro** del canal y no su borde, así que la resistencia se
    metía en la fila N1. Eso no salió como una regla de solape: el marcador `res_mk`
    cubriendo poly de **puerta** hace que el deck lea los transistores como cuerpo
    resistivo, y salieron **1222 violaciones en 48 reglas** (`SB`, `HRES`, `LRES`, `PL`,
    `CO`, `NP`, `PP`) que no hablaban de resistencias ni de transistores en concreto. Ante
    una explosión de reglas heterogéneas, mirar primero si algún **marcador** está encima
    de lo que no debe: `(region_marcador & region_difusión).area()` lo dice en una línea.
    Corolario de nombrado: un campo que es un centro debe decirlo, o venir acompañado del
    tamaño — por eso ahora `Layout` lleva `channel_h`.
42. **En rejilla no basta con estar en rejilla: hay que estar en el doble.** El PCell de
    resistencia dibuja la tira **centrada en el origen**, o sea con los bordes en
    `±l_res/2`. Con `l_res` en la rejilla de 5 nm pero múltiplo **impar** de ella, la mitad
    cae a 2.5 nm y arrastra fuera de rejilla las seis capas que se miden desde ese borde
    (`sab`, `poly2`, `pplus`, `contact`, `resistor`, `res_mk`): 90 `*_OFFGRID` de golpe.
    Medido: `l_res=76.455` descuadra las seis, `l_res=76.450` sale limpio. Regla general:
    **toda dimensión que un PCell vaya a partir por la mitad se redondea al doble de la
    rejilla** (`resistors.snap2`). Y ojo con el origen del número: `L=76.4536e-6` venía de
    una cuenta de resistencia del esquemático, que no tiene por qué caer en rejilla.
43. **Un cable horizontal por un canal lleno choca con todo lo que lo cruza.** El salto del
    terminal de la resistencia al trunk iba en metal2 a la altura del terminal, y el canal
    está lleno de stubs verticales de metal2 subiendo de la fila al trunk: **44 `M2.2a`**,
    todas en las dos líneas de `y` de los dos terminales. Se cruza por **metal3**, que en
    este flujo está vacío y cuya pila `via2` ya estaba probada en `caps.py`. Cuando una
    conexión nueva tenga que atravesar un canal ya ruteado, sube de capa: competir por
    metal2 con el router es perder.
44. **Buscar hueco en la dirección equivocada es no buscar.** El serpentín se anclaba en
    `x = BORDE` sin mirar nada, y su terminal izquierdo aterrizó encima de un stub que ya
    estaba ahí (`M2.1`, `M2.2a` y `V1.2a`: su `via1` a 0.105 µm del otro cuando `V1.2a`
    pide 0.26). La primera reacción —deslizarlo en **x**— falló en las 905 posiciones
    posibles, y el motivo es geométrico: **los trunks del canal son barras horizontales que
    lo cruzan de lado a lado**, así que un terminal aprisionado entre dos de ellas no se
    libera moviéndose de lado. Medido con instrumentación: hueco de **0.505 µm** entre
    metal2 a `y=9.58` y a `y=10.085`, donde el pad necesita `0.40 + 2×0.28 = 0.96`. El
    grado de libertad útil era la **y**, y encima había que **reservarlo** (`BUSQUEDA_Y`),
    porque el serpentín quedaba clavado contra el techo del canal. Antes de ampliar una
    búsqueda que falla, mirar en qué dirección se puede mover de verdad lo que estorba.
46. **Una lista que nadie lee es un fallo silencioso esperando su turno — y me tocó.**
    `place_resistors` rellenaba `lay.res_placed` y `lay.res_failed` con todo detalle, y
    **nadie los imprimía**. Cuando la búsqueda en x no encontró sitio, la resistencia de
    realimentación desapareció del layout sin una sola línea de aviso; el DRC bajó de 6
    violaciones a 1 y **lo di por bueno como si el arreglo hubiera funcionado**. Lo que no
    se dibuja no viola ninguna regla: un DRC limpio sobre un bloque incompleto es el
    resultado más peligroso que da este flujo, porque parece el bueno. Vale también para el
    LVS, que compara contra una netlist de referencia salida del **mismo** aplanado y por
    tanto tampoco lo nota. Dos reglas: **(a)** todo lo que se coloque después de rutear
    reporta lo colocado *y* lo rechazado, y el flujo grita si la netlist pedía algo que no
    aparece por ninguna de las dos listas; **(b)** una mejora que reduce violaciones se
    verifica comprobando que **lo que debía arreglarse sigue ahí**, no solo que el contador
    baja. La comprobación barata para esto es medir el área del marcador: `res_mk` tiene
    que dar exactamente `s·L·W` (§5.6.6). *(Es la §0 otra vez, cobrándose otra pieza.)*
45. **Una cota de distancia se cumple contra un grupo, no contra su extremo.** El pozo en L
    del dispositivo a caballo llevaba **una sola** columna de taps, puesta a la derecha de
    todo el grupo `span`. Vale mientras el grupo sea estrecho; al partir `XM43` en cuatro
    copias el grupo midió ~20 µm y su difusión más a la izquierda quedó a **18.7 µm**,
    cuando `DF.13_MV` permite 15. Ahora se añaden columnas en los huecos **entre**
    dispositivos del grupo hasta cubrirlos todos. Regla: cuando una regla acote una
    distancia máxima a un servicio (tap, contacto, riel), la cobertura se comprueba
    dispositivo a dispositivo, nunca contra el borde del conjunto.
47. **Un puerto se puede quedar sin acceso sin que ninguna regla se queje, y por 0.05 µm.**
    `INN` acabó con **19 huecos libres** en su trunk y **ninguno servible**: el cruce de
    metal3 de la resistencia pasaba a 0.32 µm de su trunk, y una plataforma de puerto le
    exige 0.47 a cualquier metal3 ajeno (`_LAND_CLEAR` = espaciado 0.28 + media anchura del
    cable del router, 0.19). No es una violación de DRC —ese layout daba **0**— sino una
    condición de *ruteabilidad* del nivel de arriba, que solo se ve al colocar el bloque
    como macro. Dos consecuencias: **(a)** lo que se dibuje después del router tiene que
    respetar las bandas de los trunks de los puertos, no solo el DRC; **(b)** cuando un
    margen se calcula sumando holguras de otro módulo, hay que escribir el desglose al lado
    del número — el primer intento se quedó corto por 0.05 µm precisamente por reutilizar
    una constante parecida (`HOLGURA`) en vez de sumar la que tocaba (`BANDA_PUERTO`).
48. **Un mensaje de error que no dice la causa cuesta una corrida entera.** «el puerto INN
    se quedó sin acceso en metal3» no distingue entre *no hay trunk*, *el trunk está lleno*
    y *el trunk está libre pero metal3 no*. Los tres piden arreglos distintos y opuestos.
    Ahora el aviso trae el largo del trunk, cuántos huecos había y contra qué chocaron, y
    eso convirtió un diagnóstico de varias iteraciones en una sola lectura.
49. **`dy` es un desplazamiento, no una coordenada.** La holgura vertical de la búsqueda se
    calculaba como `dy - (suelo + alto)`, mezclando un offset con coordenadas absolutas. La
    cuenta correcta es `(techo - suelo) - alto`. Durante un tiempo dio un número positivo
    por casualidad y la búsqueda pareció funcionar; al cambiar la altura del canal salió 0
    y la búsqueda dejó de hacerse en silencio. Toda variable que sea un delta se comprueba
    dimensionalmente antes de meterla en una comparación con coordenadas.

50. **El DRC no ve un cortocircuito, y por diseño.** `OPAM_LIN_flat` salió con **DRC 0** y
    con `OUT` fundido con `VSS`: el metal1 del serpentín de resistencia se solapaba 5.00 µm²
    con un strap de otra net. Ninguna regla se queja, porque **dos metales que se tocan es
    justo lo que hace un cable** — el DRC comprueba fabricabilidad, no conectividad. Quien
    lo detecta es el LVS, y solo si se corre. Consecuencias prácticas:
    **(a)** ningún bloque se da por bueno con DRC solo, por muy limpio que salga;
    **(b)** todo lo que el generador dibuje **después** del router tiene que comprobar su
    huella completa contra lo que ya hay, capa por capa — no basta con mirar alrededor de
    los puntos de conexión, que era lo que hacía `place_resistors`;
    **(c)** la bisección sigue siendo la herramienta más rápida para atribuir un fallo:
    construir sin la pieza sospechosa y contar. Aquí pasó de 77 ocurrencias de `OUT|VSS` a
    0, y la resta de los dos GDS dio las cuatro formas culpables con sus coordenadas.
    *(Hermana de la §46: allí el DRC daba limpio porque faltaba una pieza; aquí, porque
    sobraba una conexión. Las dos veces el número era 0 y no significaba nada.)*

51. **Un reparto de rechazos se lee en cascada, y el que manda es el que más rechaza, no el
    último.** El serpentín no cabía y el contador decía `banda 1096 / terminal 9783 /
    metal1 571 / pozo 45 / ok 0`. Se leyó «45 posiciones pasan todo y mueren en el pozo» y
    de ahí salió una conclusión falsa —que había que plegar más la resistencia, o sea tocar
    el esquemático— cuando el pozo rechazaba el **0.4 %** y la caja de terminal el **85 %**.
    El último eslabón de una cascada solo ve lo que le dejan los anteriores: su cuenta baja
    dice que llega poco, no que sea el culpable.

52. **Un envoltorio se pide cuando compensa, no cuando cabe.** `wrap_device` giraba un
    transistor con `L > W` que saliera más ancho que alto. Para el `M43` del `OPAM`
    (22.06 × 2.66) el giro ahorra 19 µm de fila y es justo para lo que se hizo. Para las
    copias de `XM43` en `OPAM_LIN` (3.96 × 4.26) ahorraba **0.30 µm** — y a cambio metía el
    dispositivo en una fila especial, con un pozo en L que partía el canal de ruteo en dos
    y un camino aparte en el router que acabó cortocircuitando la puerta con el drenador.
    Un caso especial que se activa por un margen despreciable no es una optimización: es
    una fuente de fallos con la ganancia puesta a cero. Se pide **relación 3.0**.

53. **Dos cosas apiladas se SUMAN.** El canal se dimensionaba como
    `max(lo que gastan los trunks, lo que mide el serpentín)`, y son dos bandas que conviven
    en el mismo canal, no dos aspirantes al mismo sitio. Con `max`, el router repartía sus
    trunks por todo el alto —incluido el trozo de la resistencia— y no dejaba en **ninguna**
    altura los 0.96 µm que necesita el terminal para bajar su via. El síntoma engañaba
    doblemente: subir el canal no arreglaba nada, porque el router se limitaba a separar más
    los mismos trunks. Con la suma, y descontando la reserva al repartir, los rechazos por
    caja de terminal pasaron de **9783 a 0**.

54. **Un PCell trae terminales que no son terminales.** `ppolyf_u_high_Rs_res` pone seis
    contactos por segmento y dos de ellos son la **toma de sustrato**, sobre difusión, no
    sobre poly. Cubrirlos «todos» con una envolvente de metal1 para que `CO.6` no se queje
    ataba cada tramo de la resistencia a masa. La regla general: antes de cubrir la
    geometría de un PCell ajeno, **clasificarla por lo que tiene debajo**, no por dónde
    está. Y la comprobación que lo cierra no es el DRC —daba 0— sino leer la netlist
    extraída y ver los cinco tramos con un extremo en `VSS`.

55. **Hay geometría legal que la extracción no conecta.** El terminal de la resistencia
    quedó bajo una placa MIM, con toda la pila de vias dibujada y medida, y el deck lo dejó
    en una net suelta mientras el metal2 que tenía justo encima sí era la net buena. Sin DRC
    que se queje y sin nada visiblemente mal en el dibujo. Se atribuyó con la prueba que no
    admite discusión: **borrar del mismo GDS sólo las capas del MIM y volver a extraer** —
    con ellas, net suelta; sin ellas, `OUT`. De ahí la regla de flujo (el rígido se coloca
    antes que el flexible) y la prueba de método: cuando una herramienta discrepa de la
    geometría, se le quita una pieza al mismo fichero en vez de discutir con ella.

56. **La rejilla es parte del circuito.** El esquemático pedía un cuerpo de 76.4536 µm y el
    PCell sólo puede dibujar múltiplos de 10 nm: el silicio tenía 76.450. Tres nanómetros,
    el 0.005 %, y el LVS no casaba. Se arregló **en el esquemático**, no redondeando en la
    netlist de referencia: escribir en la referencia lo que dibuja el layout habría hecho
    pasar el LVS **tapando** una diferencia real entre lo que se pide y lo que se fabrica.
    Un parámetro que la tecnología no puede dibujar es un error de diseño, no de flujo.

57. **Una constante puesta a ojo sobrevive a su motivo, y hay que ir a buscarla.**
    `BUSQUEDA_Y` reservaba 5 µm de canal para que el serpentín pudiera deslizarse buscando
    hueco entre trunks. Era razonable **cuando se puso**. Al cambiar el reparto del canal
    (§11.0.1b) esa búsqueda dejó de hacer falta, pero la reserva se quedó: medido, el
    serpentín baja **0.40 µm y ni uno más**, con cualquier valor entre 0.0 y 3.0. Cuatro
    micras y media de alto de celda pagando por un problema que ya no existía. Lo mismo
    valió para el presupuesto de ramas de los condensadores, que había que **subir** al
    duplicarse los candidatos (§5.7.1). La regla práctica: cuando se cambia el modelo,
    repasar las constantes que existían para compensarlo — y repasarlas **midiendo**, que
    es barato: un barrido de siete valores contesta en una corrida lo que el criterio no
    contesta en toda una revisión.

---

## 10. Trampas conocidas del entorno

Errores ya cometidos al operar el contenedor, para no repetirlos:

- **`klayout: not found` al lanzar `run_drc.py`.** `docker exec bash -c` abre un shell
  *no interactivo* que no carga el perfil, y `/foss/tools/klayout` no está en el `PATH`
  por defecto. Solución: `export PATH=/foss/tools/klayout:$PATH` al principio del comando
  (o usar `bash -lc`, que además imprime ruido `[INFO]`).
- **`--topcell` es obligatorio en la práctica.** La celda top se llama
  `WEIGHT_COMP_layout` (sufijo que añade `placement.py`), no como el `.gds`.
- **El reporte no es un archivo.** Son ~70 `.lyrdb`, uno por sección del deck; hay que
  agregarlos (§5.4) para tener el conteo real.
- **Comillas anidadas en PowerShell.** `docker exec ... bash -c "... python -c '...'"`
  se rompe al mezclar comillas. Usar Git Bash, o meter el snippet en un `.py`.
- **No instalar paquetes del proyecto con el `pip` del sistema del contenedor**: se
  mezclaría con gdsfactory 9.44 y kfactory 2.5 ya instalados.
- **`PYTHONPATH` del contenedor anula el venv por completo.** CONFIRMADO 2026-08-02. La
  imagen exporta un `PYTHONPATH` que empieza por `/headless/.local/lib/python3.12/site-packages`,
  así que ese directorio gana sobre el venv y `python` importa **gdsfactory 9.44 /
  kfactory 2.5.3** aunque el venv tenga clavadas 9.2.2 / 1.2.2. Ni `pip install -r
  requirements.txt` ni `PYTHONNOUSERSITE=1` lo arreglan: `pip` instala bien pero el
  import sigue yendo al otro sitio. Hay que **limpiar la variable al ejecutar**:

  ```bash
  env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python test_flow.py ...
  ```

  Verificación obligatoria antes de generar (si no imprime `9.2.2 1.2.2`, el resto no es
  reproducible):

  ```bash
  env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python \
    -c "import gdsfactory,kfactory;print(gdsfactory.__version__,kfactory.__version__)"
  ```

  *(Nota: las iteraciones #1 a #3 de la bitácora se corrieron sin saberlo con 9.44/2.5.3.
  Se re-verificó la #4 con ambas: la geometría sale idéntica, así que los resultados
  siguen siendo válidos — pero no eran el entorno que decía el documento.)*
- **La celda top se llama `WEIGHT_COMP`, ya no `WEIGHT_COMP_layout`.** Se renombró en la
  iteración #4: el LVS de KLayout aborta con *"Can't find a schematic counterpart for the
  top cell"* si el nombre no coincide con el `.subckt`. Los comandos de §5.3 usan
  `--topcell=WEIGHT_COMP`.
- **Cada herramienta lee las etiquetas en una capa distinta.** El deck LVS de KLayout usa
  `labels(34, 10)`; magic sólo mira la capa de dibujo (`calma METAL1 34 0` en
  `gf180mcuD-GDS.tech`) y **ignora** las de (34,10) — sin puertos, la netlist extraída sale
  con nodos `a_14_n116#`. `placement.add_port_label()` escribe en ambas.
- **`cp` tiene alias interactivo en este contenedor.** `cp origen destino` sobre un archivo
  que ya existe se queda esperando confirmación y, en un `bash -c` no interactivo,
  **no copia nada** — pero el resto del comando sigue, así que parece que funcionó. Ni
  `cp -f` lo evita (el alias añade `-i` después). Para sobrescribir de verdad: `\cp`,
  `/bin/cp` o `python3 -c "import shutil; shutil.copyfile(...)"`. Pasó restaurando la
  netlist de origen tras una prueba: quedó modificada sin que se notara.
- **El venv puede desviarse de `requirements.txt`.** El 2026-08-02 apareció con
  gdsfactory 9.44/kfactory 2.5.3 (¿upgrade accidental?). Verificar versiones antes de
  generar y reinstalar con `pip install -r requirements.txt` si no coinciden.
- **Bug de `gf180==0.1.1` en `draw_pfet` con `nf>1` y `gate_con_pos="alternating"`:**
  los dedos *pares* del PFET se dibujan sin end-cap inferior y **desconectados** de su
  bloque de contacto de poly (hueco de 0.42 µm; `draw_nfet` sí lo hace bien). CONFIRMADO
  contra el GDS. `device_map._wrap_multifinger_gf180` lo parchea rellenando el hueco en
  poly2; si se actualiza el paquete `gf180`, revisar si el parche sigue haciendo falta.

---

## 11. Pendientes

**El generador no tiene pendientes abiertos, ni de DRC ni de LVS.** Los cinco bloques salen
a 0 violaciones y casan con las dos herramientas (§7.1).

Lo que queda abierto de verdad son **dos cosas, y ninguna es del flujo**:

| pendiente | de quién depende |
|---|---|
| Confirmar con el fabricante que la opción de proceso de **3 kΩ/cuadro** está comprada | decisión de circuito; ninguna herramienta puede contestarla (§11.0.2) |
| Trunks en **metal3** por encima de las filas: escrito y medido (−14 %), apagado por DRC | mejora, no defecto (§13.3) |

**La lista completa de lo que queda por hacer, priorizada y con su cifra al lado, está en
§17.** Esta tabla es solo el titular.

> **Lo que sigue (§11.0 a §11.0.8) es un caso CERRADO**, no una lista de pendientes. Se
> conserva entero porque es el mejor material que ha dado el proyecto sobre una cosa
> concreta: **siete fallos seguidos con DRC 0**. Quien busque qué hacer ahora, que se quede
> con la tabla de arriba; quien vaya a tocar resistencias o condensadores, que lo lea.

### 11.0 `OPAM_LIN_flat`: cerrado (2026-08-18)

**RESUELTO Y VERIFICADO.** Cero errores de flujo, **DRC 0**, **KLayout `Netlists match`** y
**netgen empareja**: los dos MIM, la resistencia —dentro y **conectada de `G_OUT_P` a
`OUT`**— y todos los puertos con su plataforma de metal3. `98.22 × 46.57 µm`.

> **Qué costó de verdad cerrarlo.** El DRC llevaba en 0 desde hacía tres iteraciones y el
> bloque parecía terminado. Lo que faltaba eran **cinco fallos que sólo veía el LVS**
> (§11.0.3 a §11.0.7), más dos silencios en las propias herramientas de comprobación
> (§11.0.8 y §12.5). Ninguno de los siete daba una sola violación de DRC.

Se deja escrito el recorrido porque explica el tamaño de la celda:

- El problema de partida era la longitud de los trunks: `OUT` 6.00 µm con **0 puntos
  libres**, `net9` 17.39 con 0 y `net10` 21.30 con 39, cuando el `OPAM` original tenía
  `OUT` a 30.54. **CONFIRMADO** que venía de que `XM43` pasó de 0.7 × 20 µm a 2 × 1 µm,
  dejando su drenador pegado al de `XM44`.
- **`XM43` partido en `m=4` copias de W=0.5 µm** — mismo ancho total y circuito idéntico,
  verificado en continua (**103.4 V/V, INL 0.12 %, offset +24.0 mV, 2.550 mW**). El
  generador avisa `muy chico para fingers; m=4 expandido a copias paralelas`, así que no
  son dedos plegados sino cuatro copias sueltas, y eso engorda.
- **Tumbar los MIM** devolvió 6.83 µm de alto (§5.7), y **`BUSQUEDA_Y` = 5.0** se llevó 2.5.

**Balance final de tamaño**, y de dónde sale cada trozo:

| | ancho | alto | por qué |
|---|---:|---:|---|
| sin resistencia ni `m=4` | — | 33.87 | punto de partida |
| con `m=4` y los MIM tumbados | 103.85 | 38.87 | pero **sin** la resistencia dentro |
| quitando el giro que no compensaba (§11.0.5) | **98.22** | 49.57 | −5.6 de ancho; el canal pasa a ser trunks **+** serpentín (§11.0.1b) |
| apartando el MIM del terminal (§11.0.6) | 98.22 | 55.16 | +5.6 de alto, pero por un motivo evitable: un MIM acabó **de pie** |
| con los dos MIM tumbados de verdad (§5.7.1) | 98.75 | 49.57 | −5.59 de alto por +0.53 de ancho: **523 µm²** |
| con `BUSQUEDA_Y` medido en vez de a ojo (§5.6.7) | **98.22** | **46.57** | −3.00 de alto y devuelve las 0.53 de ancho: **321 µm²** |

Los 7.7 µm de alto que separan el bloque de partida del final son, casi enteros, el canal:
la resistencia no comparte sitio con los trunks. Es lo que cuesta meter 382 µm de poly
dentro de la celda, y ya no queda holgura obvia que recortar.

### 11.0.1 El cortocircuito `OUT`-`VSS`: **causa localizada y arreglada**

El LVS recién montado encontró que en el layout extraído **`OUT` y `VSS` eran la misma
net** — KLayout la nombra `OUT|VSS`, su convención para una net con dos etiquetas, y salía
así en las **77** ocurrencias:

```
M$15 \$69 OUT|VSS OUT|VSS OUT|VSS nfet_06v0 L=1U W=1U
```

Ese NFET de 1 × 1 µm es `XM44`, el de salida, con **drenador y fuente en la misma net**.

**Cómo se localizó, en tres medidas:**

1. **No era la netlist.** La que alimenta al generador tiene las dos nets separadas:
   `XM44 OUT net25 VSS VSS nfet_06v0 L=1.0u W=1.0u nf=1`. Luego lo metía el generador.
2. **Bisección.** El mismo bloque construido **sin colocar la resistencia** pasó de 77
   ocurrencias de `OUT|VSS` a **0**. La resistencia era la causa.
3. **Diferencia de GDS.** Restando el layout sin resistencia del layout con ella se aísla
   lo que dibuja el serpentín, y de ahí sale el puente:

   | capa | añade | de eso, TOCA lo que ya había |
   |---|---:|---:|
   | metal1 | 9.22 µm² | **5.00 µm² (4 formas)** |
   | metal2 | 0.37 µm² | 0.05 µm² |
   | metal3 | 27.81 µm² | 18.70 µm² (la conexión buena al trunk) |
   | contact | 1.45 µm² | 0.00 µm² |

   Las cuatro formas de metal1 están en `x ≈ 2.03..3.52`: las **cabezas de contacto
   izquierdas del serpentín**, fundidas con un strap vertical de metal1 que ya estaba ahí.

**Causa raíz:** `place_resistors` comprobaba metal2 y via1 **solo alrededor de los dos
terminales**, mientras el serpentín lleva metal1 en las cinco cabezas y en las tiras del
zigzag a lo largo de sus 76 µm, y el canal está cruzado por **67 straps verticales de
metal1**. Se dibujaba a ciegas.

**ARREGLADO:** la búsqueda comprueba la **huella de metal1 entera** del serpentín,
ensanchada por el espaciado de `M1.2a` (0.23 µm), contra todo el metal1 existente.
Verificado por la misma resta de GDS: **0.00 µm² de contacto**.

> **Lo que hay que llevarse de aquí:** el DRC de ese GDS daba **0**. Y no era un fallo del
> DRC — dos metales de nets distintas que se tocan no violan ninguna regla de espaciado,
> porque tocarse es exactamente lo que hace un cable. Un bloque puede estar limpio de DRC y
> tener la salida cortada contra masa. **El DRC no sustituye al LVS.** Ver §50.

### 11.0.1b El serpentín no cabía: era el reparto del canal, no el floorplan (RESUELTO)

Con la comprobación de metal1 puesta, `XRFB` dejó de colocarse, y se leyó mal. El reparto
de rechazos decía:

```
banda de puerto: 1096   caja de terminal: 9783   huella de metal1: 571   pozo: 45   ok: 0
```

y se interpretó que lo que bloqueaba era el **pozo** —«45 posiciones pasan todo y mueren
ahí»— con la cuenta de que el serpentín medía 78.53 µm y el brazo de nwell dejaba 1.69 µm
de ventana. De ahí salió la conclusión de que hacía falta `s=10`, o sea tocar el
esquemático. **Era falso.** El pozo sólo rechazaba 45 de 11 495; el que mandaba era la
**caja de terminal**, con 9783, y ése no depende de lo que mida el serpentín: plegarlo más
no habría cambiado nada.

**La cuenta que lo explica.** El terminal baja al canal con una pila de vias y su pad de
metal2 (`PAD_VIA` = 0.40) necesita 0.28 libres a cada lado — o sea **0.96 µm** limpios
(`resistors.BANDA_TERMINAL`). Los trunks son barras horizontales que cruzan el canal
entero, así que una `y` ocupada no la libera ninguna `x`: el terminal sólo cabe **entre**
dos trunks. Y el router **reparte** los trunks por todo el canal (`pitch = banda /
(pistas + 1)`), así que con 13 pistas en 16.65 µm el paso salía **1.19** y el hueco entre
ejes 1.19 − 0.38 (el pad de via del vecino) = **0.81**. Faltaban 0.15 µm y no había
ninguna altura buena en todo el canal.

**Y subir el canal no arreglaba nada**, que es lo que despistó: se probó, y el router se
limitó a repartir los mismos trunks por más sitio. Con paso 1.34 —justo el mínimo— seguían
muriendo 11 744 de 15 884, porque los DOS terminales van a 9.00 µm fijos uno de otro y
9.00 / 1.34 = 6.72: cuando uno caía centrado en su hueco, el otro caía a 0.38 del suyo.

**El error de modelo era el dimensionado del canal**: se pedía
`max(lo que gastan los trunks, lo que mide el serpentín)` cuando son dos cosas
**apiladas**, no dos aspirantes al mismo sitio. Arreglado en dos sitios que van juntos:

- `placement.build_layout` (`band`): el canal se dimensiona como **suma**.
- `routing.route_layout`: al repartir las pistas se **descuenta** la banda reservada
  (`lay.channel_reserved`), así que los trunks se quedan en su parte y la del serpentín
  queda limpia.

Efecto inmediato: `banda de puerto: 0`, `caja de terminal: 0`. El problema del terminal
desapareció entero.

Lo que quedó después fue el metal1 (11 773 rechazos) contra el pozo (976), y ahí sí valía
apartarse: el serpentín tiene su metal1 en **dos columnas rígidas** separadas lo que mide
la tira, y las dos tienen que caer a la vez en corredores libres. Se resolvió sin tocar el
esquemático **quitando la rotación que no compensaba** (§11.0.5): sin fila `span` no hay
brazo de nwell que parta el canal, y el contador del pozo bajó a **0**.

### 11.0.2 `ppolyf_u_3k` SÍ se puede verificar (corrige lo que decía esta sección)

Lo que se escribió aquí antes —«`ppolyf_u_3k` no existe para las herramientas de
verificación»— **era incompleto y llevaba a una conclusión equivocada**. Lo cierto:

- **El deck de KLayout tiene rama completa para 3k.** `res_extraction.lvs:274` hace
  `extract_devices(resistor_with_bulk('ppolyf_u_3k', 3000, BResistor), ...)`, y
  `gf180mcu.lvs:231` lee el interruptor: `POLY_RES = $poly_res || '1k'`.
- Quien fija el 1k es **sólo la tabla de variantes de `run_lvs.py`** (líneas 205-223), que
  lo pone igual para A, B, C y D y no lo expone por línea de órdenes.
- **`ppolyf_u_3k` es un dispositivo real del PDK**: modelado en `sm141064.ngspice`
  (`rsh_ppolyf_u_3k=3000`, esquinas `3000±750`) y con símbolo de xschem.

Así que la solución no era rehacer el circuito, sino **saltarse el envoltorio**: cuando la
netlist de referencia trae un `ppolyf_u_(2|3)k`, `run_lvs.sh` llama al deck directamente
con la batería de switches de la variante D y `-rd poly_res=3k`. Se comprueba en el log:

```
POLY_RES Selected is 3k
Extracting PPOLYF_U_3K SUB device
R$56 OUT $I332 VSS 229350 ppolyf_u_3k L=76.45U W=1U
```

229 350 Ω por tramo = 3000 Ω/cuadro × 76.45 cuadros. Cinco tramos, **1.147 MΩ**.

**Y netgen.** Su setup del PDK declara en la lista `devices` sólo `ppolyf_u_1k` y
`ppolyf_u_1k_6p0`. Esa lista no decide qué dispositivos existen —eso lo decide la
extracción— sino **cómo se comparan**: permutación de los dos extremos, reducción
serie/paralelo y borrado de propiedades. Falta la **reducción en serie**, que es justo la
que hace falta para casar `s` tramos. Se resuelve desde fuera, sin tocar el PDK, con
`zotnetic_layout/lvs/gf180mcuD_setup_polyres.tcl`: hace `source` del setup original y
repite su bloque `foreach` para `2k` y `3k`.

**Lo que sigue siendo una decisión de diseño**, y no la resuelve ninguna herramienta:
confirmar con el fabricante que la opción de proceso de 3 kΩ/cuadro está comprada. Si el
silicio saliera a 1 kΩ/cuadro, esta misma geometría daría **382 kΩ en vez de 1.15 MΩ** y la
ganancia de `OPAM_LIN` se iría a un tercio. La cadena ya sabe comprobar el caso 3k; lo que
no puede es decir si el silicio lo lleva.

### 11.0.3 La resistencia salía atada al sustrato por su propia toma de cuerpo

El primer fallo que destapó el LVS con la resistencia ya colocada: los **cinco tramos**
tenían un extremo en `VSS`.

```
R$56 VSS \$I332 VSS 229350 ppolyf_u_3k L=76.45U W=1U
R$57 VSS \$I332 VSS ...        (los cinco igual)
```

`ppolyf_u_high_Rs_res` pone **seis contactos por segmento**, y no son todos lo mismo.
Medido sobre el PCell con `l_res=76.45`:

| x | sobre | qué es |
|---|---|---|
| −1.76 .. −1.34 (`comp`) | difusión | la **isla de sustrato** del modelo de tres nodos |
| −1.66 .. −1.44 | `comp` | dos contactos de la toma de sustrato |
| −0.57 .. −0.35 | `poly2` | dos contactos de la **cabeza izquierda** |
| 76.80 .. 77.02 | `poly2` | dos contactos de la **cabeza derecha** |

`serpentin()` cubría con una sola envolvente de metal1 «todos los contactos de la cabeza»,
para que no quedara ninguno desnudo (`CO.6`). Y con eso metía la toma de sustrato dentro
del mismo polígono que la cabeza: **cada tramo quedaba con un extremo cortocircuitado
contra el sustrato**, y la realimentación, en vez de ir de `G_OUT_P` a `OUT`, iba a masa.
El DRC de ese layout daba **0**.

Arreglado clasificando los contactos por lo que tienen debajo (`comp` contra `poly2`): las
cabezas cubren sólo los de poly y la toma lleva **su propio pad**, en una región de metal1
aparte que no se fusiona con la otra. Entre los dos quedan 0.87 µm menos los encierros, de
sobra para `M1.2a` (0.23).

### 11.0.4 `term1` apuntaba a un nodo interno, no al extremo libre

Con el corto anterior arreglado, la cadena salió bien encadenada pero el último tramo
**colgando**. El serpentín une los segmentos en zigzag alternando lado, así que de qué lado
queda libre el último lo decide el **último cruce**, que es el `i = n − 2`: si es par une
por la derecha y sobra el izquierdo; si es impar, al revés. O sea que depende de la paridad
de `n`.

El código miraba la de `n − 1`, o sea justo la contraria. Con `n = 5` daba la cabeza
izquierda, que el cruce `i = 3` ya había unido a la del segmento 3: `term1` no era un
extremo sino un **nodo interno de la cadena**.

Se comprueba mirando el metal1 del propio serpentín, sin extraer nada: las formas que
quedan **sueltas** (0.90 µm de alto, sin tira de zigzag) son los dos terminales, y con
`n = 5` son la izquierda de abajo y la **derecha** de arriba.

### 11.0.5 El ruteo cortocircuitaba `G_OUT_P` con `OUT`: una rotación que no compensaba

Independiente de la resistencia — se midió construyendo el bloque **sin colocarla** y el
corto seguía ahí. Cinco tiras de metal1 cruzaban de `y=2.38` (el borde de abajo de un
dispositivo) hasta `y=14.55` (el trunk de `G_OUT_P`), atravesando por el camino el metal1
de sus **propios** terminales, que están en `OUT`.

La cadena de causas, de fuera adentro:

1. `XM43` se parte en `m=4` copias de W=0.5/L=1 (§11.0).
2. `wrap_device` gira un dispositivo cuando `L > W` y sale más ancho que alto. Cada copia
   mide **3.96 × 4.26** y girada **4.26 × 3.96**: se ahorraban **0.30 µm**.
3. Girado, el dispositivo se va a la fila `span` y saca sus terminales por carriles
   laterales, que es un camino distinto en el router. Las cuatro copias montaron una fila
   `span` de 21.77 µm cuyo pozo bajaba por todo el canal.
4. `_rotate_gf180` da por hecho que un dispositivo P alcanza su canal **por abajo**, que es
   verdad en la fila P; pero la fila `span` se coloca a la altura de la fila N1, o sea
   **debajo** del canal. Los tres puertos salían por el borde inferior y los stubs subían
   12 µm atravesando el dispositivo entero.

Arreglado exigiendo que el giro **compense**: `_ROT_MIN_RATIO = 3.0`. El `M43` del `OPAM`
original —que es para lo que se hizo el giro— mide 22.06 × 2.66, relación **8.3**; las
copias de `XM43` están en 1.08. Con 3 se separan los dos casos de sobra. De paso se corrigió
`routing._pin_access`, que clasificaba la fila `span` como si estuviera encima del canal.

Efecto: el corto desaparece, la celda pasa de 107.50 a **98.22 µm** de ancho y el brazo de
nwell deja de partir el canal. Los otros cuatro bloques **no cambian de tamaño**.

### 11.0.6 Una placa MIM encima del terminal impide que la extracción lo conecte

El fallo más raro de todos, y el único que no es un error del generador sino una
propiedad de la extracción que hay que respetar.

Con la resistencia colocada y bien encadenada, el último tramo acababa en una net suelta
(`$263`) **aunque el metal2 que tenía justo encima sí era `OUT`**. La geometría estaba
completa y medida: metal1 de la cabeza → via1 → metal2 → via2 → metal3 → 10 µm de cruce →
via2 → el trunk de `OUT`. Una conectividad hecha a mano sólo con metales las da por unidas.

La prueba que lo cierra es de las que no admiten discusión: **el mismo GDS**, borrando sólo
las capas del MIM (`metal4`, `metal5`, `fusetop`, `via3`, `via4`) y volviendo a extraer:

| GDS | cadena extraída |
|---|---|
| tal cual | `$87` … `$I335` — **`$263`** (suelta) |
| sin las capas del MIM | `$3` … `$I333` — **`OUT`** |

Nada más cambia. Así que la regla, aunque el mecanismo interno del deck no se haya
perseguido hasta el final, es: **el terminal de una resistencia no puede quedar debajo de
una placa MIM**. Y el DRC de ese layout daba 0.

Arreglado en dos movimientos:

- **Se invierte el orden**: las resistencias se colocan **antes** que los condensadores. El
  argumento de antes (un MIM necesita 20 µm seguidos de trunk y a la resistencia le basta
  un punto de via) vale para el trunk pero no para el sitio: el serpentín es una barra
  rígida de 79 µm con los terminales a distancia fija y sólo puede deslizarse, mientras que
  el MIM elige entre muchas posiciones y dos orientaciones. **El rígido va primero.**
- `place_resistors` anota sus pilas en `lay.res_terminals` y `caps._candidates` descarta
  toda placa que las tape.

Cuesta altura de celda —el MIM se aparta hacia arriba y `OPAM_LIN_flat` pasa de 49.57 a
**55.16 µm**— y es un precio que se paga a sabiendas: la alternativa es una resistencia que
no está conectada.

### 11.0.7 El largo que pedía el esquemático no era dibujable

Último punto, y afecta al **circuito**. Con todo lo anterior arreglado, netgen ya casaba y
KLayout seguía diciendo que no. No era topología: el comparador conducido a mano (§12.4)
emparejaba **37 nets, 0 sin pareja**, con los límites del deck y con los ampliados. Era un
**parámetro**.

El esquemático pedía `L = 76.4536 µm`. El PCell dibuja la tira **centrada en el origen**,
así que el largo tiene que ser múltiplo de 10 nm o las seis capas se van de rejilla
(`snap2`, §5.6.x): el layout dibujaba **76.450**. Diferencia de 3.6 nm — el 0.005 % — y el
comparador de KLayout no perdona un parámetro distinto.

Se arregló **en el esquemático**, que es donde toca: `L=76.45e-6` en `sub_diff_2_LIN.sch` y
`OPAM_LIN_flat.sch`. La alternativa —que `flatten_spice` escribiera el valor redondeado en
la netlist de referencia— habría hecho pasar el LVS **tapando** una diferencia real entre
lo que pide el esquemático y lo que hay en el silicio, que es justo la clase de silencio
que este documento lleva media vida persiguiendo.

Verificado que no cambia el circuito: `OPAM_LIN` sigue en **103.4 V/V de pico, 103.1 en el
tramo 1-4 V, INL 0.12 %, 2.550 mW, margen de fase 73.9°**, y el offset pasa de +24.0 a
**+23.8 mV**.

### 11.0.8 La netlist de referencia no llevaba la resistencia

`flatten_spice.py` escribe dos netlists: la del layout (con `nf`) y la de referencia para el
LVS (con transistores en paralelo). `build_layout_netlist()` hacía
`out.extend(fl.resistors)`; su gemela `build_lvs_netlist()` emitía MOSFET y condensadores
y **se dejaba las resistencias**. O sea que el LVS comparaba un circuito sin realimentación
contra otro sin realimentación, y podía decir que casaban.

Al escribirla hubo que resolver dos convenios, los dos medidos:

- **Elemento `R`, no `X`.** El *delegate* del deck (`custom_classes.lvs`,
  `SubcircuitModelsReader#element`) entra por la primera letra, y para una `R` de tres
  nodos monta un `DeviceClassResistorWithBulk` con terminales A, B, W. Escrita como `X…` se
  leería como llamada a subcircuito y no emparejaría con nada. Es la misma regla que ya
  obligaba a escribir los condensadores como `C…`.
- **Tramo a tramo, no con `S=5`.** El deck hace `L = L·S`, así que un solo dispositivo con
  `S=5` describiría bien la resistencia. Pero el layout dibuja `s` cuerpos encadenados y
  las dos herramientas extraen `s` dispositivos; juntarlos exige la reducción en serie, y
  netgen no la aplica aquí porque **lee la resistencia de tres nodos como si tuviera dos**
  y le pone de modelo el nodo de sustrato: la clase le sale `VSS` y su setup no la
  reconoce. Escribiendo los tramos, las dos partes cuentan lo mismo y no hace falta.
- **Y el valor.** Sin `R`, el rescate del delegate lo deja en 0 y el comparador ve 0 contra
  los 229 350 Ω extraídos. Se calcula desde el nombre del modelo con la misma equivalencia
  que usa el deck (`_hoja_ohm_sq`).

### 11.1 Límites de `COMP`

Sí hay **tres límites reales** que afectan a `COMP` y que no son mejoras cosméticas:

- [x] **Condensadores MIM** — RESUELTO 2026-08-04 (iteración #16). Se colocan encima del
      array, sin coste de área. Ver [Lecciones](#9-lecciones-aprendidas) §33-§36.
- [ ] **magic no resuelve el terminal de placa superior del MIM.** En
      `mag/*_extracted.spice` los dos condensadores salen con el modelo y el tamaño
      correctos (`cap_mim_2f0_m4m5_noshield c_width=20u c_length=10u`), pero uno de los dos
      terminales queda en un nodo interno (`m4_…#`) en vez de en su net. **El layout está
      bien**: la comprobación que manda es el LVS de KLayout —que sí tiene reglas de
      conexión propias para MIM (`mimcap_connections.lvs`)— y da `Netlists match` con los
      dos condensadores en las nets correctas; además los dos polígonos de metal5 salen
      separados y llegan cada uno a la suya. Es una limitación de la extracción de magic,
      y afecta solo a las netlists de parásitos.
- [x] **`IN-` / `IN+` como nombres de puerto** — RESUELTO renombrando en el esquemático a
      `INN`/`INP`; hoy `COMP` y `OPAM` exportan `.subckt OPAM VDD INN OUT INP VSS`. No era
      del layout: KLayout escapa `IN-` a `IN\x2d` al extraer y netgen compara la cadena
      cruda. La topología casa entera. Se arregla renombrando en el esquemático a
      `INN`/`INP`. Ver [Lecciones](#9-lecciones-aprendidas) §31.
- [ ] **netgen da errores de propiedad en los MIM.** Empareja la topología (52 vs 52
      dispositivos, `Netlists match with 6 symmetries`) pero lo extraído por KLayout lleva
      `A`/`P` y la referencia `W`/`L`, mientras que su setup del PDK espera
      `c_width`/`c_length`. Los tres nombres describen lo mismo y **los números cuadran**
      (`A=200P` = 20 × 10 µm, `P=60U` = 2·(20+10)), así que es un choque de convenios entre
      herramientas, no una diferencia de circuito. Se podría silenciar con un setup propio
      de netgen que borre esas propiedades, pero eso taparía también un desajuste de
      tamaño de verdad.

Lo que sigue son mejoras, no defectos.

- [x] **Salto del stub por metal2 para abutir nets ruteables** — RESUELTO en la v2
      (iteración #32, §13.1): 14 → 24 abutments en `OPAM` y `OPAM_LIN_flat`. Lo que sigue
      es la descripción original de por qué hacía falta. No se podía
      porque el bloque compartido está encajonado entre las dos puertas
      ([Lecciones](#9-lecciones-aprendidas) §37). Haría falta que el stub saliera del
      bloque en metal1, subiera a metal2 con una via1, cruzara por encima del pad de gate
      —que es metal1, así que no estorba— y volviera a metal1 con otra via1 ya dentro del
      canal. La mitad del trabajo está hecha y probada: `placement._shared_sd_contact()`
      pone un contacto legal en un bloque ensanchado a `ABUT_BLOCK_CON` (pasa `CO.7`), y
      `_can_join()` es el único sitio donde se decide qué net puede ser unión. Ojo con los
      pads de via (0.34) donde ahora mismo el espacio ya va justo.
- [ ] **Trunks en metal3 por encima de las filas** para adelgazar el canal, que se lleva
      ~10 µm de los 31.46 de `COMP` con 13 pistas y **cero compartición**. **Escrito y
      medido** (iteración #36): el canal baja a 3 pistas y la celda un **14 %**, pero deja
      39 violaciones y magic se planta, así que va **apagado** detrás de
      `Opciones.trunks_m3`. El trabajo que falta está acotado y es la tarea #1 de §17.
- [ ] **Altura.** El ancho ya está exprimido (37.2 µm), pero la altura subió a 28.6 al
      pasar a tres filas: dos canales, tres filas y dos rieles. Ideas por probar: repartir
      la fila N buscando **minimizar las nets que cruzan de canal** (hoy el corte es por
      ancho acumulado, y salen 6 cruces) para adelgazar el canal B, y compartir pista entre
      los dos canales cuando una net no llega al otro.
- [x] **Ordenar los dispositivos para acortar las nets** — RESUELTO 2026-08-03
      (iteración #8), aunque no como se esperaba: reordenar **empeora**; lo que hacía falta
      era alinear las filas. Ver [Lecciones](#9-lecciones-aprendidas) §15.
- [ ] **Codos (dog-legs).** `_assign_tracks()` respeta las restricciones verticales, pero
      si hubiera un **ciclo** (A debe ir bajo B y B bajo A) no hay reparto que lo resuelva:
      haría falta partir un trunk en dos pistas unidas por un tramo vertical. Hoy ese caso
      se coloca solo en su pista y **avisa** por `warnings.warn`. En este bloque no hay
      ciclos; con netlists más enredadas puede aparecer.
- [ ] Correr con `--density` y `--antenna` (ahora apagadas).

**Resueltos** (se quedan como historia, ver [Bitácora](#8-bitácora-de-iteraciones)):

- [x] **Router de canal** — RESUELTO 2026-08-03 (iteración #6). Eran **dos** problemas
      distintos, no uno: el canal no tenía alto suficiente para los trunks (se desbordaban
      dentro de las filas) y los trunks se ordenaban sin respetar la restricción vertical.
      Arreglados los dos: DRC 6 → **0** y el corto `x1_net6`↔`WE` desaparece.
      Ver [Lecciones](#9-lecciones-aprendidas) §13 y §14.

- [x] **Vías en `routing.py`** — RESUELTO iteración #3. 0.26 µm exacto + pad de 0.34 en
      ambos metales (metal1 lo exige `V1.3d`, no solo metal2). 234 → 0.
- [x] **`CO.7`** — RESUELTO iteración #4. Eran dos bugs del PCell, no del generador (§6.4).
      206 → 0.
- [x] **Taps de sustrato/pozo** (`DF.14_MV`, `NP.5di`) — RESUELTO iteración #4. → 0.
- [x] **LVS** — hecho por primera vez (§12). Con KLayout para extraer y netgen para
      comparar; `sak-lvs.sh`/magic no sirve aquí (no reconoce los taps).

- [x] **`PL.2_MV`** — RESUELTO 2026-08-03 (iteración #5). No era un `L` mal puesto: el
      inversor usaba las medidas exactas de la celda estándar de 5 V pero declarado como
      `*_06v0`, y en 6 V los mínimos son 0.55/0.7 mientras que en 5 V son **0.5/0.6**,
      justo lo que usaba. El esquemático nuevo lo declara `pfet_05v0`/`nfet_05v0` y las 6
      violaciones desaparecen sin tocar el generador. Ver [Lecciones](#9-lecciones-aprendidas) §12.

**Pendientes de diseño (no del generador):**

- [x] Exponer `OUT`/`OUT_N` como puertos del `.subckt` en Xschem — RESUELTO 2026-08-04
      (iteración #13). El top pasa de 7 a **9 puertos** y el generador los etiqueta sin
      tocar nada: la salida del comparador ya es accesible desde fuera del bloque.

**Evaluado y descartado:**

- **Celdas estándar del PDK para los inversores.** `gf180mcu_fd_sc_mcu9t5v0__inv_1` es
  sustituto exacto de `INV_1` (mismos modelos y medidas: PFET 0.5/1.83, NFET 0.6/1.32) y
  su GDS ya viene hecho en
  `/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/gds/`. Se descartó porque no
  encaja en el floorplan: mide **2.24 × 5.04 µm** con PMOS y NMOS **juntos** —incompatible
  con nuestra división fila-PFET / fila-NFET—, usa **`LVPWELL` (204,0)** mientras nuestros
  NFET van directos a sustrato, y sus pines son `I/ZN/VDD/VNW/VPW/VSS`. Habría hecho falta
  una banda de filas digital aparte, integración de pozos y LVS jerárquico. Con los
  inversores ya en 05v0 no aporta nada al DRC. Queda anotado por si más adelante interesa
  meter lógica de verdad en el bloque.

---

## 12. LVS

**LVS limpio** desde la iteración #6 (2026-08-03):

```
Circuit 1 contains 23 devices, Circuit 2 contains 23 devices.
Circuit 1 contains 20 nets,    Circuit 2 contains 20 nets.
Final result: Circuits match uniquely.
```

Y el deck de KLayout, por su cuenta: `Congratulations! Netlists match.`

**Historia** (no se borra, §0): la primera verificación (2026-08-02, iteración #4) dio
19 nets contra 20 — **`x1_net6` cortocircuitada con `WE`**, que en la netlist extraída se
veía como los dos dedos del NFET de gate `VB` con drenador y surtidor en la misma net:

```
M$14 WE VB WE GND nfet_06v0 L=1U W=2.48U
M$15 WE VB WE GND nfet_06v0 L=1U W=2.48U
```

El puente eran dos stubs de metal1 solapados 0.095 µm al cruzar el canal: uno subía de la
fila n a su trunk y otro bajaba de la fila p al suyo, con sus x a 0.135 µm (hacían falta
0.46). Lo arregló la restricción vertical del router de canal
(ver [Lecciones](#9-lecciones-aprendidas) §14), no un ajuste de separaciones.

### 12.6 Enlaces entre canales

Con el floorplan de tres filas (§5.5) una net puede tener pines en los dos canales. Entonces
lleva trunk en cada uno y un enlace vertical que los une, por una columna libre, cambiando
de capa para no cortocircuitar nada:

| Tramo | Capa | Por qué |
|---|---|---|
| dentro de cada canal | **metal1** | cruza los demás trunks (metal2) sin tocarlos |
| filas N2/N1 y riel VGND | **metal2** | cruza el riel y el metal1 de los dispositivos sin tocarlos |

Cada tramo **se pasa 0.16 µm del punto de cambio**: una via1 une metal1 con metal2 y
necesita las dos capas encima. Acabando los tramos justo en la frontera, cada via quedaba
con metal1 solo por debajo y metal2 solo por encima y el enlace no conectaba.

El orden de las decisiones importa y costó tres intentos (ver
[Lecciones](#9-lecciones-aprendidas) §17): **elegir la columna → meterla en el span de la
net → repartir pistas → dibujar**. Si se elige la columna después de dibujar, la via cae
fuera del metal2 del trunk; si se estira el trunk después de repartir pistas, dos trunks de
la misma pista se solapan y cortocircuitan.

Al cruzar las filas la columna solo tiene que esquivar **metal2**, o sea los straps de S/D
de los multi-finger: por encima de un dispositivo de un solo dedo se puede pasar.

Si alguna net se queda sin columna libre, `build_block.py` lo imprime como
`ERROR: sin enlace entre canales`. **No es cosmético**: esa net queda partida en dos y el
LVS lo reporta como nets de más.

### 12.0 `--top_lvl_pins` es obligatorio para netgen

Sin esa opción, `run_lvs.py` extrae `.SUBCKT WEIGHT_COMP` **sin lista de puertos** y netgen
termina en `Top level cell failed pin matching` aunque la topología case perfectamente
(reporta `(no pins)` frente a `VDD`). Con ella el `.SUBCKT` sale con sus 7 puertos y el
resultado es `Circuits match uniquely`. El deck de KLayout compara por nombre de net y no
la necesita, así que puede decir que todo casa mientras netgen falla: **si los dos no
coinciden, mirar primero la cabecera del `.cir` extraído.**

### 12.1 Netlist de referencia: **copias paralelas explícitas**

`flatten_spice.py` emite dos netlists del mismo circuito porque cada herramienta lo lee
distinto:

| Archivo | Forma | Para qué |
|---|---|---|
| `WEIGHT_COMP_flat.spice` | `nf=N` | generar el layout (lo consume `spice_parser`) |
| `WEIGHT_COMP_lvs.spice` | N transistores en paralelo | comparar en LVS |

El motivo está en `gf180mcuD_setup.tcl` (~línea 133): netgen hace
`property ... delete ... nf` y fusiona los paralelos con `{w add}`. El extractor ve **cada
dedo como un transistor suelto**, así que del layout le llegan N dispositivos de ancho W.
Con `nf=N` netgen leería un solo W (falla la propiedad `w`) y con `m=N` tampoco: no lo
expande al leer y quedaban 20 dispositivos contra 23. Escribiendo los N en paralelo, ambos
lados llegan a 23. **`_flat.spice` es un intermedio del generador, no una netlist de
simulación.**

### 12.2 Flujo: `./run_lvs.sh`, las DOS herramientas

```bash
cd /foss/designs/zotnetic_layout
./run_lvs.sh                  # los cinco bloques
./run_lvs.sh OPAM_LIN_flat    # uno solo
```

**Por qué dos y no una.** No comprueban lo mismo, y ya se las ha visto discrepar:

- **KLayout** extrae del GDS y compara con **sus** reglas de conexión, que incluyen las de
  MIM (`mimcap_connections.lvs`). Es el único que sabe de verdad si las dos placas del
  condensador caen en su net: magic no resuelve el terminal de placa superior (§11).
- **netgen** compara topología **y propiedades** (W, L, área), así que pilla un transistor
  del tamaño equivocado que a KLayout le cuadraría igual.

Todo lo que sale se queda en `layouts/<BLOQUE>/lvs/`:

| archivo | quién | qué es |
|---|---|---|
| `<BLOQUE>_flat_gf180.cir` | KLayout | netlist extraída del GDS |
| `<BLOQUE>_flat_gf180.lvsdb` | KLayout | base de datos de LVS (para el visor) |
| `lvs_run_*.log`, `klayout_stdout.log` | KLayout | logs de la extracción |
| **`netgen.out`** | netgen | la comparación detallada — **es la que hay que leer** |
| `netgen.log` | netgen | lo que escribió por consola |
| `RESUMEN.txt` | el script | el veredicto de las dos, en siete líneas |

Dos cosas que el script hace y que a mano se olvidan:

1. **El nombre del sustrato se lee del `.subckt`**, no se fija a mano. `--lvs_sub` es
   obligatorio —si no, el sustrato queda como nodo suelto y el LVS no significa nada— y el
   valor **tiene que ser el de la netlist**: era `GND` con el esquemático viejo y es `VSS`
   con el nuevo.
2. **El código de salida no es el veredicto. De NINGUNA de las dos.** netgen devuelve 0
   aunque los circuitos no casen, y `run_lvs.py` **también**. Este aviso llevaba escrito
   aquí desde el principio para netgen y no se aplicó a KLayout: el resumen llegó a decir
   `KLayout: LIMPIO` con `ERROR : Netlists don't match` en el log de la misma corrida. Las
   dos se juzgan ahora por lo que **escriben** (`Congratulations! Netlists match.` /
   `ERROR : Netlists don't match` / `SIN VEREDICTO`), y el código de salida se conserva
   sólo como dato, para distinguir «no casó» de «ni siquiera arrancó».
3. **La hoja de la resistencia de poly se lee de la netlist y se le pasa al deck.** Si la
   referencia trae un `ppolyf_u_(2|3)k`, el script **no** usa `run_lvs.py` —que fija
   `poly_res=1k` en su tabla de variantes— sino que llama al deck directamente con la misma
   batería de switches de la variante D y `-rd poly_res=<hoja>`, y usa el setup local de
   netgen que añade esos dispositivos. Ver §11.0.2. Esa lista de switches **duplica** la
   tabla del PDK: si se cambia de variante, hay que revisarla.

Y `--top_lvl_pins` sigue siendo obligatorio (§12.0).

#### 12.2.1 Estado (2026-08-18)

| bloque | KLayout | netgen |
|---|---|---|
| `WEIGHT_COMP` | LIMPIO | **CASAN** |
| `DECODER` | LIMPIO | **CASAN** |
| `COMP` | LIMPIO | CASAN, con avisos de propiedad |
| `OPAM` | LIMPIO | CASAN, con avisos de propiedad |
| `OPAM_LIN_flat` | **LIMPIO** | **CASAN**, con avisos de propiedad |

Los avisos de propiedad son los ya conocidos de los MIM (§12.3): `Netlists match with 6
symmetries with property errors`, `Property A/P in circuit1 has no matching property in
circuit2`. Es un choque de convenios —`A`/`P` contra `W`/`L`— y **los números cuadran**, no
es una diferencia de circuito.

### 12.3 Condensadores: la netlist de LVS los escribe **distinto**

Un MIM en la referencia **tiene que ir como elemento `C` con `W`/`L` en metros**, no como
`X` con `c_width`/`c_length`:

```spice
* en *_flat.spice (para el layout)   XC2 OUT x2_net5 cap_mim_2f0fF c_width=20.0u c_length=10.0u
* en *_lvs.spice  (para el LVS)      C2  OUT x2_net5 cap_mim_2f0fF W=2e-05 L=1e-05
```

El motivo está en el deck: KLayout lee la referencia con un *delegate*
(`rule_decks/custom_classes.lvs`, `SubcircuitModelsReader#element`) que **solo actúa
cuando el elemento empieza por `C`**, y de ahí calcula `A = W·L·1e12` y `P = 2·(W+L)·1e6`,
que son las propiedades con las que compara. Escrito como `X…` se leería como llamada a
subcircuito y no emparejaría con el dispositivo extraído. Como SPICE obliga a que un
elemento `C` empiece por `C`, en esa netlist el nombre se deriva (`XC2` → `C2`); el nombre
del esquemático se conserva en la del layout y en la etiqueta del GDS.

Comprobación rápida de que ha funcionado — los condensadores tienen que aparecer en el
`.cir` extraído con su área:

```bash
grep -i cap_mim lvs/COMP_flat_gf180.cir
# C$29 \$65 OUT 4e-13 cap_mim_2f0fF A=200P P=60U
```

Si no aparecen, el LVS puede dar `match` igualmente **por las razones equivocadas**: los
dos lados sin condensadores son coherentes entre sí.

#### 12.3.1 Y las resistencias, igual — con tres convenios propios

Lo mismo vale, palabra por palabra, para las resistencias de poly, y **el «match por las
razones equivocadas» dejó de ser una advertencia teórica**: `build_lvs_netlist()` no las
emitía y el LVS comparó durante varias corridas dos circuitos sin realimentación. El
desglose de los tres convenios está en §11.0.8; el resumen operativo:

```bash
grep -i ppolyf layouts/OPAM_LIN_flat/OPAM_LIN_flat_lvs.spice      # la referencia
grep -i ppolyf layouts/OPAM_LIN_flat/lvs/OPAM_LIN_flat_flat_gf180.cir   # lo extraido
```

Los dos tienen que dar **`s` líneas** —una por tramo— y encadenar los mismos nodos. Si la
referencia no da ninguna, cualquier veredicto que salga después no significa nada.

### 12.4 El deck llama a `compare` con los límites por defecto — y en el top no llegan

Sobre los bloques el deck cierra sin problema. Sobre el **top** (`GRADIENT_NAV`, 1707
dispositivos planos, doce rebanadas analógicas idénticas) daba `Netlists don't match` con
170 nets sin pareja, y no era el diseño.

**Cómo se demuestra que el problema es del comparador y no del layout: compararlo contra su
propia extracción.**

```bash
python3 /foss/pdks/gf180mcuD/libs.tech/klayout/tech/lvs/run_lvs.py \
  --layout=$PWD/out/GRADIENT_NAV.gds \
  --netlist=$PWD/out/lvs_klayout_GRADIENT_NAV/GRADIENT_NAV.cir \
  --variant=D --topcell=GRADIENT_NAV --run_dir=/tmp/self --lvs_sub=VSS --top_lvl_pins
```

Eso falla con **72 nets sin pareja**. Un layout no puede ser distinto de sí mismo, así que
lo que falla es la comparación. (72 y 170 son ambos múltiplos de 12: las rebanadas.)

La causa está en `gf180mcu.lvs`, que termina en un `result = compare` a secas. `compare`
usa los valores por defecto de KLayout —`max_depth` 8, `max_branch_complexity` 500— y el
deck **no los expone por línea de órdenes**. Con el mismo comparador conducido a mano:

| `max_depth` / `max_branch_complexity` | resultado |
|---|---|
| 8 / 500 (los del deck) | falla, 70 nets sin pareja |
| 30 / 10000 | **casa entero**, 0 nets, 0 dispositivos, 0 pines sin pareja |

Así que la comparación se hace aparte, con la API: extrae el deck (su `.cir`) y compara
`kdb.NetlistComparer` con los límites puestos. Está en
`a_zonetic2026/openroad/scripts/lvs_klayout.py::comparar`.

Dos avisos sobre ese camino:

- **Comprueba topología, no tamaños.** El lector SPICE genérico de KLayout no casa los
  parámetros que escribe el deck (`L=20U W=0.7U AS=… PS=…`) con los de la referencia
  (`W=… L=…` en metros): con la comparación de parámetros activada no empareja ni un
  dispositivo. De los tamaños responde **netgen**. Hacen falta los dos.
- **El lector genérico no sabe leer el MIM de la referencia** (`C… cap_mim_2f0fF W=… L=…`
  sin valor) porque eso lo entiende el *delegate* del deck, que desde Python no se puede
  pedir. Se le escribe el valor **que el propio deck extrae**: 2.0 fF/µm² por el área, o
  sea 4e-13 F para una placa de 20 × 10 µm.

### 12.5 Que las comprobaciones fallen cuando deben, y cómo comprobarlo

Un «limpio» solo vale si sabes que esa herramienta habría cantado el fallo. En este
proyecto eso no es teoría — ha pasado **cinco veces**:

- `check_connectivity.py` usaba `net.name` como identidad de la net extraída, y ese campo
  **está vacío en toda net sin etiqueta**. Metía nets distintas en el mismo saco y daba
  «55/55 conectadas» pasara lo que pasara. Con `expanded_name()` decía 13/55.
- `drc_klayout.py` contaba violaciones sobre los `.lyrdb` del directorio de la corrida; si
  el deck **no arrancaba** (por ejemplo `klayout` fuera del PATH) no había ficheros, la
  cuenta daba cero y salía **«limpio»**.
- `read_def_ports` buscaba solo `PLACED` y se saltaba en silencio los pines que OpenROAD
  escribe como `FIXED`, que eran justo los dos que importaban (`VDD` y `VSS`).
- **`run_lvs.sh` juzgaba a KLayout por su código de salida.** El aviso de no hacerlo estaba
  escrito en este mismo fichero… para netgen, y no se aplicó a la otra herramienta.
  `run_lvs.py` devuelve **0 pase lo que pase**, así que el resumen decía `KLayout: LIMPIO`
  mientras su propio log decía `ERROR : Netlists don't match` en la misma corrida.
  Arreglado leyendo el log (`Congratulations! Netlists match.` / `ERROR : Netlists don't
  match` / `SIN VEREDICTO`), y **comprobado que ahora falla**: sobre el GDS que tenía el
  corto, el mismo bloque pasó de `LIMPIO` a `NO CASAN`.
- **La netlist de referencia no llevaba la resistencia** (§11.0.8). El LVS comparaba un
  circuito sin realimentación contra otro sin realimentación y podía decir que casaban. Se
  destapó porque el bloque de al lado —el layout— sí la tenía, y no por ninguna alarma.

Los cinco tenían el mismo síntoma: **silencio**. De ahí
`a_zonetic2026/openroad/scripts/probar_verificacion.py` (`make probar` / `make probar-drc`),
que rompe el layout a propósito y comprueba que salta:

| rotura metida a mano | quién la ve |
|---|---|
| Metal3 uniendo dos nets (corto) | `check_connectivity`: 1 corto |
| via2 borradas (abierto) | `check_connectivity`: 1 abierta |
| Metal3 a 0.10 µm de otro Metal3 | el DRC de KLayout: 4 × `M3.2a` |
| el DRC **sobre el GDS con el corto** | nadie: **0 violaciones en 63 ficheros de reglas** |

La última fila es la que hay que recordar: **un corto no viola ninguna regla de DRC**, dos
formas de la misma capa que se solapan se funden en un polígono. «DRC limpio» no dice nada
sobre si el chip está bien conectado.

`OPAM_LIN_flat` lo demostró con siete casos seguidos: la resistencia atada al sustrato por
su toma de cuerpo, un terminal apuntando a un nodo interno, la puerta cortocircuitada con
el drenador por un giro innecesario, un terminal que la extracción no conectaba por tener
un MIM encima, un largo no dibujable, la resistencia ausente de la referencia y el
veredicto de KLayout leído del sitio equivocado. **Los siete con DRC 0.**

**Y una comprobación no basta con que exista: tiene que responder a lo que le preguntas.**
Aquí las tres que de verdad cerraron cada caso fueron medidas, no herramientas:

| pregunta | medida que la contesta |
|---|---|
| ¿está la resistencia en el layout? | área de `res_mk` = `s·L·W` exacto (382.25 µm²) |
| ¿está en la referencia? | `grep ppolyf` en el `_lvs.spice` |
| ¿es culpa de X? | **borrar X del mismo GDS** y volver a extraer (así se cazó el MIM) |

---

---

## 13. La v2 del generador (iteracion #32)

Misma base de codigo, un interruptor. `build_block.py <BLOQUE> --v2` escribe en
`a_zonetic2026/layouts_v2/` y `./run_lvs.sh --v2` verifica esa carpeta. **La v1 es el
camino por defecto y no cambia**: cada optimizacion va detras de un `if opts.v2`, y eso la
convierte en el control — si la v1 se mueve un nanometro, el interruptor esta mal puesto.

El nombre de la celda **no** cambia en la v2, a proposito: asi las dos se comparan contra
la **misma** netlist de referencia en el LVS, y un `Netlists match` es la prueba de que la
v2 no ha cambiado el circuito, solo el dibujo.

### 13.1 Que se cambio, y cuanto dio cada cosa

| | v1 | v2 | area |
|---|---|---|---|
| `WEIGHT_COMP` | 37.17 × 25.00 | 37.17 × 25.00 | 0 % |
| `DECODER` | 37.89 × 15.84 | **32.92 × 15.14** | **−17.0 %** |
| `COMP` | 104.28 × 31.46 | **99.75 × 31.46** | **−4.3 %** |
| `OPAM` | 88.27 × 31.46 | **77.27 × 32.68** | **−9.1 %** |
| `OPAM_LIN_flat` | 98.22 × 46.57 | **87.31 × 47.85** | **−8.7 %** |
| **total** | 12161 µm² | **11269 µm²** | **−7.3 %** |

**1. Un solo contacto de puerta.** El PCell se llamaba con `gate_con_pos="alternating"`,
que dibuja contacto arriba **y** abajo de la difusion. Solo se usa el que mira al canal; el
otro mira al riel y no lo toca nadie. Cuesta `PC_H + END_CAP` = **0.58 µm por fila**. El
PDK acepta `"top"` y `"bottom"`, asi que es un parametro.

Dos limites, y los dos importan: **solo vale para `nf == 1`** —el envoltorio multi-finger
NECESITA `alternating`, porque reparte los dedos pares abajo y los impares arriba y los ata
con un riser— y hay que envolver **despues** de repartir las filas, porque el lado depende
de la fila y N1/N2 no se sabe antes. Se re-envuelve ahi mismo: quitar un contacto cambia el
ALTO, no el ancho, y todo lo decidido hasta ese punto (cadenas, orden, reparto) depende
solo de anchos.

Da −0.70 µm de alto donde aplica (`DECODER`, `OPAM`, `OPAM_LIN_flat`) y nada donde la fila
la marca un multi-finger (`COMP`, `WEIGHT_COMP`).

**2. Cada fila pegada a su riel.** `place_row` alineaba a todos por el **origen** del PCell
—la esquina de la difusion—, y eso solo sale bien cuando el riel esta del lado del origen.
Medido:

| | hueco al riel, v1 | v2 |
|---|---|---|
| `COMP`, fila N (a VGND) | 0.35 .. 0.35 | 0.35 |
| `COMP`, fila P (a VPWR) | 0.35 .. **8.35** | **0.35** |
| `OPAM_LIN_flat`, fila P | 0.35 .. **9.85** | **0.35** |

No cambia el tamano —el alto de la fila lo marca el dispositivo mas ancho— y si acorta los
straps de alimentacion y saca del canal a los estrechos, que asomaban sin necesidad. Ojo:
al quitar el contacto de puerta (punto 1) la fila N heredaba el mismo defecto, porque
conviven dispositivos con y sin contacto abajo; por eso en la v2 **las dos** filas se
alinean por el borde del bbox del lado del riel, no por el origen.

**3. El salto del stub por metal2, y el abutment que desbloquea.** Es la pieza de fondo.
`_can_join` no dejaba abutir ninguna net que tuviera que **salir** del par, porque un bloque
S/D compartido tiene puerta a los dos lados y el stub que sale de el pasa por encima del pad
de gate del vecino: **0.155 µm entre centros cuando `M1.2a` pide 0.845**.

La salida es cambiar de capa donde estorba: el stub arranca en el bloque, sube a **metal2**
con una via1, cruza la banda del pad de gate —que es metal1, asi que no hay regla que los
separe— y vuelve a metal1 con otra via1 ya dentro del canal. Lo que desbloquea, medido:

| | abutidas v1 | v2 | ancho |
|---|---|---|---|
| `COMP` | 14 | 18 | 102.02 → 97.22 |
| `OPAM` | 14 | **24** | 85.78 → **73.78** |
| `OPAM_LIN_flat` | 14 | **24** | 95.96 → **83.96** |
| `DECODER` | 3 | 6 | 35.89 → 30.42 |

Salio con **DRC 0 y LVS limpio a la primera**. La infraestructura ya estaba hecha y
verificada desde hacia tiempo (`_shared_sd_contact`, `ABUT_BLOCK_CON`); lo unico que
faltaba era el salto y quitar la restriccion.

**4. Trunks en metal3: NO se hizo, y con la cuenta delante.** Ver §13.3.

### 13.2 Dos bugs latentes que destapo la v2

Ninguno es de la v2: estaban en la v1 y solo hacia falta un tamano distinto para que
salieran.

- **`_hbar` y el nwell usaban `gf.components.rectangle`**, que **cachea celdas por tamano**.
  `x1 - x0` en coma flotante puede quedarse 1 nm corto, la caja no mide lo pedido y el borde
  acaba fuera de rejilla. Es exactamente la trampa que ya obligo a reescribir
  `routing._rect`, y aqui seguia. En la v2 de `DECODER`: los dos rieles arrancaban en
  **x = −0.999** y el nwell en **−1.139**, con 4 `metal1_OFFGRID` y 2 `nwell_OFFGRID`.
  Arreglado insertando la caja directa (`_caja`), que es lo que ya hacia `routing`.
- **El alineado nuevo tampoco estaba a rejilla.** Mismo sintoma, misma cura: `snap`.

### 13.3 Trunks en metal3 sobre las filas: implementado, medido y APAGADO

El canal se lleva **~40 % del alto** de estos bloques (13 pistas), asi que adelgazarlo es la
ganancia grande que queda. Se intento por dos caminos.

**Camino descartado sin escribir codigo: intercalar metal3 DENTRO del canal.** La cuenta lo
mata: el stub de un trunk de metal3 sube por metal1 → via1 → **metal2** → via2 → metal3, asi
que en la altura de ese trunk hay pads de metal2 de 0.38 en cada punto de stub. Un trunk de
metal2 vecino les debe 0.28, y `0.19 + 0.28 + 0.19 = 0.66` — exactamente el paso que ya hay.
**Se gana cero.**

**Camino bueno: los trunks POR ENCIMA de las filas**, donde metal3 esta libre y no cuesta ni
una micra porque es otra capa sobre area ya ocupada. Esta **implementado** (`opts.trunks_m3`,
`routing._nets_a_metal3` y `_banda_m3`) y la ganancia esta medida:

| | canal | celda | area |
|---|---|---|---|
| v2 hoy | 13 pistas | 99.75 × 31.46 | 3138 µm² |
| con trunks en metal3 | **3 pistas** | 105.88 × **25.42** | **2690 µm² (−14 %)** |

El reparto de pistas que queda en el canal, medido en los cinco: `COMP` 13 → **3**,
`OPAM` y `OPAM_LIN_flat` 13 → **4**, `WEIGHT_COMP` 11 → 4, `DECODER` 6 → 4.

**Sube la net que no la necesita nadie mas.** Se quedan abajo las de PUERTO, las de un
CONDENSADOR y las de una RESISTENCIA, que son las tres familias que `caps`, `resistors` y
`power` leen de `lay.trunks` dando por hecho metal2. Dejandolas en el canal, los trunks de
metal3 sencillamente **no se apuntan** y no hay que tocar ninguno de los tres modulos.

**Y esta APAGADO**, por dos problemas sin resolver:

1. **DRC: 39 violaciones**, 21 de ellas `M2.2a`. Los tramos verticales de metal2 que suben de
   la fila al trunk se pisan entre ellos y con los straps de los multi-finger: se midieron
   pares de aristas a **0.135 µm** cuando la regla pide 0.28. Se probo estrechar el vertical
   de 0.38 al minimo de 0.28 y **subieron a 72**, o sea que el arreglo no es el ancho: es que
   `_spread_stubs` reparte en x contando solo el **metal1**, y estos stubs son de metal2.
   Ahi es donde hay que meter mano.
2. **magic se dispara.** Con metal3 sobre las filas su extraccion pasa de segundos a **mas de
   10 minutos**, que es justo su tiempo limite, asi que las netlists extraidas dejan de
   salir. Es independiente del DRC y habria que mirarlo aparte.

Se deja el codigo entero y comentado, detras de `Opciones.trunks_m3`, porque el camino es
bueno y el trabajo que falta esta acotado. Lo que **no** se hace es dejarlo encendido: la v2
es un entregable verificado y no se cambia por algo a medias.

---

## 14. Los bancos con el layout dentro: v1 contra v2

`XSCHEM/TEST/preparar_extraidos.sh` deja los extraidos de la v2 listos para instanciarlos
**al lado** de los de la v1 en el mismo banco, y hace dos cosas que no son opcionales.

**1. Renombrar el subcircuito.** Los dos declaran `.subckt <BLOQUE>` porque la celda se
llama igual a proposito. Se tocan **solo** las lineas `.subckt` y `.ends`: un `sed` global
tocaria tambien nodos internos que contengan el nombre (magic los genera como
`<BLOQUE>_...`) y partiria la netlist en silencio.

**2. Normalizar el orden de los puertos**, y esta es la trampa buena:

> **magic emite los puertos en el orden en que los encuentra en el layout, y ese orden
> CAMBIA con el layout.**
>
> ```
> v1: .subckt OPAM_LIN_flat    VSS VDD INP OUT INN
> v2: .subckt OPAM_LIN_flat_V2 VSS VDD INP INN OUT     <- OUT e INN al reves
> ```
>
> Con las dos instancias cableadas igual —que es lo natural, y lo que hice— la v2 tenia la
> salida conectada a la entrada negativa. **No da ningun error**: simula, converge y
> escribe numeros. Se vio porque su transferencia salia plana en 0.00..0.72 V mientras el
> esquematico hacia 0.01..4.97. `COMP` no lo destapo porque ahi las dos versiones
> coincidian por casualidad.

Reordenar la linea `.subckt` es legitimo y no toca nada mas: el cuerpo se refiere a los
nodos por NOMBRE, asi que su posicion solo decide con que nodo del llamante se empareja
cada uno. El script ademas comprueba que los dos declaran el **mismo juego** de puertos y
aborta si no.

### 14.1 Por que magic no extraia la resistencia de poly, y como se arregla

Salio al montar los bancos: el extraido de `OPAM_LIN_flat` **no tenia la resistencia**, y
sin la realimentacion de 1.15 MΩ la transferencia se quedaba clavada en 3.00..3.16 V
mientras el esquematico hacia 0.01..4.97.

```
grep -ic ppolyf  mag/OPAM_LIN_flat.mag             -> 0
grep -ic ppolyf  mag/OPAM_LIN_flat_extracted.spice -> 0
grep -ic ppolyf  mag/OPAM_LIN_flat_pex_rc.spice    -> 0
grep -c ppolyf_u_3k  lvs/OPAM_LIN_flat_flat_gf180.cir -> 5     <- KLayout SI
```

**La causa es la jerarquia del GDS, no las reglas de magic.** Su tech deriva la resistencia
de alta hoja como una **AND de cuatro capas**:

```tcl
 layer hires POLY
 and SBLK          # bloqueo de silicida  (sab, 49/0)
 and HRES          # capa `resistor`      (62/0)
 and RESDEF        # marcador `res_mk`    (110/*)
 and-not DUALGATE
```

y esa AND la evalua **celda a celda**, al leer el GDS. gdsfactory escribe cada rectangulo
en **su propia celda**, asi que las cuatro capas acaban en cuatro celdas distintas y la
interseccion sale vacia. Se ve mirando los `.mag` de las subceldas:

| celda | tipo que le sale a magic |
|---|---|
| `rectangle_S77p73_1_Lpol_*` (poly) | `polysilicon` |
| `rectangle_S76p65_1p56_L_*` (sab) | **vacia** |
| `rectangle_S78p53_1p8_Lr_*` (`resistor`) | **vacia** |
| `rectangle_S76p45_1_Lres_*` (`res_mk`) | **vacia** |

El `flatten` que el script ya hacia **llega tarde**: para entonces la conversion GDS → tipos
de magic ya ha ocurrido. Hay que aplanar **antes de que magic lea el GDS**.

**Arreglado** en `build_block.write_mag`: se aplana con KLayout (0.1 s; el `flatten` de
magic sobre esta jerarquia no termina, >10 min) y se le da a magic un GDS de una sola
celda. Salen los **cinco** tramos, encadenados hasta `OUT`:

```
X1  a_928_4922# a_16346_4472# VSS ppolyf_u_1k r_width=1u r_length=76.45u
...
X36 a_928_5822# OUT           VSS ppolyf_u_1k r_width=1u r_length=76.45u
```

**Y falta un segundo paso, o el valor esta mal.** Fijate en el modelo: `ppolyf_u_1k`. La
tech de magic solo declara

```tcl
 device rsubcircuit ppolyf_u_1k     hires   *poly ... l=r_length w=r_width
 device rsubcircuit ppolyf_u_1k_6p0 mvhires *poly ... l=r_length w=r_width
```

—**ni 2k ni 3k**, exactamente el mismo hueco que tenia netgen y que tiene la tabla de
variantes de KLayout (§11.0.2). Reconoce la resistencia por su GEOMETRIA, que es la misma
para las tres hojas, y le pone la unica etiqueta que conoce. Simular eso da **382 kΩ donde
el circuito pide 1.15 MΩ**: la ganancia se iria a un tercio sin que nada avise.

Se corrige donde se puede, que es en el netlist extraido: `_hoja_resistencia()` sustituye el
modelo por el que pide el esquematico. Es el tercer parche del mismo hueco, y los tres
hacen lo mismo por vias distintas:

| herramienta | como se le dice que es 3k |
|---|---|
| KLayout | `-rd poly_res=3k` al deck (§11.0.2) |
| netgen | setup local que declara el dispositivo |
| magic | sustituir el modelo en el extraido |

> **Lo que hay que llevarse:** que una herramienta no saque un dispositivo **no significa
> que el layout este mal**. Aqui el layout era correcto —KLayout lo extraia entero y el LVS
> casaba— y lo que fallaba era como se le daba el GDS. Y al reves: que lo saque no significa
> que lo saque BIEN. El unico modo de estar seguro es mirar el netlist extraido y contar.

### 14.2 Lo que dicen los bancos

Los **siete** bancos llevan ya las tres columnas: esquematico, layout v1 y layout v2, cada
uno con su propia alimentacion para poder comparar consumos sin mezclarlos.

**`OPAM_LIN`, que es el que importaba** (los tres bancos del g100):

| | esquematico | layout v1 | layout v2 |
|---|---|---|---|
| ganancia 1-4 V | 103.1 | 102.9 | **103.0** |
| INL | 0.12 % | 0.12 % | **0.12 %** |
| offset | +23.8 mV | +23.8 mV | **+23.8 mV** |
| consumo | 2.550 mW | 2.549 mW | **2.549 mW** |
| ganancia cc | 40.1 dB | 40.1 dB | **40.1 dB** |
| GBW | 3.631e7 Hz | 3.715e7 | **3.715e7** |
| **margen de fase** | **73.9 gr** | **65.3 gr** | **65.1 gr** |
| slew subida | 444.9 V/us | 398.3 | **396.0** |
| slew bajada | −564.9 V/us | −475.2 | **−489.8** |

Dos lecturas, y las dos son el resultado que se buscaba:

- **El layout no rompe el circuito.** Linealidad, offset y consumo salen clavados. Lo que
  si cuesta son **8.7 grados de margen de fase** (73.9 → 65.3) y un **10 % de slew**, que es
  el precio de los parasitos y sigue muy lejos de los 45 grados de la frontera.
- **La v2 se comporta como la v1.** Es lo que habia que comprobar de una reorganizacion del
  dibujo: 65.1 contra 65.3 grados, misma GBW, misma INL. La v2 ocupa un 8.7 % menos de area
  y no paga nada por ello.

**`COMP`**, con sus tres bancos:

| | esquematico | v1 | v2 |
|---|---|---|---|
| ganancia | 86663 | 84851 | **85050** |
| ganancia cc | 98.7 dB | 98.5 | **98.5** |
| margen de fase | 72.3 gr | 69.7 | **69.4** |
| retardo | 441.3 ns | 455.0 | **455.8** |

`DECODER` y `WEIGHT_COMP` dan la misma logica y la misma energia por transicion en las tres
columnas.

**El RC salio barato**, al reves de lo que avise al planificarlo: el banco mas lento es el
transitorio de `COMP`, **5.8 s** con tres instancias extraidas dentro. Lo digo igual que
habria dicho lo contrario.

Una trampa de xschem que volvio a morder: en `test_weight` la fuente nueva salio como
`V9 net1 net2 5` en vez de `V9 VDD2 GND 5`. Ese banco conecta sus fuentes con **cables**, no
con pines coincidentes, y sin los dos `N` la fuente queda flotando. El sintoma fue
`Transient op failed` y cero ficheros escritos.

---

## 15. El top con las celdas de la v2 (iteracion #34)

`GRADIENT_NAV` se construye con OpenROAD a partir de los cuatro bloques como macros. Para
poder armarlo con la v2 **sin perder el de la v1** —los dos tienen que coexistir para
compararlos— se anadio un interruptor de version que recorre todo el flujo:

```bash
cd a_zonetic2026/openroad
make top            # el top con los bloques de la v1  -> out/
make top V=v2       # el top con los bloques de la v2  -> out_v2/
```

Tres piezas, y las tres hacen falta:

- **`scripts/usar_version.sh v1|v2`** reapunta los enlaces de `gds/`, que es por donde el
  flujo lee los layouts de los bloques (`build_collateral.py` los abre como
  `gds/<BLOQUE>.gds`). Es el unico punto de entrada, asi que cambiarlos basta.
- **`TOP_OUT`** manda la salida a `out` o a `out_v2`. Lo leen los dos scripts de OpenROAD y
  los de DRC, LVS y relleno.
- **`lef/.version` y el objetivo `comprobar-version`**. Los bloques de la v2 miden distinto,
  asi que un LEF de la v1 describiria macros del tamano equivocado y el floorplan cuadraria
  igual, colocando macros solapados. Cualquier paso que lea el LEF comprueba antes que el
  collateral se genero con la version que se esta pidiendo, y se planta si no.

### 15.1 Lo que sale

| | v1 | v2 |
|---|---|---|
| die | 371.70 × 408.52 µm | **378.08 × 374.10 µm** |
| area | 0.1518 mm² | **0.1414 mm²** (−6.9 %) |
| utilizacion | — | 56 % |
| DRC del router | 0 | **0** |
| DRC de firma (KLayout) | limpio | **limpio** |
| DRC de firma con relleno | limpio | **limpio** |
| relleno de densidad | cumple | **cumple las 7 reglas** |
| conectividad (55 nets del DEF) | 55/55, 0 cortos | **55/55, 0 cortos** |
| **LVS (netgen)** | casa | **casa** |

Los bloques mas pequenos dan un die **mas ancho y bastante mas bajo**: el emplazador reparte
en 8 estanterias en vez de las de antes y la altura baja **34 µm**.

### 15.2 El LVS del top no casaba, y era el DEF equivocado

Estuvo un rato en rojo y merece quedar escrito, porque el sintoma no apuntaba a la causa.
netgen daba:

```
Number of devices: 1389        | Number of devices: 1389
Number of nets:     944 Mismatch | Number of nets:  880 Mismatch
Final result: Top level cell failed pin matching.
```

Dispositivos exactos, ninguna net de la referencia sin pareja, **64 nets de mas** en el
layout y un fallo de emparejamiento de pines. Se descarto por medida, en este orden: no eran
los bloques (los cinco pasan DRC y LVS en las dos versiones), no era la extraccion de magic
de los bloques (los nodos internos que saca por bloque son **identicos** en v1 y v2), no era
la seccion de pines del DEF (19 en las dos, todas con coordenada distinta) y **no era un
corto** — se probo el GDS con una extraccion de solo metales y los nueve pines de
`X`/`Y`/`Z` salian en nueve nets distintas.

Lo que lo cerro fue medir **cuanto metal tiene la net de cada pin**:

| | formas por net de pin |
|---|---|
| v1 | 41 .. 125 |
| v2 | **1 .. 1**, los 17 pines |

Diecisiete formas sueltas. El top no estaba ruteado. Y la causa era **mia**: al parametrizar
el `Makefile` para separar la salida por version le pase a `def_to_gds.py` el DEF del
**floorplan** en vez del **ruteado**. El script tiene bien su valor por defecto
(`GRADIENT_NAV_routed.def`); lo estropee al pasarle el argumento explicito.

> **Por que no salto antes:** un GDS con los macros colocados y sin una sola conexion entre
> ellos **pasa el DRC** — no hay nada que pueda violar una regla — y pasa el relleno de
> densidad, y el router habia terminado con 0 violaciones porque el que estaba mal no era el
> ruteo sino lo que se estreamaba despues. Es el mismo patron de §12.5 una vez mas: la unica
> comprobacion que lo veia era el LVS.

Arreglado en el `Makefile` (pasa el DEF ruteado) y en `def_to_gds.py`, cuyo valor por
defecto respeta ahora `TOP_OUT` para no leer el DEF de la otra version cuando se le invoca a
pelo. Los dos tops casan: **880 = 880 nets, `Circuits match uniquely`**.

#### 15.2.1 Y de paso: el top de la v1 en disco estaba viejo

Al comparar salio que el `out/GRADIENT_NAV.gds` que habia en disco daba **10/55** nets
conectadas en `check_connectivity`, aunque su LVS casara. Era un GDS de una corrida vieja,
anterior a los arreglos de `_hbar` y `_caja` de esta iteracion. Regenerando **solo** el GDS
salio peor todavia (34/55, 3 cortos), porque entonces se mezclaban bloques nuevos con un DEF
ruteado con los LEF viejos.

La leccion es de flujo: **el DEF, el LEF y el GDS de los bloques tienen que venir de la
misma corrida**. Rehecho el v1 entero (`collateral` + `floorplan` + `route` + `gds`) da
55/55, 0 cortos y LVS limpio. Y `check_connectivity`, que en §15.2 parecia poco fiable,
resulta que **tenia razon**: lo que fallaba era el fichero que le estaba dando.

### 15.3 Un defecto de la v2 que destapo el top

El floorplan de la v2 abortaba con

```
ERROR PDN-0006  VSS on Metal3 is blocked by obstructions on Metal4, Metal5 for x1_x1
```

y la causa era **mia**: al permitir que la placa MIM se construyera hacia ABAJO del punto de
agarre (§5.7.1), en `OPAM` se salia de la celda por abajo y tapaba el riel VGND. La
obstruccion de Metal4 del LEF lo dice sin ambiguedad:

| | obstruccion de Metal4 |
|---|---|
| v1 | `y 8.76 .. 27.08` — los rieles libres |
| v2 (rota) | `y −2.95 .. 25.41` — **cruza VGND y se sale de la celda** |

No es una regla de DRC: es que el bloque se usa como **macro** y el top le baja la
alimentacion desde metal4 a la barra de metal3 que el bloque expone sobre cada riel. Una
placa encima de esa barra aparece como obstruccion y `pdngen` se planta.

Arreglado en `caps.place_caps`: la placa tiene que quedarse **entre los dos rieles**.
`OPAM` v2 pasa de 32.68 a **31.42 µm** de alto, o sea que ademas queda mas bajo que la v1.

> **Lo que hay que llevarse:** una celda que pasa DRC y LVS **por si sola** puede seguir
> siendo inservible como macro. El contrato con el nivel de arriba —donde puede aterrizar la
> alimentacion, por donde entran los pines— no lo comprueba ninguna de las dos
> herramientas de bloque. Aqui lo canto `pdngen`, y solo porque aborta en vez de avisar.

---

---

### 15.4 Un tercer top: `GRADIENT_NAV2`

`GRADIENT_NAV` monta cuatro bloques `GRADIENT`, que llevan el `OPAM` de 98 dB.
`GRADIENT_NAV2` es el **mismo esquemático** con `GRADIENT2`, o sea con el
`OPAM_LIN_flat`. El banco de gradiente de `XSCHEM/TEST_TOTAL` dice que esa es la
cadena que funciona —error de sector 1.25° contra 29.75°—, así que hacía falta su silicio.

El flujo pasa a estar parametrizado **por top**, igual que ya lo estaba por
versión:

```bash
make top T=GRADIENT_NAV2 V=v2      # navegador con la cadena lineal
make top V=v2                      # el de siempre; T=GRADIENT_NAV por defecto
```

`TOP_CELL` recorre `load_design.tcl`, los dos `.tcl` y los seis guiones de
verificación, y cada combinación de top y versión escribe en su propio
directorio (`out`, `out_v2`, `out_v2_GRADIENT_NAV2`). Dos cosas que hubo que
añadir:

* **`OPAM_LIN_flat` no estaba en el collateral**, ni en la lista de DRC, ni en la
  de LVS. Llevaba fuera desde que se creó, sencillamente porque ningún top lo
  instanciaba.
* **El esquemático y el layout llaman distinto a la misma celda**: el netlist
  dice `OPAM_LIN` y el macro es `OPAM_LIN_flat`, que es su versión aplanada. Va
  como alias en `spice_to_verilog.py`, no como dos celdas.

| | `GRADIENT_NAV` v2 | `GRADIENT_NAV2` v2 |
|---|---|---|
| die | 0.1414 mm² | **0.1730 mm² (+22 %)** |
| macros | 12 `OPAM` + 12 `COMP` + 4 `DECODER` + 3 `WEIGHT_COMP` | 12 **`OPAM_LIN_flat`** + idem |
| DRC del router | 0 | **0** |
| DRC de firma | limpio | **limpio** |
| conectividad | 55/55, 0 cortos | **55/55, 0 cortos** |

El +22 % es entero del amplificador: `OPAM_LIN_flat` mide 4178 µm² contra los
2427 del `OPAM`.

### 15.5 El puerto que magic traza a través de la resistencia

La primera corrida del top nuevo dio **43 de 55 nets**. Las 12 abiertas eran las
salidas de los amplificadores, las tres de cada `GRADIENT2`. La causa no estaba
en el ruteo:

**magic escribe el puerto de un LEF con toda la geometría que su modelo de
conectividad da por unida, y ese modelo atraviesa el cuerpo de una resistencia de
poly.** `OPAM_LIN_flat` es el único bloque con resistencia
(`XRFB G_OUT_P OUT VSS ppolyf_u_3k`), y su LEF declaraba como pin `OUT` metal de
los **dos** lados de la realimentación: el de `OUT` y el de `G_OUT_P`, que es un
nodo interno. El router aterrizó en el lado equivocado y **los tres comparadores
de cada bloque quedaron colgados de la puerta de la etapa de salida**.

Nada de esto se queja. DRC 0, informe del router vacío, y el bloque pasa su
propio LVS porque el layout está bien: lo que miente es el abstracto. Se cazó
sondeando el GDS del bloque con `LayoutToNetlist` sobre la pila de metales: el
rótulo `OUT` cae en la net `$29` y el punto donde aterrizó el router en la `$58`.

El arreglo va en el origen. `build_collateral.podar_islas_ajenas` extrae el
metal del bloque, busca de qué net es la **etiqueta** de cada pin y quita del
puerto todo rectángulo que no esté unido a ella; lo que quita entra como
obstrucción, porque sigue siendo metal. Es quirúrgico: poda **27 + 17 + 5**
rectángulos del `OUT` de `OPAM_LIN_flat` y **nada** en los otros cuatro bloques,
así que los tops v1 y v2 no se mueven.

> Con el LEF corregido, el top pasa de 43/55 a **55/55 nets y 0 cortos**.

**Cuidado con la convención de coordenadas.** Las del LEF que escribe magic
**son** las del GDS, sin desplazar: el bloque declara `ORIGIN 1.26 0` y
`SIZE 87.31` justamente porque su geometría va de −1.26 a 86.05, que es el bbox
del GDS. El `ORIGIN` se suma **al colocar** el macro (ver
`check_connectivity.place`), no al leer el LEF. Restarlo aquí hacía que la poda
se llevara por delante casi todos los pines de los cinco bloques.

### 15.6 Relleno de desacople: dónde cabe y en qué está

La idea es llenar el hueco del top con transistores conectados como
condensadores: NMOS con la puerta a VDD y canal, fuente, drenador y sustrato a
VSS, y PMOS al revés. Los dos quedan en inversión y dan la capacidad de óxido de
puerta completa.

**Lo primero es dónde se puede.** La red de alimentación del núcleo son tiras de
Metal4 (verticales, por encima de los bloques) y Metal5 (horizontales, por los
canales): en los huecos no hay alimentación en metal bajo. Pero dentro de un
estante todos los macros miden lo mismo y cada bloque saca su riel VSS en Metal1
abajo y VDD en Metal1 arriba, a la misma altura. Un relleno metido en ese hueco
conecta **por abutment de Metal1**, sin una sola vía y sin tocar Metal2 ni
Metal3, que es por donde va el ruteo que ya cerró.

| | µm² | % del die | % del hueco |
|---|---|---|---|
| die | 172 955 | 100 | |
| macros | 92 573 | 53.5 | |
| **hueco libre** | **80 382** | 46.5 | 100 |
| alcanzable por abutment | **18 523** | 10.7 | **23 %** |
| sin abutment posible | **61 859** | 35.8 | **77 %** |

De lo que no se alcanza, 26 577 µm² son la banda de margen del die y 35 282 son
canales entre estantes o zonas cuyo vecino tiene los rieles a otra altura —el
caso típico son los `WEIGHT_COMP`, de 25.00 µm de alto al lado de filas de 31.46.
Llegar ahí exigiría una pila de vías hasta el Metal5 de los canales, y esa pila
cruza el ruteo.

**Cuánto entró.** Los huecos se calculan por **estante** —macros que comparten `y` y
alto, que es la condición para que sus rieles estén a la misma cota— restando **todo**
macro que solape en `y`, no sólo los del propio estante: `WEIGHT_COMP` vive en un estante
suyo de 25.00 µm y se mete de lleno en el hueco derecho de las cuatro filas de `COMP`.

| | µm² | |
|---|---|---|
| hueco de estante (unión) | **25 183** | 100 % |
| **rellenado** | **22 407** | **89 %** |
| sin rellenar | 2 776 | 11 % |

Lo que queda fuera son siete huecos pegados a `WEIGHT_COMP` y al `DECODER`: **esos macros
no sacan riel a la cota del estante vecino** —por su borde de abajo lo que asoma son los
dedos de sus transistores— así que una baldosa ahí se quedaría con una alimentación al
aire. El generador lo detecta y lo dice con su área.

**Lo que hay dentro:** 36 baldosas, **229 transistores** (119 NMOS + 110 PMOS), W total
855.0 µm en N y 792.0 µm en P con L = 2.0 µm, **~5.11 pF** de desacople. Los mismos 229
van al esquemático del top en un bloque `code_shown`, **escrito por el propio generador**:
el layout y el esquemático salen de la misma corrida o el LVS deja de significar nada.

**Una sola fila de cada tipo, y los transistores lo más largos que quepan.** La altura
entera del hueco va a un NMOS y un PMOS, no a varias bandas apiladas: W = **18.0 µm** en los
estantes de 47.85, 9.75 en los de 31.46 y 1.5 en la fila del `DECODER`. Para que puedan
crecer así, **cada fila lleva dos tiras de taps, una debajo y otra encima**: con una sola, el
tap queda en un extremo del canal y `DF.13_MV`/`DF.14_MV` —15 µm como mucho del tap a cada
PCOMP/NCOMP— limitan el dispositivo a unos 11 µm. Con las dos, el punto peor es el centro
del canal y el mismo margen da para 26. La tira de arriba se ata **al pad de fuente/drenador
que tiene justo debajo**, que es de su misma net; en el centro no puede, porque ahí está la
placa de puerta, que es de la net contraria. Sale la misma capacidad con **51 dispositivos
menos** (229 contra 280) y sin la escalera de barras y taps que hacía falta para intercalar
bandas.

**Cinco cosas que costaron, y que conviene no volver a pisar:**

* **La puerta es `cajas[-1]` en los dos tipos.** Los dos dispositivos se construyen con
  `gate_con="top"`, así que la placa de puerta es siempre la de arriba. Cogiendo `cajas[0]`
  para el PMOS se tomaba un drenador por puerta: el código estiraba la **placa de puerta**
  —2.0 µm de ancho, la del canal— hasta el riel contrario, y ahí pasaba a 0.07 µm de la
  fuente y del drenador. Ésas eran las cuatro `M1.2a` que quedaban de la iteración #38. Y
  no era sólo DRC: el PMOS acababa con la puerta a VDD y un drenador a VSS, o sea
  **cortado y sin capacidad ninguna**.
* **El dbu de cada layout es suyo.** Las cajas del PCell vienen en unidades enteras de su
  layout (0.001) y el GDS del top va a 0.0005. Pasándolas a micras con el dbu **de
  destino**, los dispositivos salían **a la mitad de tamaño**: 1180 `M1.1` + 886 `M1.2a`, y
  ni una en la baldosa suelta, que se construye en un layout de 0.001 y por eso cuadraba.
  La otra cara de lo mismo: `Layout.read` sobre un layout que **ya tiene celdas** le cambia
  el dbu sin reescalar lo que había, así que las baldosas no pueden venir por fichero.
* **Los rieles no llegan a los dos bordes del macro.** El VSS del vecino de la izquierda
  termina exacto en su borde derecho (x = 96.830); el del vecino de la derecha **empieza
  0.26 µm dentro**. Una baldosa dibujada de borde a borde queda **abierta por ese lado**, y
  0.26 > 0.23, así que el DRC no dice nada. Se miden y se estiran hasta solapar.
* **Un dedo de transistor no es un riel.** El primer criterio era "metal que ocupe casi
  toda la altura de la banda", y eso lo cumple cualquier dedo que cruce la banda. Con él,
  tres baldosas estiraron su VSS **dentro de `WEIGHT_COMP`** y cortocircuitaron `net5` y
  `net6` de tres de ellos: **el DRC daba limpio** —son solapes, no espaciados— y sólo lo
  vio el LVS, 877 nets contra 880. El criterio bueno es una **sonda de media micra con la
  altura entera de la banda** al fondo de la ventana, que un dedo de 0.36 µm no puede
  llenar.
* **Los estantes se solapan en `y`.** El mismo trozo de silicio aparecía como hueco de dos
  estantes distintos y se colocaban baldosas encima de baldosas. Se colocan de mayor a
  menor descartando lo que pise a una ya puesta.

**Y una comprobación que el DRC no hace.** `decap_fill.comprobar()` funde el metal1 del
resultado —`Region.merged()`, así que un polígono es una componente conexa— y exige, para
cada baldosa, que sus dos rieles estén en componentes **distintas** y que cada uno esté en
la **misma** que el riel del macro vecino. Contesta a las dos preguntas que el DRC no
contesta: si VDD y VSS acabaron siendo la misma cosa, y si el relleno quedó colgando.

**Los taps van dentro de cada dispositivo**, entre sus dos pads de fuente y drenador: ahí
hay 2.14 µm libres y esa banda sólo la cruzan en vertical los propios pads, que van a la
barra de abajo y son **su misma net**. Metiéndolos en los huecos *entre* dispositivos se
quedaban fuera cuando el hueco medía menos de `TAP_W + 2·CLR`: en las baldosas de 9.52 µm
del margen del die sólo cabe un PMOS y el único hueco medía 1.26 µm, **dos centésimas por
debajo** — once `DF.13_MV`, que pide un tap de pozo a menos de 15 µm de cada PCOMP.

**El pozo se aparta 1.8 µm del borde.** Sin `CONNECTIVITY_RULES` el deck aplica `NW.2b_MV`,
que pide **1.7 µm entre pozos aunque sean la misma net**, y el pozo del macro de la derecha
llega justo a su borde. Los carriles verticales de VDD/VSS también van metidos `CLR` hacia
dentro: pegados al borde, el de VSS quedaba a 0.14 µm del riel VDD del `DECODER` de al
lado.

**El relleno de densidad va encima.** `fill_density.py` parte de `_decap.gds` si existe y
trata las baldosas como macros —dentro hay pozo, difusión y puertas—. `GRADIENT_NAV2` es un
22 % más grande que `GRADIENT_NAV` con los mismos macros dentro, así que sus metales 2 a 5
se quedaban por debajo del mínimo donde los de la v1 llegaban: `M2.4`, `M3.4`, `M4.4`,
`M5.4` y `MT.3`, una violación por regla. Ahora, **por capa y sólo si hace falta**, se
rellena también encima de los macros; COMP, Poly2 y Metal1 no lo necesitan, y el propio
desacople sube el Metal1 del 12.95 % al 31.32 %.

### 15.7 El primer LVS de `GRADIENT_NAV2`: dos fallos de las herramientas

El LVS del tercer top no se había corrido nunca. Al correrlo no falló el layout: fallaron
las dos comprobaciones, cada una por su lado.

**`align_ports` no plegaba las continuaciones `+`.** magic parte la cabecera del `.subckt`
**por columna**, no por contenido, y el top de la v2 sale como `.subckt GRADIENT_NAV2 S1N
... VDD` + una segunda línea `+ VSS`. Leyendo sólo la primera línea física falta `VSS`,
`align_ports` ve que los conjuntos de puertos no coinciden, se rinde —con razón: le falta
un puerto— y deja el orden de magic. netgen entonces empareja los pines del top **por
posición** y termina en `Top level cell failed pin matching`, con 1401 dispositivos y 880
nets idénticos a los dos lados. El top de la v1 se libró de milagro: sus 19 puertos cabían
en una línea.

**La hoja de la resistencia de poly.** 1 k, 2 k y 3 kΩ/□ **no se dibujan distinto**: son la
misma capa y lo que cambia es una opción de proceso. El techfile de magic sólo declara
`ppolyf_u_1k`, así que extrae siempre ésa; `build_block.py::_hoja_resistencia` ya lo
corregía en cada bloque, pero el top no pasaba por ahí. Resultado: `ppolyf_u_1k (60→12)`
contra `ppolyf_u_3k (12)`, dos clases de dispositivo distintas, y **cada net que tocaba una
resistencia quedaba en fragmentos**. Doce resistencias tiraban abajo la comparación entera.
En KLayout, lo mismo por otro camino: `run_lvs.py` **fija `poly_res=1k` en su tabla de
variantes** —en las cuatro— y 1801 de 1828 nets se quedaban sin pareja.

Con los bloques, `run_lvs.sh` llama al deck a pelo con `-rd poly_res=3k`. **Con el top eso
no sirve:** la comparación del propio deck se queda dando vueltas —**6 horas sin terminar**,
contra los 12 segundos que tarda por `run_lvs.py`— y no escribe la netlist extraída hasta el
final, así que un tiempo límite no deja ni eso. Como aquí el veredicto no lo da el deck sino
`comparar()`, basta con **renombrar la hoja en la extracción**, que es donde la diferencia
vive.

**Y una tercera cosa, del comparador de KLayout:** llamarlo dos veces en el mismo proceso
lo revienta (*segmentation fault*), y sobre la netlist del GDS **con relleno de densidad**
también. Ahora se lanza en un proceso aparte, así que un fallo suyo se reporta en vez de
llevarse la corrida por delante. Para el fichero con relleno el veredicto lo da netgen
—`Circuits match uniquely`—, y KLayout firma el `_decap`, que tiene exactamente la misma
conectividad: el relleno no añade ni un dispositivo ni una conexión.

**Los 280 de desacople son todos iguales y cuelgan de las mismas dos nets**, o sea un
empate de 146 ramas. netgen lo deshace fundiendo los que están en paralelo (`property
parallel enable` en el setup del PDK); al comparador de KLayout hay que decírselo con
`Netlist.combine_devices()` en los dos lados. Sin eso quedaban **6 dispositivos sin pareja
con 0 nets y 0 pines sin pareja**, que es la firma de un empate y no de una diferencia de
circuito. Subir `max_depth` y `max_branch_complexity` lo empeora: es una búsqueda con
vuelta atrás y más ramas la despistan.

### 15.8 Lo que hacía falta para meterlo en un padring

El top ya era **una sola celda plana y autocontenida** —una `SREF` y está dentro— con sus
19 puertos etiquetados en las capas de texto (`36/10`, `42/10`, `81/10`), DRC y densidad
limpios y netlist de referencia generada. Lo que faltaba era todo de contorno, y se midió
antes de tocar nada:

| | estaba | está |
|---|---|---|
| `VDD` / `VSS` | (28.98, 398.11) y (22.98, 392.11), **dentro** del die, `USE SIGNAL` | en el borde izquierdo, `POWER` y `GROUND` |
| paso entre pines | **1.12 µm** | **5.04 µm** |
| metal1 del desacople al borde | **0.000 µm** | ≥ 1.9 µm |
| relleno de COMP al borde | **0.005 µm** | ≥ 2 µm |

**Los puertos SÍ tienen que tocar el contorno** —es por donde se entra— y siguen
tocándolo: Metal2, Metal3 y Metal5 llegan a 0.000, que es lo correcto. Lo que no puede
tocarlo es todo lo demás, porque pegado a un anillo de sellado o a otro proyecto eso es
espaciado **cero** y en aislado no lo ve nadie.

La tira de Metal5 de cada alimentación se prolonga hasta x = 0 y el pin se coloca encima
(`floorplan_top.tcl::alargar_al_borde`). Antes se ponía cerca del extremo izquierdo de la
tira, que empieza a 19.98 del borde.

**El margen de guarda cuesta capacidad, y no hace falta pagarlo entero.** Con 2 µm por los
dos lados, las ocho baldosas de desacople de los márgenes del die se quedaban con 2.92 µm
de ventana contra los 3.66 que mide un dispositivo, y se perdían 0.77 pF de 5.11. Pero el
margen de pozo de `MARGEN_P` existe por `NW.2b_MV`, que pide 1.7 µm **a otro pozo**, y
contra el contorno del die no hay ninguno: ahí basta con `NWELL_BORDE_DIE = 0.20`, porque
los 2 µm de guarda ya están fuera. Recuperado: **4.93 pF** con 224 transistores.

## 16. Banco del top: el esquemático contra su propio layout, con parásitos

`XSCHEM/TEST_TOTAL/test_NAV2.sch` es al navegador lo que `test_GRADIENT.sch` era al
gradiente: **cuatro puentes magnetorresistivos alimentando dos navegadores a la vez**, el
del esquemático y uno rehecho a mano con los 31 bloques extraídos del layout v2 **con RC**.
Cada uno con su fuente, para poder comparar también el consumo.

**Los cuatro sensores no son cuatro ejes: son cuatro posiciones.** Van en los vértices de
un **tetraedro regular inscrito en un cubo** —`S3` y `S4` en esquinas opuestas del plano z
de abajo, `S1` y `S2` en las dos contrarias del de arriba—, que es la disposición del
diseño:

| sensor | cubo [0,1] | centrado en ±1 | plano z |
|---|---|---|---|
| S1 | (0, 1, 1) | (−1, +1, +1) | superior |
| S2 | (1, 0, 1) | (+1, −1, +1) | superior |
| S3 | (0, 0, 0) | (−1, −1, −1) | inferior |
| S4 | (1, 1, 0) | (+1, +1, −1) | inferior |

Las seis aristas miden lo mismo y el centroide cae en el origen. **De ahí sale lo que la
disposición tiene que dar**: los cuatro vectores de posición son ortogonales componente a
componente —Σ u_a·u_b sale diagonal, 4 en la traza y 0 fuera—, así que de las **cuatro**
lecturas se recuperan las **tres** componentes del gradiente con una suma con signos y sin
resolver ningún sistema:

    gx = (−b1 +b2 −b3 +b4)/4     gy = (+b1 −b2 −b3 +b4)/4     gz = (+b1 +b2 −b3 −b4)/4

El estímulo es un campo con gradiente uniforme: cada sensor lee la proyección de **su
posición** sobre la dirección del gradiente, y el barrido gira esa dirección 360° dentro del
plano X–Z (`Vtilt` a 90 la pasa al X–Y). El banco comprueba la geometría de punta a punta
reconstruyendo el ángulo a partir de las cuatro lecturas: **error máximo 0.0000° a fondo de
escala y 0.0026° en la ventana fina**, con `|gy|` en 0.5 nV — que es lo que tiene que salir
para un gradiente confinado al plano X–Z.

**La comprobación que hace que la comparación signifique algo** es `comprobar_nav2.py`:
aplana el `.subckt GRADIENT_NAV2` un nivel, funde cada `WEIGHT` con su `COMP_OUT` en el
bloque que el layout tiene de verdad, y compara ese grafo contra el escrito a mano
—externos por su papel, internos por a qué pines tocan, celdas por familia—. Está probado
a la contra con dos roturas y caza las dos:

* un nodo cambiado (`SY3r` donde iba `SZ3r`);
* **el cruce VB/VC del `WEIGHT_COMP`**, que alimenta su `VB` al pin `VC` del `WEIGHT` y al
  revés. Escribirlo «en orden» pesa mal dos cadenas y no da ningún error.

**Lo que sale.** `Vcm = 2.500000 V` clavado en los cuatro sensores, ±100.0000 mV y
±0.2500 mV de señal diferencial:

| | esquemático vs layout RC | consumo |
|---|---|---|
| fondo de escala, ΔR/R = 2 % | **7° de 360** en las salidas lógicas (98.06 %); las de peso, 14° de canto | 71.467 contra 71.414 mW |
| ventana fina, ΔR/R = 50 ppm | **0°**, con 3.1 mV de diferencia máxima en las de peso | 74.024 contra 74.027 mW |

Las doce salidas de cadena (antes de los pesos) coinciden en el **98.71 %** del barrido a
fondo de escala y en el **100 %** en la ventana fina.

**Y un hallazgo del circuito, no del banco: `ZP` y `ZN` están clavadas.** La salida de cada
bloque de peso es **analógica** —promedia cuatro niveles lógicos—, y con esta geometría `X`
e `Y` se mueven entre **1.81 y 3.04 V** y sí cruzan el punto de disparo del par de
inversores de `COMP_OUT`; `Z` se queda entre **2.18 y 2.58 V** y no lo cruza, así que `ZP`
se queda en 5 V y `ZN` en 0 durante todo el barrido, a las dos amplitudes. El banco lo dice
explícitamente en vez de dar un «100 % de acuerdo» que no significaría nada: coinciden
porque las dos versiones están igual de clavadas.

Con la disposición anterior del banco —cuatro ejes a 0/90/180/270° en un plano— **las seis
estaban clavadas**: la excursión del peso era 2.18..3.04 V y ninguna cruzaba. O sea que
cuánta información sale por esas seis patas **depende de la geometría de los sensores**, y
eso es exactamente lo que este banco sirve para medir.

## 17. Lo que queda por hacer

Lista viva, **por orden de lo que vale**. Los cinco bloques y los tres tops estan con DRC de
firma 0 y LVS que casa; el relleno de desacople ya esta dentro de `GRADIENT_NAV2`. Lo unico
abierto en verificacion son las 24 `MIMTM.8a` que ve magic y que KLayout no. Cada entrada
trae **cuanto vale**, **donde se toca** y **como se comprueba**, porque una tarea sin esas
tres cosas es un deseo.

### Lo inmediato

**0.1. Las 24 `MIMTM.8a` que ve magic en `GRADIENT_NAV2`.** Dos por cada `OPAM_LIN_flat`, y
**el bloque suelto da 222**. Son anteriores a todo lo de esta iteracion: estan en el top
pelado, en el `_decap` y en el `_filled` por igual, y **KLayout no las ve** porque su version
de la regla mide area de placa (25 µm², y la placa son 200) donde la de magic mide **ancho
de placa superior: 5 µm**. `OPAM_LIN_flat` no estuvo en la lista del DRC de magic hasta la
iteracion #37, que es por lo que no habia salido antes. Hay que mirar la placa superior del
MIM en `caps.py` y decidir si es un falso positivo del techfile o una placa de verdad
estrecha.
*Se comprueba:* `make drc-magic ARGS=OPAM_LIN_flat` a **0**, y de rebote el top.

**0.2. Los tres arreglos del analisis funcional** (`XSCHEM/TEST_TOTAL/FUNCIONALIDAD_TOP.md` y
`funcionamiento_top.pdf`, y probados en `XSCHEM_v2/`). La cadena esta bien hasta el decodificador -- entradas del top,
amplificadores, comparadores y la logica del decodificador estan correctos y medidos-- pero
el bloque de salida no: el `WEIGHT` es inversor, asi que `XP` esta alto cuando el eje NO
gana; su umbral cae entre 2 y 3 votos cuando la decision es a partir de dos; y el reparto de
sensores entre las ranuras hace que **la ranura Z no pueda ganar nunca**. Con los tres
arreglos, el acierto pasa de 25/30/0 % a **100/100/95 %**, a costa de +15 % de consumo.
Falta decidir si se llevan al diseno de verdad y, si se llevan, dibujar la referencia como
celda.
*Se comprueba:* `./run_nav2_v2.sh`.

**0.2.1. `ZP` y `ZN` estan clavadas en el diseno de hoy** (§16). La salida del peso es analogica; con la
geometria de tetraedro, `X` e `Y` se mueven 1.81..3.04 V y cruzan el punto de disparo del
par de inversores de `COMP_OUT`, pero `Z` se queda en 2.18..2.58 V y no lo cruza. No es del
banco ni del layout -- pasa igual en el esquematico -- y por eso no lo ha visto ningun LVS
ni ningun DRC. Y **depende de la disposicion de los sensores**: con cuatro ejes a
0/90/180/270 en un plano se quedaban clavadas las SEIS. Hay que decidir si el peso tiene
que sacar mas excursion, si lo que va detras tiene que ser un comparador con su referencia
en vez de un inversor, o las dos cosas.
*Se comprueba:* `./run_nav2.sh` con las seis moviendose.

**0.2.2. La caja de los sensores esta sin elegir**
(`XSCHEM/TEST_TOTAL/geometria_sensores.pdf`). Solo importa la RELACION Lxy/Lz para la
isotropia -- 1000x500 y 2000x1000 dan lo mismo -- y el TAMANO para el rango. Medido: las
fronteras angulares caen sobre `atan(Lxy/Lz)` con menos de un grado de error, y **la caja
grande satura ANTES**: el producto (gradiente maximo x semilado) sale constante. Y una
leccion del banco: **sin desajuste de sensor no hay suelo de resolucion**, porque en
simulacion los cuatro puentes son identicos y la comparacion es exacta por pequena que sea
la senal. El suelo hay que meterlo a mano para que la pregunta tenga sentido.

Y una segunda leccion del mismo banco, que corrige cifras que ya estaban escritas: **el
reparto 25/50/25 de las tablas de plano es un ARTEFACTO del barrido plano**. Con `gy` a
cero las cuatro lecturas se reducen a dos parejas antipodales y la ranura que nunca lleva
la lectura suelta del trio se lleva la mitad de los minimos. Sobre la esfera completa
**cualquier cubo da 33/33/33**, del tamano que sea. Lo que rompe la isotropia es solo la
relacion Lxy/Lz.
*Se comprueba:* `./run_nav2_geo.sh`.

**0.3. Confirmar el esquema de `lvs_config.json`.** Esta escrito con el de Efabless
(caravel / mpw-precheck), que es de donde viene ese flujo, pero **no se ha contrastado con
la plantilla del chipathon**. Los ficheros a los que apunta si estan comprobados. Y en
`info.yaml` hay dos decisiones anotadas: las nueve salidas van como `analog` porque la
lista de `io_type` no tiene un tipo de salida digital sin habilitacion, y `VSS` va
declarado aunque el anuncio diga que la masa es comun.
*Se comprueba:* contra la plantilla que publiquen.

**0.3. Limpiar el repositorio de GitHub.** No se sube **ningun `.md`, ningun `.pdf` ni
ningun guion cuyo unico proposito sea generar documentacion** (`hacer_pdf.py`,
`documento.py`, `figuras.py`, `graficas.py`, `capturar.py`). Los que ya esten subidos hay
que **borrarlos**. Se siguen manteniendo en local: esta bitacora es de trabajo, no de
publicacion.

**0.4. Los 2 776 µm² que quedaron sin rellenar** (§15.6): siete huecos pegados a
`WEIGHT_COMP` y al `DECODER`, que no sacan riel a la cota del estante vecino. Para
aprovecharlos habria que **sacarles el riel a esos dos bloques por su borde de abajo**, que
es cosa del generador de bloques, no del relleno. Vale un 11 % mas de desacople; es lo mas
barato de la lista solo si ya se va a tocar `power.py`.
*Se comprueba:* `make decap` sin ningun hueco descartado por "el macro vecino no tiene riel
a esa altura".

**0.5. El comparador de KLayout se cae con el GDS con relleno de densidad.** Ahora se lanza
aparte y se reporta, pero el `_filled` se firma solo con netgen. Merece un vistazo: si son
las nets flotantes del relleno, purgarlas antes de comparar lo arregla.
*Se comprueba:* `make lvs-klayout ARGS=GRADIENT_NAV2_FILLED` con veredicto, sea el que sea.

### Despues: lo que tiene la cifra mas grande

**1. Desbloquear los trunks en metal3 por encima de las filas — vale ~14 % del area de
bloque.** Esta escrito, medido y apagado (§13.3, iteracion #36). Son **dos** problemas
independientes y hacen falta los dos:

* **DRC (39 violaciones, 21 `M2.2a`).** La causa esta localizada: `routing._spread_stubs`
  reparte los stubs en x contando solo el **metal1**, y los tramos que suben al trunk de
  metal3 son de **metal2**, asi que se pisan entre ellos y con los straps de los
  multi-finger (pares a 0.135 µm donde la regla pide 0.28). **No** es el ancho: estrechar
  el vertical de 0.38 a 0.28 las subio a 72. Hay que meter el metal2 en las restricciones
  del reparto.
* **magic se planta.** Con metal3 sobre las filas su extraccion pasa de segundos a **mas de
  10 minutos**, su tiempo limite, y deja de dar netlists. Es independiente del DRC y hay
  que mirarlo aparte (probable interaccion con el aplanado de §14.1).

Se comprueba: `Opciones.trunks_m3 = True`, los cinco bloques a **DRC 0 y LVS limpio en las
dos herramientas**, y `COMP` en `105.88 × 25.42`. Mientras no salgan las dos cosas, se
queda apagado.

**2. Confirmar con el fabricante que la opcion de 3 kΩ/cuadro esta comprada.** Es **lo
unico abierto que afecta al silicio** y ninguna herramienta lo puede contestar (§11.0.2).
1k, 2k y 3k comparten geometria y capa; lo que los separa es una opcion de proceso. Si
saliera a 1 kΩ/cuadro, esta misma geometria da 382 kΩ en vez de 1.15 MΩ y la ganancia se va
a un tercio; rehacerla para 1 kΩ triplica el largo (~1146 µm de poly) y obliga a replantear
los pliegues. La cadena de verificacion **si** sabe comprobar el caso de 3k, asi que no
bloquea el flujo — bloquea la decision.

**3. Fusionar de verdad en multi-finger los que comparten nodo.** Hoy el abutment comparte
**difusion** pero deja dos dispositivos en la netlist, que es justo lo que hace que el LVS
siga casando sin tocar la referencia. Fusionarlos en un `nf>1` de verdad ahorra el
`end_cap` de cada uno, pero **cambia la netlist extraida**, asi que hay que decidir si la
referencia se genera igual o si se acepta la reduccion en paralelo de las herramientas.
Medir primero cuanto da en un bloque antes de escribir nada.

### Despues: mejoras acotadas del generador

**4. La altura, por el reparto de la fila N.** El ancho ya esta exprimido; el alto se lo
llevan dos canales, tres filas y dos rieles. Hoy la fila N se parte por **ancho acumulado**
y salen 6 nets cruzando de canal. Partirla minimizando **los cruces** adelgazaria el canal
B. Idea, sin medir.

**5. Correr el DRC con `--density` y `--antenna`**, hoy apagadas en el flujo de bloque. En
el top **si** se corren y las 7 reglas de densidad pasan, asi que el riesgo es bajo, pero
un bloque suelto no esta comprobado contra ellas.

**6. Codos (dog-legs) para ciclos de restriccion vertical.** `_assign_tracks` respeta las
restricciones, pero un **ciclo** (A bajo B y B bajo A) no tiene reparto posible: haria
falta partir un trunk en dos pistas unidas por un tramo vertical. Hoy ese caso se coloca
solo en su pista y **avisa**. En estas netlists no hay ciclos; con logica mas enredada
aparecera.

### Limitaciones de herramienta, no del layout

**7. magic no resuelve el terminal de placa superior del MIM.** Sale en un nodo interno
(`m4_…#`) en vez de en su net. **El layout esta bien**: KLayout, que tiene reglas de
conexion propias para MIM, da `Netlists match` con los dos condensadores en sus nets.
Afecta **solo a las netlists de parasitos**. Ver §11.1.

**8. netgen avisa de propiedades en los MIM.** Choque de convenios `A`/`P` contra `W`/`L`
contra `c_width`/`c_length`; **los numeros cuadran**. Silenciarlo con un setup propio
taparia tambien un desajuste de tamano de verdad, asi que se deja el aviso.

### Del circuito, no del layout (Parte IV del PDF)

**9. Energia de conmutacion con flancos realistas.** Lo que dan hoy `DECODER` y `WEIGHT`
esta dominado por la corriente de cruce durante flancos de 1 ms.

**10. PSRR, CMRR y ruido en esquinas.** Estan medidos en tipico a 27 °C; la ganancia y la
INL si estan barridas en ff/ss a −40, 27 y 125.

**11. Decidir sobre el margen de desapareamiento.** 2.6 sigma es una decision, no un
defecto: si medio por ciento de piezas con el offset invertido es aceptable, no hay nada
que hacer.

---



---

## Resistencias sumadoras en una celda: dos limites del generador

Intentando llevar a layout `GRADIENT_NAV3` (el navegador que compara componentes
del gradiente en vez de lecturas crudas) hizo falta una celda con **resistencias
de suma**, y aparecieron tres cosas que no estaban documentadas.

**1. `r_length` es el largo de CADA TRAMO, no el total.** La resistencia total es
`s x r_length x hoja / r_width`. En `OPAM_LIN_flat` son `L=76.45u, s=5`, o sea
1.147 Mohm y no 229 kohm. Poner el total en `L` da una resistencia `s` veces mas
grande y un serpentin que no cabe: *"el serpentin mide 169.5 um de ancho y la
celda 1.0: hacen falta mas pliegues"*.

**2. Una celda SOLO de resistencias no se puede generar.** El ancho de la celda
sale de las filas de transistores. Sin transistores nace con **1.0 um** y ningun
serpentin cabe. La resistencia tiene que ir dentro de una celda que ya tenga
filas -- que ademas es mejor sitio, porque el canal de serpentines ya existe.

**3. Cada terminal de resistencia necesita una net que LLEGUE A LA FILA.** Los
carriles de metal2 se construyen desde las filas de transistores; una net que
solo toca un terminal de resistencia se queda sin carril y falla con *"trunk de
0.00 um en 0 tramo(s)"*, que el mensaje de mas arriba traduce como *"los
condensadores y los puertos ya lo han ocupado"* -- y eso es una conjetura del
mensaje, no el diagnostico. Por eso la unica resistencia de `OPAM_LIN_flat`
funciona: sus dos extremos (`G_OUT_P` y `OUT`) tocan transistores.

Se resuelve colgando de cada entrada un **condensador MOS** (`W=L=2u`, ~6 fF, 3 ns
de constante de tiempo con los 500 kohm de fuente: invisible). Le da a la net
presencia en la fila y el terminal ya aterriza. Con eso `OPAM_SUMA` coloca sus
cinco serpentines sin un solo error: 57 MOSFETs, 87.64 x 81.29 um.

**Lo que sigue abierto.** Con cinco puertos de senal en vez de tres, los plafones
de acceso de metal3 chocan entre si y con el canal de serpentines: **7
violaciones** (`M3.2a` x4, `M2.2a` x2, `V2.2a` x1) y un corto que el LVS ve como
`A1/A2/B1/B2/OUT` colapsados en un nodo. `OPAM_LIN_flat` (3 puertos, canal de 48
um) sale limpio; `OPAM_SUMA` (5 puertos, canal de 81 um) no. Arreglarlo es
reservar la banda de puertos frente al canal -- el mecanismo `BANDA_TERMINAL` /
`reservado` que `resistors.py` ya documenta, hoy dimensionado para UN serpentin.

`DECODER_MAX`, la otra celda nueva, si cierra: **DRC 0** y netgen **`Circuits
match uniquely`**, 31.88 x 14.48 um.
