#!/usr/bin/env python3
"""El die completo partido en cuatro, con nuestro proyecto arriba a la izquierda.

Lee `out_waferspace/cuatro.json`, que escribe `waferspace_cuatro.tcl`. Como en
la otra figura, aqui no se calcula nada: si el dibujo y el estudio pudieran
discrepar, un dia discrepan.

    env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python \\
        scripts/waferspace_figura4.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

WS = Path(__file__).resolve().parent.parent   # waferspace/
D = json.loads((WS / "out/cuatro.json").read_text())

COLOR = {"asig_5p0": "#c0392b", "bi_24t": "#7f8c8d",
         "dvdd": "#e67e22", "dvss": "#2c3e50"}


def caja(ax, r, **kw):
    x0, y0, x1, y1 = r
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, **kw))


fig, ax = plt.subplots(figsize=(7.2, 9.0))
dx0, dy0, dx1, dy1 = D["die"]
s, ph = D["sello"], D["padh"]
qx, qy = D["frontera"]

caja(ax, D["die"], fc="#f7f7f5", ec="#333", lw=1.2, zorder=0)
caja(ax, [s, s, dx1 - s, dy1 - s], fc="none", ec="#999", lw=.8, ls="--", zorder=1)

#  nuestro cuarto, y la frontera que nada nuestro cruza
caja(ax, [dx0, qy, qx, dy1], fc="#3498db", ec="none", alpha=.07, zorder=1)
ax.plot([qx, qx], [dy0, dy1], color="#c0392b", lw=1.1, ls=(0, (6, 4)), zorder=5)
ax.plot([dx0, dx1], [qy, qy], color="#c0392b", lw=1.1, ls=(0, (6, 4)), zorder=5)
#  Las etiquetas, en el hueco de cada cuarto y no encima de los pads.
for tx, ty, t in ((qx / 2, qy + 900, "ZOTNETIC"),
                  (qx + qx / 2, qy + 900, "proyecto 2"),
                  (qx / 2, qy / 2, "proyecto 4"),
                  (qx + qx / 2, qy / 2, "proyecto 3")):
    ax.text(tx, ty, t, ha="center", va="center", fontsize=8,
            color="#c0392b" if t == "ZOTNETIC" else "#999",
            fontweight="bold" if t == "ZOTNETIC" else "normal", zorder=6)

#  los pads
for lado, m, a, b, senal, mio in D["pads"]:
    if lado in ("sur", "norte"):
        y = s if lado == "sur" else dy1 - s - ph
        r = [a, y, b, y + ph]
    else:
        x = s if lado == "oeste" else dx1 - s - ph
        r = [x, a, x + ph, b]
    caja(ax, r, fc=COLOR.get(m, "#95a5a6"), ec="w" if mio else "none",
         lw=.5, alpha=.95 if mio else .30, zorder=2)
    if mio and senal != ".":
        ax.text((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, senal,
                ha="center", va="center", fontsize=5, color="w",
                rotation=0 if lado in ("sur", "norte") else 90, zorder=4)

caja(ax, D["core"], fc="none", ec="#2c3e50", lw=.9, zorder=3)

mb = D["macro"]["caja"]
caja(ax, mb, fc="#2980b9", ec="#154360", lw=1.0, alpha=.95, zorder=4)
ax.text((mb[0] + mb[2]) / 2, (mb[1] + mb[3]) / 2,
        "GRADIENT\n_NAV2_V3", ha="center", va="center",
        fontsize=6, color="w", zorder=5)

#  las pistas, que son la razon de todo el reparto
for lado, m, a, b, senal, mio in D["pads"]:
    if not mio or senal == "." or senal not in D["pines"]:
        continue
    px0, py0, px1, py1 = D["pines"][senal]
    c = (a + b) / 2
    if lado == "norte":
        ax.plot([(px0 + px1) / 2, (px0 + px1) / 2, c],
                [py1, dy1 - s - ph - 20, dy1 - s - ph],
                color="#c0392b" if m == "asig_5p0" else "#34495e",
                lw=.6, alpha=.85, zorder=4)

qw, qh = qx - dx0, dy1 - qy
ax.set_title(
    f"die completo {dx1:.0f} x {dy1:.0f} um, partido en cuatro\n"
    f"nuestro cuarto {qw:.0f} x {qh:.0f} um   ·   "
    f"17 pads propios, arco norte hasta x={1406:.0f} y oeste hasta y={4441:.0f}\n"
    f"nada nuestro cruza x={qx:.0f} ni y={qy:.0f}", fontsize=8)
ax.set_xlim(-60, dx1 + 60)
ax.set_ylim(-60, dy1 + 60)
ax.set_aspect("equal")
ax.set_xlabel("um", fontsize=7)
ax.set_ylabel("um", fontsize=7)
ax.tick_params(labelsize=6)

sal = WS / "out/cuatro.png"
fig.savefig(sal, dpi=190, bbox_inches="tight")
print(f"  {sal}")
