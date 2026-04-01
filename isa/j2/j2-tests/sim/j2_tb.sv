`timescale 1ns/1ps
// Simple testbench for J2 processor
// Loads hex file via $readmemh, checks for pass/fail addresses

module j2_tb;
    reg clk, reset;
    wire [31:0] zero32 = 32'd0;
    wire zero1 = 1'b0;
    // SR initial value: MD=1 (privileged mode), BL=0 (exceptions enabled)
    wire [31:0] init_sr = 32'h40000000;

    j2_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_pc(zero32),
        .reset_pr(zero32),
        .reset_t_rd(zero1),
        .reset_delay_slot(zero1),
        .reset_branch_target_rd(zero32),
        .reset_macl(zero32),
        .reset_mach(zero32),
        .reset_gbr(zero32),
        .reset_sr(init_sr),
        .reset_vbr(zero32)
    );

    reg [31:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    initial begin
        clk = 0; reset = 1;

        // Get pass/fail addresses from command line
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;

        // Memory is loaded by the DUT's initial block from imem.hex, dmem.hex, rf.hex

        // Reset sequence
        repeat(3) @(posedge clk);
        reset = 0;

        // Run simulation
        $display("pass_addr=0x%h fail_addr=0x%h", pass_addr, fail_addr);
        for (i = 0; i < 10000; i = i + 1) begin
            @(posedge clk);
            // Display actual decoded instruction (select halfword from 32-bit word based on PC[1])
            if (i < 200 || (dut.pc_rd >= 32'h600 && dut.pc_rd <= 32'h640)) begin
                $display("Cycle %0d: PC=0x%h instr=0x%h T=%b SR=%h R0=%h R8=%h R15=%h", i, dut.pc_rd,
                    dut.pc_rd[1] ? dut.umem[dut.pc_rd[12:2]][15:0] : dut.umem[dut.pc_rd[12:2]][31:16],
                    dut.t_rd, dut.sr_rd, dut.rf[0], dut.rf[8], dut.rf[15]);
            end
            if (dut.pc_rd == pass_addr) begin
                $display("TEST PASSED at cycle %0d", i);
                $finish;
            end
            if (dut.pc_rd == fail_addr) begin
                $display("TEST FAILED at pc=%h cycle=%0d", dut.pc_rd, i);
                $finish;
            end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
