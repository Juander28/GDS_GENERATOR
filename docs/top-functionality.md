# `GRADIENT_NAV2`: qué hace cada bloque, y dónde hay que cruzar positivo y negativo

Determinación funcional del top, con medidas. **Ninguna cifra de aquí está tecleada a
mano**: todas salen de `analisis_top.py`, que las recalcula desde los CSV de los dos bancos
y desde el netlist. Si un banco se vuelve a correr y algo cambia, el guion lo canta.

```bash
cd XSCHEM/TEST_TOTAL
python3 analisis_top.py          # todas las cifras, por consola
./medir_disparo.sh               # el punto de disparo del inversor, contra VDD y temperatura
python3 figuras_top.py           # las figuras, con los rotulos en ingles
python3 doc_top/hacer_pdf_top.py # -> funcionamiento_top.pdf
```

**`funcionamiento_top.pdf`** es este mismo analisis con las graficas y, en cada punto de la
cadena, una tabla de *esperado / medido / cuadra*.

**`geometria_sensores.pdf`** contesta la pregunta de al lado: **qué caja de sensores
elegir**. La isotropía la fija la relación Lxy/Lz y la resolución la fija el tamaño — pero
no como uno esperaría, porque la ventana útil se estrecha al agrandar la caja. Se genera con
`./run_nav2_geo.sh` + `figuras_geo.py` + `doc_geo/hacer_pdf_geo.py`.

De dónde sale cada cosa:

| fuente | qué aporta |
|---|---|
| `datos/ancho.csv` | banco del gradiente. Es el **único** que guarda las señales internas de la cadena (`SX/SY/SZ`, `XY/XZ/YZ`), que es lo que permite medir la polaridad de cada etapa por separado |
| `datos_nav2/ancho_nav2.csv` | banco del navegador con la geometría de tetraedro |
| `XSCHEM/simulation/GRADIENT_NAV2.sch/GRADIENT_NAV2.spice` | el cableado y la lógica de verdad |

---

## 1. La disposición de los sensores: es correcta

Cuatro **posiciones**, no cuatro ejes. Vértices de un **tetraedro regular inscrito en un
cubo**: `S3` y `S4` en esquinas opuestas del plano z inferior, `S1` y `S2` en las dos
contrarias del superior.

| sensor | x | y | z | plano z |
|---|---|---|---|---|
| S1 | −1 | +1 | +1 | superior |
| S2 | +1 | −1 | +1 | superior |
| S3 | −1 | −1 | −1 | inferior |
| S4 | +1 | +1 | −1 | inferior |

Las seis aristas miden **2.8284** y el centroide cae en el origen: es regular. Y lo que la
hace útil: `Σ u_a·u_b` sale **diag(4, 4, 4) con 0 fuera de la diagonal**, o sea que los tres
ejes se recuperan por separado, de las **cuatro** lecturas a las **tres** componentes, con
una suma con signos y sin resolver ningún sistema:

    gx = (−b1 +b2 −b3 +b4)/4      gy = (+b1 −b2 −b3 +b4)/4      gz = (+b1 +b2 −b3 −b4)/4

Comprobado de punta a punta con el gradiente girando en el plano X–Z: `|gx|` y `|gz|` llegan
a 14.14 mV, **`|gy|` se queda en 0.0000 nV** —que es lo que tiene que salir— y el ángulo
reconstruido sigue al pedido con **0.0071° de error máximo**.

**Veredicto: la foto es correcta y la geometría hace lo que se le pide.** Lo que falla está
más abajo, en el cableado del top y en el bloque de salida.

---

## 2. La cadena, etapa por etapa

Medido sobre `G2` (esquemático con `OPAM_LIN`, que es la cadena del navegador) y `G4` (su
layout extraído con RC).

| etapa | qué hace, medido | ¿cruzar P y N? |
|---|---|---|
| Puente | `V(SkP) − V(SkN) = VEXC·b`; Vcm clavado en 2.500000 V, independiente de la señal | **no** |
| Entradas del top | `SXP←S1P`, `SXN←S1N`… las cuatro cadenas, cada P a su P | **no** |
| Amplificador `OPAM_LIN` | **no inversor**: correlación salida/señal **+0.942**; excursión 0.012–4.973 V, el rail entero | **no** |
| Comparadores `COMP` | alto ⟺ `INP > INN`, en el **99.6 %** del barrido (99.3 % en el layout) | **no** |
| `DECODER` | selector de **mínimo**, correcto y completo: una sola salida alta el **100 %** del tiempo | decisión, no fallo |
| `WEIGHT` | contador analógico de votos, **inversor** | **sí** |
| `COMP_OUT` | tres inversores; dispara **entre 2 y 3 votos** | **sí** |

### La lógica del decodificador, leída del netlist

Puerta a puerta (`andGate` = AND, `invertor` = NOT, la celda `Z` = NOR):

    X = XY · XZ    = (SY>SX)·(SZ>SX)    →  SX es el menor
    Y = YZ · ¬XY   = (SZ>SY)·(SX≥SY)    →  SY es el menor
    Z = ¬XZ · ¬YZ  = (SX≥SZ)·(SY≥SZ)    →  SZ es el menor

Las tres fórmulas aciertan el **100 %** del barrido contra la simulación. **El decodificador
no tiene ningún error interno**: es exactamente un selector de mínimo de tres, y las tres
salidas son mutuamente excluyentes y cubren todos los casos.

---

## 3. Mínimo o máximo: es una decisión de especificación

La cadena señala el sensor con la lectura **menor**: 98.6 % en el esquemático y 97.8 % en el
layout. El máximo, **0.0 %** en los dos.

Con el tetraedro, mínimo y máximo son **imágenes especulares**: la misma información con la
etiqueta contraria. El mínimo es el sensor «aguas arriba» del gradiente, el máximo el de
«aguas abajo». Cuál de los dos se quiere es cosa del sistema, no del circuito.

**Si se quisiera el máximo**, se arregla en un solo sitio: cruzar `INP`/`INN` en los **tres
`COMP` de dentro de `GRADIENT2`**. Eso voltea los tres bits de forma consistente, porque
niega las tres entradas del decodificador a la vez:

    X = ¬XY·¬XZ = (SX>SY)·(SX>SZ)   →  SX es el MAYOR      (y las otras dos, igual)

No hay que tocar ni los amplificadores ni las entradas del top: cruzarlos ahí haría lo mismo
pero además cambiaría el signo del gradiente reconstruido, que sí se usa.

Está preparado en `XSCHEM_v2/COMBINATION/GRADIENT2_MAX.sch` y **el top no lo instancia**.

---

## 4. Hallazgo 1: `XP` y `XN` están cambiados respecto a su nombre

El `WEIGHT` es un **contador analógico de votos, e inversor**. Medido:

| votos | tensión del peso | `P` alto | `N` alto |
|---|---|---|---|
| 0 | 3.035 V | 100 % | 0 % |
| 1 | 2.579 V | 100 % | 0 % |
| 2 | 2.178 V | 100 % | 0 % |
| 3 | 1.814 V | **0 %** | **100 %** |

Correlación votos/tensión **−0.999**: escalones iguales de ~0.4 V, monótonos, hacia abajo.
Como `COMP_OUT` es un buffer **no** inversor, la salida que se llama `P` está alta cuando el
eje **no** gana, y la que se llama `N` cuando sí.

**Arreglo:** intercambiar `XP` y `XN` en la instancia de `COMP_OUT` del top. Es cableado; no
cambia ninguna celda y no toca el layout de ningún bloque.

---

## 5. Hallazgo 2: el umbral de decisión está mal

El punto de disparo del inversor de `COMP_OUT` cae **entre 2 y 3 votos** (~2.0 V). Acierto
de cada umbral contra «este eje es el más votado»:

| eje | ≥1 | ≥2 | ≥3 *(el de hoy)* | ≥4 | dispara hoy | debería |
|---|---|---|---|---|---|---|
| X | 100.0 % | **100.0 %** | 74.8 % | 52.3 % | 22.5 % | **47.7 %** |
| Y | 100.0 % | **100.0 %** | 70.2 % | 47.7 % | 22.5 % | **52.3 %** |
| Z | 0.0 % | 44.9 % | 100.0 % | 100.0 % | 0.0 % | 0.0 % |

X e Y disparan **menos de la mitad** de lo que deberían. El umbral correcto es **≥2 votos**,
o sea un punto de disparo en torno a **2.35 V**, entre los escalones de 2.578 y 2.178 V.

El 100 % de Z es vacío: acierta porque nunca dispara, y nunca dispara porque **nunca es el
más votado**. Eso es el hallazgo 3.

> **Un inversor sesgado es un mal discriminador aquí.** Los escalones del peso son de
> 0.4 V y el punto de disparo de un inversor se mueve con proceso, temperatura y VDD.
> `INV_1` es `pfet_05v0` W=1.83/L=0.5 contra `nfet_05v0` W=1.32/L=0.6 — y son dispositivos
> de **5 V** en un raíl de 5 V, mientras el resto de la cadena es de 6 V. Lo robusto sería
> un comparador contra una referencia sacada de una **réplica del propio `WEIGHT`** cargada
> con 1.5 votos: así la referencia se mueve con el proceso igual que la señal y el margen no
> depende de un punto de disparo absoluto.

---

## 6. Hallazgo 3: por qué `Z` no puede ganar — y por qué su propio `WEIGHT` no lo arregla

**La ranura Z nunca es la más votada.** Medido con el cableado de hoy, en los dos planos de
barrido: gana **X 50 % / Y 50 % / Z 0 %**. Z llega a 2 votos como mucho en el plano X–Z y a
1 en el X–Y, y el umbral que le haría falta sería **≥4**.

No es del umbral ni del bloque de pesos. Es del **reparto de sensores entre las ranuras**:

    ranura X:  x1=S1  x2=S1  x3=S3  x4=S3     ← solo DOS sensores distintos
    ranura Y:  x1=S2  x2=S2  x3=S4  x4=S4     ← solo DOS
    ranura Z:  x1=S3  x2=S4  x3=S1  x4=S2     ← los CUATRO

Cada cadena elige el mínimo de su trío. Un sensor que esté en la **misma ranura de dos
cadenas** se lleva dos votos de golpe; los votos de la ranura que ve los cuatro sensores se
reparten y no se juntan nunca. Por eso X e Y llegan a 3 y Z no pasa de 2.

**Un `WEIGHT` propio para Z no lo arregla**: por muy bajo que se le ponga el umbral, sigue
sin ser el más votado — bajarlo a ≥1 le haría disparar el 100 % del barrido, que es tan
inútil como el 0 % de ahora.

### Lo que sí lo arregla: cambiar el orden dentro de cada trío

Los cuatro tríos ya son los cuatro subconjuntos de tres —cada cadena omite un sensor, y eso
está bien—. Lo que falla es a qué ranura va cada uno.

De las **24** asignaciones en que cada ranura ve los cuatro sensores una vez, **solo 6 dejan
viva a las tres ranuras en los dos planos**: que cada ranura vea los cuatro es necesario,
pero no suficiente. La mejor:

    G1 (X, Y, Z) = S1 S2 S3
    G2 (X, Y, Z) = S4 S1 S2
    G3 (X, Y, Z) = S3 S4 S1
    G4 (X, Y, Z) = S2 S3 S4

| | gana X | gana Y | gana Z |
|---|---|---|---|
| hoy, plano X–Z | 50.0 % | 50.0 % | **0.0 %** |
| hoy, plano X–Y | 50.0 % | 50.0 % | **0.0 %** |
| propuesta, los dos planos | 25.3 % | 49.7 % | **25.0 %** |
| propuesta, **esfera completa** | 33.3 % | 33.4 % | **33.3 %** |

> **Ojo con las tres primeras filas: son de un barrido de PLANO, y ahí el 25/50/25 es un
> artefacto.** Con la componente `gy` a cero las cuatro lecturas se reducen a dos parejas
> antipodales (`b4 = −b1`, `b3 = −b2`), y la ranura que nunca lleva la lectura «suelta» del
> trío —que resulta ser siempre la Y— tiene una lectura negativa garantizada y se lleva la
> mitad de los mínimos. Sobre la esfera completa sale **33/33/33**. Está desarrollado en
> §5 de `geometria_sensores.pdf`.

La más floja pasa del **0 % al 25 %** en plano y a **33 %** sobre la esfera. Es cableado del
top: las celdas no cambian.

---

## 7. Qué **no** está roto

Esto también es un resultado, y conviene tenerlo escrito para no volver a buscar ahí:

* **Los puentes**: Vcm clavado en VEXC/2, independiente de la señal.
* **Las entradas del top**: cada P a su P y cada N a su N, en las cuatro cadenas.
* **Los amplificadores**: no inversores, y con la excursión entera del raíl.
* **Los comparadores**: altos cuando `INP > INN`, en el esquemático y en el layout.
* **La lógica del decodificador**: selector de mínimo correcto, completo y excluyente.
* **El bloque de pesos, como contador**: monótono, con escalones iguales de 0.4 V.

## 8. Resumen de los arreglos

| # | qué | dónde | coste |
|---|---|---|---|
| 1 | cruzar `XP`↔`XN` | cableado del top | ninguno: no cambia ninguna celda |
| 2 | reparto de sensores entre ranuras | cableado del top | ninguno: no cambia ninguna celda |
| 3 | umbral a ~2.35 V | `COMP_OUT` | celda nueva; mejor un comparador con réplica que un inversor sesgado |
| — | mínimo → máximo | los tres `COMP` de `GRADIENT2` | solo si el sistema lo pide; hoy no es un fallo |

Los tres primeros están puestos en `XSCHEM_v2/`, sin tocar el diseño de hoy. El 1 y el 3 se
arreglan de una vez: el comparador se cablea con la polaridad buena y ya no hace falta cruzar
nada.

---

## 9. Medido: `XSCHEM_v2` contra el de hoy, mismo estímulo

`./run_nav2_v2.sh` cuelga los dos navegadores de los **mismos ocho nodos de sensor**, cada
uno con su fuente. La cifra es **cuánto acierta cada salida `P` la pregunta «¿gana este
eje?»**, con el recuento de votos de sus propias cuatro cadenas como respuesta correcta:

| eje | hoy | `XSCHEM_v2` |
|---|---|---|
| X | 25.2 % | **100.0 %** |
| Y | 29.8 % | **100.0 %** |
| Z | **0.0 %** — nunca dispara | **95.1 %** (99.6 % en la ventana fina) |

La referencia del comparador se queda en **2.3785 V**, justo entre los escalones de 2.178 y
2.579 V, y **no se mueve en todo el barrido**. `Z` pasa de estar clavada a disparar el
32.3 % del barrido cuando le toca el 27.5 %.

Lo que queda del 95.1 % de `Z` es el comparador resolviendo empates: en la ventana fina, con
los escalones mejor separados, sube al 99.6 %.

**El precio.** El de hoy consume 74.024 mW y el de v2, **85.077 mW**: +15 %. Son las dos
réplicas del bloque de pesos, que están siempre encendidas, y los tres comparadores. Si eso
molesta, las réplicas se pueden compartir mejor —una sola referencia para los tres ejes ya lo
está— o escalarlas a menos corriente, que es exactamente lo que una réplica permite hacer sin
perder el seguimiento con el proceso.
