"""coil_layout - SPICE netlist -> GDS layout para SKY130 / GF180.

Flujo: parsear netlist (.subckt) -> mapear dispositivos al PCell del PDK ->
placement estilo logica (filas p/n, rieles VPWR/VGND, wells/taps) -> ruteo ->
exportar GDS.
"""

from coil_layout.spice_parser import Device, SubcktNetlist, parse_spice

__all__ = ["Device", "SubcktNetlist", "parse_spice"]
