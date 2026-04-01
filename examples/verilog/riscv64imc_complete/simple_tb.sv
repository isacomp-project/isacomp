`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;
    wire [63:0] zero64 = 64'd0;

    riscv64imc_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(zero64)
    );

    reg [63:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    initial begin
        clk = 0; reset = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 64'hFFFFFFFFFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 64'hFFFFFFFFFFFFFFFE;
        $readmemh("umem.hex", dut.umem);
        $readmemh("rf.hex", dut.rf);
        repeat(3) @(posedge clk);
        reset = 0;
        for (i = 0; i < 10000; i = i + 1) begin
            @(posedge clk);
            if (i < 100) $display("cycle %d: pc=%h c_instr=%h instr=%h s0=%h t0=%h t2=%h x17=%d", i, dut.pc_rd, dut.c_instr, dut.instr, dut.rf[8], dut.rf[5], dut.rf[7], dut.rf[17]);
            // Single-cycle: PC updates every cycle, check directly
            if (dut.pc_rd == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (dut.pc_rd == fail_addr) begin $display("TEST FAILED at pc=%h testnum=%d", dut.pc_rd, dut.rf[17]); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
