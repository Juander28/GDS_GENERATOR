#!/usr/bin/env python3
"""Reference netlist of the top, ready for an external LVS.

The chipathon runs its own LVS reading `lvs_config.json` from the repo root, and
there you must tell it **what** to compare the GDS against. The netlist xschem
exports is not usable as is: it carries three things that are not part of the
circuit and that stop the deck's reader from even finding the cell.

* the top cell `.subckt` comes out **commented** (`**.subckt GRADIENT_NAV ...`),
  which is how xschem exports from the CLI;
* 0 V sources (`Vmeas net11 GND 0`) used as current probes:
  `Not a known element type: 'V'`. A 0 V source is electrically a wire, so the
  right thing is not to drop it but to **merge the two nets**, which is what
  layout tiene ahi;
* tarjetas de simulacion (`.save`, `.control`, `.tran`...).

And it has to be flattened too: the top layout is **a single cell** (see
`def_to_gds.py::flatten_all`), so the reference has to be one as well.

None of this is invented here: it is exactly `lvs_klayout.prepare()`, the same
patching KLayout's LVS already uses to compare this very top locally. This file
just writes it to a stable, versioned place so the external LVS can find it.
fuera pueda apuntarle.

**It is regenerated, not edited.** The schematic changes and the netlist has to
change with it; a hand-tweaked reference netlist is an elegant way of making
the LVS lie.

    python3 scripts/lvs_reference.py        # -> out/GRADIENT_NAV_lvs.spice
"""

from __future__ import annotations

import sys
from pathlib import Path

from lvs_klayout import OUT, ROOT, TARGETS, TOP, prepare

#: Cell and directory come from the environment, as everywhere else in the flow.
CELL = TOP
DESTINO = OUT / f"{CELL}_lvs.spice"


def main() -> int:
    _, ref = TARGETS[CELL]
    if not ref.exists():
        sys.exit(f"xschem netlist missing: {ref}\n"
                 f"  export it from the schematic before running this")

    clean = prepare(ref, CELL, ROOT / "work_lvs")
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(clean.read_text())

    lines = DESTINO.read_text().splitlines()
    cabecera = next((l for l in lines if l.lower().startswith(".subckt")), "")
    if CELL not in cabecera:
        sys.exit(f"the generated netlist does not declare '.subckt {CELL}' -- "
                 f"algo cambio en xschem o en prepare()")
    device_lines = sum(1 for l in lines
                       if l[:1] in "MmXxCcRrDdQq" and not l.startswith("*"))
    print(f"  {DESTINO}")
    print(f"  {cabecera.split()[1]}: {len(cabecera.split()) - 2} ports, "
          f"{device_lines} devices, {len(lines)} lines")
    print(f"  source: {ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
