`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;
    wire [31:0] zero32 = 32'd0;

    riscv32imc_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(zero32)
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
            if (i < 100) $display("cycle %d: pc=%h c_instr=%h instr=%h s0=%h t0=%h t2=%h x28=%d", i, dut.pc_rd, dut.c_instr, dut.instr, dut.rf[8], dut.rf[5], dut.rf[7], dut.rf[28]);
            // Single-cycle: PC updates every cycle, check directly
            if (dut.pc_rd == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (dut.pc_rd == fail_addr) begin $display("TEST FAILED at pc=%h testnum=%d", dut.pc_rd, dut.rf[28]); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
