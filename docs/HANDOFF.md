# HANDOFF — where this design stands, and how to pick it up cold

Last updated **2026-08-29**. Written so a chat that has never seen this tree can
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

## 4. The secondary ESD: the organisers' cell, adopted as drawn

The rule the user set: **run DRC and LVS on their GDS; if it passes, use it as
it is; redraw it only if it fails.** It passed, so it is used.

    repo    sscs-ose/sscs-chipathon-2026, commit aa834f5
    path    resources/Integration/Chipathon2025_pads/magic/secondary_ESD.gds
    cell    io_secondary_5p0, 75.65 x 85.35 um = 6457 um2

* **DRC**: 0 violations, 63 rule tables, KLayout sign-off deck.
* **LVS**: `Congratulations! Netlists match` — against a reference that
  describes what is **drawn**.
* **Their published schematic does not match their own GDS.** It declares
  `XR1 ppolyf_u W=16e-6 L=4e-6`; the drawn resistor is **40 x 10 um** (same
  0.25 squares, same 87.5 ohm, different geometry), and it uses `m=4` on the
  diodes where LVS wants four explicit instances. **Worth reporting upstream.**
* `openroad/scripts/esd_jacket.py` wraps their cell and adds **only**: the shift
  to origin (0,0), a copy of each port label on datatype 0, and one Metal3
  landing pad per port with its via stack. Not one polygon of their devices is
  touched.
* Pin mapping: their `ASIG5V` is our `PAD`; their `to_gate` is our `CORE`.
* Area cost: 6457 um2 each against 501 um2 for our own `ESD_CDM`, times 11
  instances. Our `esd_layout.py` and `XSCHEM_v2/ESD_CDM.sch` are **kept, not
  deleted** — they are simply not what gets fabricated.

Vendored at `layouts_v2/io_secondary_5p0/` with `README_ORIGEN.txt` beside it.
**It is not in `layouts/` (v1).** If a v1 flow ever needs it, copy it there.

---

## 5. Where the flow stands, block by block

Measured 2026-08-29.

| thing | state | evidence |
|---|---|---|
| `OPAM_LIN_flat` v1 (`layouts/`) | **built, clean** — 1 k sheet, KLayout LIMPIO, netgen CASAN | `layouts/OPAM_LIN_flat/lvs/RESUMEN.txt`, 05:57 |
| `OPAM_LIN_flat` v2 (`layouts_v2/`) | **built, clean**, 86.94 x 48.71 um | `layouts_v2/.../lvs/RESUMEN.txt`, 06:41 |
| `io_secondary_5p0` | **vendored + jacket + LEF** | `lef/io_secondary_5p0.lef`, 10:22 |
| collateral (`lef/`, `verilog/`) | **regenerated** for every block | 10:22–10:23 |
| `GRADIENT_NAV2` floorplan | **re-done** | `out_v2_GRADIENT_NAV2/GRADIENT_NAV2.def`, 10:23 |
| `GRADIENT_NAV2` route / GDS | **STALE — from 2026-08-27.** The rebuild was interrupted right after the floorplan. | `GRADIENT_NAV2_routed.def`, `GRADIENT_NAV2.gds` |
| `B26_A` integration | **STALE — from 2026-08-28**, i.e. older than the new amplifier and older than the ESD adoption | `out_integration/B26_A.gds` |
| `B26_A_filled.gds` density | **passes**: 0 violations on the density pass | `out/density_B26_A_FILLED` |
| `B26_A_filled.gds` sign-off DRC | **57 x `M2.2b`** on the 03:21 file. Cause found and fixed in `fill_density.py` (06:44); the fill has to be re-run and re-checked. | `out/drc_B26_A_FILLED` |

### THE ONE THING TO DO NEXT

The top rebuild is **half-done**. Finish it, in this order, and everything
downstream follows:

```bash
cd /foss/designs/a_zonetic2026/openroad
make route T=GRADIENT_NAV2 V=v2
make gds   T=GRADIENT_NAV2 V=v2
make decap T=GRADIENT_NAV2 V=v2
make fill  T=GRADIENT_NAV2 V=v2
make lvs-ref T=GRADIENT_NAV2 V=v2

# then the integration on top of it
openroad -no_init -exit scripts/integrate_top.tcl
env -u PYTHONPATH python3 scripts/def_to_gds.py \
    out_integration/B26_A_routed.def out_integration/B26_A.gds
TOP_OUT=out_integration TOP_CELL=B26_A env -u PYTHONPATH python3 scripts/fill_density.py
make lvs-ref T=B26_A TOP_OUT=out_integration

# and the four checks, which check four DIFFERENT things
make drc         T=B26_A TOP_OUT=out_integration ARGS=B26_A_FILLED
make drc-density T=B26_A TOP_OUT=out_integration
make lvs-klayout T=B26_A TOP_OUT=out_integration ARGS=B26_A_FILLED
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python scripts/check_integration.py
```

`make fill` on the 1110 x 1110 die takes about **three hours** and ~1.7 GB of
RAM. Run it in the background.

`openroad/README.md` still carries a section titled *"The schematic is AHEAD of
the GDS"*. Three of its four items are still true (the top is not rebuilt); the
fourth, the 1 kohm amplifier, is now built. **Delete that section, and its
"What that means for the files here" sub-section, the moment the top is rebuilt.**

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
eleven `io_secondary_5p0` clamps — so its reference comes out of xschem through
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
  documentation, not for the PDFs or the generator scripts.

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

LFS is not needed: the largest file is `B26_A_filled.gds` at ~42 MB, under
GitHub's 100 MB limit. `FINAL/.gitattributes` declares `*.gds binary` so that
line-ending normalisation cannot corrupt a GDS.
