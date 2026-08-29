# OpenROAD collateral for the analog macros.
#
#   make collateral   regenerate LEF / Liberty / Verilog from the layouts
#   make netlist      regenerate the top SPICE netlist from the schematic
#   make verilog      regenerate the top Verilog from the xschem netlist
#   make decap        decoupling capacitors in the gaps between macros
#   make check        load everything in OpenROAD and list the macros
#   make floorplan    place the whole top, build the power grid, write the DEF
#   make route        place_pins + global_route + detailed_route
#   make gds          DEF -> GDS, with the real layout inside every macro
#   make top          verilog + collateral + floorplan + route + gds
#   make drc          KLayout sign-off DRC on the four blocks and the top
#   make drc-magic    magic DRC, a second opinion with a different deck
#   make lvs          netgen LVS on the four blocks and the top
#   make lvs-ref      reference netlist for the external chipathon LVS
#   make probar       breaks the layout on purpose: checks that DRC/LVS notice
#   make probar-drc   the same plus the two DRC tests (~15 min)
#   make check-all    the three above
#   make clean        remove generated outputs (not the collateral)

#  Which version of the blocks the top is built from.
#
#      make top          the top with the v1 blocks (out/)
#      make top V=v2     the top with the v2 blocks (out_v2/)
#
#  Both coexist: output goes to a different directory and the `gds/` links are
#  repointed before each run. What canNOT be skipped is regenerating the
#  collateral when switching version -- the v2 blocks are a different size and a
#  stale LEF would describe macros of the wrong size -- and that is why
#  `collateral` records it in `lef/.version` and everything else checks it.
#  And which TOP gets built:
#
#      make top T=GRADIENT_NAV2 V=v2    the navigator with the linear chain
#
#  `GRADIENT_NAV` builds four GRADIENT blocks, with the 98 dB OPAM;
#  `GRADIENT_NAV2` is the same schematic with GRADIENT2, that is with
#  OPAM_LIN_flat. Each top/version combination gets its own directory, so that
#  todas puedan coexistir y compararse.
V ?= v1
T ?= GRADIENT_NAV
BASEDIR := $(if $(filter v2,$(V)),out_v2,out)
OUTDIR  := $(if $(filter GRADIENT_NAV,$(T)),$(BASEDIR),$(BASEDIR)_$(T))
export TOP_OUT  = $(OUTDIR)
export TOP_CELL = $(T)

OPENROAD := /foss/tools/bin/openroad
PYTHON   := python3
# KLayout's Python module lives in the project venv; PYTHONPATH has to be
# dropped or the system packages shadow it (see zotnetic_layout/DRC_KLAYOUT.md).
KPYTHON  := env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python

.PHONY: all top verilog netlist decap collateral check floorplan route gds fill \
        comprobar-version \
        drc drc-magic drc-density lvs lvs-klayout lvs-ref probar probar-drc \
        check-all clean

all: verilog collateral check

top: verilog collateral floorplan route gds fill lvs-ref

#  The top netlist is ALWAYS REGENERATED from the schematic. The `.spice` on
#  disk is never reused: the schematic now carries a code block that
#  `decap_fill.py` writes with the decoupling transistors, and a stale netlist
#  would have LVS compare today's GDS against yesterday's circuit.
#  xschem sometimes returns code 10 with the file perfectly written, so the
#  verdict is the file's DATE, not its exit code.
netlist:
	@cd ../XSCHEM && 	  rm -f simulation/$(T).sch/$(T).spice && 	  xschem -n -s -q -o simulation/$(T).sch $(T).sch >/dev/null 2>&1; 	  test -s simulation/$(T).sch/$(T).spice 	    || { echo "  ERROR: xschem did not regenerate simulation/$(T).sch/$(T).spice"; exit 1; }
	@echo "  netlist: ../XSCHEM/simulation/$(T).sch/$(T).spice"

#  The decoupling fill: drops transistors into the gaps between macros and
#  writes into the schematic the block with those SAME transistors, so that LVS
#  matches by construction. Runs AFTER the GDS and before the density fill.
#  densidad.
decap:
	$(KPYTHON) scripts/decap_fill.py $(ARGS)

verilog: netlist
	$(PYTHON) scripts/spice_to_verilog.py

collateral:
	./scripts/usar_version.sh $(V)
	$(PYTHON) scripts/patch_techlef.py
	$(KPYTHON) scripts/build_collateral.py
	@echo $(V) > lef/.version

#  Firewall: any step that reads the LEF first checks that the collateral was
#  generated with the SAME version being asked for. Without this, a `make route
#  V=v2` after a v1 `make collateral` would go ahead and place macros of the
#  wrong size.
.PHONY: comprobar-version
comprobar-version:
	@test -f lef/.version || { echo "  ERROR: no collateral. Run 'make collateral V=$(V)'"; exit 1; }
	@test "$$(cat lef/.version)" = "$(V)" || { \
	  echo "  ERROR: collateral is version $$(cat lef/.version) and you asked for $(V)."; \
	  echo "         Corre 'make collateral V=$(V)' antes."; exit 1; }

check:
	$(OPENROAD) -no_init -exit scripts/load_design.tcl

floorplan: comprobar-version
	$(OPENROAD) -no_init -exit scripts/floorplan_top.tcl

route: comprobar-version
	$(OPENROAD) -no_init -exit -threads 4 scripts/route_top.tcl

gds: comprobar-version
	$(KPYTHON) scripts/def_to_gds.py $(OUTDIR)/$(T)_routed.def $(OUTDIR)/$(T).gds

#  The density fill runs AFTER the GDS and touches nothing upstream: it reads
#  out/GRADIENT_NAV.gds and writes out/GRADIENT_NAV_filled.gds, which is the
#  submission file. The starting one stays for the debug loop.
fill:
	$(KPYTHON) scripts/fill_density.py

#  ARGS lets you ask for one specific target instead of the whole list:
#
#      make drc T=GRADIENT_NAV2 V=v2 ARGS=GRADIENT_NAV2
#
#  Without this `make lvs` ALWAYS ran the four blocks and there was no way to
#  ask for the top, which is why the GRADIENT_NAV2 LVS had never been run.
drc:
	$(KPYTHON) scripts/drc_klayout.py $(ARGS)

#  Density rules are a separate pass: the deck does not run them unless asked.
#  magic is no second opinion here -- its GF180 techfile carries not a single
#  density rule.
drc-density:
	$(KPYTHON) scripts/drc_klayout.py --density $(T)_FILLED

drc-magic:
	$(PYTHON) scripts/drc_magic.py $(ARGS)

lvs:
	$(PYTHON) scripts/lvs_netgen.py $(ARGS)

lvs-klayout:
	$(PYTHON) scripts/lvs_klayout.py $(ARGS)

#  Reference netlist for the EXTERNAL LVS (the chipathon one, which reads
#  lvs_config.json from the repo root). Chained into `top` on purpose: if it
#  goes stale, the external LVS compares today's GDS against last week's
#  schematic and says it matches.
lvs-ref:
	$(PYTHON) scripts/lvs_reference.py

#  Breaks the layout on purpose and checks that the checks notice. A "clean" is
#  only worth something if you know that tool would have flagged the fault.
probar:
	$(PYTHON) scripts/probar_verificacion.py

#  Same but adding the two DRC tests, which take about 15 minutes: one with a
#  hand-inserted violation (it must see it) and one on the GDS with the short
#  (it must come out CLEAN, because DRC does not see a short).
#  A separate target and not an option: `make probar --con-drc` does not work,
#  make thinks `--con-drc` is one of its own options and aborts.
probar-drc:
	$(PYTHON) scripts/probar_verificacion.py --con-drc

check-all: drc drc-magic drc-density lvs

clean:
	rm -rf out work work_drc work_lvs work_prueba
