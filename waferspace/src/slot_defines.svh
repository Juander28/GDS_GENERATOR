`ifdef SLOT_1X1

// Power/ground pads for core and I/O
`define NUM_DVDD_PADS 6
`define NUM_DVSS_PADS 8

`define NUM_VDD_PADS 2
`define NUM_VSS_PADS 2

// Signal pads
`define NUM_INPUT_PADS 12
`define NUM_BIDIR_PADS 40
`define NUM_ANALOG_PADS 2

`endif

`ifdef SLOT_0P5X1

// Power/ground pads for core and I/O
`define NUM_DVDD_PADS 7
`define NUM_DVSS_PADS 7

`define NUM_VDD_PADS 1
`define NUM_VSS_PADS 1

// Signal pads
`define NUM_INPUT_PADS 4
`define NUM_BIDIR_PADS 44
`define NUM_ANALOG_PADS 6

`endif

`ifdef SLOT_1X0P5

// Power/ground pads for core and I/O
`define NUM_DVDD_PADS 7
`define NUM_DVSS_PADS 7

`define NUM_VDD_PADS 1
`define NUM_VSS_PADS 1

// Signal pads
`define NUM_INPUT_PADS 4
`define NUM_BIDIR_PADS 46
`define NUM_ANALOG_PADS 4

`endif

`ifdef SLOT_0P5X0P5

// Power/ground pads for core and I/O
`define NUM_DVDD_PADS 3
`define NUM_DVSS_PADS 3

`define NUM_VDD_PADS 1
`define NUM_VSS_PADS 1

// Signal pads
//
// Zotnetic: four analog pads became eight. The block has four magnetoresistive
// bridges and each one is differential, so all eight ends have to come out.
// The four extra ones are taken out of the bidirs, NOT added to the ring: the
// total stays at 48 signal pads so the pad ring keeps the pitch and the
// positions wafer.space documents for this slot. All the signal cells in
// gf180mcu_fd_io are 75 x 350 um, so an asig_5p0 where a bi_24t used to be
// moves nothing at all.
//
// Of the 34 bidirs only three are wired -- XP, YP and ZP. See chip_core.sv.
`define NUM_INPUT_PADS 4
`define NUM_BIDIR_PADS 34
`define NUM_ANALOG_PADS 8

`endif
