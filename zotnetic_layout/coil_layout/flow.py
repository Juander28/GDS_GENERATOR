"""Orquestacion del flujo completo: parse -> place -> route -> export -> render.

Reutilizado por la GUI (coil_layout.gui) y por el test headless (test_flow.py).
"""

from __future__ import annotations

import warnings
from pathlib import Path

warnings.filterwarnings("ignore")


def render_png(component, path: str, dpi: int = 140, size=(13, 9),
               highlights=None) -> str:
    """Renderiza un componente gdsfactory a PNG (sin display).

    highlights: lista opcional de (x0, y0, x1, y1, label) en um; se dibujan como
    rectangulos rojos punteados para marcar los transistores que hacen overlap.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    component.plot()
    fig = plt.gcf()
    ax = fig.axes[0] if fig.axes else plt.gca()
    for (x0, y0, x1, y1, label) in (highlights or []):
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                               edgecolor="red", linewidth=1.6, linestyle="--"))
        ax.text(x0, y1, label, color="red", fontsize=8, va="bottom", ha="left")
    fig.set_size_inches(*size)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def abut_highlights(lay):
    """Devuelve los bboxes (union de las dos celdas) de cada par abutido."""
    hl = []
    for a, b, net in getattr(lay, "abut_pairs", []):
        ra, rb = lay.placed.get(a), lay.placed.get(b)
        if not ra or not rb:
            continue
        ba, bb = ra.ref.dbbox(), rb.ref.dbbox()
        x0 = min(ba.left, bb.left); y0 = min(ba.bottom, bb.bottom)
        x1 = max(ba.right, bb.right); y1 = max(ba.top, bb.top)
        hl.append((x0, y0, x1, y1, f"{a}+{b}"))
    return hl


def build_report(nl, lay) -> str:
    """Genera un reporte de texto del resultado."""
    lines = [f"# Reporte de layout: {nl.name}",
             f"PDK: {lay.pdk}",
             f"Transistores: {len(nl.devices)}",
             f"Nets: {len(lay.nets)}",
             f"Nets abutidas (difusion compartida): {sorted(lay.abutted_nets)}",
             f"Ancho de la celda: {lay.width:.2f} um",
             f"Tamano total: {lay.component.dxsize:.2f} x "
             f"{lay.component.dysize:.2f} um",
             "",
             "## Transistores"]
    for r in nl.transistor_table():
        lines.append(f"  {r['inst']:6} {r['type']} {r['model']:24} "
                     f"W={r['W_um']}u L={r['L_um']}u nf={r['nf']}")
    lines.append("\n## Conexiones (net -> pines)")
    for r in nl.connection_table():
        tag = " [POWER]" if r["is_power"] == "yes" else ""
        ab = " [ABUTIDA]" if r["net"] in lay.abutted_nets else ""
        lines.append(f"  {r['net']:8}{tag}{ab}: {r['pins']}")
    return "\n".join(lines)


def run_flow(spice_path: str, pdk: str, out_dir: str,
             manual_order: dict | None = None, do_route: bool = True,
             route_cfg=None, opts=None):
    """Ejecuta el flujo completo y escribe GDS + PNG + reporte en out_dir.

    Devuelve dict con keys: nl, lay, gds, png, report, report_path.
    """
    from coil_layout.caps import place_caps
    from coil_layout.resistors import (altura_necesaria, ancho_necesario,
                                       place_resistors)
    from coil_layout.power import add_power_access
    from coil_layout.pdk_manager import activate_pdk
    from coil_layout.placement import Opciones, build_layout
    from coil_layout.routing import route_layout
    from coil_layout.spice_parser import parse_spice

    activate_pdk(pdk)
    opts = opts or Opciones()
    nl = parse_spice(Path(spice_path).read_text())
    #  El canal tiene que nacer ya con sitio para los serpentines: van metidos
    #  entre la fila P y la fila N, asi que la celda se queda en tres bandas y
    #  los terminales caen al lado de los trunks. No depende del layout, asi que
    #  se calcula antes de la primera pasada y se pasa a todas.
    canal = {"A": altura_necesaria(nl.resistors, 0.0)} if nl.resistors else None
    #  Y el ANCHO libre de pozo que necesita, que se traduce en apartar la fila
    #  'span' hacia la derecha. Sin esto la resistencia solo tenia hueco donde ya
    #  habia nwell y no se colocaba ninguna de las 976 posiciones que llegaban
    #  hasta ese chequeo. Ver `resistors.ancho_necesario`.
    reserva_x = ancho_necesario(nl.resistors) if nl.resistors else 0.0
    lay = build_layout(nl, pdk, manual_order=manual_order, extra_channel=canal,
                       reserva_x=reserva_x, opts=opts)
    if do_route:
        route_layout(lay, route_cfg)
        # El canal se dimensiona antes de rutear, cuando aun no se sabe cuantas
        # pistas hara falta: se reserva una por net (el peor caso). El router
        # comparte pistas entre nets cuyos trunks no se solapan, asi que suele
        # gastar bastantes menos; con el numero real se rehace el layout y el
        # canal adelgaza. El reparto de pistas solo depende de las x, que no
        # cambian con el alto del canal, asi que la segunda pasada es estable.
        if 0 < lay.tracks_used < lay.tracks_reserved:
            lay = build_layout(nl, pdk, manual_order=manual_order,
                               tracks=dict(lay.tracks_by_channel),
                               extra_channel=canal, reserva_x=reserva_x, opts=opts)
            route_layout(lay, route_cfg)
        # Con las cadenas de difusion los dispositivos quedan tan juntos que a
        # veces un stub no cabe entre el pad de gate del vecino y su propio pad.
        # El router no puede resolverlo solo —el stub ya esta en el borde de su
        # pad—, asi que pide hueco y se vuelve a colocar. Lo que se pide son
        # centesimas y solo separa cadenas enteras, pero separar una cadena puede
        # destapar el mismo roce en la siguiente (en DECODER hicieron falta tres),
        # asi que se itera hasta que nadie pide nada. El tope solo esta para no
        # colgarse; si se agota, `need_gap` sigue lleno y build_block lo avisa.
        gaps: dict = {}
        for _ in range(4):
            if not lay.need_gap:
                break
            for k, v in lay.need_gap.items():
                gaps[k] = gaps.get(k, 0.0) + v
            lay = build_layout(nl, pdk, manual_order=manual_order,
                               tracks=dict(lay.tracks_by_channel), extra_gap=gaps,
                               extra_channel=canal, reserva_x=reserva_x, opts=opts)
            route_layout(lay, route_cfg)
        # Las resistencias PRIMERO, y los condensadores despues. Los dos van tras
        # el ruteo, porque se cuelgan de los trunks que acaba de dibujar el
        # router, pero entre ellos el orden importa y estaba al reves.
        #
        # El argumento de antes era que un MIM necesita 20 um seguidos de trunk y
        # a la resistencia le basta un punto de via, asi que la que tiene que
        # ceder es la resistencia. Es verdad para el TRUNK, pero no para el
        # SITIO: el serpentin es una barra rigida de 79 um con sus dos terminales
        # a distancia fija, y solo puede deslizarse; el MIM elige entre muchas
        # posiciones y dos orientaciones (`caps._candidates`). El rigido va
        # primero.
        #
        # Y hay un motivo mas fuerte: **la extraccion no conecta un terminal de
        # resistencia que quede debajo de una placa MIM**. Medido -- el mismo
        # bloque sin condensadores saca la cadena entera de `G_OUT_P` a `OUT`, y
        # con ellos el ultimo tramo acaba en una net suelta mientras el metal2
        # que tiene justo encima si es `OUT`. Colocando la resistencia antes, el
        # MIM se aparta solo.
        place_resistors(lay, nl.resistors)
        place_caps(lay, nl.caps)
        # Y despues la subida de alimentacion y senales a metal3, que asi VE los
        # risers de los condensadores y los esquiva. Al reves salia una `V2.2a` de
        # 0.14 en COMP: el pad de un puerto caia sobre la via2 de un MIM colocado
        # despues. Los dos buscan hueco, pero el MIM tiene mas donde elegir.
        add_power_access(lay)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(spice_path).stem
    gds = out / f"{stem}_{pdk}.gds"
    png = out / f"{stem}_{pdk}.png"
    rpt = out / f"{stem}_{pdk}_report.txt"

    lay.component.write_gds(str(gds))
    render_png(lay.component, str(png))
    report = build_report(nl, lay)
    rpt.write_text(report, encoding="utf-8")

    return {"nl": nl, "lay": lay, "gds": str(gds), "png": str(png),
            "report": report, "report_path": str(rpt)}
