`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;
    wire [31:0] zero32 = 32'd0;
    wire [2:0] zero3 = 3'd0;
    wire [7:0] zero8 = 8'd0;
    wire zero1 = 1'b0;

    sparcv8 dut (
        .clk(clk),
        .reset(reset),
        .reset_branch_target_rd(zero32),
        .reset_cwp(zero3),
        .reset_delay_slot(zero1),
        .reset_fsr(zero32),
        .reset_pc(zero32),
        .reset_psr(zero32),
        .reset_tbr(zero32),
        .reset_trap_rd(zero1),
        .reset_tt_rd(zero8),
        .reset_wim(zero32),
        .reset_y(zero32)
    );

    reg [31:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    initial begin
        clk = 0; reset = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;
        $readmemh("umem.hex", dut.umem);
        repeat(3) @(posedge clk);
        reset = 0;
        for (i = 0; i < 10000; i = i + 1) begin
            @(posedge clk);
            // Check PC for pass/fail
            if (dut.pc == pass_addr) begin $display("TEST PASSED"); $finish; end
            // Use physical register 72 for %l0 (with CWP=0, locals start at physical 72)
            if (dut.pc == fail_addr) begin $display("TEST FAILED at pc=%h testnum(l0)=%d", dut.pc, dut.rf[72]); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
