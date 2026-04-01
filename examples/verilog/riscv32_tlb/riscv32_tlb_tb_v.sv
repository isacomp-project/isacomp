`timescale 1ns/1ps
// Testbench for riscv32_tlb processor - V environment tests
// Uses PC-based pass/fail detection
module riscv32_tlb_tb_v;
    reg clk, reset;

    // Reset values for TLB processor - V-environment starts in M-mode at 0x0
    wire [31:0] reset_pc = 32'h00000000;
    wire [1:0] reset_priv_mode = 2'b11;  // M-mode
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
    wire [31:0] reset_sstatus_rd = 32'h0;

    riscv32_tlb dut (
        .clk(clk),
        .reset(reset),
        .reset_pc(reset_pc),
        .reset_priv_mode(reset_priv_mode),
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
        .reset_mscratch_rd(reset_mscratch_rd),
        .reset_sstatus_rd(reset_sstatus_rd)
    );

    reg [31:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    string hex_file;

    // TLB statistics - track accesses and hit/miss/superpage
    // Superpages (4MB) are now cached in TLB with depth=1
    integer itlb_hits, itlb_misses, itlb_superpages;
    integer dtlb_hits, dtlb_misses, dtlb_superpages;
    reg [31:0] prev_pc;
    reg prev_addr_vm_enabled;

    always @(posedge clk) begin
        if (reset) begin
            prev_pc <= 32'h0;
            prev_addr_vm_enabled <= 0;
        end else begin
            // ITLB: Track when we start a new fetch with VM enabled
            if (dut.pc != prev_pc && dut.vm_enabled_for_fetch) begin
                if (dut.itlb_hit_depth1 || dut.itlb_hit_depth2) begin
                    itlb_hits <= itlb_hits + 1;
                end else if (dut.is_leaf_pte1) begin
                    // Superpage miss - PTW found leaf at pte1, will fill TLB with depth=1
                    itlb_superpages <= itlb_superpages + 1;
                end else begin
                    itlb_misses <= itlb_misses + 1;
                end
            end
            prev_pc <= dut.pc;

            // DTLB: Track when a load/store starts with VM enabled
            if (dut.addr_vm_enabled && !prev_addr_vm_enabled) begin
                if (dut.dtlb_hit_depth1 || dut.dtlb_hit_depth2) begin
                    dtlb_hits <= dtlb_hits + 1;
                end else if (dut.addr_is_leaf_pte1) begin
                    dtlb_superpages <= dtlb_superpages + 1;
                end else begin
                    dtlb_misses <= dtlb_misses + 1;
                end
            end
            prev_addr_vm_enabled <= dut.addr_vm_enabled;
        end
    end

    initial begin
        clk = 0; reset = 1;
        itlb_hits = 0; itlb_misses = 0; itlb_superpages = 0;
        dtlb_hits = 0; dtlb_misses = 0; dtlb_superpages = 0;

        // Get addresses from plusargs
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;

        // Get hex file
        if (!$value$plusargs("hex=%s", hex_file)) begin
            $display("ERROR: No hex file specified");
            $finish;
        end

        // Initialize memory to zero
        for (i = 0; i < 262144; i = i + 1) dut.umem[i] = 32'h0;

        // Load hex file directly into word-addressed memory
        // (hex file is already in 32-bit word format, little-endian encoded)
        $readmemh(hex_file, dut.umem);

        repeat(3) @(posedge clk);
        reset = 0;

        for (i = 0; i < 100000; i = i + 1) begin
            @(posedge clk);

            if (dut.pc == pass_addr) begin
                $display("TEST PASSED at cycle %0d", i);
                $display("  ITLB: %0d hits, %0d 4KB misses, %0d superpage fills",
                         itlb_hits, itlb_misses, itlb_superpages);
                $display("  DTLB: %0d hits, %0d 4KB misses, %0d superpage fills",
                         dtlb_hits, dtlb_misses, dtlb_superpages);
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
