# `XSCHEM_v2` — el navegador con los arreglos del análisis funcional

Aquí se prueban los arreglos que salen de `XSCHEM/TEST_TOTAL/FUNCIONALIDAD_TOP.md`
**sin tocar el diseño de hoy**. `XSCHEM/` se queda exactamente como está: su GDS, su DRC y
sus dos LVS siguen siendo válidos.

> **Este `v2` no tiene nada que ver con `layouts_v2` ni con los `*_V2_pex_rc.spice`.** Esos
> son la segunda versión del **generador de layout**, y son ortogonales a esto. Aquí `v2`
> quiere decir «segunda versión del circuito del navegador».

La celda se llama `GRADIENT_NAV2_V2` y no `GRADIENT_NAV2` por una razón práctica: el banco
comparativo instancia las dos a la vez, y dos `.subckt` con el mismo nombre no pueden
convivir en una netlist.

## Qué cambia respecto a `XSCHEM/GRADIENT_NAV2.sch`

**1. El reparto de sensores entre las ranuras X/Y/Z de las cuatro cadenas.** Los cuatro
tríos son los mismos —cada cadena sigue omitiendo un sensor—; lo que cambia es el orden
dentro de dos de ellos:

| | hoy | aquí |
|---|---|---|
| x1 | S1 S2 S3 | S1 S2 S3 |
| x2 | S1 S2 S4 | **S4 S1 S2** |
| x3 | S3 S4 S1 | S3 S4 S1 |
| x4 | S3 S4 S2 | **S2 S3 S4** |

Con el de hoy, la ranura X ve solo dos sensores distintos y la Z los cuatro, así que los
votos de Z nunca se juntan y **Z no puede ganar nunca** (medido: gana X 50 % / Y 50 % /
Z 0 %, en los dos planos de barrido). Con este reparto cada ranura ve los cuatro una vez y
sale 25 / 50 / 25.

**2. La decisión de salida.** Fuera las tres `COMP_OUT`; en su lugar, el bloque de código
`DECISION`: un comparador `COMP` por eje contra una referencia sacada de **dos réplicas del
propio bloque de pesos**, una cargada con 1 voto y otra con 2, promediadas. Eso arregla las
dos cosas de golpe:

* la polaridad —`XP` pasa a estar alto cuando el eje **gana**, que es lo que dice su
  nombre—, y
* el umbral —la decisión pasa a estar entre 1 y 2 votos en vez de entre 2 y 3—.

Va como bloque de código **a propósito**: instancia celdas que ya existen (`WEIGHT`, `COMP`,
`invertor`), así que se puede medir la idea antes de dibujarla. Si los números convencen se
dibuja como celda y las dos resistencias del promedio pasan a ser `ppolyf` de verdad.

**Por qué no un inversor sesgado**, que sería más barato: se midió. Con el PMOS a 3.0/0.5 el
punto de disparo cae en 2.365 V a 27 °C y 5 V, justo en medio de la ventana útil
(2.178–2.579 V). Pero es un divisor de relación y **sigue a VDD**: 2.110 V a 4.5 V y
2.620 V a 5.5 V. Con VDD ±10 % se sale por los dos lados. La temperatura da igual (±0.02 V).

## Lo que NO está aquí

* **La variante «máximo»** (señalar el sensor de lectura mayor en vez de menor, cruzando
  `INP`/`INN` en los tres `COMP` de `GRADIENT2`). Es una decisión de sistema, no un fallo, y
  está sin decidir. Ver §3 del documento.
* **Layout.** Esto es esquemático y simulación. Llevarlo al flujo de OpenROAD es un paso
  aparte.

## Cómo se mira

```bash
cd ../XSCHEM/TEST_TOTAL && ./run_nav2_v2.sh     # el de hoy contra este, mismo estimulo
```
