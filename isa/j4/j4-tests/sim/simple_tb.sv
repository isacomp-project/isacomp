`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;
    wire [31:0] zero32 = 32'd0;

    j4_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_pc(zero32),
        .reset_sr(zero32),
        .reset_pr(zero32),
        .reset_vbr(zero32),
        .reset_gbr(zero32),
        .reset_mach(zero32),
        .reset_macl(zero32),
        .reset_fpscr(zero32),
        .reset_fpul(zero32),
        .reset_spc(zero32),
        .reset_ssr(zero32),
        .reset_sgr(zero32),
        .reset_dbr(zero32),
        .reset_delay_slot(1'b0),
        .reset_branch_target_rd(zero32),
        .reset_pteh(zero32),
        .reset_ptel(zero32),
        .reset_ttb(zero32),
        .reset_tea(zero32),
        .reset_mmucr(zero32),
        .reset_t(1'b0),
        .irq_i_rd(1'b0),
        .irq_i_wr(1'b0)
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
            if (i < 100) $display("Cycle %0d: PC=%h instr=%h t=%b spc=%h r0=%h rb0=%h sr=%h", i, dut.pc_rd, dut.instr, dut.t_rd, dut.spc_rd, dut.rf[0], dut.rf_bank[0], dut.sr_rd);
            if (dut.pc_rd == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (dut.pc_rd == fail_addr) begin $display("TEST FAILED at pc=%h testnum=%d", dut.pc_rd, dut.rf[4]); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
