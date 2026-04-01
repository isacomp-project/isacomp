`timescale 1ns/1ps
module hppa_tb_simple;

    // Clock and reset
    reg clk;
    reg reset;

    // Reset values for all architectural state
    wire [31:0] reset_cr0_rd = 32'h0;
    wire [31:0] reset_cr10_rd = 32'h0;
    wire [31:0] reset_cr11_rd = 32'h0;
    wire [31:0] reset_cr16_rd = 32'h0;
    wire [31:0] reset_cr17_rd = 32'h0;
    wire [31:0] reset_cr18_rd = 32'h0;
    wire [31:0] reset_cr19_rd = 32'h0;
    wire [31:0] reset_cr20_rd = 32'h0;
    wire [31:0] reset_cr21_rd = 32'h0;
    wire [31:0] reset_cr22_rd = 32'h0;
    wire [31:0] reset_cr23_rd = 32'h0;
    wire [31:0] reset_cr24_rd = 32'h0;
    wire [31:0] reset_cr25_rd = 32'h0;
    wire [31:0] reset_cr8_rd = 32'h0;
    wire [31:0] reset_cr9_rd = 32'h0;
    wire [31:0] reset_fpsr_rd = 32'h0;
    wire [31:0] reset_iaoq_back_rd = 32'h0;
    wire [31:0] reset_iaoq = 32'h0;
    wire [31:0] reset_iiasq_rd = 32'h0;
    wire [31:0] reset_iir_rd = 32'h0;
    wire [31:0] reset_ior_rd = 32'h0;
    wire [31:0] reset_ipsw_rd = 32'h0;
    wire [31:0] reset_isr_rd = 32'h0;
    wire [31:0] reset_pc = 32'h0;
    wire [31:0] reset_psw = 32'h0;
    wire [4:0] reset_sar_rd = 5'h0;
    wire [31:0] reset_sr0_rd = 32'h0;
    wire [31:0] reset_sr1_rd = 32'h0;
    wire [31:0] reset_sr2_rd = 32'h0;
    wire [31:0] reset_sr3_rd = 32'h0;
    wire [31:0] reset_sr4_rd = 32'h0;
    wire [31:0] reset_sr5_rd = 32'h0;
    wire [31:0] reset_sr6_rd = 32'h0;
    wire [31:0] reset_sr7_rd = 32'h0;

    // Device Under Test
    hppa dut (
        .clk(clk),
        .reset(reset),
        .reset_cr0_rd(reset_cr0_rd),
        .reset_cr10_rd(reset_cr10_rd),
        .reset_cr11_rd(reset_cr11_rd),
        .reset_cr16_rd(reset_cr16_rd),
        .reset_cr17_rd(reset_cr17_rd),
        .reset_cr18_rd(reset_cr18_rd),
        .reset_cr19_rd(reset_cr19_rd),
        .reset_cr20_rd(reset_cr20_rd),
        .reset_cr21_rd(reset_cr21_rd),
        .reset_cr22_rd(reset_cr22_rd),
        .reset_cr23_rd(reset_cr23_rd),
        .reset_cr24_rd(reset_cr24_rd),
        .reset_cr25_rd(reset_cr25_rd),
        .reset_cr8_rd(reset_cr8_rd),
        .reset_cr9_rd(reset_cr9_rd),
        .reset_fpsr_rd(reset_fpsr_rd),
        .reset_iaoq_back_rd(reset_iaoq_back_rd),
        .reset_iaoq(reset_iaoq),
        .reset_iiasq_rd(reset_iiasq_rd),
        .reset_iir_rd(reset_iir_rd),
        .reset_ior_rd(reset_ior_rd),
        .reset_ipsw_rd(reset_ipsw_rd),
        .reset_isr_rd(reset_isr_rd),
        .reset_pc(reset_pc),
        .reset_psw(reset_psw),
        .reset_sar_rd(reset_sar_rd),
        .reset_sr0_rd(reset_sr0_rd),
        .reset_sr1_rd(reset_sr1_rd),
        .reset_sr2_rd(reset_sr2_rd),
        .reset_sr3_rd(reset_sr3_rd),
        .reset_sr4_rd(reset_sr4_rd),
        .reset_sr5_rd(reset_sr5_rd),
        .reset_sr6_rd(reset_sr6_rd),
        .reset_sr7_rd(reset_sr7_rd)
    );

    // Clock generation (10ns period = 100MHz)
    initial clk = 0;
    always #5 clk = ~clk;

    // Test execution
    integer cycle_count;
    reg [31:0] pass_pc;
    reg [31:0] fail_pc;

    initial begin
        cycle_count = 0;

        // Get pass/fail addresses from plusargs
        if (!$value$plusargs("pass_addr=%h", pass_pc)) begin
            pass_pc = 32'h24;  // Default pass address
        end
        if (!$value$plusargs("fail_addr=%h", fail_pc)) begin
            fail_pc = 32'h2c;  // Default fail address
        end

        $display("Pass address: 0x%08x", pass_pc);
        $display("Fail address: 0x%08x", fail_pc);

        // Wait for hppa.v initial block to complete before loading memory
        #1;

        // Load program into instruction memory
        $readmemh("program.hex", dut.umem);
        $display("Loaded program into memory");

        // Reset sequence
        reset = 1;
        repeat(5) @(posedge clk);
        reset = 0;
        $display("Reset released, starting execution...");

        // Monitor execution
        forever begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Debug: Print PC for first 10 cycles
            if (cycle_count <= 10) begin
                $display("Cycle %0d: PC=0x%08x", cycle_count, dut.pc_rd);
            end else if (cycle_count % 100 == 0) begin
                $display("Cycle %0d: PC = 0x%08x", cycle_count, dut.pc_rd);
            end

            if (cycle_count >= 10000) begin
                $display("ERROR: Timeout after %0d cycles", cycle_count);
                $display("Final PC: 0x%08x", dut.pc_rd);
                $display("FAILED");
                $finish(1);
            end

            // Check for pass condition (PC stuck at pass label)
            if (dut.pc_rd == pass_pc) begin
                $display("*** TEST PASSED *** at cycle %0d (PC=0x%08x)", cycle_count, pass_pc);
                $finish(0);
            end

            // Check for fail condition (PC stuck at fail label)
            if (dut.pc_rd == fail_pc) begin
                $display("*** TEST FAILED *** at cycle %0d (PC=0x%08x)", cycle_count, fail_pc);
                $display("Test number in r28: %0d", dut.rf[28]);
                $finish(1);
            end
        end
    end

    // Waveform dumping
    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("hppa_tb.vcd");
            $dumpvars(0, hppa_tb_simple);
        end
    end

endmodule
