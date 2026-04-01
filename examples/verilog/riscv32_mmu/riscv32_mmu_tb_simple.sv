`timescale 1ns/1ps
module riscv32_mmu_tb_simple;

    // Clock and reset
    reg clk;
    reg reset;

    // Reset value signals
    wire [31:0] reset_pc = 32'h0;
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

    // Device Under Test
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
        .reset_sscratch_rd(reset_sscratch_rd)
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
    integer translation_diff_cycles = 0;
    reg vm_ever_enabled = 0;
    reg translation_ever_differed = 0;
    reg [31:0] first_translated_pc = 0;
    reg [31:0] first_original_pc = 0;

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

        // Load hex file into instruction memory and data memory
        $display("Loading hex file: %s", hex_file);
        $fflush();
        $readmemh(hex_file, dut.imem);
        $readmemh(hex_file, dut.dmem);
        $display("Loaded program into instruction and data memory");
        $display("First few instructions:");
        $display("  imem[0] = 0x%08x", dut.imem[0]);
        $display("  imem[1] = 0x%08x", dut.imem[1]);
        $display("  imem[2] = 0x%08x", dut.imem[2]);
        $display("  imem[3] = 0x%08x", dut.imem[3]);
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

            // Debug PC update logic
            if (cycle_count <= 20 || (cycle_count >= 78 && cycle_count <= 90)) begin
                $display("Cycle %0d: pc_rd=%h pc_vm_result=%h instr=%h sret_en=%b jal_en=%b",
                         cycle_count, dut.pc_rd, dut.pc_vm_result, dut.instr, dut.sret_enable, dut.jal_enable);
            end

            // Track VM translation activity
            if (dut.vm_enabled) begin
                vm_enabled_cycles = vm_enabled_cycles + 1;
                if (!vm_ever_enabled) begin
                    vm_ever_enabled = 1;
                    $display("*** VM ENABLED for first time at cycle %0d ***", cycle_count);
                    $display("    satp=0x%08x priv=%b", dut.satp_rd, dut.priv_mode_rd);
                end

                // Check if translation actually differs from original PC
                if (dut.pc_translated != dut.original_pc) begin
                    translation_diff_cycles = translation_diff_cycles + 1;
                    if (!translation_ever_differed) begin
                        translation_ever_differed = 1;
                        first_original_pc = dut.original_pc;
                        first_translated_pc = dut.pc_translated;
                        $display("*** TRANSLATION OCCURRED for first time at cycle %0d ***", cycle_count);
                        $display("    original_pc=0x%08x -> pc_translated=0x%08x",
                                 dut.original_pc, dut.pc_translated);
                        $display("    pte1=0x%08x pte0=0x%08x", dut.pte1, dut.pte0);
                    end
                end
            end

            // Debug: print store instructions when dmem_write_enable is active
            if (dut.dmem_write_enable) begin
                $display("Cycle %0d: STORE PC=0x%08x addr=0x%08x addr_pa=0x%08x data=0x%08x sw=%b sh=%b sb=%b",
                         cycle_count, dut.pc, dut.sb_addr, dut.sb_addr_pa, dut.dmem_write_data_mux,
                         dut.sw_enable, dut.sh_enable, dut.sb_enable);
            end

            // Track dmem[0xAF54/4] around the critical cycles
            if (cycle_count >= 1186 && cycle_count <= 1195) begin
                $display("Cycle %0d: dmem[0x2BD5]=0x%08x", cycle_count, dut.dmem[32'h2BD5]);
            end

            // Detect sret execution
            if (dut.sret_enable) begin
                $display("Cycle %0d: SRET executing! sepc=0x%08x sepc_val=0x%08x pc_wr_mux=0x%08x",
                         cycle_count, dut.sepc, dut.sepc_val, dut.pc_wr_mux);
            end

            // Track sepc changes
            if (dut.csrrw_enable && dut.is_sepc) begin
                $display("Cycle %0d: CSRRW to SEPC! new_val=0x%08x rs1=%d rs1_val=0x%08x PC=0x%08x instr=0x%08x rf5=0x%08x",
                         cycle_count, dut.csrrw_new_csr_val, dut.rs1, dut.r1, dut.pc, dut.instr, dut.rf[5]);
            end

            // Track exception handling around sret
            if (cycle_count >= 1222 && cycle_count <= 1230) begin
                $display("Cycle %0d: PC=0x%08x instr=0x%08x exc_taken=%b vm=%b pte1=0x%08x pte0=0x%08x final_pte_x=%b final_pte_v=%b",
                         cycle_count, dut.pc, dut.instr, dut.exception_taken, dut.vm_enabled, dut.pte1, dut.pte0, dut.final_pte_x, dut.final_pte_v);
            end
            if (dut.sepc_wr !== dut.sepc) begin
                $display("Cycle %0d: SEPC changing! old=0x%08x new=0x%08x sepc_wr_mux=0x%08x is_sepc=%b csrrw=%b csrrwi=%b",
                         cycle_count, dut.sepc, dut.sepc_wr, dut.sepc_wr_mux, dut.is_sepc, dut.csrrw_enable, dut.csrrwi_enable);
            end

            // Track satp changes
            if (dut.satp_wr !== dut.satp_rd) begin
                $display("Cycle %0d: SATP changing! old=0x%08x new=0x%08x PC=0x%08x instr=0x%08x is_satp=%b csrrw=%b csrrs=%b csrrc=%b",
                         cycle_count, dut.satp_rd, dut.satp_wr, dut.pc, dut.instr, dut.is_satp, dut.csrrw_enable, dut.csrrs_enable, dut.csrrc_enable);
            end

            // Print first 100 cycles, around S-mode transition, then every 50
            if (cycle_count <= 100 || (cycle_count >= 1200 && cycle_count <= 1280) || cycle_count % 50 == 0) begin
                $display("Cycle %0d: PC=0x%08x sepc=0x%08x satp_rd=0x%08x priv=%b vm=%b is_m=%b satp_mode=%b invis_m=%b orig_pc=0x%08x xlated=0x%08x",
                         cycle_count, dut.pc, dut.sepc, dut.satp_rd, dut.priv_mode_rd, dut.vm_enabled, dut.is_m_mode,
                         dut.satp_mode, dut.invis_m_mode, dut.original_pc, dut.pc_translated);
                $fflush();
            end

            // Check for ecall instruction
            // The v environment uses: li a0, 1; ecall for pass
            //                         a0 = (testnum << 1) | 1 for fail
            if (dut.ecall_enable) begin
                if (dut.rf[10] == 32'd1) begin  // a0 == 1 means pass
                    $display("\n========================================");
                    $display("TEST PASSED (via ecall) at cycle %0d", cycle_count);
                    $display("PC = 0x%08x, a0 = %0d", dut.pc, dut.rf[10]);
                    $display("----------------------------------------");
                    $display("VM Translation Statistics:");
                    $display("  vm_enabled cycles: %0d", vm_enabled_cycles);
                    $display("  translation diff cycles: %0d", translation_diff_cycles);
                    if (vm_ever_enabled)
                        $display("  VM was enabled: YES");
                    else
                        $display("  VM was enabled: NO (TEST MAY NOT HAVE RUN WITH MMU!)");
                    if (translation_ever_differed)
                        $display("  Translation occurred: YES (0x%08x -> 0x%08x)",
                                 first_original_pc, first_translated_pc);
                    else
                        $display("  Translation occurred: NO (ADDRESSES NEVER DIFFERED!)");
                    $display("========================================\n");
                    if (!vm_ever_enabled || !translation_ever_differed) begin
                        $display("WARNING: Test passed but VM translation may not have occurred!");
                    end
                    $finish;
                end else begin
                    $display("\n========================================");
                    $display("TEST FAILED (via ecall) at cycle %0d", cycle_count);
                    $display("PC = 0x%08x, a0 = %0d", dut.pc, dut.rf[10]);
                    $display("TESTNUM = %0d", dut.rf[10] >> 1);
                    $display("----------------------------------------");
                    $display("VM Translation Statistics:");
                    $display("  vm_enabled cycles: %0d", vm_enabled_cycles);
                    $display("  translation diff cycles: %0d", translation_diff_cycles);
                    $display("========================================\n");
                    $finish;
                end
            end

            // Check for pass condition (legacy PC-based detection)
            if (dut.pc == pass_addr) begin
                $display("\n========================================");
                $display("TEST PASSED at cycle %0d", cycle_count);
                $display("PC = 0x%08x", dut.pc);
                $display("========================================\n");
                $finish;
            end

            // Check for fail condition (legacy PC-based detection)
            if (dut.pc == fail_addr) begin
                $display("\n========================================");
                $display("TEST FAILED at cycle %0d", cycle_count);
                $display("PC = 0x%08x", dut.pc);
                $display("x28 (TESTNUM) = %0d", dut.rf[28]);
                $display("========================================\n");
                $finish;
            end

            // Timeout check
            if (cycle_count >= max_cycles) begin
                $display("\n========================================");
                $display("TIMEOUT after %0d cycles", cycle_count);
                $display("Final PC = 0x%08x", dut.pc);
                $display("========================================\n");
                $finish;
            end
        end
    end

endmodule
