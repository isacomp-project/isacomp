`timescale 1ns/1ps
module riscv32_tlb_tb_simple;

    // Clock and reset
    reg clk;
    reg reset;

    // Reset value signals
    wire [31:0] reset_pc = 32'h0;
    wire [1:0] reset_priv_mode = 2'b11;  // M-mode
    wire [31:0] reset_satp_rd = 32'h0;
    wire [31:0] reset_mtvec_rd = 32'h0;
    wire [31:0] reset_mepc = 32'h0;
    wire [31:0] reset_mcause_rd = 32'h0;
    wire [31:0] reset_mtval_rd = 32'h0;
    wire [31:0] reset_mscratch_rd = 32'h0;
    wire [31:0] reset_sepc = 32'h0;
    wire [31:0] reset_medeleg_rd = 32'h0;
    wire [31:0] reset_stvec_rd = 32'h0;
    wire [31:0] reset_scause_rd = 32'h0;
    wire [31:0] reset_stval_rd = 32'h0;
    wire [31:0] reset_sscratch_rd = 32'h0;
    wire [31:0] reset_sstatus_rd = 32'h0;

    // Device Under Test
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
        .reset_mscratch_rd(reset_mscratch_rd),
        .reset_sepc(reset_sepc),
        .reset_medeleg_rd(reset_medeleg_rd),
        .reset_stvec_rd(reset_stvec_rd),
        .reset_scause_rd(reset_scause_rd),
        .reset_stval_rd(reset_stval_rd),
        .reset_sscratch_rd(reset_sscratch_rd),
        .reset_sstatus_rd(reset_sstatus_rd)
    );

    // Clock generation: 10ns period (100MHz)
    initial clk = 0;
    always #5 clk = ~clk;

    // Test control
    string hex_file;
    integer pass_addr, fail_addr;
    integer max_cycles = 100000;
    integer cycle_count = 0;

    // Translation verification counters
    integer vm_enabled_cycles = 0;
    reg vm_ever_enabled = 0;

    // TLB statistics
    integer itlb_hits = 0, itlb_misses = 0;
    integer dtlb_hits = 0, dtlb_misses = 0;

    initial begin
        // Get hex file and pass/fail addresses from command line
        if (!$value$plusargs("hex=%s", hex_file)) begin
            $display("ERROR: No hex file specified. Use +hex=<file.hex>");
            $finish;
        end
        if (!$value$plusargs("pass_addr=%h", pass_addr)) begin
            pass_addr = 32'hFFFFFFFF;  // Invalid address if not specified
        end
        if (!$value$plusargs("fail_addr=%h", fail_addr)) begin
            fail_addr = 32'hFFFFFFFE;  // Invalid address if not specified
        end

        // Load hex file into unified memory
        $display("Loading hex file: %s", hex_file);
        $fflush();
        $readmemh(hex_file, dut.umem);
        $display("Loaded program into unified memory");
        $display("First few instructions:");
        $display("  umem[0] = 0x%08x", dut.umem[0]);
        $display("  umem[1] = 0x%08x", dut.umem[1]);
        $display("  umem[2] = 0x%08x", dut.umem[2]);
        $display("  umem[3] = 0x%08x", dut.umem[3]);
        // Dump page table area (PA 0x5000-0x6020 = word addr 0x1400-0x1808)
        $display("Page table dump:");
        $display("  L1 PT @ 0x5000: [0]=0x%08x [1]=0x%08x [2]=0x%08x [3]=0x%08x",
                 dut.umem[32'h1400], dut.umem[32'h1401], dut.umem[32'h1402], dut.umem[32'h1403]);
        $display("  L0 PT @ 0x6000: [0]=0x%08x [1]=0x%08x [2]=0x%08x [3]=0x%08x",
                 dut.umem[32'h1800], dut.umem[32'h1801], dut.umem[32'h1802], dut.umem[32'h1803]);
        $display("  L0 PT @ 0x6010: [4]=0x%08x [5]=0x%08x [6]=0x%08x [7]=0x%08x",
                 dut.umem[32'h1804], dut.umem[32'h1805], dut.umem[32'h1806], dut.umem[32'h1807]);
        $fflush();

        // Reset sequence
        reset = 1;
        repeat(5) @(posedge clk);
        reset = 0;
        $display("Reset released, starting execution...");
        $display("  Pass address: 0x%08x", pass_addr);
        $display("  Fail address: 0x%08x", fail_addr);
        $display("  Initial PC: 0x%08x", dut.pc);
        $fflush();
    end

    // Monitor for pass/fail
    always @(posedge clk) begin
        if (!reset) begin
            cycle_count = cycle_count + 1;

            // Track VM enabled cycles
            if (dut.satp_rd[31] == 1'b1) begin
                vm_enabled_cycles = vm_enabled_cycles + 1;
                vm_ever_enabled = 1;
            end

            // Track ITLB hits/misses (when VM enabled for instruction fetch)
            if (dut.vm_enabled) begin
                if (dut.itlb_hit_depth1 || dut.itlb_hit_depth2)
                    itlb_hits = itlb_hits + 1;
                else
                    itlb_misses = itlb_misses + 1;
            end

            // Track DTLB hits/misses (when VM enabled for data access)
            if (dut.addr_vm_enabled) begin
                if (dut.dtlb_hit_depth1 || dut.dtlb_hit_depth2)
                    dtlb_hits = dtlb_hits + 1;
                else
                    dtlb_misses = dtlb_misses + 1;
            end

            // Check for pass
            if (dut.pc == pass_addr) begin
                $display("");
                $display("========================================");
                $display("TEST PASSED at cycle %0d", cycle_count);
                $display("  VM enabled for %0d cycles", vm_enabled_cycles);
                if (vm_ever_enabled) begin
                    $display("  VM translation was enabled during test");
                    $display("  ITLB: %0d hits, %0d misses (%.1f%% hit rate)",
                             itlb_hits, itlb_misses,
                             (itlb_hits + itlb_misses > 0) ? 100.0 * itlb_hits / (itlb_hits + itlb_misses) : 0.0);
                    $display("  DTLB: %0d hits, %0d misses (%.1f%% hit rate)",
                             dtlb_hits, dtlb_misses,
                             (dtlb_hits + dtlb_misses > 0) ? 100.0 * dtlb_hits / (dtlb_hits + dtlb_misses) : 0.0);
                end
                $display("========================================");
                $finish;
            end

            // Check for fail
            if (dut.pc == fail_addr) begin
                $display("");
                $display("========================================");
                $display("TEST FAILED at cycle %0d", cycle_count);
                $display("  TESTNUM = %0d", dut.rf[3]);  // x3/gp holds test number
                $display("  PC = 0x%08x", dut.pc);
                $display("========================================");
                $finish;
            end

            // Timeout
            if (cycle_count >= max_cycles) begin
                $display("");
                $display("========================================");
                $display("TIMEOUT after %0d cycles", max_cycles);
                $display("  Last PC: 0x%08x", dut.pc);
                $display("  TESTNUM = %0d", dut.rf[3]);
                $display("========================================");
                $finish;
            end
        end
    end

    // Debug output (optional, can be enabled with +trace)
    reg trace_enabled = 0;
    initial begin
        if ($value$plusargs("trace=%d", trace_enabled)) begin
            trace_enabled = 1;
        end
    end

    reg prev_vm_enabled = 0;
    reg [31:0] prev_pc = 0;
    always @(posedge clk) begin
        if (trace_enabled && !reset && cycle_count < 2000) begin
            $display("[%0d] PC=0x%08x instr=0x%08x priv=%0d vm=%0d",
                     cycle_count, dut.pc, dut.umem[dut.pc[19:2]], dut.priv_mode, dut.vm_enabled);
        end
        // Detect when VM is enabled
        if (!reset && dut.vm_enabled && !prev_vm_enabled) begin
            $display("[%0d] *** VM ENABLED *** (SATP=0x%08x, priv=%0d)", cycle_count, dut.satp_rd, dut.priv_mode);
            $display("  pte1_addr=0x%08x pte1=0x%08x pte1_v=%0d is_leaf=%0d",
                     dut.pte1_addr, dut.pte1, dut.pte1_v, dut.is_leaf_pte1);
            $display("  pte0_addr=0x%08x pte0=0x%08x pte0_v=%0d",
                     dut.pte0_addr, dut.pte0, dut.pte0_v);
            $display("  final_pte_v=%0d final_pte_x=%0d exception_taken=%0d",
                     dut.final_pte_v, dut.final_pte_x, dut.exception_taken);
            $display("  sret_enable=%0d delegate_to_smode=%0d jal_enable=%0d",
                     dut.sret_enable, dut.delegate_to_smode, dut.jal_enable);
            $display("  trap_target=0x%08x pc_pa=0x%08x instr=0x%08x",
                     dut.trap_target, dut.pc_pa, dut.instr);
            $display("  original_priv_mode=%0d vm_enabled_for_fetch=%0d is_m_mode_orig=%0d",
                     dut.original_priv_mode, dut.vm_enabled_for_fetch, dut.is_m_mode_orig);
        end
        prev_vm_enabled <= dut.vm_enabled;

        // Detect PC jump to trap handler (0x154 or virtual equivalent)
        if (!reset && (dut.pc == 32'h00000154 || dut.pc == 32'hffc00154)) begin
            $display("[%0d] *** TRAP ENTRY *** prev_pc=0x%08x", cycle_count, prev_pc);
        end
        // One cycle after trap entry, show CSR values (after register update)
        if (!reset && (prev_pc == 32'h00000154 || prev_pc == 32'hffc00154)) begin
            $display("[%0d] *** TRAP CSRs *** scause=0x%08x stval=0x%08x sepc=0x%08x",
                     cycle_count, dut.scause_rd, dut.stval_rd, dut.sepc);
        end
        prev_pc <= dut.pc;
    end

endmodule
