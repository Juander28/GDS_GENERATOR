#!/usr/bin/env python3
"""Dibuja el slot quarter de wafer.space con GRADIENT_NAV2_V3 dentro.

Lo lee TODO de `out_waferspace/quarter.json`, que escribe
`waferspace_floorplan.tcl`. Nada se recalcula aqui: si el dibujo y el estudio
pudieran discrepar, un dia discrepan, y el dibujo es lo que la gente mira.

    env -u PYTHONPATH /headless/.venvs/zotnetic/bin/python \\
        scripts/waferspace_figura.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

WS = Path(__file__).resolve().parent.parent   # waferspace/
D = json.loads((WS / "out/quarter.json").read_text())

COLOR = {"asig_5p0": "#c0392b", "bi_24t": "#7f8c8d", "in_c": "#7f8c8d",
         "in_s": "#7f8c8d", "dvdd": "#e67e22", "dvss": "#2c3e50"}


def caja(ax, r, **kw):
    x0, y0, x1, y1 = r
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, **kw))


fig, ax = plt.subplots(figsize=(6.4, 8.0))
dx0, dy0, dx1, dy1 = D["die"]
s, ph = D["sello"], D["padh"]

caja(ax, D["die"], fc="#f7f7f5", ec="#333", lw=1.2, zorder=0)
#  el sello y la banda del padring
caja(ax, [s, s, dx1 - s, dy1 - s], fc="none", ec="#999", lw=0.8, ls="--", zorder=1)
caja(ax, [s + ph, s + ph, dx1 - s - ph, dy1 - s - ph],
     fc="none", ec="#bbb", lw=0.8, zorder=1)

#  los 56 pads, con su tipo
for lado, lista in D["pads"].items():
    for m, a, b, senal in lista:
        if lado in ("sur", "norte"):
            y = s if lado == "sur" else dy1 - s - ph
            r = [a, y, b, y + ph]
        else:
            x = s if lado == "oeste" else dx1 - s - ph
            r = [x, a, x + ph, b]
        caja(ax, r, fc=COLOR.get(m, "#95a5a6"), ec="none", alpha=.85, zorder=2)
        if senal != ".":
            cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            ax.text(cx, cy, senal, ha="center", va="center", fontsize=5.2,
                    color="w", rotation=0 if lado in ("sur", "norte") else 90,
                    zorder=4)

#  el core y lo que queda libre
caja(ax, D["core"], fc="none", ec="#2c3e50", lw=1.0, zorder=3)
for r in D["libre"]:
    caja(ax, r, fc="#27ae60", ec="none", alpha=.13, zorder=2)

#  el bloque
mb = D["macro"]["caja"]
caja(ax, mb, fc="#2980b9", ec="#154360", lw=1.0, alpha=.9, zorder=3)
ax.text((mb[0] + mb[2]) / 2, (mb[1] + mb[3]) / 2,
        "GRADIENT\n_NAV2_V3\n" + D["macro"]["orient"],
        ha="center", va="center", fontsize=6.5, color="w", zorder=4)

#  las pistas que hay que tirar, de pin a pad
for lado, lista in D["pads"].items():
    for m, a, b, senal in lista:
        if senal == "." or senal not in D["pines"]:
            continue
        px0, py0, px1, py1 = D["pines"][senal]
        if lado == "norte":
            ax.plot([(px0 + px1) / 2, (a + b) / 2], [py1, dy1 - s - ph],
                    color="#c0392b", lw=.5, alpha=.7, zorder=3)
        else:
            ax.plot([px1, dx1 - s - ph], [(py0 + py1) / 2, (a + b) / 2],
                    color="#34495e", lw=.5, alpha=.7, zorder=3)

libre = sum((r[2] - r[0]) * (r[3] - r[1]) for r in D["libre"]) / 1e6
usa = (mb[2] - mb[0]) * (mb[3] - mb[1]) / 1e6
cx0, cy0, cx1, cy1 = D["core"]
ax.set_title(f"wafer.space 0.5x0.5 (quarter) — {dx1:.0f} x {dy1:.0f} um\n"
             f"core {cx1-cx0:.0f} x {cy1-cy0:.0f} = {(cx1-cx0)*(cy1-cy0)/1e6:.2f} mm2   ·   "
             f"bloque {usa:.3f} mm2 ({100*usa/((cx1-cx0)*(cy1-cy0)/1e6):.0f} %)   ·   "
             f"libre {libre:.2f} mm2", fontsize=8)
ax.set_xlim(-40, dx1 + 40)
ax.set_ylim(-40, dy1 + 40)
ax.set_aspect("equal")
ax.set_xlabel("um", fontsize=7)
ax.set_ylabel("um", fontsize=7)
ax.tick_params(labelsize=6)

sal = WS / "out/quarter.png"
fig.savefig(sal, dpi=200, bbox_inches="tight")
print(f"  {sal}")
