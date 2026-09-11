#!/usr/bin/env python3
"""Rasteriza un GDS a PNG, para poder mirarlo sin abrir KLayout.

Usa la paleta de la plantilla (`librelane/gf180mcu_render.lyp`), que es la que
el fabricante usa para sus propias imagenes, asi que los colores significan lo
mismo que en su documentacion.

    python3 flow/render.py [out/quarter.gds [out/quarter_layout.png [ancho]]]
"""

from __future__ import annotations

import sys
from pathlib import Path

import klayout.db as kdb
import klayout.lay as klay

WS = Path(__file__).resolve().parent.parent
LYP = WS / "librelane/gf180mcu_render.lyp"


def main() -> int:
    g = Path(sys.argv[1]) if len(sys.argv) > 1 else WS / "out/quarter.gds"
    png = Path(sys.argv[2]) if len(sys.argv) > 2 else g.with_name(g.stem + "_layout.png")
    ancho = int(sys.argv[3]) if len(sys.argv) > 3 else 1400
    if not g.exists():
        sys.exit(f"no hay GDS en {g} — corre antes flow/gds.py")

    lv = klay.LayoutView()
    lv.load_layout(str(g), 0)
    if LYP.exists():
        lv.load_layer_props(str(LYP))
    lv.max_hier()

    #  La caja del LAYOUT, no la de la vista: `lv.box()` devuelve el
    #  rectangulo de la ventana, que arranca cuadrado, y con el la imagen sale
    #  con la proporcion equivocada y el die deformado.
    ly = kdb.Layout()
    ly.read(str(g))
    caja = ly.top_cell().dbbox()
    alto = int(round(ancho * caja.height() / caja.width()))
    lv.set_config("background-color", "#ffffff")
    lv.set_config("grid-visible", "false")
    #  Un recorte opcional, en um: `--zoom x0 y0 x1 y1`. Sobre un die de 5 mm
    #  con un bloque de 0.4, la vista completa no deja ver nada de lo que
    #  importa.
    if "--zoom" in sys.argv:
        i = sys.argv.index("--zoom")
        z = [float(v) for v in sys.argv[i + 1:i + 5]]
        caja = kdb.DBox(z[0], z[1], z[2], z[3])
        alto = int(round(ancho * caja.height() / caja.width()))
        lv.zoom_box(caja)
    else:
        lv.zoom_fit()
    lv.save_image(str(png), ancho, alto)
    print(f"  {png}  ({ancho}x{alto}, {png.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
