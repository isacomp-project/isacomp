// Stub cvfpu_simple module for HPPA simulation
// FP operations return 0 — sufficient for Linux boot which doesn't use FP
// Replace with real cvfpu vendor files for correct FP behaviour.
module cvfpu_simple #(
    parameter int unsigned WIDTH       = 32,
    parameter int unsigned FP_FORMAT   = 0,
    parameter int unsigned SRC_FP_FORMAT = 0
) (
    input  logic                  clk_i,
    input  logic                  rst_ni,
    input  logic [WIDTH-1:0]      a_i,
    input  logic [WIDTH-1:0]      b_i,
    input  logic [WIDTH-1:0]      c_i,
    input  logic [4:0]            op_select_i,
    input  logic [2:0]            rnd_mode_i,
    input  logic                  valid_i,
    output logic                  ready_o,
    output logic [WIDTH-1:0]      result_o,
    output logic [4:0]            status_o,
    output logic                  valid_o
);
    assign ready_o  = 1'b1;
    assign result_o = '0;
    assign status_o = 5'b0;
    assign valid_o  = valid_i;
endmodule
