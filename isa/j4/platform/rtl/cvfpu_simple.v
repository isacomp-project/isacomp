// Stub FPU module for testing non-FPU instructions
// Returns 0 for all operations - replace with real FPU for FP tests

module cvfpu_simple #(
    parameter WIDTH = 32,
    parameter FP_FORMAT = 0,
    parameter SRC_FP_FORMAT = 0
) (
    input  wire                clk_i,
    input  wire                rst_ni,
    input  wire [WIDTH-1:0]    a_i,
    input  wire [WIDTH-1:0]    b_i,
    input  wire [WIDTH-1:0]    c_i,
    input  wire [4:0]          op_select_i,
    input  wire [2:0]          rnd_mode_i,
    input  wire                valid_i,
    output wire                ready_o,
    output wire [WIDTH-1:0]    result_o,
    output wire [4:0]          status_o,
    output wire                valid_o
);
    // Stub: just return 0 for all operations
    // Real FPU tests will need the actual cvfpu implementation
    assign result_o = {WIDTH{1'b0}};
    assign status_o = 5'b0;
    assign ready_o = 1'b1;
    assign valid_o = valid_i;
endmodule
