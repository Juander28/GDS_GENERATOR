// SPDX-FileCopyrightText: (c) 2026 Zotnetic / B26
// SPDX-License-Identifier: Apache-2.0
//
// The core of the wafer.space quarter slot is one hard macro and the wiring
// that reaches it. There is no logic here on purpose: GRADIENT_NAV2_V3 is a
// full analog block -- twelve amplifiers, twelve comparators, four decoders --
// already laid out, verified and hardened. This file only decides which pad
// each of its ports reaches.
//
// See librelane/slots/slot_0p5x0p5.yaml for the other half of that decision,
// which is where in the ring each of those pads sits.

`default_nettype none

module chip_core #(
    parameter NUM_INPUT_PADS,
    parameter NUM_BIDIR_PADS,
    parameter NUM_ANALOG_PADS
    )(
    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif

    input  wire clk,       // clock
    input  wire rst_n,     // reset (active low)

    input  wire [NUM_INPUT_PADS-1:0] input_in,   // Input value
    output wire [NUM_INPUT_PADS-1:0] input_pu,   // Pull-up
    output wire [NUM_INPUT_PADS-1:0] input_pd,   // Pull-down

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in,   // Input value
    output wire [NUM_BIDIR_PADS-1:0] bidir_out,  // Output value
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,   // Output enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,   // Input type (0=CMOS Buffer, 1=Schmitt Trigger)
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,   // Slew rate (0=fast, 1=slow)
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,   // Input enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,   // Pull-up
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd,   // Pull-down

    inout  wire [NUM_ANALOG_PADS-1:0] analog  // Analog
);

    // -----------------------------------------------------------------------
    //  The block's own ports
    // -----------------------------------------------------------------------
    //  Nine outputs come out of the decoder, three per axis: "this axis wins"
    //  (XP), "it does not" (XN) and the raw comparison (X). XP and XN are exact
    //  complements of each other -- the chip does not put out a sign -- so XN
    //  carries nothing XP does not. Only the three positives are bonded; the
    //  other six are declared and left in the air, which for an output is
    //  harmless and saves six pads and six tracks across the core.
    wire nav_XP, nav_X, nav_XN;
    wire nav_YP, nav_Y, nav_YN;
    wire nav_ZP, nav_Z, nav_ZN;

    GRADIENT_NAV2_V3 u_nav (
        `ifdef USE_POWER_PINS
        .VDD (VDD),
        .VSS (VSS),
        `endif

        //  The four bridges, differential. The order follows the pins along the
        //  block's own edge, which is the order the pad ring repeats, so the
        //  eight nets run side by side and never cross.
        .S1P (analog[0]),
        .S1N (analog[1]),
        .S2N (analog[2]),
        .S2P (analog[3]),
        .S3P (analog[4]),
        .S3N (analog[5]),
        .S4N (analog[6]),
        .S4P (analog[7]),

        .XP (nav_XP), .X (nav_X), .XN (nav_XN),
        .YP (nav_YP), .Y (nav_Y), .YN (nav_YN),
        .ZP (nav_ZP), .Z (nav_Z), .ZN (nav_ZN)
    );

    // -----------------------------------------------------------------------
    //  Pads
    // -----------------------------------------------------------------------
    //  Three bidirs driven as outputs, at the bottom of the vector because the
    //  slot file puts bidir[0..2] at the top of the east row, which is the
    //  corner the block's right edge looks at.
    assign bidir_out = {{(NUM_BIDIR_PADS-3){1'b0}}, nav_XP, nav_YP, nav_ZP};

    //  Only those three drive. The rest stay off and pulled down rather than
    //  floating: an unbonded pad left tri-state with no pull is an input with
    //  nothing on it, and it will sit around the switching threshold.
    localparam logic [NUM_BIDIR_PADS-1:0] USED = {{(NUM_BIDIR_PADS-3){1'b0}}, 3'b111};

    assign bidir_oe = USED;
    assign bidir_cs = '0;
    assign bidir_sl = '0;
    assign bidir_ie = '0;   // nothing is ever read back in
    assign bidir_pu = '0;
    assign bidir_pd = ~USED;

    //  No input pad is used either.
    assign input_pu = '0;
    assign input_pd = '0;

    //  Everything the block is deliberately not connected to. The net is never
    //  read, so synthesis drops it; it exists so the linter can see that the
    //  ports were left unconnected on purpose and not by accident.
    logic _unused;
    assign _unused = &{clk, rst_n, input_in, bidir_in,
                       nav_X, nav_XN, nav_Y, nav_YN, nav_Z, nav_ZN};

endmodule

`default_nettype wire
