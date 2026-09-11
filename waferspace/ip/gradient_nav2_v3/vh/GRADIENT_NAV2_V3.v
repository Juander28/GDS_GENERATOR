// Black-box declaration of the GRADIENT_NAV2_V3 analog macro.
// The layout is the real implementation; this only gives the tools
// an interface to bind against.

(* blackbox *)
module GRADIENT_NAV2_V3 (
    S1N,
    VDD,
    XP,
    VSS,
    S1P,
    S2N,
    S2P,
    S3N,
    S3P,
    S4N,
    S4P,
    XN,
    YP,
    YN,
    ZP,
    ZN,
    X,
    Y,
    Z
);
  input  S1N;
  inout  VDD;
  output XP;
  inout  VSS;
  input  S1P;
  input  S2N;
  input  S2P;
  input  S3N;
  input  S3P;
  input  S4N;
  input  S4P;
  output XN;
  output YP;
  output YN;
  output ZP;
  output ZN;
  output X;
  output Y;
  output Z;
endmodule
