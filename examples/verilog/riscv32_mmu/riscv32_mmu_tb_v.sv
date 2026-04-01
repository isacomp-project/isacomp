`timescale 1ns/1ps
// Simple testbench for riscv32_mmu processor - V environment tests
// Uses PC-based pass/fail detection
module riscv32_mmu_tb_v;
    reg clk, reset;

    // Reset values for MMU processor - V-environment starts in M-mode
    wire [31:0] reset_pc = 32'h80000000;
    wire [1:0] reset_priv_mode_rd = 2'b11;  // M-mode
    wire [31:0] reset_satp_rd = 32'h0;
    wire [31:0] reset_mtvec_rd = 32'h0;
    wire [31:0] reset_mepc = 32'h0;
    wire [31:0] reset_mcause_rd = 32'h0;
    wire [31:0] reset_mtval_rd = 32'h0;
    wire [31:0] reset_sepc = 32'h0;
    wire [31:0] reset_medeleg_rd = 32'h0;
    wire [31:0] reset_stvec_rd = 32'h0;
    wire [31:0] reset_scause_rd = 32'h0;
    wire [31:0] reset_stval_rd = 32'h0;
    wire [31:0] reset_sscratch_rd = 32'h0;
    wire [31:0] reset_mscratch_rd = 32'h0;

    riscv32_mmu dut (
        .clk(clk),
        .reset(reset),
        .reset_pc(reset_pc),
        .reset_priv_mode_rd(reset_priv_mode_rd),
        .reset_satp_rd(reset_satp_rd),
        .reset_mtvec_rd(reset_mtvec_rd),
        .reset_mepc(reset_mepc),
        .reset_mcause_rd(reset_mcause_rd),
        .reset_mtval_rd(reset_mtval_rd),
        .reset_sepc(reset_sepc),
        .reset_medeleg_rd(reset_medeleg_rd),
        .reset_stvec_rd(reset_stvec_rd),
        .reset_scause_rd(reset_scause_rd),
        .reset_stval_rd(reset_stval_rd),
        .reset_sscratch_rd(reset_sscratch_rd),
        .reset_mscratch_rd(reset_mscratch_rd)
    );

    reg [31:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    // Byte array for loading hex file
    reg [7:0] byte_mem [0:524287];  // 512KB for v-tests
    string hex_file;

    initial begin
        clk = 0; reset = 1;

        // Get addresses from plusargs
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;

        // Get hex file
        if (!$value$plusargs("hex=%s", hex_file)) begin
            $display("ERROR: No hex file specified");
            $finish;
        end

        // Initialize and load hex
        for (i = 0; i < 524288; i = i + 1) byte_mem[i] = 8'h00;
        $readmemh(hex_file, byte_mem);

        // Pack bytes into 32-bit words (little-endian)
        for (i = 0; i < 131072; i = i + 1) begin
            dut.umem[i] = {byte_mem[i*4+3], byte_mem[i*4+2], byte_mem[i*4+1], byte_mem[i*4]};
        end

        repeat(3) @(posedge clk);
        reset = 0;

        for (i = 0; i < 100000; i = i + 1) begin
            @(posedge clk);
            if (dut.pc == pass_addr) begin
                $display("TEST PASSED at cycle %0d", i);
                $finish;
            end
            if (dut.pc == fail_addr) begin
                $display("TEST FAILED at pc=%h gp=%0d", dut.pc, dut.rf[3]);
                $finish;
            end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
