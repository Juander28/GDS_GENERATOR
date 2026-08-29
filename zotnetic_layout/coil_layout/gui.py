"""Interfaz grafica Tkinter para el flujo SPICE -> GDS (SKY130 / GF180).

Pasos:
  1. Seleccionar archivo SPICE y carpeta de salida.
  2. Elegir PDK en el menu (sky130 / gf180).
  3. 'Parsear' -> llena las dos tablas (transistores y conexiones).
  4. 'Placement' -> coloca (auto estilo logica) y permite reordenar las filas.
  5. 'Rutear' -> conecta potencia y senales; actualiza el preview.
  6. 'Exportar' -> escribe GDS + PNG + reporte en la carpeta de salida.

Extras: zoom in/out del preview, panel con los pares de transistores que hacen
overlap (abutment), y un menu para fijar el grosor de cada tipo de conexion
(por defecto = ancho minimo del PDK).
"""

from __future__ import annotations

import os
import tempfile
import traceback
import warnings
import webbrowser
from pathlib import Path

warnings.filterwarnings("ignore")

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from coil_layout import flow
from coil_layout.pdk_manager import activate_pdk, available_pdks
from coil_layout.placement import build_layout
from coil_layout.routing import RouteConfig, route_layout
from coil_layout.spice_parser import parse_spice


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SPICE -> GDS  |  SKY130 / GF180")
        self.geometry("1240x820")

        self.pdk_var = tk.StringVar(value="gf180")
        self.spice_path = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(Path.cwd() / "out"))
        self.status = tk.StringVar(value="Listo. Selecciona un archivo SPICE.")
        self.show_overlap = tk.BooleanVar(value=True)

        self.nl = None
        self.lay = None
        self.route_cfg = RouteConfig.minimum("gf180")
        self._preview_pil = None
        self._preview_img = None
        self._zoom = 1.0

        self._build_menu()
        self._build_topbar()
        self._build_body()
        self._build_statusbar()

    # ---------------- UI ----------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        pdk_menu = tk.Menu(menubar, tearoff=0)
        for p in available_pdks():
            pdk_menu.add_radiobutton(label=p, value=p, variable=self.pdk_var,
                                     command=self._on_pdk_change)
        menubar.add_cascade(label="PDK", menu=pdk_menu)

        route_menu = tk.Menu(menubar, tearoff=0)
        route_menu.add_command(label="Grosores de conexion...",
                               command=self._open_widths_dialog)
        menubar.add_cascade(label="Ruteo", menu=route_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Zoom +", command=lambda: self._zoom_by(1.25))
        view_menu.add_command(label="Zoom -", command=lambda: self._zoom_by(0.8))
        view_menu.add_command(label="Ajustar", command=self._zoom_fit)
        view_menu.add_checkbutton(label="Resaltar overlaps (abutment)",
                                  variable=self.show_overlap,
                                  command=self._update_preview)
        menubar.add_cascade(label="Vista", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Documentacion (HTML)", command=self._open_docs)
        help_menu.add_command(label="Acerca de", command=self._about)
        menubar.add_cascade(label="Ayuda", menu=help_menu)
        self.config(menu=menubar)

    def _build_topbar(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Archivo SPICE:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.spice_path, width=66).grid(
            row=0, column=1, padx=4, sticky="we")
        ttk.Button(top, text="Examinar...", command=self._pick_spice).grid(
            row=0, column=2, padx=2)
        ttk.Label(top, text="Carpeta de salida:").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.out_dir, width=66).grid(
            row=1, column=1, padx=4, sticky="we")
        ttk.Button(top, text="Examinar...", command=self._pick_out).grid(
            row=1, column=2, padx=2)

        ttk.Label(top, text="PDK:").grid(row=0, column=3, padx=(16, 2), sticky="e")
        self.pdk_combo = ttk.Combobox(top, textvariable=self.pdk_var, width=10,
                                      values=available_pdks(), state="readonly")
        self.pdk_combo.grid(row=0, column=4, sticky="w")
        self.pdk_combo.bind("<<ComboboxSelected>>", lambda e: self._on_pdk_change())

        btns = ttk.Frame(top)
        btns.grid(row=1, column=3, columnspan=2, sticky="e", padx=(16, 0))
        ttk.Button(btns, text="1. Parsear", command=self.do_parse).pack(side="left", padx=2)
        ttk.Button(btns, text="2. Placement", command=self.do_place).pack(side="left", padx=2)
        ttk.Button(btns, text="3. Rutear", command=self.do_route).pack(side="left", padx=2)
        ttk.Button(btns, text="4. Exportar", command=self.do_export).pack(side="left", padx=2)
        top.columnconfigure(1, weight=1)

    def _build_body(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=4)
        self.nb = nb

        # --- Tab 1: tablas ---
        tab1 = ttk.Frame(nb)
        nb.add(tab1, text="1. Netlist (tablas)")
        paned = ttk.Panedwindow(tab1, orient="horizontal")
        paned.pack(fill="both", expand=True)
        f_tr = ttk.Labelframe(paned, text="Transistores")
        self.tree_tr = self._make_tree(
            f_tr, ["inst", "type", "model", "W_um", "L_um", "nf", "m",
                   "drain", "gate", "source", "bulk"])
        paned.add(f_tr, weight=3)
        f_cn = ttk.Labelframe(paned, text="Conexiones (nets)")
        self.tree_cn = self._make_tree(f_cn, ["net", "n_pins", "is_power", "pins"])
        paned.add(f_cn, weight=2)

        # --- Tab 2: placement + preview ---
        tab2 = ttk.Frame(nb)
        nb.add(tab2, text="2. Placement / Ruteo")
        left = ttk.Frame(tab2, padding=4)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Orden fila PFET (arriba):").pack(anchor="w")
        self.list_p = tk.Listbox(left, height=6, exportselection=False)
        self.list_p.pack(fill="x")
        self._order_buttons(left, self.list_p)
        ttk.Label(left, text="Orden fila NFET (abajo):").pack(anchor="w", pady=(6, 0))
        self.list_n = tk.Listbox(left, height=6, exportselection=False)
        self.list_n.pack(fill="x")
        self._order_buttons(left, self.list_n)
        ttk.Button(left, text="Regenerar con este orden",
                   command=self.do_place).pack(fill="x", pady=6)

        ttk.Label(left, text="Transistores con OVERLAP (abutment):").pack(anchor="w")
        self.tree_ab = ttk.Treeview(left, columns=["par", "net"], show="headings",
                                    height=7)
        self.tree_ab.heading("par", text="Transistores"); self.tree_ab.column("par", width=130)
        self.tree_ab.heading("net", text="Nodo"); self.tree_ab.column("net", width=70)
        self.tree_ab.pack(fill="x")

        right = ttk.Frame(tab2)
        right.pack(side="left", fill="both", expand=True)
        # toolbar de zoom
        tb = ttk.Frame(right); tb.pack(fill="x")
        ttk.Button(tb, text="Zoom +", width=8,
                   command=lambda: self._zoom_by(1.25)).pack(side="left", padx=2)
        ttk.Button(tb, text="Zoom -", width=8,
                   command=lambda: self._zoom_by(0.8)).pack(side="left", padx=2)
        ttk.Button(tb, text="Ajustar", width=8, command=self._zoom_fit).pack(side="left", padx=2)
        ttk.Checkbutton(tb, text="Resaltar overlaps", variable=self.show_overlap,
                        command=self._update_preview).pack(side="left", padx=8)
        ttk.Label(tb, text="(rueda del raton = zoom)").pack(side="left")

        canvas = tk.Canvas(right, bg="black")
        hbar = ttk.Scrollbar(right, orient="horizontal", command=canvas.xview)
        vbar = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        hbar.pack(side="bottom", fill="x"); vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind("<MouseWheel>", self._on_wheel)            # Windows
        canvas.bind("<Button-4>", lambda e: self._zoom_by(1.25))
        canvas.bind("<Button-5>", lambda e: self._zoom_by(0.8))
        self.preview_canvas = canvas

    def _order_buttons(self, parent, listbox):
        fr = ttk.Frame(parent); fr.pack(fill="x")
        ttk.Button(fr, text="Subir", width=8,
                   command=lambda: self._move(listbox, -1)).pack(side="left")
        ttk.Button(fr, text="Bajar", width=8,
                   command=lambda: self._move(listbox, 1)).pack(side="left")

    def _make_tree(self, parent, cols):
        tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=70 if c not in ("pins",) else 320, anchor="w")
        vs = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tree.pack(fill="both", expand=True)
        return tree

    def _build_statusbar(self):
        bar = ttk.Frame(self, relief="sunken")
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(fill="x", padx=6)

    # ---------------- acciones ----------------
    def _pick_spice(self):
        p = filedialog.askopenfilename(
            title="Selecciona netlist SPICE",
            filetypes=[("SPICE", "*.spice *.sp *.cir *.txt *.net"), ("Todos", "*.*")])
        if p:
            self.spice_path.set(p); self.status.set(f"Archivo: {p}")

    def _pick_out(self):
        d = filedialog.askdirectory(title="Carpeta de salida")
        if d:
            self.out_dir.set(d)

    def _on_pdk_change(self):
        self.route_cfg = RouteConfig.minimum(self.pdk_var.get())
        self.status.set(f"PDK activo: {self.pdk_var.get()} "
                        f"(grosores reseteados al minimo). Vuelve a Placement.")

    def _move(self, listbox, delta):
        sel = listbox.curselection()
        if not sel:
            return
        i = sel[0]; j = i + delta
        if j < 0 or j >= listbox.size():
            return
        txt = listbox.get(i)
        listbox.delete(i); listbox.insert(j, txt); listbox.selection_set(j)

    def do_parse(self):
        path = self.spice_path.get()
        if not path or not os.path.exists(path):
            messagebox.showwarning("Falta archivo", "Selecciona un archivo SPICE valido.")
            return
        try:
            self.nl = parse_spice(Path(path).read_text())
        except Exception as e:
            messagebox.showerror("Error al parsear", f"{e}\n\n{traceback.format_exc()}")
            return
        self.tree_tr.delete(*self.tree_tr.get_children())
        for r in self.nl.transistor_table():
            self.tree_tr.insert("", "end", values=[r[c] for c in self.tree_tr["columns"]])
        self.tree_cn.delete(*self.tree_cn.get_children())
        for r in self.nl.connection_table():
            self.tree_cn.insert("", "end", values=[r[c] for c in self.tree_cn["columns"]])
        self.list_p.delete(0, "end"); self.list_n.delete(0, "end")
        for d in self.nl.devices:
            (self.list_p if d.kind == "p" else self.list_n).insert("end", d.name)
        self.status.set(
            f"Parseado: {len(self.nl.devices)} transistores, "
            f"{len(self.nl.nets())} nets. Ahora 'Placement'.")
        self.nb.select(0)

    def _manual_order(self):
        return {"p": list(self.list_p.get(0, "end")),
                "n": list(self.list_n.get(0, "end"))}

    def do_place(self):
        if self.nl is None:
            self.do_parse()
            if self.nl is None:
                return
        try:
            activate_pdk(self.pdk_var.get())
            self.lay = build_layout(self.nl, self.pdk_var.get(),
                                    manual_order=self._manual_order())
        except Exception as e:
            messagebox.showerror("Error en placement", f"{e}\n\n{traceback.format_exc()}")
            return
        self._fill_abut_table()
        self.status.set(f"Placement listo: {len(self.lay.abut_pairs)} pares con "
                        f"overlap. Ahora 'Rutear'.")
        self._zoom = 1.0
        self._update_preview()
        self.nb.select(1)

    def do_route(self):
        if self.lay is None:
            self.do_place()
            if self.lay is None:
                return
        try:
            route_layout(self.lay, self.route_cfg)
        except Exception as e:
            messagebox.showerror("Error en ruteo", f"{e}\n\n{traceback.format_exc()}")
            return
        self.status.set("Ruteo completado. Ahora 'Exportar'.")
        self._update_preview()
        self.nb.select(1)

    def do_export(self):
        if self.nl is None:
            messagebox.showwarning("Nada que exportar", "Primero Parsea y haz Placement.")
            return
        try:
            res = flow.run_flow(self.spice_path.get(), self.pdk_var.get(),
                                self.out_dir.get(), manual_order=self._manual_order(),
                                route_cfg=self.route_cfg)
        except Exception as e:
            messagebox.showerror("Error al exportar", f"{e}\n\n{traceback.format_exc()}")
            return
        self.lay = res["lay"]
        self._fill_abut_table()
        self._update_preview()
        self.status.set(f"Exportado: {res['gds']}")
        messagebox.showinfo("Exportado",
                            f"GDS:    {res['gds']}\nPNG:    {res['png']}\n"
                            f"Reporte: {res['report_path']}")

    def _fill_abut_table(self):
        self.tree_ab.delete(*self.tree_ab.get_children())
        for a, b, net in getattr(self.lay, "abut_pairs", []):
            self.tree_ab.insert("", "end", values=[f"{a}  +  {b}", net])

    # ---------------- preview + zoom ----------------
    def _update_preview(self, *_):
        if self.lay is None:
            return
        try:
            from PIL import Image
        except Exception:
            self.status.set("Instala pillow para el preview (pip install pillow).")
            return
        png = os.path.join(tempfile.gettempdir(), "coil_preview.png")
        hl = flow.abut_highlights(self.lay) if self.show_overlap.get() else None
        flow.render_png(self.lay.component, png, dpi=170, size=(16, 11), highlights=hl)
        self._preview_pil = Image.open(png)
        self._redraw_preview()

    def _redraw_preview(self):
        if self._preview_pil is None:
            return
        from PIL import Image, ImageTk
        w = max(1, int(self._preview_pil.width * self._zoom))
        h = max(1, int(self._preview_pil.height * self._zoom))
        resized = self._preview_pil.resize((w, h), Image.LANCZOS)
        self._preview_img = ImageTk.PhotoImage(resized)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self._preview_img)
        self.preview_canvas.configure(scrollregion=(0, 0, w, h))

    def _zoom_by(self, factor):
        self._zoom = min(8.0, max(0.1, self._zoom * factor))
        self._redraw_preview()

    def _zoom_fit(self):
        if self._preview_pil is None:
            return
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
        if cw < 10 or ch < 10:          # canvas aun no mapeado
            cw, ch = 900, 650
        self._zoom = max(0.1, min(cw / self._preview_pil.width,
                                  ch / self._preview_pil.height))
        self._redraw_preview()

    def _on_wheel(self, event):
        self._zoom_by(1.25 if event.delta > 0 else 0.8)

    # ---------------- dialogo de grosores ----------------
    def _open_widths_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Grosores de conexion (um)")
        dlg.transient(self); dlg.grab_set()
        cfg = self.route_cfg
        rows = [("Stub de senal (metal1)", "stub_w"),
                ("Trunk de senal (metal2)", "trunk_w"),
                ("Strap de potencia (rieles)", "power_w")]
        vars_ = {}
        for i, (lbl, attr) in enumerate(rows):
            ttk.Label(dlg, text=lbl).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            v = tk.StringVar(value=f"{getattr(cfg, attr):g}")
            ttk.Entry(dlg, textvariable=v, width=10).grid(row=i, column=1, padx=8)
            vars_[attr] = v
        mn = RouteConfig.minimum(self.pdk_var.get())
        ttk.Label(dlg, text=f"Minimo {self.pdk_var.get()}: "
                            f"m1={mn.stub_w:g}  m2={mn.trunk_w:g} um",
                  foreground="#555").grid(row=3, column=0, columnspan=2, padx=8)

        def reset_min():
            for attr, v in vars_.items():
                v.set(f"{getattr(mn, attr):g}")

        def apply():
            try:
                self.route_cfg = RouteConfig(
                    stub_w=float(vars_["stub_w"].get()),
                    trunk_w=float(vars_["trunk_w"].get()),
                    power_w=float(vars_["power_w"].get()))
            except ValueError:
                messagebox.showerror("Valor invalido", "Introduce numeros validos.")
                return
            dlg.destroy()
            if self.lay is not None:
                self.do_place(); self.do_route()

        bar = ttk.Frame(dlg); bar.grid(row=4, column=0, columnspan=2, pady=8)
        ttk.Button(bar, text="Restablecer minimo", command=reset_min).pack(side="left", padx=4)
        ttk.Button(bar, text="Aplicar", command=apply).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancelar", command=dlg.destroy).pack(side="left", padx=4)

    def _open_docs(self):
        docs = Path(__file__).resolve().parent.parent / "docs" / "index.html"
        if docs.exists():
            webbrowser.open(docs.as_uri())
        else:
            messagebox.showinfo("Docs", f"No encontrado: {docs}")

    def _about(self):
        messagebox.showinfo(
            "Acerca de",
            "SPICE -> GDS para SKY130 / GF180\n"
            "Flujo: parse -> placement (estilo logica + abutment) -> ruteo -> GDS.\n"
            "Construido con gdsfactory.")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
