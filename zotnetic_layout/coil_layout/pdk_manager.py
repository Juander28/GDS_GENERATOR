"""Gestion de PDK (sky130 / gf180): activacion y metadata de capas/metales.

Ambos PDK son objetos gf.Pdk. Cambiar de PDK = llamar .activate() del modulo
correspondiente. Aqui centralizamos esa logica y exponemos la metadata de capas
que necesitan el placement, el ruteo, el GUI y la documentacion HTML.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

warnings.filterwarnings("ignore")  # silenciar avisos de pydantic/NDArray de los PDK


@dataclass(frozen=True)
class MetalInfo:
    """Info de una capa de metal para ruteo."""

    name: str
    layer: tuple[int, int]
    min_width: float          # ancho minimo de ruta (um)
    default_width: float      # ancho por defecto que usa el router (um)


@dataclass
class PDKInfo:
    """Metadata de un PDK que consume el resto de la app."""

    name: str
    # capas base
    diff: tuple[int, int]          # comp / diffusion
    poly: tuple[int, int]
    nwell: tuple[int, int]
    nplus: tuple[int, int]
    pplus: tuple[int, int]
    contact: tuple[int, int]
    # stack de metales (de abajo hacia arriba)
    metals: list[MetalInfo] = field(default_factory=list)
    via_layers: dict[str, tuple[int, int]] = field(default_factory=dict)
    # nombres de dispositivos disponibles
    nfet_models: list[str] = field(default_factory=list)
    pfet_models: list[str] = field(default_factory=list)
    # capa para labels de metal1 (texto en pines)
    metal1_label: tuple[int, int] = (0, 0)
    notes: str = ""


# ---------------------------------------------------------------------------
#  Definiciones por PDK (valores de min_width tomados de las reglas de cada PDK)
# ---------------------------------------------------------------------------
GF180 = PDKInfo(
    name="gf180",
    diff=(22, 0),
    poly=(30, 0),
    nwell=(21, 0),
    nplus=(32, 0),
    pplus=(31, 0),
    contact=(33, 0),
    metals=[
        MetalInfo("metal1", (34, 0), 0.23, 0.38),
        MetalInfo("metal2", (36, 0), 0.28, 0.38),
        MetalInfo("metal3", (42, 0), 0.28, 0.38),
        MetalInfo("metal4", (46, 0), 0.28, 0.38),
        MetalInfo("metal5", (81, 0), 0.28, 0.38),
    ],
    via_layers={"via1": (35, 0), "via2": (38, 0), "via3": (40, 0), "via4": (41, 0)},
    nfet_models=["nfet_03v3", "nfet_05v0", "nfet_06v0", "nfet_06v0_nvt"],
    pfet_models=["pfet_03v3", "pfet_05v0", "pfet_06v0"],
    metal1_label=(34, 10),
    notes="GF180MCU. Soporta bulk='None' (sin guard ring) -> ideal para wells estilo logica.",
)

SKY130 = PDKInfo(
    name="sky130",
    diff=(65, 20),
    poly=(66, 20),
    nwell=(64, 20),
    nplus=(93, 44),
    pplus=(94, 20),
    contact=(66, 44),
    metals=[
        MetalInfo("li1", (67, 20), 0.17, 0.17),
        MetalInfo("met1", (68, 20), 0.14, 0.14),
        MetalInfo("met2", (69, 20), 0.14, 0.14),
        MetalInfo("met3", (70, 20), 0.30, 0.30),
        MetalInfo("met4", (71, 20), 0.30, 0.30),
        MetalInfo("met5", (72, 20), 1.60, 1.60),
    ],
    via_layers={"mcon": (67, 44), "via": (68, 44), "via2": (69, 44),
                "via3": (70, 44), "via4": (71, 44)},
    nfet_models=["sky130_fd_pr__nfet_01v8", "sky130_fd_pr__nfet_g5v0d10v5"],
    pfet_models=["sky130_fd_pr__pfet_01v8", "sky130_fd_pr__pfet_g5v0d10v5"],
    metal1_label=(68, 5),
    notes=("SkyWater 130nm. Los PCells nmos/pmos de stock incluyen bulk tie + "
           "pwell + deep nwell por dispositivo (sin opcion bulk=None)."),
)

_INFO = {"gf180": GF180, "sky130": SKY130}
_active = "gf180"


def available_pdks() -> list[str]:
    return list(_INFO.keys())


def get_info(pdk: str | None = None) -> PDKInfo:
    return _INFO[pdk or _active]


def active_pdk() -> str:
    return _active


def activate_pdk(pdk: str):
    """Activa el PDK de gdsfactory indicado y devuelve su modulo."""
    global _active
    if pdk not in _INFO:
        raise ValueError(f"PDK desconocido: {pdk} (opciones: {available_pdks()})")
    if pdk == "gf180":
        import gf180
        gf180.PDK.activate()
        _active = "gf180"
        return gf180
    else:
        import sky130
        sky130.PDK.activate()
        _active = "sky130"
        return sky130


def get_pdk_module(pdk: str | None = None):
    """Importa (sin reactivar global) el modulo del PDK pedido."""
    pdk = pdk or _active
    if pdk == "gf180":
        import gf180
        return gf180
    import sky130
    return sky130


if __name__ == "__main__":
    for name in available_pdks():
        info = get_info(name)
        print(f"\n=== {name} ===  {info.notes}")
        print("  metales:", [(m.name, m.layer, m.default_width) for m in info.metals])
        print("  nfet:", info.nfet_models)
        print("  pfet:", info.pfet_models)
    activate_pdk("gf180")
    print("\nPDK activo:", active_pdk())
