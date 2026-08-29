# OpenROAD collateral

> **Coming to this cold? Read `../HANDOFF.md` first.** It carries the state of
> every block as of 2026-08-29, the one thing to do next, and every fact in this
> flow that cost a build to learn. This file is the long logbook underneath it.


Everything OpenROAD needs to assemble the analog blocks of this project into the
top level, `GRADIENT_NAV`. Nothing here is a source: it is all generated from the
layouts and the xschem netlist, and it is regenerated with one command.

## The full process

From nothing to submission file, in order. Each step depends on the previous one.

```bash
# 0. The blocks, if the schematics changed (outside this folder)
cd /foss/designs/zotnetic_layout
for B in COMP OPAM DECODER WEIGHT_COMP; do
  env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python build_block.py $B
done

# 1. The whole top: verilog -> collateral -> floorplan -> route -> GDS -> fill
cd /foss/designs/a_zonetic2026/openroad
make top

# 2. Verification. The three check DIFFERENT things; they are not opinions on the same.
make drc          # KLayout, deck de firma: FEOL/BEOL/conectividad
make drc-density  # KLayout, reglas de densidad: `make drc` NO las corre
make drc-magic    # magic: includes the `DPF.*` fill rules KLayout does not check
make lvs          # netgen sobre la extraccion de magic
make lvs-klayout  # segunda opinion: extraccion y comparador de KLayout
python3 scripts/check_connectivity.py   # 55/55 conectadas y 0 cortos

# 3. And the question to ask before believing a "clean":
#    would this tool notice if the chip were wrong?
make probar       # breaks the layout on purpose and checks that it fires
```

o paso a paso:

```bash
make verilog      # xschem netlist -> structural + flat Verilog
make collateral   # layouts -> LEF / Liberty / black-box Verilog
make check        # load it all in OpenROAD and list the macros
make floorplan    # place the macros, build the power grid, write the DEF
make route        # global + detailed routing
make gds          # DEF -> GDS, with the real layout inside every macro
make fill         # density fill -> out/GRADIENT_NAV_filled.gds
make lvs-ref      # reference netlist for the external chipathon LVS
```

**Cual es el entregable.** `out/GRADIENT_NAV.gds` es el de trabajo: es el que leen
DRC, LVS and `check_connectivity.py` read it, and it is the one to look at when
something fails. The submission one is **`out/GRADIENT_NAV_filled.gds`**, the
densidad encima.

**If the top DRC is not clean first time**, that is not unusual: the DRC-driven
DRC necesita un par de vueltas (ver mas abajo). `out/drc_blockages.txt` es
cumulative and already ships with the 11 zones needed; if deleted, it has to be
rehacer las vueltas.

    python3 scripts/drc_blockages.py   # anade lo de la ultima tanda de DRC
    make top && make drc               # y otra vuelta

## What is here

| Path | What it is | Generated? |
|---|---|---|
| `gds/` | relative symlinks to `../Layouts/*/…gds` | links, nothing was moved |
| `lef/` | abstract LEF: outline, pins, obstructions | yes, by magic |
| `lib/` | black-box Liberty (pins only, no timing arcs) | yes |
| `verilog/<MACRO>.v` | black-box module declarations, for yosys | yes |
| `verilog/GRADIENT_NAV.v` | structural Verilog, full hierarchy | yes |
| `verilog/top_macros.v` | **the design OpenROAD reads**: flat, macros only | yes |
| `verilog/top.v` | the hand-written template from before there was a netlist | by hand, unused |
| `constraints/top.sdc` | placeholder constraints (no clock yet) | by hand |
| `scripts/` | the generators and the OpenROAD scripts | by hand |
| `out/GRADIENT_NAV.gds` | the top, **working file**: read by DRC, LVS and connectivity | yes |
| `out/GRADIENT_NAV_filled.gds` | the top with density fill, **the one submitted** | yes |
| `out/GRADIENT_NAV_lvs.spice` | reference netlist **for the external LVS** of the chipathon | yes, `make lvs-ref` |
| `out/drc_blockages.txt` | zones forbidden to the router, from the DRC-driven loop | yes, cumulative |

## The blocks

| Macro | Size | Pins | Status |
|---|---|---|---|
| `COMP` | 104.28 × 31.46 µm | `VDD INN OUT INP VSS` | DRC 0, LVS matches, 2 MIM |
| `OPAM` | 88.27 × 31.46 µm | `VDD INN OUT INP VSS` | DRC 0, LVS matches, 2 MIM, `M43` girado y a caballo |
| `WEIGHT_COMP` | 37.17 × 25.00 µm | `VDD VSS VA VB VC VD WE OUT OUT_N` | DRC 0, LVS matches |
| `DECODER` | 37.89 × 15.84 µm | `VDD XY XZ X Y YZ Z VSS` | DRC 0, LVS matches |

**`M43` del OPAM va aparte.** Es un `pfet_06v0` de `L=20u W=0.7u`; girado 90° mide
4.46 × 22.96 µm, y dentro de la fila P la estiraba entera a 22.96 cuando el resto
its devices are 11.96 -- the block ended up 43.12 tall. Now it is placed
**to the far right, straddling both rows**, which is where its height fits into
what N + channel + P already occupy: **87.44 x 43.12 -> 88.27 x 31.46**,
27 % less area, and OPAM stops being the tallest block on the chip.

What needs care with a PFET there is the well. It reaches down to the N row, so
it is drawn **in an L**, as one piece with the P row well (two separate wells
would need 1.7 um by `NW.2b_MV`), and its strip is excluded from the p+ tap
strip -- a tap there would be pplus inside the nwell, which also shorts VGND to
the VDD well. And since it is 23 um tall, the n+ tap strip below VPWR does not
reach its bottom end (`DF.13_MV` asks for a tap within 15 um), so it carries a
**column of taps** on its right.

The terminals needed nothing new: the rotated wrapper's side lanes already run
its full height, so the router's stub extends them to the channel trunk, which
crosses it halfway up.

Each block **brings its ports up to Metal3**: the rails with a full-width bar
and each signal port with its own over its trunk
(`zotnetic_layout/coil_layout/power.py`). Sin eso, un pin de señal se queda en
Metal1/Metal2 surrounded by the block's own routing and the top router cannot
drop a via without touching the neighbour: 43 `Cut Short` in detailed routing.

The top is **31 macros**: 12 `OPAM`, 12 `COMP`, 4 `DECODER`, 3 `WEIGHT_COMP`.

## The top

| | |
|---|---|
| Die | 371.70 × 408.52 µm, 151 847 µm², proporción **1.099** |
| Macro area | 77 880 µm², **57 %** de utilización |
| Arrangement | shelf packing (FFDH), 9 shelves; eight of them are 31.46 because `OPAM` and `COMP` are now equally tall, and each OPAM shelf picks up a `WEIGHT_COMP` as a bonus |
| Power | Metal4 vertical over the blocks, Metal5 horizontal in the channels, down to each block Metal3 bar. **31 of 31 tied to both nets** |
| Signal | 53 nets, **100 % ruteadas**, `detailed_route` con **0 violaciones** |
| Output | `out/GRADIENT_NAV.def`, `..._routed.def`, `.gds`, `.png` |

Before all this the die was 495.12 x 390.58 (193,385 um2, aspect 1.27) at
51 %: **13 % less area, squarer and denser**. What was wasted was the column
grid, which forced every column to be as wide as its widest macro -- each OPAM
row (87.44) threw away 16.84 um inside a column
de 104.28, doce veces.

Rows and columns are sized **per row and per column**, not once from the tallest
macro. A single pitch left the 15.84 µm `DECODER` floating in the middle of a
43.46 µm cell, too far from the channel for anything to reach it.

A macro narrower than its column is **shifted right onto the column's widest
Metal4-free band**, because that is where the power straps come down. Left flush
against the column edge, the `DECODER` and the `WEIGHT_COMP` sat under the MIM
plates of `OPAM` and `COMP`, which block Metal4 exactly there, and pdngen aborted
with `PDN-0232` on all four DECODERs.

## How the power gets in

Each block brings `VDD` and `VSS` up from its Metal1 rail to a **full-width
Metal3 bar** over that rail (`zotnetic_layout/coil_layout/power.py`, run after
routing because the vias need a gap in Metal2 and there is no gap to find until
the router has finished). That bar is the landing pad.

The top then runs **Metal4 vertically over the blocks** — not down the channels,
which was the earlier attempt and could never work, because a stripe in a channel
never crosses a pin. Where Metal4 may go is read from the LEF obstructions of
each column's macros, since the MIM plates block it across the middle of `COMP`
and `OPAM` and the free bands are not the same in the two. Metal5 stays in the
row channels and only has to meet Metal4.

All 31 macros end up tied to both nets: 67 via3 per net.

Two traps worth remembering:

- pdngen reports a block whose grid came out empty (`PDN-0232`) and then aborts
  the whole run (`PDN-0233`). It is not a warning you can ignore.
- `PDN-0231 <inst> is not connected to any power/ground nets` is about the
  **netlist**, not the geometry. That is how the floating supplies on the twelve
  OPAMs surfaced: in `COMBINATION/GRADIENT.sch` the `VDD`/`VSS` labels of the
  three OPAM instances sat 20 units to the left of the pins and never touched
  them, so the netlist gave them `net4`…`net9` instead. Twelve op-amps with no
  supply, and nothing else in the flow had complained.

## Verification

```bash
make drc         # KLayout, el deck de firma: cuatro bloques + top
make fill        # relleno de densidad -> out/GRADIENT_NAV_filled.gds
make drc-density # the density rules, which `make drc` does NOT run
make drc-magic   # magic -- NOT a second opinion: it brings the `DPF.*` fill
                 # rules KLayout does not check, and lacks the density ones
make lvs         # netgen sobre la extracción de magic
make lvs-klayout # el deck de firma, también sobre el top
make check-all   # drc + drc-magic + drc-density + lvs
```

Estado a día de hoy:

| | KLayout DRC | densidad | KLayout LVS | magic DRC | netgen LVS |
|---|---|---|---|---|---|
| `COMP` | limpio | n/a (1) | match | limpio | **match** |
| `OPAM` | limpio | n/a (1) | match | limpio | **match** |
| `WEIGHT_COMP` | limpio | n/a (1) | match | limpio | **match** |
| `DECODER` | limpio | n/a (1) | match | limpio | **match** |
| `GRADIENT_NAV` | **limpio** | no cumple | **match** (3) | **limpio** | **match uniquely** |
| `GRADIENT_NAV_filled` | **limpio** | **limpio** | pendiente (2) | **limpio** | pendiente (2) |

(1) Density is measured **over the whole die**, so on a loose 3,000 um2 block it
means nothing. The only place it makes sense is the top.

(2) The fill shows up in extraction as floating metal -- the decks add the dummy
to the physical layer -- so LVS on the filled file has to be run again. It
changes nothing above, but it is unverified.

(3) **The PDK deck's verdict is no good for the top; KLayout's comparer is.**
The deck says `Netlists don't match` -- but it also fails comparing the layout
against **its own extraction** (72 unmatched nets), and there is nothing a
layout can do wrong there. The cause is that it calls `compare` with the default
limits (`max_depth` 8, `max_branch_complexity` 500), not enough for a
circuito plano de 1707 dispositivos con doce rebanadas analogicas iguales, y no
exposes them on the command line. With the **same KLayout comparer** driven
a mano (`max_depth=30`, `max_branch_complexity=10000`) el emparejamiento cierra
entero: **840 nets emparejadas, 0 nets, 0 dispositivos y 0 pines sin pareja**. Eso
that is what `lvs_klayout.py::comparar` does, and it is the verdict in the table.

Ese camino comprueba la **topologia**, no los **tamanos**: el lector SPICE
KLayout's generic reader cannot match the parameters the deck writes (`L=20U
W=0.7U AS=.. AD=.. PS=..`) against the reference ones (`W=.. L=..` in metres),
and with them enabled it matches not one device. Sizes are netgen's job, which
does compare them. **The two opinions together cover both; neither alone does.**

And one more check, which is neither DRC nor LVS but answers the question
neither of them answers -- is the routing actually connected?

```bash
python3 scripts/check_connectivity.py    # 55/55 conectadas, 0 cortos, 19 puertos
```

### How to check it yourself

The above are commands that return "clean". A "clean" is only worth something
sabes **qué habría cantado esa herramienta si el chip estuviera mal**, y en este
proyecto eso no es filosofía: `check_connectivity.py` dio «55/55» durante días
no matter what, because it used `net.name` as net identity and that field
está vacío en casi todas. No fallaba: mentía.

**1. That the checks fail when they should.** This breaks the layout on
propósito, de tres formas conocidas, y mira quién se entera:

```bash
make probar        # corto y abierto, ~1 min
make probar-drc    # además las dos pruebas de DRC, ~15 min
```

(Separate targets and not an option: `make probar --con-drc` **does not work**,
make thinks `--con-drc` is one of its own options and aborts.)

What comes out today, as is:

| rotura metida a mano | quién la ve |
|---|---|
| Metal3 uniendo `X1` y `XP`, 2.9 µm (**corto**) | `check_connectivity`: **1 corto** |
| 7 via2 borradas alrededor de `X1` (**abierto**) | `check_connectivity`: **1 abierta** |
| Metal3 a 0.10 µm de otro Metal3, en COMP | el DRC de KLayout: **4 × `M3.2a`** |
| DRC **on the GDS with the short** | **0 violations across 63 rule files** |

La última fila es la que más dice: **un corto no viola ninguna regla de DRC**. Dos
overlapping shapes on the same layer merge into one polygon, and where metal is
missing there is nothing to measure. That is why "DRC clean" says nothing about
whether the chip is properly connected, and why all three checks are needed.

And a warning this very script earned: **its first version passed the DRC test
when DRC had not even started** (`klayout` was not on
en el PATH; contaba violaciones sobre cero ficheros y salía cero). Se cazó a sí
itself. `drc_klayout.py` had the same hole and now both abort if they do not
aparece ni un `.lyrdb`.

**2. Without trusting the scripts here.** The same checks, calling the PDK
directly -- if these agree, nothing above was invented:

```bash
cd /foss/designs/a_zonetic2026/openroad

# Sign-off DRC on the file being submitted
python3 /foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py \
  --path=$PWD/out/GRADIENT_NAV_filled.gds --variant=D \
  --topcell=GRADIENT_NAV --run_dir=/tmp/midrc --mp=4

# ...and count violations: it must give 0
grep -c "<item>" /tmp/midrc/*.lyrdb | awk -F: '{s+=$2} END {print s" violaciones"}'

# LVS with netgen (engine and extraction independent of KLayout)
python3 scripts/lvs_netgen.py GRADIENT_NAV
grep "Final result" out/lvs_netgen_GRADIENT_NAV.rpt
```

**3. Mirándolo.** El GDS se abre en KLayout y las violaciones se cargan encima:

```bash
klayout out/GRADIENT_NAV_filled.gds -m out/drc_GRADIENT_NAV_FILLED/*.lyrdb
```

**4. What each one checks, so as not to expect the impossible.**

| | topología | tamaños (W/L) | reglas de dibujo | densidad | relleno de poly |
|---|---|---|---|---|---|
| KLayout DRC | — | — | **sí** | sólo con `--density` | no |
| magic DRC | — | — | **sí** | no | **sí** (`DPF.*`) |
| netgen LVS | **sí** | **sí** | — | — | — |
| KLayout LVS | **sí** | no (ver abajo) | — | — | — |
| `check_connectivity` | routing shorts and opens | -- | -- | -- | -- |

### Density: a separate pass, and only in KLayout

**The sign-off DRC does not check density unless asked.** The deck only runs
those rules with `--density` / `--density_only`, so every "clean" in the other
sections is FEOL/BEOL/connectivity **without density**. And `magic` is no
second opinion: its GF180 techfile carries not one density rule, so
esta comprobacion existe unicamente en KLayout.

When asked, the top broke all of them. They are **minimums**: metal is missing.

| rule | layer | without fill | with fill | asks |
|---|---|---|---|---|
| `DCF.1b` | COMP (activo) | 10.19 % | **32.27 %** | 25 % |
| `PL.8` | Poly2 | 7.26 % | **20.77 %** | 14 % |
| `M1.4` | Metal1 | 9.98 % | **31.37 %** | 30 % |
| `M2.4` | Metal2 | 3.83 % | **31.34 %** | 30 % |
| `M3.4` | Metal3 | 5.30 % | **30.47 %** | 30 % |
| `M4.4` | Metal4 | 21.43 % | **32.70 %** | 30 % |
| `M5.4` `MT.3` `MT.1` | Metal5 | 20.00 % | **30.46 %** | 30 % |

`scripts/fill_density.py` corre **despues** del GDS (`make fill`): lee
`out/GRADIENT_NAV.gds` and writes `out/GRADIENT_NAV_filled.gds`, which is the
submission file. The starting one is untouched, so the debug loop stays the same.

**Filling the channels is enough.** The 31 macros take 77,880 um2 of the 151,847
of the die and 73,967 are left free; with that the seven layers reach the
minimum, so **there is no floating metal over the amplifiers or the MIMs**.

Tres cosas que costaron un intento fallido de 6214 violaciones:

1. **DRC and LVS DO see the dummy.** What is defined as `get_polygons(34, 0)` is
   the *drawn* layer; the physical one is composed afterwards with
   `metal1 = metal1_drawn + metal1_dummy` (`layers_def.drc`), and LVS does the
   same. The fill has to pass the whole DRC, and appears in extraction
   como metal flotante.
2. **Cuadrados enteros, nunca recortados.** Recortar la rejilla contra la zona
   free area leaves necks and pieces below minimum area: thousands of
   `M*.1` and `M*.3` came from that. Now a square either fits whole or is not
   y area se cumplen por construccion.
3. **`MT.*` applies to Metal5.** For the 5-metal stack the deck does
   `top_metal = metal5`, so Metal5 is governed by `MT.1` (0.36 width),
   `MT.2a` (0.46 spacing) and `MT.4` (0.5625 um2 area), not by the 0.28 and
   0.1444 de las `M5.*`.

And an honest warning: `comp_dummy` and `poly2_dummy` are what the deck counts,
but in silicon dummy active needs its implant. To pass the PDK DRC drawing the
datatype is enough; to fabricate, it would need reviewing with the foundry.

The grid is generated by region erosion -- a square of side L fits whole if its
centro cae en la zona erosionada L/2—, no probando poligono a poligono, que tardaba
minutes per layer.

### The MIM and the hierarchy: 572 per block, and 13,745 on the top

magic reported 572 `Can't overlap those layers` violations in every block with a
MIM, and its extraction left the capacitor terminals on their own nets (43 nets
against 41 in netgen). One single cause, and it was not the deck:

**The booleans magic reads a GDS with are evaluated cell by cell.** The rule
reconoce el contacto del MIM es

```
layer mimcc VIA4 and MET5 and CAPM and CAPDEF
```

y el mar de vía4 salía de `gf180.via_generator`, que trae jerarquía propia. En esa
subcell there is no `fusetop` (CAPM), no `cap_mk` (CAPDEF) and no metal5 -- the
markers live in the parent cell -- so the rule never fired: the via came in as
a flat `via4` inside a `mimcap`, two types of the same plane, and hence the
conflict. Flattening **after** the `gds read` is no good: by then the layer is
already painted wrong.

Se arregla en el origen (`coil_layout/caps.py::flat_add`): la geometría de las
vias is copied into the parent cell instead of instantiated. With that magic
reads the block clean in 0.8 s, with no flags or patches. `gds flatglob` on read
also works, but you must also flatten the rectangles and the unnamed cells --
`via_generator`'s hierarchy hangs off them -- and that is minutes per block.

The top inherited the same multiplied by its 24 MIMs: **13,745 -> 17**.

### What netgen additionally needed

Tres traducciones de la netlist de referencia, todas en `lvs_netgen.py` y sólo
for netgen -- the `<B>_lvs.spice` on disk stays as KLayout wants it:

- **`M` -> `X`** on the MOSFETs. KLayout needs `M` (an element starting with any
  other letter is not a MOSFET to SPICE); magic extracts `X ... pfet_06v0`,
  en el PDK esos modelos son subcircuitos.
- **`C ... cap_mim_2f0fF` -> `X ... cap_mim_2f0_m4m5_noshield`**, which is how
  llama magic. Antes netgen comparaba un condensador de pines `top`/`bottom`
  contra un subcircuito de pines posicionales.
- **The two MIM terminals, declared permutable.** The two COMP capacitors are
  identical and share a terminal on `OUT`: topologically they are
  intercambiables salvo por el orden de sus pines, y netgen no sabe deshacer ese
  tie -- it says so itself, `Port matching may fail to disambiguate symmetries`.
  Permuting a capacitor's two legs is what KLayout's LVS does.

And the extracted `.subckt` port order is rearranged to follow the reference
one: netgen matches the top pins **by position**, and with the very same
conectividad exacta terminaba en `Top level cell failed pin matching`.

### The top: five causes, and none was the layout

The top LVS started at 1436 devices and 1003 nets against the 1389 and 880 of
la referencia. Antes de tocar nada conviene saber **si el layout está bien**, y
that is what `scripts/check_connectivity.py` is for: it extracts connectivity
KLayout —sólo metales y vías, sin dispositivos, un segundo— y comprueba dos cosas
that DRC cannot see: that all terminals of each DEF net land on the same
extracted net (**opens**) and that no two DEF nets land on the same
(**cortos**).

What was wrong, by size:

0. **The LEF `ORIGIN`, the big one, hidden until the very end.**
   It has its own section below, in *Lessons learned*: OpenROAD and KLayout read
   it differently and **all 31 macros came out shifted in the GDS**, which left
   42 of the 55 nets open. That alone is almost the whole net gap that
   netgen cantaba.

   And it stayed hidden because the tool that should have seen it was lying:
   `check_connectivity.py` usaba `net.name` como identidad de la net extraída, y
   **that field is empty on every unlabelled net**, i.e. on almost all of them.
   It threw different nets into the same bucket and said "55/55 connected" no
   matter what. With `expanded_name()` -- which gives `$1143` -- it said 13/55.
   A check that cannot fail is checking nothing.

1. **El pin del LEF era la caja envolvente, no el metal.** `lef write` de magic da
   one rectangle per port. When a port's pads never merged into a bar
   (`add_signal_access` only joins them if the spacing allows), that rectangle
   declares the gap between them landable: in `OPAM.INN` it is 0.4 um of
   nothing, and another net's riser passes underneath. The router landed there,
   0.14 um from the pad next door. **That was eight genuinely open nets.**
   `build_collateral.py::_clip_to_real` now clips each pin RECT against the
   metal really present in the GDS.
2. **Every macro's n-well came out floating.** The per-cell booleans again: on
   swapping the macros, KLayout's DEF reader rebuilds their internal hierarchy
   differently and the tap stops satisfying `COMP and NPLUS and NWELL`, so the
   well was left a loose node (`w_1724_75756#`) instead of VDD. Reading the same
   block from its own GDS it is tied. **43 well nets and 47 active ones
   de más.** Se cura aplanando el top al escribir el GDS
   (`def_to_gds.py::flatten_all`).
3. **On flattening, the macro labels tread on each other.** Each block brings
   propias etiquetas de puerto en Metal1 (`OUT`, `INN`, `Z`, `VDD`...), y aplanadas
   they all land in the same cell: twelve `OUT`, twelve `INN`, four `Z`. magic
   treats everything sharing a label name as **joined**, so net `Z` came out with
   1501 pins and the chip dropped to 848 nets, below the 880. The top labels are
   saved before flattening and restored after: the 19 DEF pin ones remain and
   none other.
4. And a false trail worth not following again: **the top GDS does have the
   router vias**. It looked like it did not because `cell.shapes()` without
   recursion does not see them -- the DEF reader puts each via in its own cell
   (`VIA_Via3_HH`). The technology vias the router builds from the `VIARULE`
   resolve themselves from the cell library LEF; they need not be dumped anywhere.

### The MIM that did not match in OPAM

`OPAM` sat at 38 nets against 37 with netgen: one terminal of one of the two
capacitors came out as a loose net (`m4_6467_2958#`). It was not the metal5, as
parecia al medir la geometria en planta — era la **placa de arriba**, y el motivo
it is the same kind of thing as the rest of this section.

Each metal5 plate drops to metal3 through a single via4 outside the MIM marker.
MIM B's lands on its own clean metal4 pad. MIM A's landed **on top of MIM B's
metal4 plate**, which is entirely inside its `cap_mk`.
There magic no longer sees metal4 but `mimcap`, and a plain via4 over `mimcap` is
neither a via nor a MIM contact -- `mimcc` also requires being inside `fusetop`
el terminal se quedaba flotando. En silicio esa via es buena; para la extraccion
no existe.

It was allowed by the same-net exception in `caps.py::_too_close`, which lets two
shapes of the same net contain one another because once merged there is no
spacing to measure. Correct between two pads, not against a MIM plate. With the
added condition -- and **symmetric**, because it does not matter which of the two
is placed first -- the search finds another placement without the block growing:
sigue en 88.27 x 31.46 y netgen da `Circuits match uniquely`.

### The top DRC: from 37 to zero

The first thing was to know **against what** they were. Subtracting from the top
metal what the block instances contribute, the 15 left turned out to be all the
**cable del router contra metal de un macro**, ninguna macro contra macro ni
same: router against router, with gaps from 0.236 to 0.273 -- just below the
0.28 of the rule. That is not chance any more, it is two systematic biases:

1. **The obstruction has to carry half a wire width.** The top nets use the
   non-standard `ANCHO` rule (0.38), and the router keeps the wire outside the
   obstruction measuring by its **axis**: growing it by the spacing alone, the
   acababa dentro. `_OBS_GROW` crece ahora `0.30 + 0.19`.
2. **El router mide por proyeccion y el deck en euclidea.** `Mn.2a` se comprueba
   corner to corner, so leaving exactly 0.280 orthogonally gives less at a
   diagonal corner. The patched techlef asks the router for **0.300** on
   Metal2/3/4: cualquier separacion euclidea es entonces >= 0.300 > 0.280 y el
   the problem disappears by construction. It costs 7% of slack, which we have.

And the same, one step earlier, in two more places: the LEF pin was the bounding
box and declared the gap between two pads landable; and a port landing pad needs
room for the wire that will land on it, not just for itself
misma (`_LAND_CLEAR` en `power.py`; en DECODER dos pads de puertos distintos
(they sat 0.295 um apart, legal between them but with no room for the wire).

That got it to **9-10, with no common pattern**: isolated spots that each run
moved around without dropping below ten. Below that, raising margins only
reshuffles, so it is closed with a **DRC-driven loop**, entirely inside
OpenROAD (`scripts/drc_blockages.py`):

```
route -> GDS -> sign-off DRC -> blockages -> route
```

The spots the deck marks become `dbObstruction` and the router lays down again.
The file `out/drc_blockages.txt` is **cumulative on purpose**: what was
forbidden on one pass stays forbidden on the next, and that is why the loop
converges instead of ringing. **10 -> 1 -> 0 in two passes**, with the 55 DEF
nets connected in all three -- it did not close DRC by breaking the routing.
tambien limpio.

    python3 scripts/drc_blockages.py           # anade lo de la ultima tanda
    python3 scripts/drc_blockages.py --reset   # empieza de cero

### The top LVS, and what is left

**The top, in LVS.** It now also has the sign-off deck
(`scripts/lvs_klayout.py`), which it lacked: until now it was only checked with
netgen. Setting it up needed three things in preparing the reference, and each
tapaba a la siguiente:

1. The `Vmeas` current probes in the xschem netlist. They are 0 V sources, i.e.
   a wire: the right thing is not to drop them but to **merge the two nets**, and
   per scope, because names repeat across blocks. Without this the deck did not
   arrancaba (`Not a known element type: 'V'`).
2. The reference was **hierarchical** against a layout that is one flat cell.
   That way it matched not one of 1815 nets nor one of 3414 devices.
3. The extracted netlist came out **without a single pin**; the deck only calls
   `make_top_level_pins` con `--top_lvl_pins`.

**Y el top cuadra: `Circuits match uniquely`**, 1389 dispositivos y 880 nets a cada
side. Besides the `ORIGIN` (point 0 above, which took the 54 difference
entero), hicieron falta dos cosas mas:

1. **El MIM estaba declarado permutable en un solo lado.** `setup_con_permute.tcl`
   pedia `permute "-circuit2 cap_mim_2f0_m4m5_noshield"`, y ese nombre en el top
   **only exists in the layout**: the reference instantiates them as
   `cap_mim_2f0fF`. So netgen permuted the two terminals in the layout and
   los dejaba fijos en la referencia, y contaba `cap/(1|2) = 2` frente a
   `cap/1 = 1` y `cap/2 = 1` — misma conectividad, distinta clase de pin. Ahora el
   nombre se saca de cada netlist (`lvs_netgen._modelos_mim`) en vez de escribirse
   a mano.
2. **The top `VDD` and `VSS` ports were FLOATING.** `place_pins` treats them
   like any other signal and leaves them on the die edge, on a pad that never
   touches the grid; the router does not close them because it skips POWER/GROUND
   nets. netgen already said `Netlists match with 144 symmetries` and failed only
   alimentacion de verdad salia sin nombre (`w_1904_7964#` el pozo,
   `a_2082_4860#` el sustrato) y los dos puertos salian sueltos. Se arregla en
   `floorplan_top.tcl` puts each pin **on top of its own Metal5 strap**
   con `place_pin`, despues de `pdngen` y despues de `place_pins`.

The symmetries that remain (144) are the 318 devices netgen merges in
parallel: genuinely interchangeable groups, and it resolves them by net name.

**Two collateral changes made BEFORE the ORIGIN was found and never re-measured.**
Both turn pin metal into obstruction, and both stand on their own
-- a block's internal via stack is not an access point for the top -- but they
were put in to cover shorts that were probably
sintoma del ORIGIN:

* the ~55 Metal2 pads of each power pin (`keep_top_access`);
* the Metal3 pads against another pin, closer than 0.94 um (`drop_trapped_pads`):
  `XZ` de DECODER, `WE` y `OUT_N` de WEIGHT_COMP.

Removing either requires redoing collateral, routing, GDS and the five
comprobaciones, y con el flujo entero en verde no se toco. Queda anotado: si algun
day the router runs short of room, **there is obstruction there that may be
forma de saberlo es quitarla y mirar `check_connectivity.py`, no razonarlo.

## Things that will bite you

**1. Do not give the black-box Verilog to OpenROAD.** `verilog/COMP.v` and
friends are for synthesis (yosys). OpenROAD binds each instance to the LEF
`MACRO` with the same name; if you also hand it the module definition, it
elaborates it as an empty hierarchical module and the instances vanish —
`link_design` still reports success and you get a block with **0 instances**.
`scripts/load_design.tcl` reads only `verilog/top_macros.v` for this reason.

**2. `WEIGHT` and `COMP_OUT` become one `WEIGHT_COMP`.** The top instantiates
them separately; the macro that exists packs both. `spice_to_verilog.py` does not
hard-code the substitution: it reads the pattern from `WEIGHT_COMP`'s own netlist
and matches it, and raises if it stops matching. That matters because the pin
order is not the identity — `WEIGHT_COMP` feeds its `VB` into `WEIGHT`'s `VC` pin
and vice versa, so a hand-typed mapping would swap two weights and route
perfectly.

**3. `+`, `-` and `.` are not Verilog.** The schematics used to carry `S1+`,
`X-`, `IN-` and a symbol called `comp._out`. They are now `S1P`, `XN`, `INN` and
`COMP_OUT`. Anything that still refers to the old names (the `TEST/` testbenches)
needs updating.

**4. The abstract must not advertise more than the top can use.** Signal pins
are clipped to Metal3 (`keep_top_access`), and what is taken from them **becomes
obstrucción**, no a la basura: en COMP y OPAM esas formas de Metal4/Metal5 son la
the MIM plate, and deleting them from the LEF left it invisible -- the power
straps were laid 0.51 um from it when `MIMTM.1` asks 1.2.

**5. A LEF obstruction is clipped to the macro outline.** Growing it does not
protect what is outside, so the router laid Metal4 against a plate from the
channel next door. What it does respect is a blockage declared on the top, and
that is what `floorplan_top.tcl` does with the 72 Metal4 halos.

**6. KLayout and netgen want opposite conventions for the same transistor.**
KLayout needs `M` (an element starting with any other letter is not a MOSFET to
SPICE); magic extracts `X ... pfet_06v0`, because in the PDK those models are
subcircuitos, y netgen entonces compara una llamada a subcircuito contra un
device and matches none. `lvs_netgen.py` translates the reference on the fly;
the `<B>_lvs.spice` on disk stays as KLayout wants it.

**7. `lef write` without `-hide`.** With `-hide`, magic collapses the
obstructions into a few coarse blocks and one of them covered the block's own
Metal1 power rail — pdngen reported `VSS on Metal1 is partially blocked (99.0%)`
and could not place a single via. Detailed obstructions are verbose and correct.

**8. This OpenROAD has no `write_gds`.** The stream-out goes through KLayout,
which reads the DEF and substitutes each macro's abstract for the GDS it was
abstracted from (`macro_resolution_mode = 2`). Mode 1 reads the GDS files,
ignores them, and writes LEF outlines — a chip-shaped box with no transistors.

**9. Pin directions come from the schematic, and some look wrong.** `OUT` on
`COMP`, and `WE` / `OUT` / `OUT_N` on `WEIGHT_COMP`, come out as `inout` because
that is how they are drawn in xschem (`iopin` / `:B`). If they really are
outputs, change them to `opin` and re-run `make collateral`.

## Lessons learned

What was hard to find, one line each. Nearly all of them cost hours.

**On the tools**

- **OpenROAD y KLayout leen el `ORIGIN` del LEF de forma distinta, y esa fue la causa de
  root cause of the top LVS.** OpenROAD **normalises the master**: it adds ORIGIN to all
  the geometry, so the lower-left corner of the macro box lands on (0, 0) and
  the DEF point is that corner. KLayout's DEF reader, on swapping the abstract
  for the GDS (`macro_resolution_mode = 2`), leaves the GDS in the block's own
  coordinates, which here start negative because the substrate taps stick out left
  del origen: COMP y OPAM en -1.26, DECODER en -1.00, WEIGHT_COMP en (-1.45, -4.21).

  Result: **all 31 macros came out shifted by their ORIGIN in the GDS**, up to 4.21 um.
  The proof, on `x5_weight_comp`: the via3 the router uses to reach pin `VA` lands at
  (354.20, 38.48), y el pad de `VA` esta en x[349.84, 354.34] y[38.28, 38.68] **sumando el
  ORIGIN**; sin sumarlo se queda en y[34.07, 34.47] — a 4.21 um exactos.

  That left **42 of the 55 nets open**, and the shorts too: a wire that in the
  router's model passes cleanly beside a pin goes through it in the GDS. The worst
  part is how quiet it is: **the router was never wrong** -- its DEF is consistent and its
  DRC report comes out empty -- and the sign-off DRC does not see it either, because two
  overlapping shapes on the same layer merge into one polygon. Only LVS sees it, and there
  it appears disguised as "54 nets missing". Fixed in `def_to_gds.py::normalizar_origen`,
  moving the macro CELL (not the instance: that way it works for a rotated macro too).

  La regla general: **si dos herramientas comparten un LEF con `ORIGIN` distinto de cero,
  check by hand where each of them puts a pin before trusting anything.**
- **KLayout's `net.name` is empty on every unlabelled net.** Using it as the identity of
  an extracted net throws different nets into the same bucket. The identifier is
  `expanded_name()`. With `name` the connectivity check said "55/55" whatever
  hiciera el layout, que es la peor clase de error: no falla, miente.

  And the general version, the expensive lesson of the day: **a check that cannot
  fail is checking nothing.** It happened three times running and three different ways --
  the empty `net.name`; `read_def_ports` looking only at `PLACED` and silently skipping the
  only two pins that mattered, which OpenROAD writes as `FIXED`; and the MIM `permute`
  asked on a name that does not exist in that circuit, which netgen accepts without a word.
  In all three the symptom was the same: silence. That is why `read_def_ports` now
  **compares against the pin count the DEF declares and aborts on a mismatch**, and the MIM
  name **is read from each netlist**. Every new check needs a known way of seeing it
  fallar.
- **The PDK LVS deck calls `compare` with the default limits.**
  `max_depth` 8 y `max_branch_complexity` 500 no dan para un circuito plano de 1707
  devices with twelve identical slices, and the deck does not expose them. How to
  prove the problem is the comparer and not the design: **compare the layout
  against its own extraction**. If that fails -- 72 unmatched nets -- there is no
  layout to fix. With `max_depth=30` and `max_branch_complexity=10000`, the same
  comparador cierra el emparejamiento entero.
- **A check that cannot tell "clean" from "never ran" is worse than
  no check at all.** `drc_klayout.py` counted violations over the `.lyrdb` of the
  directorio; si el deck no arrancaba no habia ficheros, la cuenta daba cero y
  came out **"clean"**. `probar_verificacion.py` caught it... by catching itself,
  which had the same bug. Now both abort if there is not one `.lyrdb`.
- **A label on the top cell is not a hint: it is a PORT.** Putting each DEF net
  name onto its metal looked like the way to give the comparer anchors; what it
  does is give the layout 55 pins against the 19 of the reference. It did not help
  the deck (the same 170 messages) and would have broken the
  emparejamiento de netgen, que hoy cuadra.
- **`permute` de netgen es silencioso si el nombre no existe.** El MIM se llama
  `cap_mim_2f0_m4m5_noshield` en la extraccion de magic y `cap_mim_2f0fF` en el
  schematic. Asking for the first in both circuits leaves the capacitor permutable in the
  layout and fixed in the reference, and neither side can match: `cap/(1|2) = 2`
  against `cap/1 = 1` and `cap/2 = 1`. Nothing warns. Device names going into a
  `permute` are taken from the file, not written by hand.
- **magic evaluates GDS booleans cell by cell.** A shape only exists for it if
  all the layers defining it are in the SAME cell. It cost us three times: the MIM
  vias in a subcell without the markers (572 violations per block), the well tap
  al sustituir macros (43 nets de pozo flotantes) y, de rebote, la solucion —aplanar— trajo
  la siguiente.
- **magic merges by label name.** Flattening the top, twelve `OUT`, twelve `INN` and
  four `Z` fell in the same cell and net `Z` ended with 1501 pins. Only the top pin
  labels should survive.
- **No single tool covers everything.** KLayout has the density rules but does not look at
  the poly fill geometry; magic has not one density rule but does have the
  `DPF.*`. On the same file, KLayout said clean and magic reported 134,488 violations.
- **El DRC no ve un corto.** Dos formas de nets distintas que se solapan se funden en un
  polygon and no rule fires. Nor does an open: it breaks nothing. That is why
  `check_connectivity.py` exists, the only thing that answers "is the routing connected?".
- **KLayout and netgen want opposite conventions** for the same transistor (`M` vs `X`) and
  for the same capacitor (`C ... cap_mim_2f0fF` vs `X ... cap_mim_2f0_m4m5_noshield`).
  La traduccion vive en `lvs_netgen.py` y no toca el `.spice` de disco.

**Sobre el deck de GF180**

- **`MT.*` se aplica a Metal5** en un stack de cinco metales: el deck hace
  `top_metal = metal5`. They are harsher than `M5.*` -- 0.36 width, 0.46 spacing,
  0.5625 um2 de area.
- **El DRC y el LVS SI ven el dummy.** `get_polygons(34, 0)` es la capa *drawn*; la fisica
  is composed afterwards with `metal1 = metal1_drawn + metal1_dummy`. The fill has to
  cumplir el DRC entero.
- **`make drc` does not run density.** It must be asked for separately. Every "clean" from
  a deck without `--density` is FEOL/BEOL/connectivity and nothing more.
- **The deck measures `Mn.2a` euclidean**, corner to corner; the router measures by projection.
  Leaving exactly 0.280 orthogonally gives less at a diagonal corner.

**Sobre el flujo de OpenROAD**

- **A LEF obstruction is clipped to the macro outline.** Growing it does not get it out of
  there; protecting something outside needs top-level obstructions.
- **The obstruction has to carry half a wire width.** The router respects it measuring
  by the wire axis, not by its edge.
- **A port landing pad needs room for the wire that will land on it**, not
  just for itself.
- **A LEF pin must declare the metal that exists, not its bounding box.** `lef write` gives
  one rectangle per port; if the pads never merged, that rectangle declares
  aterrizable un hueco vacio y el router aterriza ahi.
- **`place_pins` does not connect a power pin.** It treats it like any other signal and
  leaves it on the die edge, on a pad that never touches the grid; `pdngen` does not come
  down for it and the router skips it, because it skips POWER/GROUND nets. **The top `VDD`
  and `VSS` ports had been floating the whole project** and nobody saw it: not DRC (an open
  breaks no rule), not the router, not `check_connectivity.py`, which only looked at macro
  terminals. They are placed by hand with `place_pin` **on a strap of their own net**,
  y despues de `place_pins`.
- **Whatever you declare as a pin, the router believes it may use.** The internal Metal2
  stack a block uses to bring its rail up to Metal3 comes out of `lef write` as power pin
  geometry -- ~55 pads per rail -- and that is not an access point for the top: it is
  block metal. As a pin it invites; as an obstruction the router respects it and besides
  `add_via_obstructions` derives the Via1 and Via2 obstruction from it, which is where it
  colaba.
- **A pin pad against another pin is not a place to land.** If a wire with its spacing on
  each side does not fit between them (here 2 x (0.19 + 0.28) = 0.94 um), the router has no
  legal way to reach the neighbour -- and it does not stop: it goes over. That pad is
  removed **only if the pin keeps another free one** (`drop_trapped_pads`); an unreachable
  pin is worse than a short, because nobody can route it.
- **When there is no common pattern left, the DRC-driven loop closes the rest**: the zones
  the deck marks become obstructions and the router repeats. Cumulative, so that
  converja en vez de oscilar. 10 -> 1 -> 0 en dos vueltas.

**On the density fill**

- **Cuadrados enteros, nunca recortados.** Recortar la rejilla contra la zona libre deja
  cuellos y trozos bajo el area minima: miles de `M*.1` y `M*.3`.
- **The channels are enough.** The macros take 51 % of the die and the free 49 % is plenty
  for the seven layers -- with no floating metal over the amplifiers or the MIMs.
- **The grid is generated by region erosion**: a square of side L fits whole if its
  centre lands in the L/2-eroded zone. Testing polygon by polygon took minutes per layer.

**Sobre el proyecto**

- **Always regenerate the spice from the schematic.** Never read the one you generated
  puede haber cambiado en xschem.
- **A 0 V source (`Vmeas`) is a wire.** For LVS it is not dropped: the two nets are
  **merged**, and per scope, because names repeat across blocks.
- **The top LVS needs the reference flattened and `--top_lvl_pins`.** Without the first it
  matches nothing; without the second the extraction comes out with no pins and the
  arranca.
- **Un netlist de referencia se genera, no se retoca.** El de xschem no vale tal cual —
  `.subckt` comentado, sondas de 0 V, tarjetas de simulacion— pero el arreglo va en un
  script (`lvs_reference.py`, encadenado en `make top`), no en el fichero. Un netlist de
  reference edited by hand is the elegant way of making LVS lie.
- **Two engines, not one.** netgen on magic's extraction and the KLayout deck on its own
  share neither code nor extractor: both saying the same is worth far more than
  one saying it. Today the top only has the first, hence it is listed as pending in the
  tabla de estado en vez de como cerrado.
- **Diagnose by measuring, not by reasoning.** Three things were said along the way about
  the top LVS that turned out false: that there was a VDD-VSS short through the Metal4
  straps, that the problem was the bulk of 780 pfets, and that `pplus and comp and nwell`
  detected misplaced taps (it is the PMOS's own diffusion). All three came from reasoning
  about a hypothesis instead of measuring. What did work was instrumenting: ablating the
  connectivity model layer by layer until seeing which one the short appeared in, and from
  concreto.

## Uploading to GitHub

El repositorio es **`git@github.com:AnBuiUCI/sscs-2026-zotnetic.git`**, compartido con
the rest of the team: it has `main`, `add-pads` and `glayout`. This machine's SSH key
authenticates as `Juander28`; the repository belongs to `AnBuiUCI`, so write access
depends on being listed as a collaborator.

**What goes up and where.** All of `a_zonetic2026/` goes inside `FINAL/` in the repository.
No `zotnetic_layout/`, que es un arbol hermano y queda fuera.

**How, without touching the working tree.** No `git init` in here: git cannot push a
local repository into a subdirectory of the remote, and besides it is better that
`/foss/designs/a_zonetic2026` stays without `.git` or anything moved. Clone into a scratchpad
y se copia dentro:

```bash
cd /tmp/…/scratchpad
git clone git@github.com:AnBuiUCI/sscs-2026-zotnetic.git repo
git -C repo config user.name "Juander28"
git -C repo config user.email "jdsanch4@uci.edu"

/bin/cp -a /foss/designs/a_zonetic2026/. repo/FINAL/   # `/bin/` a proposito: cp esta
                                                        # aliaseado a `cp -i` y se queda
                                                        # asking about each file
git -C repo add -A
git -C repo diff --cached --name-only --diff-filter=D   # debe salir VACIO
git -C repo commit -m "…"
git -C repo push origin main
```

**Four things to check before pushing:**

1. **`FINAL/` already exists** since commit `d018403`. It is **updated**, not recreated.
   eso `cp -a` y no `rsync --delete`: sobrescribe y anade, pero nunca borra. Comprobar
   always check that `--diff-filter=D` comes out empty.
2. **Nothing outside `FINAL/`.** `git diff --cached --name-only | grep -v '^FINAL/'` must
   come out empty: there are two more branches with other people's work.
3. **The four `spice_blocks/` links are broken by every copy.** In the working folder
   son absolutos a `/foss/designs/...`; en el repo estan guardados **relativos**
   (`../XSCHEM/...`), which is the only thing that works in someone else's clone. `cp -a`
   preserves the link as is and therefore makes them absolute: that part of the copy
   copia** antes del commit.

       git checkout -- FINAL/spice_blocks/

   Y la comprobacion buena **no es `find FINAL -xtype l`**: en esta maquina el destino
   absolute target exists, so the link is not "broken" and that command comes out empty
   works is to look for absolute links, which must never exist here:

       find FINAL -type l -lname '/*'      # must come out empty

4. **Nunca `--force`, nunca reescribir historia.**

**Verificar de verdad** es clonar en un directorio limpio, no mirar la copia de trabajo:

```bash
git clone git@github.com:AnBuiUCI/sscs-2026-zotnetic.git verify
cd verify && find FINAL -type l -lname '/*'   # vacio: ni un enlace absoluto
ls -l FINAL/spice_blocks/                     # los cuatro, relativos y vivos
python3 -c "print(open('FINAL/openroad/out/GRADIENT_NAV_filled.gds','rb').read(4).hex())"
# 00060002 = valid GDSII header
```

**The `lvs_config.json` at the repo root is what points at the deliverable.** It is the
file the chipathon reads, reached through `info.yaml -> project.lvs_config`. Both
came with the template placeholders (`A01_topcell`,
`<relative-path-to-lvs_config.json>`); ahora dicen:

| clave | valor | quien lo genera |
|---|---|---|
| `info.yaml` `project.lvs_config` | `lvs_config.json` | a mano, una vez |
| `TOP_SOURCE` / `TOP_LAYOUT` | `GRADIENT_NAV` | a mano, una vez |
| `LAYOUT_FILE` | `$UPRJ_ROOT/FINAL/openroad/out/GRADIENT_NAV_filled.gds` | `make fill` |
| `LVS_SPICE_FILES` | `$UPRJ_ROOT/FINAL/openroad/out/GRADIENT_NAV_lvs.spice` | `make lvs-ref` |
| `LVS_VERILOG_FILES` | `$UPRJ_ROOT/FINAL/openroad/verilog/GRADIENT_NAV.v` | `make verilog` |

`TOP_LAYOUT` stays `$TOP_SOURCE`: the top cell of the filled GDS is called
`GRADIENT_NAV`, same as the schematic one, and the file is flattened to a single
cell. If the die is rebuilt these keys must be re-checked --
pointing at the unfilled GDS breaks all seven density rules at once.

**The reference netlist has to be generated; the xschem one is not usable as is.** It
carries the top `.subckt` COMMENTED (`**.subckt GRADIENT_NAV ...`, which is how xschem
exports from the CLI), 0 V sources as current probes -- `Not a known element type: 'V'`,
and electrically they are a wire, so the two nets must be **merged**, not dropped -- and
simulation cards. It also has to be flattened, because the top layout is a single cell.
`scripts/lvs_reference.py` does all three reusing `lvs_klayout.prepare()`, which is
the same patching KLayout's LVS uses to compare this top locally, and writes
`out/GRADIENT_NAV_lvs.spice` (19 puertos, 1707 dispositivos). Va encadenado en `make top`:
a stale reference netlist makes LVS compare today's GDS against last week's schematic
de la semana pasada y diga que cuadra.

**A warning about `LVS_VERILOG_FILES`.** In these configs the Verilog and the spice are
**alternative** sources for the same circuit. This design has not one standard cell: the
blocks are custom layout, and `GRADIENT_NAV.v` is structural with the macros as black
boxes -- that is, **without a single transistor to compare**. Its natural place is the
entrada de OpenROAD, no la referencia de un LVS. Se declara porque se pidio declararlo; si
the harness reads it alongside the spice, it will compare a black-box hierarchy against a
flat layout and it will not match. If that happens, empty `LVS_VERILOG_FILES` and leave

LFS is not needed: the largest file is the 25 MB of
`out/GRADIENT_NAV_filled.gds` -- the density fill quadruples the 5.7 MB of the working
GDS -- and it is still well under GitHub's 100 MB limit. If one day it
becomes a nuisance, it can be reduced by instantiating a fill cell instead of flattening.
`FINAL/`'s `.gitattributes` only declares `*.gds binary`, so that
line-ending normalisation cannot corrupt a GDS should git decide to take it
por texto.

## Notes on the generated LEF

- The pins are marked as ports with magic's `port makeall`. Without it magic
  writes a LEF with **no pins at all and no error message**, which is why
  `build_collateral.py` fails loudly if the pin count does not match the netlist.
- `COMP` has `ORIGIN 1.260 0.000` because the substrate taps stick out to the
  left of the origin in the layout. That is legal LEF and OpenROAD handles it;
  KLayout applies it on stream-out too, which is worth checking after a change.
- OpenROAD warns that the macro pins are not on the routing grid (`MPL-0002`).
  That is why signal routing is out of scope here: snapping the stub positions to
  the 0.56 µm grid in the layout generator would have to come first.

## Where the PDK collateral comes from

```
/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/
    techlef/gf180mcu_fd_sc_mcu9t5v0__nom.tlef      technology
    lef/gf180mcu_fd_sc_mcu9t5v0.lef                standard cells
    lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_5v00.lib  typical corner, 5 V
/foss/pdks/gf180mcuD/libs.tech/klayout/tech/gf180mcu.map   LEF/DEF -> GDS layers
```

The site for the floorplan is `GF018hv5v_green_sc9` (the name in the cell LEF,
not the library name). Routing tracks: 0.56 µm pitch on Metal1–Metal4, 0.90 µm on
Metal5. Metal4 is vertical and Metal5 horizontal, which is why the power stripes
are assigned to those layers the way they are.


## Two versions of the blocks

The top can be assembled with v1 or v2 of the block layouts, and both results
conviven:

```bash
make top            # bloques de layouts/     -> out/
make top V=v2       # bloques de layouts_v2/  -> out_v2/
```

Tres piezas:

* `scripts/usar_version.sh v1|v2` repoints the `gds/` links, which is how the flow
  reads the block layouts. It is the only entry point.
* `TOP_OUT` sends output to `out` or `out_v2`. The OpenROAD scripts read it and so do the
  DRC, LVS y relleno.
* `lef/.version` + el objetivo `comprobar-version`: los bloques de la v2 miden distinto, y
  a LEF from the other version would describe macros of the wrong size. The floorplan would
  still close and place overlapping macros, so any step that reads the LEF first checks
  which version the collateral was generated with.

Both tops are verified: **DRC clean** (router, sign-off and filled), the 7 density rules,
**55/55 nets connected with no shorts** and **matching LVS** (880 = 880 nets). The
la v2 es un **6.9 % mas pequeno** (0.1414 contra 0.1518 mm2).

Two things worth keeping in mind when using this:

* **The blocks DEF, LEF and GDS must come from the SAME run.**
  Regenerating only part leaves the top inconsistent and no error fires: it was seen
  regenerating the v1 GDS over an old DEF, which went from 55/55 nets connected to 34/55
  with 3 shorts. If you switch version or touch the blocks, run the whole flow.
* **`make gds` starts from the ROUTED DEF.** The floorplan DEF yields a GDS with the macros
  placed and without a single connection, and that **passes DRC** and passes the fill. Only
  LVS. Ver `zotnetic_layout/DRC_KLAYOUT.md` §15.2.

---

## The schematic is AHEAD of the GDS. Read this before running LVS.

As of 2026-08-28 the design in `XSCHEM/` carries four changes that are **not in
the GDS**, because rebuilding the top was deliberately deferred until the
organisers send a padring generated from the reordered `info.yaml`. Rebuilding
it twice would waste a full flow.

What is in the schematic and not in the layout:

1. **`WEIGHT` decides with TWO votes.** It is a current-mode vote counter and
   the buffer behind it was tripping between 2 and 3. A fifth branch, always on
   and an exact copy of a vote branch, drops every level by one whole step.
   Measured over the 16 input combinations, VDD 4.5..5.5 V and 0..85 C: the
   buffer used to flip at 3 votes in all 15 corners and now flips at 2 in all
   15. See `XSCHEM/TEST/run_umbral.sh`.
2. **The output polarity.** With the threshold moved, `COMP_OUT`'s `OUT` is LOW
   when the axis wins, so `XP` now comes from `OUT_N` and `XN` from `OUT`. The
   pin NAMES do not change, so `info.yaml` is unaffected.
3. **The chain wiring.** The four chains used to be two pairs sharing two of
   their three legs, which correlated the votes and pushed the ideal ties to
   36 %. They are now the four rotations and the ties drop to 1.3 %.

4. **`OPAM_LIN` runs on the 1 kohm HRES sheet.** The integration README fixes
   `ppolyf_u_1k` for this shuttle and the cell was written for `ppolyf_u_3k`.
   In the PDK's LVS deck the three values are a SWITCH and not a layer --
   `case POLY_RES when '1k'` over the same `RES_MK` on the same poly -- so
   **not one polygon of the resistor changes**: the same 382 squares are
   382 kohm instead of 1.147 Mohm. What changes is the gain, from 103 to
   33 V/V, because this stage's gain is Gm x RFB. Redrawing the resistor three
   times longer would have been 15 strips instead of 5, +22.5 um of channel
   and a cell 47 % bigger, twelve times over, so the factor of three was bought
   back in the transistors:

       M21 1u -> 7.5u, M22 1u -> 8.5u   the nfet pair takes over Gm, and its
                                        asymmetry the positive offset
       M29, M30 5u -> 10u               the cascode: with RFB/3 the summing
                                        node asks for 3x the current, and this
                                        is what fixes the linearity
       M43 0.5u -> 1.0u (m=4)           the top of the output swing
       M15 1.1u -> 0.55u, M16 -> 0.5u   the pfet pair carries no Gm any more,
       M27, M28 2.5u -> 2u              so narrowing it and the class-AB
       M32, M33 5u -> 4u                drivers gives the power back
       C1, C3 4x25 -> 8x25 um           Miller: 3x the Gm on the same Cc cost
                                        18 deg of phase margin. A MIM is on
                                        Metal4/5, so it costs no silicon.

   Measured: gain 103.3 vs 103.4 V/V, INL **0.10 vs 0.12 %**, offset +20.0 vs
   +23.9 mV, phase margin 76.0 vs 76.6 deg, 2.673 vs 2.550 mW -- under the
   2.753 mW of the OPAMt this family may not exceed. Over 27 corners of
   process, temperature and supply: gain 50.1..189.4 against 47.5..188.0, INL
   never worse than 0.68 % against 3.10 %, phase margin never under 73.8
   against 75.3. See `XSCHEM/TEST/run_opam_rfb.sh`.

Measured over the whole sphere, the first three together take the top from
**0 % right and 100 % undecided** to **69.96 / 83.68 / 90.70 %** at the three
gradient levels, matching the reference implementation digit for digit.

**What this means for LVS.** Both LVS scripts read the sheet from the REFERENCE
netlist and rename the extraction to match, and the extraction always comes out
as `ppolyf_u_1k`; with the schematic now on 1k the rename is a no-op and
`lvs_klayout.ajustar_hoja` / `lvs_netgen._hoja_resistencia` do nothing. Nothing
to configure. But `Layouts/OPAM_LIN_flat/` and `layouts_v2/OPAM_LIN_flat/` still
hold the OLD transistor sizes, so **do not regenerate their reference netlists
until the cell is rebuilt** -- the reference would move and the extraction would
not, and LVS would fail on a layout that is merely out of date.

### What that means for the files here

`out_v2_GRADIENT_NAV2/GRADIENT_NAV2_lvs.spice` and `verilog/GRADIENT_NAV2.v` are
generated from the schematic **as it was when the GDS was built**, so that they
match `GRADIENT_NAV2_filled.gds` and the external LVS in `lvs_config.json`
passes. They are NOT what `make lvs-ref` produces from today's schematic --
that one has 2139 devices against these 2130.

So: **do not regenerate them until the top is rebuilt.** When it is, everything
regenerates together and this section goes away.
