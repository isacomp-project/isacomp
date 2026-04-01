// OpenSBI Boot Testbench for RISC-V 32 MMU
// Loads OpenSBI firmware and boots in Verilator simulation
//
// Memory Map:
//   0x80000000 - 0x83EFFFFF: Main RAM (63MB)
//   0x83F00000 - 0x83FFFFFF: Reserved for peripherals (1MB)
//     0x83F00000 - 0x83F000FF: UART (NS16550A compatible)
//     0x83F10000 - 0x83F1FFFF: CLINT (timer)

`timescale 1ns/1ps

module opensbi_boot_tb;
    // Clock generation
    reg clk = 0;
    always #10 clk = ~clk;  // 50MHz

    // Reset
    reg reset;
    integer reset_counter;

    // Memory layout
    localparam MEMORY_BASE = 32'h80000000;  // OpenSBI expects RAM at 0x80000000
    localparam MEMORY_SIZE = 32'h03f00000;  // 63MB (last 1MB reserved for peripherals)
    localparam CLINT_BASE  = 32'h83f10000;  // In reserved peripheral region
    localparam UART_BASE   = 32'h83f00000;  // In reserved peripheral region

    // FDT location - must match OpenSBI's FW_FDT_PATH configuration
    // OpenSBI fw_payload.bin is built with FDT at 0x82200000
    localparam FDT_ADDR    = 32'h82200000;  // 34MB offset, matches OpenSBI config

    // Entry point for OpenSBI (passed via plusarg)
    reg [31:0] entry_point;
    reg [31:0] fdt_addr;

    // =========================================================================
    // CLINT (Timer) Instance
    // =========================================================================
    logic [31:0] clint_addr;
    logic [31:0] clint_wdata;
    logic        clint_we;
    logic        clint_re;
    logic [31:0] clint_rdata;
    logic        clint_ack;
    logic [31:0] mtime_lo;
    logic [31:0] mtime_hi;
    logic        timer_irq_pending;
    logic        sw_irq_pending;

    clint #(
        .BASE_ADDR(CLINT_BASE),
        .CLOCK_FREQ_HZ(50_000_000),
        .TIMER_FREQ_HZ(10_000_000)
    ) clint_inst (
        .clk(clk),
        .reset(reset),
        .bus_addr(clint_addr),
        .bus_wdata(clint_wdata),
        .bus_we(clint_we),
        .bus_re(clint_re),
        .bus_rdata(clint_rdata),
        .bus_ack(clint_ack),
        .mtime_lo(mtime_lo),
        .mtime_hi(mtime_hi),
        .timer_irq_pending(timer_irq_pending),
        .sw_irq_pending(sw_irq_pending)
    );

    // =========================================================================
    // UART Instance
    // =========================================================================
    logic [31:0] uart_addr;
    logic [31:0] uart_wdata;
    logic        uart_we;
    logic        uart_re;
    logic [31:0] uart_rdata;
    logic        uart_ack;
    logic        uart_tx_valid;
    logic [7:0]  uart_tx_data;

    fake_uart #(
        .BASE_ADDR(UART_BASE)
    ) uart_inst (
        .clk(clk),
        .reset(reset),
        .bus_addr(uart_addr),
        .bus_wdata(uart_wdata),
        .bus_we(uart_we),
        .bus_re(uart_re),
        .bus_rdata(uart_rdata),
        .bus_ack(uart_ack),
        .tx_valid(uart_tx_valid),
        .tx_data(uart_tx_data)
    );

    // =========================================================================
    // CPU Instance
    // =========================================================================
    riscv32_mmu cpu (
        .clk(clk),
        .reset(reset),

        // Reset values
        .reset_pc(entry_point),
        .reset_priv_mode(2'b11),              // M-mode
        .reset_satp_rd(32'h0),                // VM disabled initially
        .reset_mtvec_rd(32'h0),
        .reset_mepc(32'h0),
        .reset_mcause_rd(32'h0),
        .reset_mtval_rd(32'h0),
        .reset_sepc(32'h0),
        .reset_mscratch_rd(32'h0),
        .reset_sscratch_rd(32'h0),
        .reset_sstatus_rd(32'h0),             // S-mode status register
        .reset_medeleg_rd(32'h0),
        .reset_stvec_rd(32'h0),
        .reset_scause_rd(32'h0),
        .reset_stval_rd(32'h0),
        .reset_mie_rd(32'h0),
        .reset_mstatus_rd(32'h0),
        .reset_stimecmp_rd(32'hFFFFFFFF),   // Max value to prevent immediate interrupt
        .reset_stimecmph_rd(32'hFFFFFFFF),  // Max value to prevent immediate interrupt
        .reset_lr_reservation_rd(32'h0),    // No LR reservation initially

        // Timer inputs from CLINT
        .mtime_lo_rd(mtime_lo),
        .mtime_lo_wr(mtime_lo),
        .mtime_hi_rd(mtime_hi),
        .mtime_hi_wr(mtime_hi),
        .timer_irq_pending_rd(timer_irq_pending),
        .timer_irq_pending_wr(timer_irq_pending)
    );

    // =========================================================================
    // Peripheral Bus Controller
    // Intercepts CPU memory accesses to peripheral ranges
    // =========================================================================

    // Detect store instructions (unified write enable)
    wire store_enable = cpu.umem_write_enable;
    wire load_enable = cpu.lw_enable || cpu.lh_enable || cpu.lhu_enable ||
                       cpu.lb_enable || cpu.lbu_enable;

    // Get load address for debugging (use umem read address)
    wire [31:0] load_addr = cpu.umem_addr_pa_rd;
    wire is_clint_load = (load_addr >= CLINT_BASE) && (load_addr < (CLINT_BASE + 32'h10000));

    // Get the physical address being accessed (use unified write address)
    wire [31:0] store_addr = cpu.umem_write_addr_mux;
    wire [31:0] store_data = cpu.umem_write_data_mux;

    // Check if access is to peripheral range
    wire is_clint_access = (store_addr >= CLINT_BASE) && (store_addr < (CLINT_BASE + 32'h10000));
    wire is_uart_access = (store_addr >= UART_BASE) && (store_addr < (UART_BASE + 32'h100));

    // MMIO mapping constants for mirroring peripheral values to umem
    // Peripherals in reserved last 1MB map directly to umem without conflicts
    // CLINT at 0x83F10000: (0x83F10000 - 0x80000000) >> 2 = 0x00FC4000
    localparam CLINT_UMEM_BASE = 32'h00fc4000;
    // UART at 0x83F00000: (0x83F00000 - 0x80000000) >> 2 = 0x00FC0000
    localparam UART_UMEM_BASE = 32'h00fc0000;

    // Forward peripheral writes
    always_ff @(posedge clk) begin
        if (reset) begin
            clint_we <= 1'b0;
            clint_re <= 1'b0;
            uart_we <= 1'b0;
            uart_re <= 1'b0;
        end else begin
            // Default: no bus operations
            clint_we <= 1'b0;
            clint_re <= 1'b0;
            uart_we <= 1'b0;
            uart_re <= 1'b0;

            // Handle stores to peripherals
            if (store_enable) begin
                if (is_clint_access) begin
                    clint_addr <= store_addr;
                    clint_wdata <= store_data;
                    clint_we <= 1'b1;
                    $display("[%0d] CLINT WRITE: addr=0x%08x data=0x%08x offset=0x%04x",
                             cycle_count, store_addr, store_data, store_addr[15:0]);
                end else if (is_uart_access) begin
                    uart_addr <= store_addr;
                    uart_wdata <= store_data;
                    uart_we <= 1'b1;
                    // Check if this is LCR write (offset 3) - marks UART as initialized
                    if (store_addr[3:0] == 4'h3 && store_data[7] == 1'b0) begin
                        uart_initialized <= 1'b1;
                    end
                    // Log THR writes (offset 0) to file after UART is initialized
                    if (store_addr[3:0] == 4'h0 && uart_initialized) begin
                        $fwrite(uart_log_handle, "%c", store_data[7:0]);
                        $fflush(uart_log_handle);
                    end
                end
            end

            // =========================================================================
            // Mirror CLINT registers to umem for CPU reads
            // CLINT register offsets (from 0x02000000):
            //   0x0000: MSIP
            //   0x4000: MTIMECMP_LO / 0x4004: MTIMECMP_HI
            //   0xBFF8: MTIME_LO / 0xBFFC: MTIME_HI
            // =========================================================================
            // Debug: verify peripheral umem mapping once
            if (cycle_count == 1) begin
                $display("CLINT_UMEM_BASE = 0x%08x (maps to 0x%08x)", CLINT_UMEM_BASE, CLINT_BASE);
                $display("UART_UMEM_BASE = 0x%08x (maps to 0x%08x)", UART_UMEM_BASE, UART_BASE);
                $display("MTIME offset = 0x%08x", CLINT_UMEM_BASE + (32'hBFF8 >> 2));
            end
            // MSIP at offset 0x0000
            cpu.umem[CLINT_UMEM_BASE + 0] <= {31'b0, clint_inst.msip};
            // MTIMECMP at offset 0x4000
            cpu.umem[CLINT_UMEM_BASE + (32'h4000 >> 2)] <= clint_inst.mtimecmp[31:0];
            cpu.umem[CLINT_UMEM_BASE + (32'h4004 >> 2)] <= clint_inst.mtimecmp[63:32];
            // MTIME at offset 0xBFF8
            cpu.umem[CLINT_UMEM_BASE + (32'hBFF8 >> 2)] <= clint_inst.mtime[31:0];
            cpu.umem[CLINT_UMEM_BASE + (32'hBFFC >> 2)] <= clint_inst.mtime[63:32];

            // =========================================================================
            // Mirror UART registers to umem for CPU reads
            // Word 0 (offsets 0-3): THR/RBR, IER, IIR/FCR, LCR
            // Word 1 (offsets 4-7): MCR, LSR, MSR, SCR
            // LSR at byte offset 5 = bits [15:8] of word 1
            // =========================================================================
            cpu.umem[UART_UMEM_BASE + 1] <= {16'h0, uart_inst.lsr, 8'h0};

            // NOTE: stimecmp and CLINT mtimecmp are INDEPENDENT in RISC-V sstc extension.
            // stimecmp generates STIP internally in the CPU (mmu.isa: stip = mtime >= stimecmp).
            // CLINT mtimecmp generates MTIP and is only written via M-mode MMIO writes.
            // Do NOT mirror stimecmp to mtimecmp - that causes M-mode timer floods.
        end
    end

    // =========================================================================
    // Boot Image Loading
    // =========================================================================
    string firmware_file;
    string fdt_file;
    integer file_handle;
    integer uart_log_handle;
    integer bytes_read;
    reg [7:0] byte_data;
    integer word_count;
    integer fdt_word_offset;
    integer i, j;
    reg uart_initialized;

    initial begin
        // Get firmware file from command line
        if (!$value$plusargs("firmware=%s", firmware_file)) begin
            firmware_file = "fw_jump.bin";
        end

        // Get FDT file from command line
        if (!$value$plusargs("fdt_file=%s", fdt_file)) begin
            fdt_file = "riscv32_mmu.dtb";
        end

        // Get entry point
        if (!$value$plusargs("entry=0x%h", entry_point)) begin
            entry_point = MEMORY_BASE;  // 0x80000000
        end

        // Get FDT address
        if (!$value$plusargs("fdt=0x%h", fdt_addr)) begin
            fdt_addr = FDT_ADDR;
        end

        $display("==============================================");
        $display("OpenSBI Boot Testbench");
        $display("==============================================");
        $display("Firmware: %s", firmware_file);
        $display("FDT file: %s", fdt_file);
        $display("Entry point: 0x%08x", entry_point);
        $display("FDT address: 0x%08x", fdt_addr);
        $display("==============================================");

        // Open UART log file
        uart_log_handle = $fopen("uart_output.txt", "w");
        uart_initialized = 0;

        // Reset sequence
        reset = 1;
        reset_counter = 0;

        // Wait for clock to stabilize
        repeat(10) @(posedge clk);

        // Load firmware into memory
        $display("Loading firmware...");
        file_handle = $fopen(firmware_file, "rb");
        if (file_handle == 0) begin
            $display("ERROR: Cannot open firmware file: %s", firmware_file);
            $finish;
        end

        word_count = 0;
        while (!$feof(file_handle)) begin
            // Read 4 bytes (little-endian)
            for (j = 0; j < 4; j = j + 1) begin
                bytes_read = $fread(byte_data, file_handle);
                if (bytes_read == 1) begin
                    // OpenSBI expects to be at 0x80000000, but our memory starts at 0
                    // So we load at offset (entry_point - 0x80000000)
                    cpu.umem[word_count][j*8 +: 8] = byte_data;
                end
            end
            word_count = word_count + 1;
        end
        $fclose(file_handle);
        $display("Loaded %0d words (%0d bytes)", word_count, word_count * 4);

        // Load FDT into memory at FDT_ADDR
        $display("Loading FDT...");
        file_handle = $fopen(fdt_file, "rb");
        if (file_handle == 0) begin
            $display("WARNING: Cannot open FDT file: %s (continuing without FDT)", fdt_file);
        end else begin
            // FDT word offset = (FDT_ADDR - MEMORY_BASE) / 4
            fdt_word_offset = (fdt_addr - MEMORY_BASE) >> 2;
            word_count = 0;
            while (!$feof(file_handle)) begin
                for (j = 0; j < 4; j = j + 1) begin
                    bytes_read = $fread(byte_data, file_handle);
                    if (bytes_read == 1) begin
                        cpu.umem[fdt_word_offset + word_count][j*8 +: 8] = byte_data;
                    end
                end
                word_count = word_count + 1;
            end
            $fclose(file_handle);
            $display("Loaded FDT: %0d words (%0d bytes) at 0x%08x", word_count, word_count * 4, fdt_addr);
            // Display FDT magic (should be 0xd00dfeed in big-endian = 0xedfe0dd0 in little-endian memory)
            $display("FDT magic: 0x%08x", cpu.umem[fdt_word_offset]);
        end

        // Set a1 register to FDT address (OpenSBI expects FDT pointer in a1)
        cpu.rf[11] = fdt_addr;
        $display("Set a1 (x11) = 0x%08x (FDT address)", fdt_addr);

        // Timer interrupt test mode: set mtimecmp low to trigger interrupt quickly
        if ($test$plusargs("timer_test")) begin
            $display("TIMER TEST MODE: Setting mtimecmp=100, enabling interrupts");
            clint_inst.mtimecmp = 64'd100;  // Will trigger when mtime reaches 100
            // Force mtvec to a known value (we'll check if PC jumps there)
            // Note: This tests the interrupt mechanism, not a real handler
        end

        // Display first few instructions
        $display("First instructions:");
        for (i = 0; i < 4; i = i + 1) begin
            $display("  [0x%08x]: 0x%08x", MEMORY_BASE + i*4, cpu.umem[i]);
        end

        // Release reset
        repeat(5) @(posedge clk);
        reset = 0;
        $display("Reset released, starting execution...");
        $display("==============================================");
    end

    // =========================================================================
    // Simulation Monitor
    // =========================================================================
    integer cycle_count = 0;
    integer max_cycles = 1_500_000_000;  // 1.5B cycles max
    logic wfi_seen = 0;
    logic [63:0] prev_stimecmp = 64'hFFFFFFFF_FFFFFFFF;  // Track stimecmp changes
    logic prev_timer_irq = 1'b0;  // Track timer_irq_pending transitions
    logic [31:0] prev_mcause = 0;  // Track mcause changes for interrupt detection
    logic [1:0] prev_priv = 2'b11;  // Track privilege mode transitions
    logic [31:0] prev_scause = 0;  // Track S-mode traps
    logic [31:0] prev_ra = 0;     // Track ra (x1) for corruption detection
    logic [31:0] prev_stack_val = 0; // Track stack memory at crash address
    // Circular trace buffer
    logic [31:0] trace_buf_pc[32];
    logic [31:0] trace_buf_instr[32];
    logic [31:0] trace_buf_ra[32];
    logic [31:0] trace_buf_sp[32];
    logic [31:0] trace_buf_cycle[32];
    int trace_idx = 0;
    logic trace_dumped = 0;
    logic [31:0] prev_pc = 0;  // Track PC for jump-to-zero detection
    logic [31:0] prev_sp = 0;  // Track sp for crash debug

    always @(posedge clk) begin
        if (!reset) begin
            cycle_count = cycle_count + 1;

            // Detect privilege mode transitions
            if (cpu.priv_mode_rd != prev_priv) begin
                if (cpu.priv_mode_rd == 2'b11 && prev_priv != 2'b11) begin
                    // Entered M-mode: show trap cause
                    $display("[%0d] TRAP->M: mcause=0x%08x mepc=0x%08x mtvec=0x%08x from_priv=%0d PC=0x%08x",
                             cycle_count, cpu.mcause_rd, cpu.mepc, cpu.mtvec_rd,
                             prev_priv, cpu.pc_rd);
                end else if (prev_priv == 2'b11 && cpu.priv_mode_rd != 2'b11) begin
                    // Left M-mode (MRET)
                    $display("[%0d] MRET->%0d: PC=0x%08x mstatus=0x%08x",
                             cycle_count, cpu.priv_mode_rd, cpu.pc_rd, cpu.mstatus_rd);
                end
                prev_priv = cpu.priv_mode_rd;
            end

            // Detect S-mode traps - when PC matches stvec (catches all traps, even same cause)
            if (cpu.pc_rd == {cpu.stvec_rd[31:2], 2'b00} && prev_pc != {cpu.stvec_rd[31:2], 2'b00} && cpu.priv_mode_rd == 2'b01) begin
                $display("[%0d] S-TRAP: scause=0x%08x sepc=0x%08x stval=0x%08x PC=0x%08x stvec=0x%08x",
                         cycle_count, cpu.scause_rd, cpu.sepc_rd, cpu.stval_rd, cpu.pc_rd, cpu.stvec_rd);
            end

            // Detect when ra (x1) becomes 0 in S-mode - track corruption
            if (cpu.rf[1] == 0 && prev_ra != 0 && cpu.priv_mode_rd == 2'b01) begin
                $display("[%0d] *** RA ZEROED: PC=0x%08x prev_PC=0x%08x sp=0x%08x s0=0x%08x scause=0x%08x sepc=0x%08x",
                         cycle_count, cpu.pc_rd, prev_pc, cpu.rf[2], cpu.rf[8], cpu.scause_rd, cpu.sepc_rd);
                // Print more registers for context
                $display("[%0d]   a0=0x%08x a1=0x%08x a2=0x%08x a3=0x%08x a4=0x%08x a5=0x%08x",
                         cycle_count, cpu.rf[10], cpu.rf[11], cpu.rf[12], cpu.rf[13], cpu.rf[14], cpu.rf[15]);
                $display("[%0d]   s1=0x%08x s2=0x%08x s3=0x%08x rd_instr=0x%08x",
                         cycle_count, cpu.rf[9], cpu.rf[18], cpu.rf[19], cpu.umem_pc_vm_result_rd);
            end
            prev_ra = cpu.rf[1];

            // Detect jump to address 0 (NULL function pointer)
            if (cpu.pc_rd == 0 && prev_pc != 0) begin
                $display("[%0d] *** JUMP TO ZERO: from PC=0x%08x priv=%0d ra=0x%08x sp=0x%08x",
                         cycle_count, prev_pc, cpu.priv_mode_rd, cpu.rf[1], cpu.rf[2]);
            end
            prev_pc <= cpu.pc_rd;

            // Print PC periodically
            if (cycle_count <= 100 || cycle_count % 1000000 == 0) begin
                $display("[%0d] PC=0x%08x priv=%0d mstatus=0x%08x mcause=0x%08x timer_irq=%0b",
                         cycle_count, cpu.pc_rd, cpu.priv_mode_rd, cpu.mstatus_rd,
                         cpu.mcause_rd, timer_irq_pending);
            end

            // Detect PC leaving the 0x80XXXXXX range
            if (cpu.pc_rd < 32'h80000000 && cpu.pc_rd != 0) begin
                $display("[%0d] *** BAD PC: 0x%08x priv=%0d mstatus=0x%08x mepc=0x%08x mtvec=0x%08x mcause=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.priv_mode_rd, cpu.mstatus_rd,
                         cpu.mepc, cpu.mtvec_rd, cpu.mcause_rd);
            end

            // Detect WFI (OpenSBI idle) - just log, don't terminate
            // Timer interrupts will wake the CPU from WFI
            if (cpu.umem_pc_vm_result_rd == 32'h10500073 && !wfi_seen) begin  // WFI instruction encoding
                $display("[%0d] WFI instruction executed at PC=0x%08x (continuing simulation)", cycle_count, cpu.pc_rd);
                wfi_seen = 1;
            end

            // Detect stimecmp CSR writes (sstc extension)
            if ({cpu.stimecmph_rd, cpu.stimecmp_rd} != prev_stimecmp) begin
                $display("[%0d] STIMECMP: 0x%08x%08x mtime=0x%08x%08x PC=0x%08x",
                         cycle_count, cpu.stimecmph_rd, cpu.stimecmp_rd, mtime_hi, mtime_lo, cpu.pc_rd);
                prev_stimecmp = {cpu.stimecmph_rd, cpu.stimecmp_rd};
            end

            // Debug: detect timer_irq_pending transitions
            if (timer_irq_pending && !prev_timer_irq) begin
                $display("[%0d] MTIP ASSERTED: mtime=0x%08x%08x mtimecmp=0x%08x%08x timer_irq=%b",
                         cycle_count, mtime_hi, mtime_lo,
                         clint_inst.mtimecmp[63:32], clint_inst.mtimecmp[31:0],
                         timer_irq_pending);
            end
            prev_timer_irq <= timer_irq_pending;

            // Timeout
            if (cycle_count >= max_cycles) begin
                $display("==============================================");
                $display("TIMEOUT after %0d cycles", cycle_count);
                $display("Final PC: 0x%08x", cpu.pc_rd);
                $display("==============================================");
                $finish;
            end
        end
    end

endmodule
