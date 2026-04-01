`timescale 1ns/1ps

module riscv32i_ila_testbench;
    reg clk;
    reg reset;
    wire [31:0] reset_pc;
    wire [31:0] reset_pc_rd;

    // Test control signals
    reg [31:0] pass_pc;
    reg [31:0] fail_pc;
    integer cycle_count;
    integer max_cycles;

    // Instantiate processor
    riscv32i_ila dut (
        .clk(clk),
        .reset(reset),
        .reset_pc(reset_pc),
        .reset_pc_rd(reset_pc_rd)
    );

    // Clock generation (10ns period = 100MHz)
    initial clk = 0;
    always #5 clk = ~clk;

    // Reset PC to 0
    assign reset_pc = 32'h0;
    assign reset_pc_rd = 32'h0;

    // Test control
    initial begin
        // Parse plusargs
        if (!$value$plusargs("load=%s", test_hex)) begin
            $display("ERROR: No hex file specified. Use +load=<file.hex>");
            $finish(1);
        end

        if (!$value$plusargs("pass_pc=%h", pass_pc)) begin
            $display("ERROR: No pass PC specified. Use +pass_pc=<addr>");
            $finish(1);
        end

        if (!$value$plusargs("fail_pc=%h", fail_pc)) begin
            $display("ERROR: No fail PC specified. Use +fail_pc=<addr>");
            $finish(1);
        end

        $display("Loading test from: %s", test_hex);
        $display("Pass PC: 0x%08x", pass_pc);
        $display("Fail PC: 0x%08x", fail_pc);

        // Load program into instruction/data memory
        $readmemh(test_hex, dut.mem);

        // Reset sequence
        reset = 1;
        repeat(5) @(posedge clk);
        reset = 0;
        $display("Reset released, starting execution...");
        $display("Initial PC: 0x%08x", dut.pc_rd);

        // Monitor execution
        cycle_count = 0;
        max_cycles = 10000;

        forever begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Debug output every 100 cycles
            if (cycle_count % 100 == 0) begin
                $display("Cycle %0d: PC = 0x%08x", cycle_count, dut.pc_rd);
            end

            // Check for timeout
            if (cycle_count >= max_cycles) begin
                $display("TIMEOUT after %0d cycles", cycle_count);
                $display("Final PC: 0x%08x", dut.pc_rd);
                $display("UNEXPECTED TRAP");
                $finish(1);
            end

            // Check for pass condition
            if (dut.pc_rd == pass_pc) begin
                $display("TEST PASSED at cycle %0d", cycle_count);
                $finish(0);
            end

            // Check for fail condition
            if (dut.pc_rd == fail_pc) begin
                $display("TEST FAILED at cycle %0d", cycle_count);
                $display("PC reached fail address: 0x%08x", fail_pc);
                $finish(1);
            end
        end
    end

    // VCD dumping for debug
    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("testbench.vcd");
            $dumpvars(0, riscv32i_ila_testbench);
        end
    end

    // String for test hex file
    reg [1024*8-1:0] test_hex;

endmodule
