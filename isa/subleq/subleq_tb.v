`timescale 1ns/1ps

module subleq_tb;
    // Clock and reset
    reg clk;
    reg reset;

    // Reset PC value
    wire [31:0] reset_pc_rd = 32'h0;

    // DUT instantiation
    subleq_cpu dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(reset_pc_rd)
    );

    // Clock generation (10ns period = 100MHz)
    initial clk = 0;
    always #5 clk = ~clk;

    // Simulation control
    integer cycle_count;
    integer max_cycles = 10000;
    reg [31:0] halt_addr = 32'hFFFFFFFF;  // Halt when PC reaches this address

    // Test execution
    initial begin
        $display("===========================================");
        $display("SUBLEQ Processor Testbench");
        $display("===========================================");
        $display("Loading program from data.mem");

        // Initialize
        cycle_count = 0;
        reset = 1;

        // Hold reset for 5 cycles
        repeat(5) @(posedge clk);
        reset = 0;

        $display("Reset released at time %0t", $time);
        $display("Starting execution from PC=0x%08x", dut.pc_rd);
        $display("");

        // Monitor execution
        while (cycle_count < max_cycles) begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Print detailed debug for first few cycles and periodic status
            if (cycle_count <= 10 || cycle_count % 100 == 0) begin
                $display("[Cycle %0d] PC=%0d a=%0d b=%0d c=%0d result=%0d is_neg_or_zero=%b pc_wr=%0d",
                    cycle_count, dut.pc_rd, dut.a_addr, dut.b_addr, dut.c_addr,
                    dut.result, dut.is_negative_or_zero, dut.pc_wr);
            end

            // Check for halt condition
            if (dut.pc_rd == halt_addr) begin
                $display("");
                $display("===========================================");
                $display("HALTED at cycle %0d", cycle_count);
                $display("Final PC: 0x%08x", dut.pc_rd);
                $display("===========================================");
                $finish(0);
            end

            // Check for out-of-bounds PC
            if (dut.pc_rd >= 1024) begin
                $display("");
                $display("===========================================");
                $display("ERROR: PC out of bounds at cycle %0d", cycle_count);
                $display("PC: 0x%08x (>= 1024)", dut.pc_rd);
                $display("===========================================");
                $finish(1);
            end
        end

        // Timeout
        $display("");
        $display("===========================================");
        $display("TIMEOUT after %0d cycles", cycle_count);
        $display("Final PC: 0x%08x", dut.pc_rd);
        $display("===========================================");
        $finish(1);
    end

    // Optional: Waveform dumping
    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("subleq_tb.vcd");
            $dumpvars(0, subleq_tb);
        end
    end

endmodule
