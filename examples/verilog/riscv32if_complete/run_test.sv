`timescale 1ns/1ps
// Simple test runner for RV32IF processor
// Uses $readmemh to load tests

module run_test;

    // Clock and reset
    reg clk;
    reg reset;

    // Processor interface
    wire [31:0] reset_pc_rd = 32'h0;
    wire [31:0] reset_fcsr_rd = 32'h0;

    // Device Under Test
    riscv32if_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_fcsr_rd(reset_fcsr_rd),
        .reset_pc_rd(reset_pc_rd)
    );

    // Clock generation (100MHz)
    initial clk = 0;
    always #5 clk = ~clk;

    // Test control
    integer cycle_count;
    reg [31:0] pass_addr;
    reg [31:0] fail_addr;
    string hex_file;

    initial begin
        cycle_count = 0;
        pass_addr = 32'h0;
        fail_addr = 32'h0;

        // Get hex file and addresses from plusargs
        if (!$value$plusargs("hex=%s", hex_file)) begin
            $display("ERROR: No hex file specified. Use +hex=<file.hex>");
            $finish;
        end

        if (!$value$plusargs("pass=%h", pass_addr)) begin
            $display("WARNING: No pass address specified. Use +pass=<addr>");
        end

        if (!$value$plusargs("fail=%h", fail_addr)) begin
            $display("WARNING: No fail address specified. Use +fail=<addr>");
        end

        $display("Test file: %s", hex_file);
        $display("Pass addr: 0x%08x", pass_addr);
        $display("Fail addr: 0x%08x", fail_addr);

        // Load program into unified memory
        $readmemh(hex_file, dut.umem);
        $display("Loaded program into memory");

        // Reset sequence
        reset = 1;
        repeat(5) @(posedge clk);
        reset = 0;
        $display("Reset released, PC = 0x%08x", dut.pc_rd);

        // Run test
        forever begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Timeout
            if (cycle_count >= 100000) begin
                $display("TIMEOUT at cycle %0d, PC = 0x%08x", cycle_count, dut.pc_rd);
                $display("FAIL");
                $finish;
            end

            // Check pass (loop at pass address)
            if (pass_addr != 0 && dut.pc_rd == pass_addr) begin
                $display("PASS at cycle %0d", cycle_count);
                $finish;
            end

            // Check fail (loop at fail address)
            if (fail_addr != 0 && dut.pc_rd == fail_addr) begin
                $display("FAIL at cycle %0d, PC = 0x%08x", cycle_count, dut.pc_rd);
                $finish;
            end

            // Debug every 10000 cycles
            if (cycle_count % 10000 == 0) begin
                $display("Cycle %0d: PC = 0x%08x", cycle_count, dut.pc_rd);
            end
        end
    end

    // VCD dump
    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("test.vcd");
            $dumpvars(0, run_test);
        end
    end

endmodule
