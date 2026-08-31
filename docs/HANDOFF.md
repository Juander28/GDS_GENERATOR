# HANDOFF — where this design stands, and how to pick it up cold

Last updated **2026-08-31**. Written so a chat that has never seen this tree can
carry on without re-deriving anything. Read this first, then
`openroad/README.md` (the long logbook) and `zotnetic_layout/DRC_KLAYOUT.md`.

Everything below is measured, not assumed. Where a number appears, the command
that produced it is next to it.

---

## 1. What the chip is

GF180MCU-D analog IC for the SSCS Chipathon 2026, team **B26 Zotnetic**.

Four magnetoresistive bridges sample the **magnitude** of the magnetic field,
`|B|`, at the vertices of a tetrahedron. The chip reconstructs `grad|B|` — which
points towards where the magnitude grows, i.e. **towards the source** — and puts
out a sign per axis. The sensors do not measure a vector; they measure `|B|`.
That distinction is the whole design.

Top cell: **`GRADIENT_NAV2`**. Integrated into the padring's user area as
**`B26_A`** (1110 x 1110 um).

Signal chain per axis: bridges -> `OPAM_LIN_flat` (linear amplifier) ->
`OPAM_SUMA` / `RED_SUMA` -> `WEIGHT_COMP` (current-mode vote counter) ->
`DECODER` / `DECODER_MAX` -> `COMP` -> digital output pair (`XP`/`XN`, ...).

---

## 2. The three trees on disk

| path | what it is | in git? |
|---|---|---|
| `/foss/designs/a_zonetic2026` | **the project**. Schematics, layouts, OpenROAD flow, submission files. | yes, as `FINAL/` in the repo |
| `/foss/designs/zotnetic_layout` | the **layout generator** (`coil_layout/`, `build_block.py`, `run_lvs.sh`). A sibling tree. | no |
| `/tmp/chipa26` | clone of `sscs-ose/sscs-chipathon-2026` (the organisers' repo), HEAD `aa834f5` | no |

There is **no `.git` inside `/foss/designs`**. That is deliberate — see §9.

`layouts/` and `Layouts/` are **the same directory** (inode 2251799815237516;
WSL2/drvfs is case-insensitive). `layouts_v2/` is genuinely separate.

---

## 3. Hard-won facts. Each of these cost at least one build.

### The generator

* **`env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python` is mandatory** for
  anything under `zotnetic_layout`. Without it gdsfactory 9.44 shadows the
  pinned 9.2.2 and the geometry silently changes.
* `build_block.py` writes the GDS, `<cell>_flat.spice` **and** the LVS reference
  `<cell>_lvs.spice` in one act. Reference and layout therefore move together;
  you can never regenerate one without the other.
* **Never read the SPICE that is on disk. Always re-export it from xschem**
  before building — the schematic may have moved under you:

      cd XSCHEM/OPAM/simulation/OPAM_LIN_flat.sch
      rm -f OPAM_LIN_flat.spice
      ( cd ../.. && xschem -n -s -q -o simulation/OPAM_LIN_flat.sch OPAM_LIN_flat.sch )

* Do **not move** the `.py` generators. Editing them in place is fine and is how
  the flow evolves; moving them breaks every relative path in the Makefile.

### Resistors

* **`POLY_RES` is a deck switch, not a drawing.**
  `libs.tech/klayout/tech/lvs/rule_decks/res_extraction.lvs:180` —
  `case POLY_RES / when '1k' / extract_devices(resistor_with_bulk('ppolyf_u_1k', 1000, ...))`.
  The same `RES_MK` (110/5) over the same poly is 1k, 2k or 3k depending on the
  fab's implant option. **Not one polygon changes**, only the value.
* **A `RES_MK` marker alone does NOT make a resistor high-sheet.** Proven on the
  organisers' cell: `RES_MK` over nwell still extracts as plain `ppolyf_u` at
  350 ohm/sq. Do not infer the model from the marker — run the extraction.
* Plain poly over nwell keeps the device **name** `ppolyf_u`; only the bulk
  terminal changes (`nwell_con` instead of `sub`).

### LVS

* **`run_lvs.py` returns exit code 0 even on a mismatch.** The verdict must be
  taken by grepping the log for `Netlists don't match` / `Congratulations!
  Netlists match`. This bug once produced a false clean on `OPAM_LIN_flat`.
  `run_lvs.sh` already greps; anything new must too.
* **xschem emits poly resistors as `X`-prefixed subcircuit calls**
  (`XR1 ... ppolyf_u r_width=... r_length=...`). KLayout's SPICE reader
  **silently drops them, and their nets with them**. The PDK ships
  `gf180_xschem_klayout_spice_convert.py` to rewrite `XR1` -> `RR1 ... W= L=`;
  our flow does the same in `lvs_klayout.prepare()` / `lvs_netgen.as_subckt_calls()`.
  Symptom when it bites: a net simply missing from the schematic side of the
  cross-reference.
* **KLayout LVS does not expand `m=4` on diodes.** The reference must carry four
  explicit instances.
* **netgen cannot parse a 3-terminal `R a b c <value> <model>` line** with the
  default setup — it reads the third node as the value and invents a device
  named after it. Hence `zotnetic_layout/lvs/gf180mcuD_setup_polyres.tcl`.
* KLayout `lvsdb` Python API: `ci.first`, `ci.second`, `ci.status` are
  **methods**, not attributes; and the pair iterators live on the
  `NetlistCrossReference`, taking the circuit pair as an argument —
  `x.each_net_pair(ci)`, `x.each_device_pair(ci)`, `x.each_pin_pair(ci)`.

### DRC

* **`M*.2b` is the rule that catches fill.** Every metal has a *second* spacing
  number — 0.30 um (0.50 for the top metal, `MT.2b`) — that applies whenever the
  neighbour is wider **and** longer than 10 um. Fill squares never trip it
  themselves; the plate they sit next to does. In `B26_A` the 73 pin ports are
  44 x 55 um of Metal2, and filling at the minimum 0.28 left a 0.285 um gap:
  **57 x `M2.2b` on a file the density pass called clean**. `fill_density.py`
  now uses the *wide* number as its guard on every metal.
* magic's GF180 techfile carries **not one density rule**, so on density
  KLayout has no second opinion. It does carry poly **fill** rules KLayout does
  not check (`DPF.1` 5.6 um width, `DPF.2a` 2.4 um between, `DPF.5` 5 um to real
  poly) — with 0.4 um squares magic reported 134,488 violations on a file
  KLayout called clean. Hence the 5.6 um poly squares.
* The DRC deck **lies when it runs out of memory**: it exits without writing
  `.lyrdb` files and that reads as zero violations. `drc_klayout.py` therefore
  fails loudly if there is not a single `.lyrdb`.
* **`MSLOT.1` had never actually run, and nobody could tell.** The deck is
  normally driven table by table, and in that mode the PDK's own `mslot` table
  **crashes** — `undefined method 'sized' for nil:NilClass`, a bug in the deck,
  not in the design. A crashed table writes **no `.lyrdb`**, and a check that
  counts result files reads that as *clean*. So every "63 tables, 0 violations"
  this project ever produced was true about what it said and silent about
  `MSLOT.1`.

  Two things came out of it. `drc_klayout.py::completo()` no longer accepts a
  run where only `mslot` died without also checking the table count — a run
  killed at table 48 of 63 had been reading as clean because the `mslot`
  message arrived first. And there is now a **second way to run the deck that
  does not crash**:

      DRC_MODE=deep DRC_THR=1 DRC_MP=1 make drc T=B26_A TOP_OUT=out_integration ARGS=B26_A_FILLED

  One `main` table in `deep` mode, single-threaded. Slow, fits in memory, and
  `mslot` runs. **This is the run that decides whether the deck passes.** Split
  tables are the fast screen, not the verdict.

  `drc_klayout.py::mslot1_local()` is the fallback: our own implementation of
  the rule, so a crashed table still gets an answer. It had a unit bug of its
  own — it read database units as nanometres and so measured 15 um where the
  rule says 30. Fixed by taking `um()` from `ly.dbu`.
* **exit 137 is SIGKILL is out of memory.** Docker on native Linux imposes no
  memory or CPU cap of its own (the cgroup reads `max`); on WSL2 the cap is
  whatever the VM was given in `%UserProfile%\.wslconfig`. If a DRC dies at
  137, the machine is the limit, not the tool.
* **`PR_bndry` is layer 0/0, and exactly one is allowed at top level.** Two of
  them is what stopped the organisers from regenerating B26's DEF:
  `Top level has 2 PR_bndry shapes. only one is allowed`. Flattening the routed
  DEF brings up the block's own boundary alongside the die's.
  `def_to_gds.py::una_sola_frontera()` now counts 0/0 shapes **unmerged** —
  merged, two touching rectangles look like one — and aborts the write rather
  than shipping a GDS the organisers' flow will reject. **Check this on every
  GDS that leaves this tree.**

### Density fill

* `scripts/fill_density.py` is **ours** — the PDK ships no fill generator.
* Dummy goes on **datatype 4** of the same layer number, and the decks add it
  into the physical layer (`metal1 = metal1_drawn + metal1_dummy`). So the fill
  **must pass the whole DRC** and shows up in extraction as floating metal.
* **Whole squares only, never clipped.** Clipping against the free area creates
  0.1 um necks and sub-minimum pieces: that is where 6214 width/area/spacing
  violations came from.
* The rules are **global**, not windowed: `CHIP = extent.sized(0.0)` and
  `ratio = layer.area / CHIP.area`. Targets: COMP 25 %, Poly2 14 %,
  Metal1..Metal5 30 %.

### Current density (electromigration)

* **DRC will never say a word about it.** Electromigration is not a design rule,
  it is a current limit, and the DEF has no idea how much current runs through
  anything. `integrate_top.tcl` sizes the power ring in a **comment**; a comment
  is not a measurement. `scripts/check_current_density.py` reads the routed DEF,
  measures what is drawn, and contrasts it with what each net has to carry.
* The numbers: the block draws **14.81 mA at 5 V** (measured on the
  RC-extracted layout), and the PDK's limit at **125 C** — the column that
  assumes nothing — is **0.67 mA/um** of line and **0.18 mA per via cut**. So a
  supply needs 22.10 um of metal and 83 via cuts per path.
* **Do not judge a supply by its narrowest segment.** That criterion failed the
  ring at 0.38 um — which is the width of the 48 **tie-off stubs**, leaves that
  hold a control pin at a rail and carry none of the block's current. What
  limits is how much copper **crosses** a line between the edge, where the
  current comes in, and the block, where it is spent. The script cuts the die in
  half on each axis and adds up the widths crossing: 48.00 um against 22.10
  required, per supply, per direction.
* A regex that stopped at the first `+ LAYER ... WIDTH` line read **two of the
  five** non-default rules and called the run clean. `[^\n]*` at the end of the
  repetition fixed it — the Metal2..Metal4 lines carry a trailing `SPACING`.

### Layout / routing

* `add_pdn_connect -grid macro -layers {Metal3 Metal4}` in `floorplan_top.tcl`
  means **every block must export a full-width Metal3 bar over each supply rail
  with via1+via2 drops**, or `pdngen` aborts with
  `PDN-0232 grid does not contain any shapes or vias`.
* A block's signal pin must **reach Metal3** or `build_collateral.keep_top_access`
  will not let the router one level up use it.
* `coil_layout/routing.py::_Access.fijo` — an escape stub off a **shared**
  source/drain block has no pad to slide on. Sliding it in x takes the via off
  the metal1 contact strip and **the net comes out OPEN**, while the only
  warning is an `M1.2a`-flavoured `AVISO: stubs justos`, which reads as
  harmless. Measured in `OPAM_LIN_flat`: `net13`'s escape was pushed 0.625 um
  off a 0.36 um strip and split the net in two. `fijo` pins those stubs and
  makes the neighbours give way instead.
* MIM caps sit on Metal4 (bottom plate + `cap_mk`) / fusetop / Metal5 — they
  cost **no silicon area**. `caps.py::_dims_um` reads `c_width`/`c_length`
  straight from the SPICE, so MIM geometry is fully parameterised.

---

## 4. The secondary ESD: their circuit, our layout

The history matters, because the decision was reversed once.

**First** the rule the user set was: run DRC and LVS on the organisers' GDS; if
it passes, use it as drawn; redraw it only if it fails.

    repo    sscs-ose/sscs-chipathon-2026, commit aa834f5
    path    resources/Integration/Chipathon2025_pads/magic/secondary_ESD.gds
    cell    io_secondary_5p0, 75.65 x 85.35 um = 6457 um2

It passed the split-table DRC, so it was adopted, jacketed by `esd_jacket.py`
and integrated. Then `MSLOT.1` turned out never to have run (§3), and on the
run that does run it **all three of their variants carry `MSLOT.1`** — a plate
of metal wider than the 30 um the rule allows without slotting. Their cell was
importing a violation into our die, eleven times.

**So we drew it ourselves — their circuit, not a redesign.** `ESD_CDM`,
`scripts/esd_layout.py`, schematic `XSCHEM_v2/ESD_CDM.sch`:

* **8 diodes**, exactly their `m=4` written out as four explicit instances each
  (KLayout does not expand `m=`, and LVS wants the instances):
  4 x `diode_nd2ps_06v0` from `VSS` to `PAD`, 4 x `diode_pd2nw_06v0` from `PAD`
  to `VDD`, all 10 x 10 um — `AREA=100p PJ=40u`.
* **the series resistor exactly as their schematic declares it**:
  `ppolyf_u W=16e-6 L=4e-6`, 0.25 squares, **87.5 ohm**, bulk in `VDD` over
  n-well. Note this is their *schematic*: their own GDS draws 40 x 10 um
  instead — same squares, same resistance, different geometry. **Their
  schematic and their GDS do not agree, and that is worth reporting upstream.**
* Pin mapping is theirs: `ASIG5V` = our `PAD`, `to_gate` = our `CORE`.
* **63.16 x 27.90 um = 1762 um2** per clamp against their 6457 — about
  52,000 um2 saved over eleven instances — and no `MSLOT.1`.

Verdict, `layouts_v2/ESD_CDM/lvs/RESUMEN.txt`, 2026-08-30 07:37:
**KLayout LIMPIO, netgen CASAN.**

Two traps paid for while drawing it:

* `via_generator` called with a `y_range` **exactly** the size of one via draws
  **nothing**, silently. Give it room.
* the deletion window in `_fix_res_heads()` ate the well-tap contacts before it
  was bounded. If the taps vanish, look there.

`io_secondary_5p0` stays vendored at `layouts_v2/io_secondary_5p0/` with its
`README_ORIGEN.txt`, and `esd_jacket.py` stays in the flow. **They are kept, not
deleted — they are simply not what gets instantiated.**

---

## 5. Where the flow stands, block by block

Measured 2026-08-31.

| thing | state | evidence |
|---|---|---|
| `COMP`, `DECODER`, `DECODER_MAX`, `OPAM`, `OPAM_LIN_flat`, `WEIGHT_COMP` | **built, clean** — KLayout LIMPIO, netgen CASAN | `layouts_v2/*/lvs/RESUMEN.txt`, 2026-08-29 18:10 |
| `ESD_CDM` | **built, clean** | `layouts_v2/ESD_CDM/lvs/RESUMEN.txt`, 2026-08-30 07:37 |
| `OPAM_SUMA` | **broken, and left broken on purpose** — NO CASAN in both engines. `GRADIENT_NAV2` does not use it. | same file |
| `GRADIENT_NAV2` | **rebuilt**, 460.90 x 386.99 um, netgen `Circuits match uniquely` | `out_v2_GRADIENT_NAV2/`, 2026-08-29 |
| `B26_A` integration | **done**, 11 x `ESD_CDM` placed by the pads | `out_integration/B26_A.gds`, 2026-08-30 08:05 |
| `B26_A_filled.gds` | **built**, archived as `integration/gds/2026-08-30_03` | sha256 `5982dfe4...` |
| — density | **clean** | `out/density_B26_A_FILLED` |
| — LVS netgen | **`Circuits match uniquely`**, 1442 devices, 894 nets | `out/lvs_netgen_B26_A.rpt` |
| — `check_integration.py` | **17 / 17**, 11 of them through their clamp | script output |
| — `PR_bndry` | **1**, on all four GDS files | `def_to_gds.py::una_sola_frontera()` |
| — current density | **passes**: 48.00 um of section against 22.10 required | `check_current_density.py` |
| — sign-off DRC, split tables | 63 tables, 0 violations | `out/drc_B26_A_FILLED` |
| — sign-off DRC, **`main`/deep** | **11 x `MSLOT.1`**, everything else clean | the run of 2026-08-31 |

### THE ONE THING TO DO NEXT

**Eleven `MSLOT.1` on Metal2, and they are ours.** Not the fill and not the ESD:
measured with `mslot1_local` they appear identically on `B26_A_filled.gds` and
on `B26_A.gds`, and they were there in the previous version with the
organisers' cell too.

They are the **pin escape channels**. The padring's pad pin arrives as a comb of
1.00 x 2.54 um Metal2 rectangles at x 0..1; `integrate_top.tcl` runs each tooth
straight out to `ESCAPE_X = 55.72`, and the union of the comb comes out as a
single polygon:

    metal2 in the flagged band (0..60, 118..167): 2 polygons
       bbox  55.91 x  44.77   area 2445.7 um2   points=36
       bbox   0.44 x   0.44   area    0.2 um2   points=4

55.91 x 44.77 um — over 30 um in **both** directions, which is exactly what
`MSLOT.1` forbids without slotting. Eleven of them, one per analog pad, in bands
every 100 um: `(0,120.34;55.72,164.66)`, `(0,220.34;55.72,264.66)`, ...

Two ways out:

1. **break up the escape** so no 30 x 30 um square fits inside it — a small
   change around `set ESCAPE_X [pista [expr {$VDD_OFF + $BUS_W + 4.0}]]` in
   `integrate_top.tcl`. **This is the one to do.**
2. slot the region, which is what the rule literally asks for and is more work
   for the same result.

Then, in this order:

```bash
cd /foss/designs/a_zonetic2026/openroad
openroad -no_init -exit scripts/integrate_top.tcl
env -u PYTHONPATH python3 scripts/def_to_gds.py \
    out_integration/B26_A_routed.def out_integration/B26_A.gds

# the verdict run: one main table, deep, single-threaded -- mslot survives here
DRC_MODE=deep DRC_THR=1 DRC_MP=1 \
    make drc T=B26_A TOP_OUT=out_integration ARGS=B26_A

# only once that is zero:
TOP_OUT=out_integration TOP_CELL=B26_A env -u PYTHONPATH python3 scripts/fill_density.py
make lvs-ref T=B26_A TOP_OUT=out_integration
make drc-density T=B26_A TOP_OUT=out_integration
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/check_integration.py
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/check_current_density.py
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/archivar_integracion.py
```

`make fill` on the 1110 x 1110 die takes about **three hours** and ~1.7 GB of
RAM; the `main`/deep DRC on the filled file takes longer still. Run both in the
background, and **fix the geometry before filling** — filling first only means
doing the three hours twice.

### And the thing that is not ours to do

The submission still waits on **the organisers regenerating the padring** with
today's pin order (`VSS` first, `VDD` last). `openroad/padframe/B26_A.def` is
still the 27 August file. What used to block them — the two `PR_bndry` shapes —
is fixed and pushed; there is nothing of B26 in their repository yet.

---

## 6. The submission interface

`info.yaml` is the pad map: **the order of the list is the order of the slots.**
Two rules from the organisers' own `resources/info.yaml`:

* the **first** pin must be a ground connection — so `VSS` opens the list;
* a power/ground cell breaks the I/O power rails, so the supplies sit at the
  **two ends** — so `VDD` closes it.

19 pins: 11 analog + 6 digital + 2 supplies.

**The padring in `openroad/padframe/` PREDATES this order.** `B26_A.def`, sent
by the organisers on 2026-08-23 (issue #58), was built from the previous list,
which had `VSS` third and `VDD` fourth. **The organisers have to regenerate the
ring** before the slot assignment in that DEF means anything.
`scripts/padframe_def.py` notices and says so.

`lvs_config.json` at the repo root is what the chipathon's external LVS reads,
reached through `info.yaml -> project.lvs_config`. It now points at the
integrated area:

| key | value |
|---|---|
| `TOP_SOURCE` / `TOP_LAYOUT` | `B26_A` |
| `LAYOUT_FILE` | `$UPRJ_ROOT/FINAL/openroad/out_integration/B26_A_filled.gds` |
| `LVS_SPICE_FILES` | **stale — still `.../out_v2_GRADIENT_NAV2/GRADIENT_NAV2_lvs.spice`. Point it at `.../out_integration/B26_A_lvs.spice`.** |
| `LVS_VERILOG_FILES` | `$UPRJ_ROOT/FINAL/openroad/verilog/B26_A.v` |

`B26_A` now has a schematic of its own, `XSCHEM/B26_A.sch` — the block plus its
eleven `ESD_CDM` clamps — so its reference comes out of xschem through
`lvs_reference.py` like every other cell's.
`scripts/lvs_reference_integration.py` is **superseded**; it is kept only so the
history reads, and its own docstring says so.

A note on `LVS_VERILOG_FILES`: in these configs the Verilog and the SPICE are
**alternative** sources for the same circuit. This design has not one standard
cell — `B26_A.v` is structural with the macros as black boxes, i.e. without a
single transistor to compare. If the harness reads it *alongside* the SPICE it
will compare a black-box hierarchy against a flat layout and it will not match.
If that happens, empty `LVS_VERILOG_FILES`.

---

## 7. The four checks, and why they are four

They are not four opinions on one thing.

| command | what only it can see |
|---|---|
| `make drc` | KLayout sign-off deck: geometry, 63 rule tables |
| `make drc-density` | the density minimums — a **separate pass**, the deck does not run them unless asked |
| `make drc-magic` | magic's poly **fill** rules (`DPF.*`), which KLayout does not check |
| `make lvs` / `make lvs-klayout` | netgen and KLayout: two independent engines and two independent extractions |
| `scripts/check_connectivity.py`, `scripts/check_integration.py` | that the 73 pins actually **conduct**. A tie-off drawn 0.02 um short passes DRC and passes LVS-with-`--top_lvl_pins`, and does not conduct. |

And the question to ask before believing any "clean": **would this tool notice
if the chip were wrong?** `make probar` and `make probar-drc` answer it by
breaking a cell on purpose and checking that the check fails.

---

## 8. Standing instructions from the user

* **Language: everything produced is in English** — code, comments, docstrings,
  names, commit messages, config, figure labels. Two exceptions, both Spanish:
  **chat replies** and **PDFs/documents delivered to the user**.
* **Never read the SPICE on disk; always re-export from xschem.**
* **Do not move the `.py` generators.** Editing in place is fine.
* **Nothing is deleted from the repository without asking first.**
* GitHub hygiene: the repo is **the design** — schematics, layouts, netlists,
  flow scripts. Historically **no `.md`, no `.pdf`, and no document-generator
  script** (`hacer_pdf*.py`, `documento.py`, `figuras*.py`, `graficas.py`,
  `capturar*.py`) went up; `/foss/designs/.gitignore` enforces it. On
  2026-08-29 the user asked for the knowledge MDs to go up **so that a fresh
  chat can resume from zero** — that is a deliberate exception for the
  documentation, not for the PDFs or the generator scripts. And the user then
  narrowed it: **the MDs and the generator go to `Juander28/GDS_GENERATOR`, not
  to the design repository.** That is this repository. The design repository
  keeps only the design.

---

## 9. How to upload

The repository is **`git@github.com:AnBuiUCI/sscs-2026-zotnetic.git`**, shared
with the team (`main`, `add-pads`, `glayout`). This machine's SSH key
authenticates as **`Juander28`**; the repository belongs to `AnBuiUCI`, so write
access depends on being a collaborator. There is no repository of this project
under `Juander28` itself — checked, 2026-08-29.

All of `a_zonetic2026/` goes inside **`FINAL/`**. Nothing outside `FINAL/`:
there are two other branches with other people's work.

**Never `git init` here.** Git cannot push a local repository into a
subdirectory of a remote, and it is better that `/foss/designs/a_zonetic2026`
stays without a `.git`. Clone into a scratchpad and copy in:

```bash
cd <scratchpad>
git clone git@github.com:AnBuiUCI/sscs-2026-zotnetic.git repo
git -C repo config user.name  "Juander28"
git -C repo config user.email "jdsanch4@uci.edu"

/bin/cp -a /foss/designs/a_zonetic2026/. repo/FINAL/   # /bin/ on purpose:
                                                       # cp is aliased to cp -i
git -C repo add -A
git -C repo diff --cached --name-only --diff-filter=D  # MUST be empty
git -C repo diff --cached --name-only | grep -v '^FINAL/'   # MUST be empty
git -C repo commit -m "..."
git -C repo push origin main
```

Four things that will bite:

1. **`FINAL/` already exists** (since `d018403`). It is *updated*, never
   recreated — hence `cp -a` and not `rsync --delete`, and hence the
   `--diff-filter=D` check.
2. **Nothing outside `FINAL/`.**
3. **The `spice_blocks/` symlinks break on every copy.** In the working tree
   they are absolute into `/foss/designs/...`; in the repo they are stored
   **relative** (`../XSCHEM/...`), which is the only form that works in someone
   else's clone. `cp -a` preserves them as absolute, so restore them before
   committing: `git -C repo checkout -- FINAL/spice_blocks/`.
   And the check is **not** `find FINAL -xtype l` — on this machine the
   absolute target exists, so nothing looks broken. The check that works is:

       find FINAL -type l -lname '/*'      # must be empty

4. **Never `--force`, never rewrite history.**

Verify by cloning into a clean directory, not by looking at the working copy:

```bash
git clone git@github.com:AnBuiUCI/sscs-2026-zotnetic.git verify
cd verify && find FINAL -type l -lname '/*'
python3 -c "print(open('FINAL/openroad/out_integration/B26_A_filled.gds','rb').read(4).hex())"
# 00060002 = valid GDSII header
```


### The other repository — this one

**`git@github.com:Juander28/GDS_GENERATOR.git`**, owned by this machine's key,
so pushing needs no collaborator status. It holds the **tooling and the
knowledge**: `zotnetic_layout/`, `flow_scripts/` (a copy of
`FINAL/openroad/scripts/` plus its `Makefile`) and `docs/`.

It is a **copy**, so it goes stale silently. When a flow script or a generator
module changes, sync it:

```bash
cd <scratchpad>
git clone git@github.com:Juander28/GDS_GENERATOR.git gen
for b in $(ls gen/flow_scripts); do
    src=/foss/designs/a_zonetic2026/openroad/scripts/$b
    [ -f "$src" ] && { cmp -s "gen/flow_scripts/$b" "$src" || echo "DIFF $b"; }
done
```

`/bin/cp` on purpose there too — `cp` is aliased to `cp -i` and a plain `cp -f`
in a loop will sit waiting for an answer nobody types.

**No generated artefacts go here**: no GDS, no `.lyrdb`, no extraction
databases. They weigh hundreds of megabytes, they are regenerated by the flow,
and a stale one is exactly how a DRC and an LVS come to pass against the wrong
circuit. The deliverables live in the design repository.

LFS is not needed: the largest file is `B26_A_filled.gds` at ~42 MB, under
GitHub's 100 MB limit. `FINAL/.gitattributes` declares `*.gds binary` so that
line-ending normalisation cannot corrupt a GDS.
