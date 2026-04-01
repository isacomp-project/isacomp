`timescale 1ns/1ps

// Simple testbench for PDP-11 processor that loads hex files
module simple_tb;
    reg clk;
    reg reset;

    // Reset values
    wire reset_flag_C_rd = 1'b0;
    wire reset_flag_N_rd = 1'b0;
    wire reset_flag_V_rd = 1'b0;
    wire reset_flag_Z_rd = 1'b0;
    wire reset_halted_rd = 1'b0;
    wire [15:0] reset_pc_rd = 16'h0000;
    wire [2:0] reset_priority_rd = 3'b000;
    wire reset_waiting_rd = 1'b0;

    // Device Under Test
    pdp11_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_flag_C_rd(reset_flag_C_rd),
        .reset_flag_N_rd(reset_flag_N_rd),
        .reset_flag_V_rd(reset_flag_V_rd),
        .reset_flag_Z_rd(reset_flag_Z_rd),
        .reset_halted_rd(reset_halted_rd),
        .reset_pc_rd(reset_pc_rd),
        .reset_priority_rd(reset_priority_rd),
        .reset_waiting_rd(reset_waiting_rd)
    );

    // Clock generation (100MHz = 10ns period)
    initial clk = 0;
    always #5 clk = ~clk;

    // Test control
    reg [31:0] pass_addr, fail_addr;
    integer cycle_count;
    integer i;

    initial begin
        // Default pass/fail addresses (can override with plusargs)
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFE;

        $display("Pass address: 0x%04x", pass_addr[15:0]);
        $display("Fail address: 0x%04x", fail_addr[15:0]);

        // Load test program into memory
        $readmemh("umem.hex", dut.umem);
        $display("Loaded umem.hex");

        // Clear registers
        for (i = 0; i < 8; i = i + 1) begin
            dut.rf[i] = 16'h0000;
        end

        // Initialize flags
        dut.flag_C_rd = 0;
        dut.flag_N_rd = 0;
        dut.flag_V_rd = 0;
        dut.flag_Z_rd = 0;
        dut.halted_rd = 0;
        dut.waiting_rd = 0;

        // Reset sequence
        reset = 1;
        repeat(5) @(posedge clk);
        reset = 0;

        $display("Reset released, starting execution...");
        $display("Initial PC: 0x%04x", dut.pc_rd);

        // Run until pass/fail or timeout
        cycle_count = 0;
        while (cycle_count < 10000) begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Debug output every 1000 cycles
            if (cycle_count % 1000 == 0) begin
                $display("Cycle %0d: PC=0x%04x R0=0x%04x R1=0x%04x R2=0x%04x",
                    cycle_count, dut.pc_rd, dut.rf[0], dut.rf[1], dut.rf[2]);
            end

            // Check for pass
            if (dut.pc_rd == pass_addr[15:0]) begin
                $display("*** TEST PASSED *** at cycle %0d (PC=0x%04x)", cycle_count, dut.pc_rd);
                $display("Final registers: R0=0x%04x R1=0x%04x R2=0x%04x R3=0x%04x",
                    dut.rf[0], dut.rf[1], dut.rf[2], dut.rf[3]);
                $display("PASSED");
                $finish;
            end

            // Check for fail
            if (dut.pc_rd == fail_addr[15:0]) begin
                $display("*** TEST FAILED *** at cycle %0d (PC=0x%04x)", cycle_count, dut.pc_rd);
                $display("Final registers: R0=0x%04x R1=0x%04x R2=0x%04x R3=0x%04x",
                    dut.rf[0], dut.rf[1], dut.rf[2], dut.rf[3]);
                $display("Test number in R0: %0d", dut.rf[0]);
                $display("FAILED");
                $finish;
            end

            // HALT check disabled for tests - HALT opcode (0x0000) may
            // match uninitialized memory. Tests use pass/fail addresses instead.
        end

        $display("TIMEOUT after %0d cycles at PC=0x%04x", cycle_count, dut.pc_rd);
        $display("Final registers: R0=0x%04x R1=0x%04x R2=0x%04x R3=0x%04x",
            dut.rf[0], dut.rf[1], dut.rf[2], dut.rf[3]);
        $display("TIMEOUT");
        $finish;
    end

    // VCD dump
    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("pdp11_tb.vcd");
            $dumpvars(0, simple_tb);
        end
    end

endmodule
