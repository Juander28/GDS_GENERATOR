# HANDOFF — where this design stands, and how to pick it up cold

Last updated **2026-09-01**. Written so a chat that has never seen this tree can
carry on without re-deriving anything. Read this first, then
`openroad/README.md` (the long logbook) and `zotnetic_layout/DRC_KLAYOUT.md`.

Everything below is measured, not assumed. Where a number appears, the command
that produced it is next to it.

---

## 1. What the chip is

GF180MCU-D analog IC for the SSCS Chipathon 2026, team **B26 Zotnetic**.

Four magnetoresistive bridges sample the **magnitude** of the magnetic field,
`|B|`, at the vertices of a tetrahedron. The chip reconstructs `grad|B|` — which
points towards where the magnitude grows, i.e. **towards the source** — and
names **which axis** that is. The sensors do not measure a vector; they measure
`|B|`. That distinction is the whole design.

**It does NOT put out a sign per axis.** This line said so until 2026-09-04 and
it was wrong. The six digital pins are three decisions and their complements:
`COMP_OUT` is `OUT = buffer(IN)`, `OUT_N = NOT(IN)`, instantiated in
`GRADIENT_NAV2.sch` as `x8 VDD XN X XP VSS COMP_OUT`, so `XN` is exactly
`NOT(XP)`. `XP` high means *this axis won the vote*; `XN` is there to drive the
other side of an H-bridge. Telling `+X` from `−X` needs a further comparison —
that is what `GRADIENT_NAV3` does, and it is not instantiated on this die.

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

### `wrdata` writes no header, so a short name list slides silently

`XSCHEM/TEST/figuras.py` names its columns by position:

    CELDAS = ["OPAMt", "OPAM_G100A", "OPAM_G100B", "OPAM_LIN"]
    RAMAS  = ["schematic", "extracted layout"]

Every one of those benches has since grown a THIRD variant -- schematic, v1
layout, **v2 layout**, and v2 is what is on the die. `test_comp_dc.sch` now
writes 6 vectors where the list names 4; `test_opam_g100_dc.sch` writes 12
where it names 8. `wrdata` emits no header, so nothing fails: the names just
slide onto the wrong columns.

What that produces today, if `figuras.py` is re-run:

* the COMP power plot reads `v(OUT2)` -- a VOLTAGE -- as the schematic power,
  and prints ~2500 mW for a 3 mW block;
* the WEIGHT figure's "OUT_N schematic" curve is really the v2 layout's `OUT`;
* the amplifier's `P_OPAM_LIN` is actually OPAM_G100A's supply;
* DECODER and WEIGHT compare against the **v1** layout, not the v2 that ships.

The PNGs saved beside those benches predate the third variant, so they look
right and are stale. **`figuras.py` has not been touched** -- its outputs feed
`doc/opam_g100.pdf` too, and rerunning it would replace good PNGs with wrong
ones. The report does not use them: `reportes/figuras_bloques.py` reads the raw
data with the vector order taken from each bench's own `wrdata` line, and
refuses to load a file whose column count does not match its name list. That
check is the fix; the name lists in `figuras.py` still need the same treatment.

Found 2026-09-02, while building the per-block figures for the report.

### `test_weight.sch` probes the layout branches out of order

Its `wrdata current.txt` line says, in its own comment, "first the four
schematic ones and then the four layout ones, **in the same VA VB VC VD
order**". The layout half is not in that order:

    i(v.x1.Vmeas) i(v.x1.Vmeas1) i(v.x1.Vmeas2) i(v.x1.Vmeas3)
    + @m.xextrc.x31.m0[id] @m.xextrc.x16.m0[id]
    + @m.xextrc.x23.m0[id] @m.xextrc.x24.m0[id]

`x16` and `x23` are the other way round, so the layout series read VA, **VC,
VB**, VD. Cross-comparing every layout branch against every schematic one, in
µA, leaves no doubt:

            esq_VA   esq_VB   esq_VC   esq_VD
    lay_VA    0.46   171.82   171.82   171.82
    lay_VB  171.82   171.82     0.44   171.82
    lay_VC  171.82     0.52   171.82   171.82
    lay_VD  171.82   171.82   171.82     0.84

**It is the probe, not the circuit.** Read in the true order the four branches
agree to within a microamp, and the WE sum node matches between schematic and
layout, as does the whole navigator across its sweep.

(An earlier version of this paragraph argued the point by saying a real VB/VC
swap would change the weighted sum, because the branches were believed to be
binary weighted ×8 ×4 ×2 ×1. They are not — see the next section. That does not
change the conclusion, which rests on the cross-comparison table above, but the
reasoning was wrong and swapping two branches of a majority counter would in
fact change nothing at the sum node.)

It stayed hidden because the figure drew the schematic in one panel and the
layout in another; nobody compares branch to branch across two axes. Splitting
it into one panel per branch, which is what the report now does, made it
obvious on sight. `reportes/figuras_bloques.py` carries the corrected order and
the evidence; **the `.sch` itself is untouched** and still needs the two device
names swapped, or its comment corrected.

Found 2026-09-03.

### WEIGHT is not binary weighted: it is a plain majority counter

Its own bench titles say "the four binary-weighted inputs", `bloques.py` said
so, and the block diagram drew ×8 ×4 ×2 ×1. The data says otherwise, and says
it cleanly. Grouping `test_weight.sch` by the weighted sum a 1-2-4-8 reading
would give:

    sum   3      5      6      9     10     12      ->  WE = 2.166 .. 2.173 V
    sum   7     11     13     14             ->  WE = 1.802 .. 1.810 V

Six different "weights" land on the same WE within 10 mV, and four more do the
same one step down. WE depends only on HOW MANY branches are high. The branch
currents confirm it: all four carry the same ~170 µA, not 1:2:4:8.

So the transfer is a staircase in the COUNT -- 3.006 V at none, then 2.563,
2.168, 1.808, 1.488 -- about 0.38 V per vote, and **the output flips at 3 of
4**. It is majority rule. At the top level the same staircase reads 611 mV per
vote on X and Y but 401 mV on Z; that asymmetry is the same one that made Z
unable to win until the order inside each triple was changed.

Found 2026-09-03, by drawing the four branch currents one per panel instead of
schematic-in-one-panel / layout-in-another. Corrected in `reportes/`; the
`.sch` titles still claim binary weighting.

### A DC sweep of the field must not start at zero

`test_GRADIENT.sch` gained two sweeps that hold the direction and sweep `Vamp`.
Started at exactly 0 they spend the run in gmin stepping and never finish: with
no field the three bridges are identical, so the three amplifiers sit at the
same output and all three comparators land exactly on their trip point. The
operating point is not unique. Starting one step in (20 µV wide, 1 µV fine)
costs nothing and converges.

And read the result carefully: the DC sweep decides correctly at every point,
down to 1 ppm. That is not a sensitivity -- **a `dc` analysis carries no
noise**. The floor is the amplifier's own 222 µVrms input-referred noise over
its 338 kHz bandwidth, which against 5 V of excitation is **44.4 ppm of dR/R**.
That is why the bench's fine window sits at 50 ppm.

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

* **The KLayout deck does not match on the top, and netgen does.** Same devices
  on both sides -- 1442, class by class -- and netgen, which also compares W and
  L, says `Circuits match uniquely`. What fails is the comparer, on twelve
  near-identical analogue chains plus eleven identical clamps. Four causes,
  measured, in **[`lvs-klayout-top.md`](lvs-klayout-top.md)**; one of them is a
  real defect in `XSCHEM/B26_A.sch` (four ports that connect to nothing) and is
  still open. **The chipathon's external LVS runs the KLayout deck, not netgen**,
  so this is a submission risk, not a curiosity.

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
  not in the design. A crashed table leaves **no usable `.lyrdb`**, and a check
  that counts result files reads that as *clean*. So every "63 tables, 0
  violations" this project ever produced was true about what it said and silent
  about `MSLOT.1`. (**Measured 2026-09-01:** it does write a file — an empty
  shell of 464 bytes with **zero rule categories**. Worse than writing none,
  because the file satisfies a file count. Count *categories*, not files; the
  crash is identified by a zero-category file **plus** an `| ERROR |` line
  naming that table. See [`drc-full-deck.md`](drc-full-deck.md).)

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
* **The deck has a SECOND switch that changes the verdict: connectivity.**
  `NW.2b_MV` is *Min. Nwell Space [Different potential]*, 1.7 um; its
  equipotential twin `NW.2a_MV` asks 0.74 um. Which applies depends on knowing
  the potentials, so **without connectivity the deck assumes the worst and
  flags every neighbouring well**. Measured 2026-09-01: the same
  `B26_A_filled3.gds` gave **0** with connectivity and **33 `NW.2b_MV`**
  without it. The eleven clamps each drew four separate n-wells 1.330 um apart
  — all of them `VDD`, the `m=4` of one device — and `esd_layout.py` now draws
  **one** well under the row, which is what `NW.2a_MV` tells you to do
  (*"Merge if the space is less than"*). The cell did not grow and the LEF is
  unchanged. **A sign-off now runs both modes**; the `--no_connectivity` pass
  costs 70 seconds on the filled top. See [`drc-full-deck.md`](drc-full-deck.md).

* **`layouts/` is not what the top reads — `layouts_v2/` is.**
  `esd_layout.py` writes to `layouts/ESD_CDM/`, while `openroad/gds/ESD_CDM.gds`
  is a symlink that `usar_version.sh v2` points at `layouts_v2/ESD_CDM/`. So a
  regenerated block changes nothing on the top until it is copied across. This
  cost a whole integration cycle plus a 17-minute density fill: the clamp was
  verified clean, the top rebuilt, and the DRC still reported the same 33.
  **The block being clean is not the same as the top using it.** Check with
  `sha256sum $(readlink -f openroad/gds/ESD_CDM.gds)`.

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

Measured 2026-09-01. **The deliverable is clean; nothing has to be rebuilt.**

| thing | state | evidence |
|---|---|---|
| `COMP`, `DECODER`, `DECODER_MAX`, `OPAM`, `OPAM_LIN_flat`, `WEIGHT_COMP` | **built, clean** — KLayout LIMPIO, netgen CASAN | `layouts_v2/*/lvs/RESUMEN.txt` |
| `ESD_CDM` | **built, clean** | `layouts_v2/ESD_CDM/lvs/RESUMEN.txt` |
| `OPAM_SUMA` | **broken, and left broken on purpose** — `GRADIENT_NAV2` does not use it | same file |
| `GRADIENT_NAV2` | **rebuilt**, 460.90 x 386.99 um, netgen `Circuits match uniquely` | `out_v2_GRADIENT_NAV2/` |
| **`B26_A_filled3.gds`** — THE DELIVERABLE | rebuilt 2026-09-02 with the merged clamp n-wells, sha `41bef27a…` (it is **no longer** byte-identical to `_filled2`/`_filled`, which were `95ebcf92…`). Archived under `integration/gds/`, DRC filed under its own name | `lvs_config.json -> LAYOUT_FILE`, `info.yaml` |
| — sign-off DRC, **`main`/deep**, with connectivity | **660 rule categories, 0 items**, with `MSLOT.1` and `NW.2b_MV` both among them, so both really ran | `out/drc_B26_A_FILLED/B26_A_filled_main.lyrdb` |
| — density pass | clean | `out/density_B26_A_FILLED` |
| — `MSLOT.1` | **0** (was 11) | `drc_klayout.mslot1_local` |
| — `PR_bndry` | **1** | `def_to_gds.una_sola_frontera()` |
| — LVS netgen | **`Circuits match uniquely`** | `out_integration/lvs_netgen_B26_A.rpt` |
| — sign-off DRC, **`--no_connectivity`** | **0 items** (was 33 `NW.2b_MV` before the clamp fix). The deck passes in BOTH modes now | `out/verif_sinconn_full` |
| — `check_integration.py` | **17 / 17**, 11 through their clamp | script output |
| — current density | 48.00 um of section against 22.10 required | `check_current_density.py` |
| — LVS KLayout | **does not match, and it is not the circuit** | [`lvs-klayout-top.md`](lvs-klayout-top.md) |

Two things were fixed on 31 August and are worth knowing about:

* **The pin escapes are combs, not plates.** Each signal pin gets a Metal2
  escape past the two supply buses, drawn as one solid box over the whole pin.
  On an analogue pad that is eight teeth spanning 44.32 um, so the box came out
  55.7 x 44.3 um — over 30 um in both directions, which is `MSLOT.1`. Eleven
  pads, eleven violations, invisible for weeks because `mslot` crashes in
  split-table mode. `integrate_top.tcl` now draws one 2.54 um finger per tooth
  plus a 2 um spine at the far end that keeps it a single polygon.
* **The four dangling ports are gone from `XSCHEM/B26_A.sch`.** Six `ipin`
  symbols — `XP_IN` … `ZN_IN` — sat in a corner wired to nothing. On this pad
  `<sig>_OUT` is terminal `A`, the pad's data *input* and the one the block
  drives; `<sig>_IN` is the receiver output, unused. The port list is now the
  nineteen pins of `info.yaml` and nothing else.

### What is left, in order

1. **Nothing blocking.** The deliverable passes every check this machine can run.
2. **The KLayout LVS on the top.** It does not match while netgen does, and the
   chipathon's external LVS runs the KLayout deck. Four causes are measured in
   [`lvs-klayout-top.md`](lvs-klayout-top.md); one of them (the dangling ports)
   is fixed, the rest are the comparer, not the layout. **This is the open
   submission risk.**
3. **Two checks that need a bigger machine**, both in
   [`moving-machine.md`](moving-machine.md) §4: the split-table DRC on the filled
   GDS, which loses five tables to memory here, and the KLayout LVS on the filled
   GDS, which does not finish here at all.
4. **The organisers' regenerated padring.** `openroad/padframe/B26_A.def` is
   still the 27 August file, built from the old pin order. What used to block
   them — the two `PR_bndry` shapes — is fixed and pushed.
5. **The LVS run directories have no staleness guard.** `archivar_integracion.py`
   refuses a DRC run older than the GDS it claims to judge — `STALE — the run
   predates this GDS` — and there is no equivalent for LVS. That gap is exactly
   what put a 29 August extraction, two GDS generations old, into
   [`lvs-klayout-top.md`](lvs-klayout-top.md) as if it described the current
   layout. **A run directory older than the GDS is not a verdict about that GDS.**

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
| `LAYOUT_FILE` | `$UPRJ_ROOT/FINAL/openroad/out_integration/B26_A_filled3.gds` |
| `LVS_SPICE_FILES` | `$UPRJ_ROOT/FINAL/openroad/out_integration/B26_A_lvs.spice` — **corrected 2026-09-01**; it used to point at `.../out_v2_GRADIENT_NAV2/GRADIENT_NAV2_lvs.spice` |
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
* **Everything delivered out of `reportes/` ships with a `.txt` of the same
  name beside it**, explaining **in Spanish** what each slide is there to say
  and what to point at while it is on screen — for the English deck too, since
  whoever presents it is the same person. Asked for on 2026-09-02. It is
  generated by the same pass that builds the deck (`guion.py` hooks
  `estilo.OBSERVADOR`, and refuses to write the file if a slide has no line),
  never written afterwards by hand: a narration numbered one slide off is worse
  than no narration.
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

Las dos URL, con qué va en cada repositorio y las trampas de cada subida,
están juntas en [`docs/repositorios.md`](docs/repositorios.md).

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
python3 -c "print(open('FINAL/openroad/out_integration/B26_A_filled4.gds','rb').read(4).hex())"
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

---

## 10. Findings from the 2026-09-04 report pass

### The benches were older than the schematic, and two of them were wrong

`GRADIENT_NAV2.sch` is dated 2026-09-02. `datos_nav2` was 2026-08-22 and
`datos_geo` / `datos_fuente` 2026-08-26, so **every system-level number in the
report described an older revision of the top**. Two changes landed in between:

* the sensor split became the **four rotations** `(1,2,3) (4,1,2) (3,4,1)
  (2,3,4)` — every slot sees each sensor exactly once — where it had been two
  pairs sharing two legs, `(1,2,3) (1,2,4) (3,4,1) (3,4,2)`;
* `XP` and `XN` were swapped to their correct polarity.

`test_NAV2.sch`'s hand-rebuilt navigator had **neither** fix, so
`comprobar_nav2.py` was scoring one wiring against the other's and the
layout-against-schematic comparison was between two different circuits. Both are
fixed now and the checker passes: *the rebuilt navigator is the SAME circuit as
the schematic (31 cells)*. `docs/top-functionality.md` §4/§6,
`XSCHEM_v2/README.md` and the comment at `analizar_caja.py:90` still describe
the old split as current — they are stale, the code itself reads the wiring from
the netlist and is fine.

### The comparator slews; the amplifier does not

`COMP`: **6.3 V/µs rising and falling**, and it is a real slew rate because the
slope is constant to within a percent across the whole 601 ns edge. Anything
computed with `np.gradient` on this file gives ~38 V/µs — that is an artefact of
the non-uniform time step at the edges, not the circuit.

`OPAM_LIN`: **not slew limited at 2 V.** Its edge (102 V/µs schematic, 562 V/µs
layout) is at or above the 456 V/µs that the 36.3 MHz unity-gain crossing would
give on its own, so nothing is holding the output back and there is no slew rate
to quote. Measuring it needed a dedicated analysis — `tran 20p 2.2u 1.95u 20p`
with a 2 V step, added to `test_opam_g100_tran.sch` writing `slew.txt`. The
original `tran 2n 20u` lands thirteen samples on a 10 ns edge and a slope taken
from two of them is not reproducible.

### The axis is claimed from THREE votes of four, not two

Measured over all 48 cases of `umbral_WEIGHT_COMP` — sixteen input combinations
× three temperatures, each swept over VDD 4.5–5.5 V — `WE` falls **389 mV per
vote** (3.043, 2.584, 2.180, 1.815, 1.489 V) and `OUT` flips **between 2 and 3**
in all nine corners without exception. The comment at `WEIGHT.sch:8-17` says the
always-on fifth branch moved the trip to *"an axis wins from TWO votes on"*.
It did not. Requiring 3 of 4 is demanding and is part of why the navigator's
octant hit rate is what it is.

### Where the sensing block actually fails

Driving the three bridge readings independently (the new `v(sel) = 1` mode in
`test_GRADIENT.sch`, 24 cases = 8 sign patterns × 3 magnitude orderings), the
decoder returns `argmin(bx, by, bz)` **in all eight octants, 100 %, up to
dR/R = 1.40 %**. Above that it falls, and the mechanism is visible in the data:
that is where **two amplifiers saturate against the same rail**, at which point
the ordering between them is gone before any comparator sees it and the decision
is left to offset. The layout scoring higher there is not a better layout — its
larger offset happens to break the tie the right way.

### The source figure and its own caption disagreed

`figuras_fuente_rep.py` titled each panel with `mean(|chip − perfect|)` while
`textos.py` quoted `mean(chip) − mean(perfect)` weighted by `|sin(ang)|` — 0.58°
against 0.25° at 3 mm, on the same slide. The signed weighted form is the right
one (the absolute value counts a sample where the chip lands *closer* than the
ideal as if it were error) and both now use it.

And the number that matters there is neither: a **perfect** chip already misses
by 14° at 3 mm, because the chip does not measure a gradient at a point — it
takes a finite difference over a 1 mm box, and the field curves sharply across
it. Only the difference between the two curves belongs to the circuit.

### The `_V2_` extracted copies had been stale for weeks — RESOLVED

This one produced two wrong conclusions in a row and is worth reading in full.

`XSCHEM/TEST/preparar_extraidos.sh` makes the `<BLOCK>_V2_*.spice` copies the
system benches include: it renames the subcircuit so v1 and v2 can live in one
netlist, and normalises the port order to v1's. It takes that order from
`$V1/<BLOCK>/mag/<BLOCK>_<suffix>.spice`, with

    V1=/foss/designs/a_zonetic2026/layouts     # lowercase

**On this machine `layouts/` and `Layouts/` are two different directories**
(inodes 12597222 and 12583050). `layouts/` holds only `ESD_CDM`; every v1 block
is in `Layouts/`. §2 of this file says they are the same inode, which was true
on WSL2/drvfs and is **not** true here. So every lookup failed, the script
aborted with `12 file(s) not prepared`, and the `_V2_` copies silently stayed at
whatever they were the last time it worked — **2026-08-26 16:11**, before the
fifth WEIGHT branch went in on 08-26 23:54 and before the 08-29 layout rebuild.

The benches were therefore simulating a `WEIGHT_COMP` with four branches while
the schematic, the layout and the GDS all had five. Fixed by pointing `V1` at
`Layouts`. Verified on the gate nets of the w=2.48u branch devices:

    WEIGHT_COMP_pex_rc.spice     (29-ago, the real layout)   VA VB VC VD VDD
    WEIGHT_COMP_V2_...  (26-ago, what the bench was reading)  VA VB VC VD

**The GDS was never affected.** `openroad/gds/WEIGHT_COMP.gds` is a symlink to
`layouts_v2/WEIGHT_COMP/WEIGHT_COMP_flat_gf180.gds` (2026-08-29 02:17), the
five-branch version; `B26_A_filled3.gds` is 09-01 18:18; and the top LVS
(`out_integration/lvs_netgen_B26_A.rpt`, 09-01 18:26) reports **Circuits match
uniquely** over **1442 devices**, comparing the extracted layout against a
reference derived from the schematic that has the fifth branch. A missing branch
would be nine devices short and netgen would have said so.

**What the two wrong conclusions were**, so neither gets repeated:

1. *"The axis is claimed from THREE votes of four, and the schematic comment
   saying two is wrong."* Backwards. `umbral_WEIGHT_COMP/u001.txt` was written
   at 23:48 and `WEIGHT.sch` saved at **23:54** — the data was six minutes older
   than the circuit. Re-run, the buffer flips **between 1 and 2 votes at all
   fifteen VDD/temperature corners**, which is exactly what the fifth branch was
   added to do. The comment was right.
2. *"The layout navigator never trips its own threshold, cause unknown, OPEN."*
   An artefact of the stale `_V2_` copy: a four-branch counter reads one step
   high, never reaches the trip, and the pins sit at 75.6 / 49.9 / 73.5 %. With
   the copies refreshed the six digital outputs agree on **99.45 %** (X, Y) and
   **98.89 %** (Z), 2–4 degrees out of 360, and the disagreement sits on the
   sector boundaries where the decision is on a knife edge. Chain outputs agree
   on 99.72 %.

**The lesson is the same one this file already records twice**: a stale input
that still parses produces numbers, not errors. `preparar_extraidos.sh` printed
its failure every single run and the benches ran anyway on whatever copies
happened to be on disk. It should refuse to leave a `_V2_` file older than the
extraction it derives from.


### Los límites de electromigración SÍ están en el PDK, en los tech-LEF

No en el DRC — ninguna regla los comprueba, y por eso hace falta
`check_current_density.py`. Están declarados en, por ejemplo,
`/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/techlef/*__max.tlef`:

```
Metal1..Metal4   DCCURRENTDENSITY AVERAGE 0.67      (mA por µm de ancho)
Metal5           DCCURRENTDENSITY AVERAGE 1.5
Via1..Via4       DCCURRENTDENSITY AVERAGE 0.18      (mA por corte)
```

**Son idénticos en los tres corners: no dependen de la temperatura.** La tabla
que traía `integrate_top.tcl` — «2.09 / 1.00 / 0.67 a 85 / 110 / 125 °C» —
confunde los ejes: 1.00 y 0.67 son el valor **AC** y el **DC** de la misma capa,
y 2.09 y 0.58 no aparecen en ningún sitio del PDK. El «Integration README» que
cita como fuente no está en disco. Por suerte el número que acabó usándose (0.67
DC) es el correcto para una alimentación continua; el razonamiento no lo era.

`check_current_density.py` ahora **los lee del tech-LEF** en vez de tenerlos
escritos a mano.

### Tres errores del chequeo de corriente, corregidos

Ninguno era del layout:

* **Sumaba micras de capas distintas contra un único límite.** Una micra de
  Metal5 lleva 1.5 mA y una de Metal4 solo 0.67; sumarlas y compararlas con el
  límite de Metal4 suspendía mallas que iban sobradas. Ahora suma **corriente**,
  pesando cada tramo por el límite de su capa.
* **`SIDE_UM = 1110.0` estaba cableado**, el lado del área de usuario. Sobre el
  DEF de un bloque el corte caía fuera del die y devolvía ceros con cara de
  fallo. Ahora lee `DIEAREA` del propio DEF, así que sirve para cualquier top.
* **Aplicaba al bloque la anchura de señal que promete la integración.** Son dos
  reglas distintas, `ANCHO` (0.38 µm) y `ANCHO_INT` (0.84 µm), y comparar la
  primera contra la segunda suspendía dos capas que estaban bien.

Y una cosa que no miraba y ahora sí: **cuántos cortes de vía hay**, leyendo el
`ROWCOL` de cada definición del bloque `VIAS`. Contar instancias sin eso
subestima por un factor de doce.

### El layout de la v3: `openroad/out_v2_GRADIENT_NAV2_V3/`

Prueba, no aceptada, fuera del die. Se construye con

```
make top T=GRADIENT_NAV2_V3 V=v2 SCHDIR=../XSCHEM_v3
```

`SCHDIR` es lo único que hubo que añadir al flujo: el esquemático de ese top
vive en `XSCHEM_v3/`. El resto ya leía `TOP_CELL`. Dos generalizaciones que
convenía hacer de todas formas:

* `load_design.tcl` saltaba el LEF cuyo nombre coincidía con el top. Con más de
  un top eso deja de valer: ahora salta **cualquier LEF sin su `.lib`**, que es
  como se reconoce el abstracto de un top.
* `spice_to_verilog.py`, `lvs_netgen.py` y `decap_fill.py` leen `SCHDIR_ABS`.

Dimensionado al **doble del pico medido**, 31 mA (el bloque consume 14.97 mA de
media y 15.50 de pico). Resultado, contra la misma medida sobre la v2, **en el
peor corte de cada eje**:

```
                        v2 (el die)          v3          pide 31 mA
Metal4 vertical VDD  24.0 um  16.1 mA   48.08 um 32.21 mA    v2 CORTO
Metal4 vertical VSS  24.0 um  16.1 mA   46.89 um 31.42 mA    v2 CORTO
Metal5 horiz.   VDD  24.0 um  36.0 mA   39.95 um 59.92 mA
Metal5 horiz.   VSS  24.0 um  36.0 mA   78.14 um 117.21 mA
pin del bloque VDD    3x3 um   4.5 mA   7 puertos 104.77 mA  v2 CORTO
pin del bloque VSS    3x3 um   4.5 mA   4 puertos  58.61 mA  v2 CORTO
vias Metal3-Metal4      612   110 mA    960-1130  173-203 mA
vias Metal4-Metal5      832   150 mA   4704-5742  847-1034 mA
puntos de contacto        1                  2 (peor caso)
die                 460.90 x 386.99      460.90 x 386.99
```

DRC limpio (63 tablas, 0 items, con y sin desacoplo), LVS `Circuits match
uniquely` en las dos pasadas — 1407 = 1407 sin desacoplo y 1409 = 1409 con él,
883 nets las dos veces —, `route_drc.rpt` de 0 bytes.

**Las filas van espejadas.** Las estanterías alternan `R0` y `MX`, así que cada
canal lleva **un solo net**: los raíles abutan VDD contra VDD y VSS contra VSS,
y en vez de una pareja VDD/VSS a 2 µm el canal lleva un strap dedicado de 10 µm.
La separación entre nets contrarios pasa de 2 µm a 43.46 µm. Ningún canal lleva
los dos nets. Abutición medida: 86.8 % en los dos canales de puro `OPAM`,
62.6 % el peor canal interior (los que mezclan alturas sólo abutan con las
celdas más altas).

**Lo que descubrió el trabajo:** el pin de alimentación del bloque era un
cuadrado de 3×3 µm de Metal5 — 4.5 mA para un bloque que pide 31 — porque el
flujo bajaba al borde del die **un solo** strap. Y cada macro recibía **un solo
punto de contacto**, con lo que su barra de Metal3 de 0.9 µm llevaba toda su
corriente de punta a punta.

**Y cuatro trampas, todas silenciosas, que sólo salieron al espejar:**

* **`-offset` de `add_pdn_stripe` es el EJE del strap, no su borde izquierdo.**
  Con 3 µm no se nota; con 8 el strap se sale media anchura, pisa la placa MIM
  de al lado y pdngen lo parte. El floorplan informaba de 47 µm de VDD vertical
  y por el die cruzaban 1.29. Y la comprobación de límites de pdngen **sí** usa
  `offset + ancho`: coloca por el eje y comprueba por el borde.
* **El `ORIGIN 1.260` del LEF.** odb NO se lo aplica a `getObstructions` pero
  `getBBox` ya está colocado; sumar uno a otro corre todos los bloqueos de
  Metal4 1.26 µm a la derecha. Afectaba a las bandas libres y al halo de los MIM.
* **El halo de los MIM no espejaba**: con `MX` la placa está a `alto − y`.
* **pdngen borra los tramos de strap donde no le pone vía, sin avisar.** Entre
  dos canales del mismo net hay dos estanterías cuyos raíles son del otro, así
  que el tramo del medio se queda sin ninguna vía y desaparece. `floorplan_top.tcl`
  los **cose** después de `pdngen`, sólo las columnas que caen enteras en una
  banda libre de bloqueo Metal4 a toda altura.

**Y el propio comprobador estaba mal:** `check_current_density.py` cortaba el
die en `max(ancho, alto) / 2`, que sobre un die rectangular no es el centro de
ningún eje. Daba 30.15 mA de VSS vertical donde el peor corte real llevaba 16.
Ahora barre el eje entero, dentro del vano de cada net, y reporta el peor corte
con su posición.

### Y la v3 ES el chip: `B26_A_filled4.gds`

Desde el 2026-09-07 la integración lleva `GRADIENT_NAV2_V3` dentro.
`lvs_config.json → LAYOUT_FILE` e `info.yaml` apuntan a
`out_integration/B26_A_filled4.gds`; el `_filled3` de la v2 queda archivado en
`integration/gds/2026-09-02_06/` con su sha `41bef27a…`.

**La integración ya no tiene el macro a fuego.** Sale del entorno, como el resto
del flujo:

```
MACRO=GRADIENT_NAV2_V3 MACRO_OUT=out_v2_GRADIENT_NAV2_V3 \
    python3 scripts/integrate_padframe.py
MACRO=GRADIENT_NAV2_V3 openroad -no_init -exit scripts/integrate_top.tcl
```

Lo leen `integrate_padframe.py`, `integrate_top.tcl`, `check_integration.py` y
`lvs_reference_integration.py`. `macro_lef.py` pasó a `TOP_CELL`/`TOP_OUT`/
`SCHDIR_ABS` como los demás. Y `XSCHEM/B26_A.sch` instancia
`XSCHEM_v3/GRADIENT_NAV2_V3.sym`. Los dos bloques conviven: cuál entra lo dice
`MACRO=`, no cuál de los dos enlaces de `gds/` exista.

**Se destrabó el cuello que quedaba.** `integrate_top.tcl` alimentaba el bloque
por **un solo** puerto —se quedaba con el de más a la izquierda—: 3 µm de Metal5,
4.5 mA contra los 31 que consume. Ahora ata todos los que el abstracto expone:

```
block VSS: 4 puertos, 39.07 um -> 58.61 mA, 1066 via4 -> 191.88 mA
block VDD: 3 puertos, 29.95 um -> 44.93 mA,  806 via4 -> 145.08 mA
```

Para que eso fuera posible, `macro_lef.py` escribe **un `PORT` por caja**: antes
se quedaba con la última del DEF, que ni siquiera tenía por qué ser la que mejor
le viene al bus.

**Y un fallo de contabilidad que inflaba el informe.** `extend_all_to_edge`
creaba la caja dentro del mismo `foreach` que recorría los hilos, así que el
recorrido se encontraba lo que acababa de insertar y lo volvía a estirar: VDD
salía con «7 puertos, 69.85 µm → 104.77 mA» de los que solo 3 eran distintos. Lo
de verdad son 3 puertos y 29.95 µm → 44.92 mA. Sigue estando por encima de 31,
pero el número que se publicaba no existía.

| B26_A con la v3 | Resultado |
|---|---|
| DRC KLayout, split-table | **0 items**, 63 tablas |
| DRC densidad | **limpio** |
| LVS netgen | **`Circuits match uniquely`**, 1442 = 1442 dispositivos, 894 = 894 nets |
| `check_integration.py` | **17/17** señales (11 por su clamp), **50/50** tie-offs |
| Ruteo | `route_drc.rpt` de 0 bytes |
| Densidad de corriente a 31 mA | los cuatro conductores, en el peor corte |
| Relleno de densidad | las siete reglas, de 2–13 % a 31–42 % |

**Lo que sigue pendiente:** nada de la alimentación. Queda el LVS de KLayout
sobre el top, que no cuadra mientras netgen sí, y es el riesgo de entrega que ya
estaba (ver `lvs-klayout-top.md`).
