# GDS_GENERATOR

The **tooling** behind the B26 Zotnetic chip (GF180MCU-D, SSCS Chipathon 2026),
kept apart from the design itself. The design — schematics, layouts, netlists,
GDS — lives in `AnBuiUCI/sscs-2026-zotnetic` under `FINAL/`. **This repository is
what builds it, and everything worth knowing about how.**

If you are picking this work up cold, read **[`docs/HANDOFF.md`](docs/HANDOFF.md)**
first. It is written for exactly that: what the chip is, where every tree lives,
the state of every block with the evidence for it, the one thing to do next, and
every fact in this flow that cost a full build to learn.

## What is here

| path | what it is |
|---|---|
| `zotnetic_layout/` | the **analog layout generator**. Reads a SPICE netlist and draws the cell: placement, abutment, routing, MIM capacitors, poly resistors. `build_block.py` is the entry point. |
| `flow_scripts/` | the **OpenROAD flow** of the top level: collateral, floorplan, route, DEF-to-GDS, decoupling fill, density fill, DRC and LVS drivers, padring integration, the ESD clamp generator (`esd_layout.py`) and the electromigration check (`check_current_density.py`). A copy of `FINAL/openroad/scripts/` plus its `Makefile`, so the flow can be read without the design tree. |
| `docs/` | the knowledge. `HANDOFF.md` (start here), `drc-full-deck.md` (**how to run the sign-off DRC so that it actually runs** — read it before believing a clean), `openroad-flow.md` (the long logbook of the top level), `xschem-v2.md`, `top-functionality.md`. `zotnetic_layout/DRC_KLAYOUT.md` covers the block-level DRC. |

## How to run the generator

`env -u PYTHONPATH` is **mandatory**. Without it gdsfactory 9.44 shadows the
pinned 9.2.2 and the geometry silently changes.

```bash
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python build_block.py OPAM_LIN_flat
env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python build_block.py OPAM_LIN_flat --v2
./run_lvs.sh OPAM_LIN_flat
./run_lvs.sh --v2 OPAM_LIN_flat
```

`build_block.py` writes the GDS, the flat netlist and **the LVS reference** in
one act, so the reference and the layout can never drift apart.

## Four rules that are not obvious

Every one of these has produced a **false clean** in this project.

* **Never read the SPICE that is on disk. Re-export it from xschem first** — the
  schematic may have moved under you.
* **`run_lvs.py` returns exit code 0 even on a mismatch.** The verdict comes from
  grepping the log for `Netlists don't match` / `Congratulations! Netlists match`.
* **A sign-off DRC in split-table mode does not run `MSLOT.1`** — the PDK's
  `mslot` table crashes, and a crashed table writes no `.lyrdb`, which counts as
  zero violations. The verdict run is `DRC_MODE=deep DRC_THR=1 DRC_MP=1`.
  See `docs/drc-full-deck.md`.
* **Check the boundary before shipping any GDS.** `PR_bndry` is layer 0/0 and
  exactly one is allowed at top level; two of them is what stopped the
  organisers from regenerating this team's DEF. `def_to_gds.py` now refuses to
  write a GDS with more than one.

`docs/HANDOFF.md` §3 has the rest, each one paid for with a build.

## What is deliberately not here

Generated artefacts — GDS, `.lyrdb`, extraction databases. They are regenerated
by the flow, they weigh hundreds of megabytes, and a stale one is exactly how a
DRC and an LVS come to pass against the wrong circuit. The submission
deliverables live in the design repository.
