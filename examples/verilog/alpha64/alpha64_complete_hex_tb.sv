`timescale 1ns/1ps
// Testbench for alpha64_complete processor - loads test programs from hex files
module alpha64_complete_hex_tb;
    reg clk, reset;
    wire [63:0] zero64 = 64'd0;

    alpha64_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_fpcr(zero64),
        .reset_pc_rd(zero64)
    );

    reg [63:0] pass_addr, fail_addr;
    integer cycles;
    integer max_cycles;
    always #5 clk = ~clk;

    initial begin
        clk = 0; reset = 1;
        cycles = 0;
        // Get max cycles from plusargs, default 50000
        if (!$value$plusargs("cycles=%d", max_cycles)) max_cycles = 50000;
        // Get pass/fail addresses from test dump file
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 64'hFFFFFFFFFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 64'hFFFFFFFFFFFFFFFE;

        // Load memory from hex files
        $readmemh("imem.hex", dut.imem);
        $readmemh("rf.hex", dut.rf);

        // Initialize FP register file to zeros
        for (integer i = 0; i < 32; i = i + 1) begin
            dut.frf[i] = 64'd0;
        end

        repeat(3) @(posedge clk);
        reset = 0;

        forever begin
            @(posedge clk);
            cycles = cycles + 1;

            // Check for pass condition (PC reaches pass label)
            if (dut.pc_rd == pass_addr) begin
                $display("TEST PASSED");
                $finish;
            end

            // Check for fail condition (PC reaches fail label)
            if (dut.pc_rd == fail_addr) begin
                $display("TEST FAILED at pc=%h testnum=%d", dut.pc_rd, dut.rf[4]);
                $finish;
            end

            // Also check memory location 0xF00 for result (as per test_macros.h)
            // dmem is 64-bit, address 0xF00 is word 0x1E0 (0xF00/8)
            if (dut.dmem[64'h1E0][31:0] == 32'h00000001) begin
                $display("TEST PASSED (via result memory)");
                $finish;
            end
            if (dut.dmem[64'h1E0][31:0] != 32'h0 && dut.dmem[64'h1E0][0] == 1'b0) begin
                $display("TEST FAILED: result=%h testnum=%d", dut.dmem[64'h1E0], dut.dmem[64'h1E0] >> 1);
                $finish;
            end

            // Timeout
            if (cycles >= max_cycles) begin
                $display("TIMEOUT after %d cycles at pc=%h", cycles, dut.pc_rd);
                $finish;
            end
        end
    end
endmodule
