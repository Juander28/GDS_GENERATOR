"""Prueba headless del flujo completo (sin GUI).

Uso:
    python test_flow.py [archivo.spice] [pdk] [carpeta_salida]
    python test_flow.py examples/bias.spice gf180 ./out

Verifica: parsea, coloca, rutea, exporta GDS y lo recarga para confirmar que la
celda top existe y tiene geometria.
"""

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")


def main():
    spice = sys.argv[1] if len(sys.argv) > 1 else "examples/bias.spice"
    pdk = sys.argv[2] if len(sys.argv) > 2 else "gf180"
    out = sys.argv[3] if len(sys.argv) > 3 else "./out"

    from coil_layout.flow import run_flow

    print(f">> Flujo: {spice}  pdk={pdk}  out={out}")
    res = run_flow(spice, pdk, out)
    nl, lay = res["nl"], res["lay"]

    print(f"   transistores: {len(nl.devices)}")
    print(f"   nets:         {len(lay.nets)}")
    print(f"   abutidas:     {sorted(lay.abutted_nets)}")
    print(f"   tamano:       {lay.component.dxsize:.2f} x "
          f"{lay.component.dysize:.2f} um")
    print(f"   GDS:          {res['gds']}")
    print(f"   PNG:          {res['png']}")
    print(f"   reporte:      {res['report_path']}")

    # recargar el GDS para validar
    import gdsfactory as gf
    reloaded = gf.import_gds(res["gds"])
    npoly = sum(len(v) for v in reloaded.get_polygons(by="tuple").values())
    assert npoly > 0, "el GDS recargado no tiene geometria"
    print(f"   GDS recargado OK: {npoly} poligonos en celda "
          f"'{reloaded.name}'")
    print(">> OK")


if __name__ == "__main__":
    main()
