// OpenSBI Boot Testbench for RISC-V 64 MMU
// Loads OpenSBI firmware and boots in Verilator simulation
//
// Memory Map:
//   0x80000000 - 0x87EFFFFF: Main RAM (127MB)
//   0x87F00000 - 0x87FFFFFF: Reserved for peripherals (1MB)
//     0x87F00000 - 0x87F000FF: UART (NS16550A compatible)
//     0x87F10000 - 0x87F1FFFF: CLINT (timer)

`timescale 1ns/1ps

module opensbi_boot_tb;
    // Clock generation
    reg clk = 0;
    always #10 clk = ~clk;  // 50MHz

    // Reset
    reg reset;
    integer reset_counter;

    // Memory layout
    localparam [63:0] MEMORY_BASE = 64'h80000000;  // OpenSBI expects RAM at 0x80000000
    localparam [63:0] MEMORY_SIZE = 64'h07f00000;  // 127MB (last 1MB reserved for peripherals)
    localparam [63:0] CLINT_BASE  = 64'h87f10000;  // In reserved peripheral region
    localparam [63:0] UART_BASE   = 64'h87f00000;  // In reserved peripheral region

    // FDT location - must match OpenSBI's FW_FDT_PATH configuration
    localparam [63:0] FDT_ADDR    = 64'h82200000;  // 34MB offset, matches OpenSBI config

    // Entry point for OpenSBI (passed via plusarg)
    reg [63:0] entry_point;
    reg [63:0] fdt_addr;

    // =========================================================================
    // CLINT (Timer) Instance
    // =========================================================================
    logic [63:0] clint_addr;
    logic [31:0] clint_wdata;
    logic        clint_we;
    logic        clint_re;
    logic [31:0] clint_rdata;
    logic        clint_ack;
    logic [63:0] mtime_val;
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
        .mtime_out(mtime_val),
        .timer_irq_pending(timer_irq_pending),
        .sw_irq_pending(sw_irq_pending)
    );

    // =========================================================================
    // UART Instance
    // =========================================================================
    logic [63:0] uart_addr;
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
    riscv64_mmu cpu (
        .clk(clk),
        .reset(reset),

        // Reset values
        .reset_pc(entry_point),
        .reset_priv_mode(2'b11),              // M-mode
        .reset_satp_rd(64'h0),                // VM disabled initially
        .reset_mtvec_rd(64'h0),
        .reset_mepc(64'h0),
        .reset_mcause_rd(64'h0),
        .reset_mtval_rd(64'h0),
        .reset_sepc(64'h0),
        .reset_mscratch_rd(64'h0),
        .reset_sscratch_rd(64'h0),
        .reset_sstatus_rd(64'h0),             // S-mode status register
        .reset_medeleg_rd(64'h0),
        .reset_stvec_rd(64'h0),
        .reset_scause_rd(64'h0),
        .reset_stval_rd(64'h0),
        .reset_mie_rd(64'h0),
        .reset_mstatus_rd(64'h0),
        .reset_stimecmp_rd(64'hFFFFFFFF_FFFFFFFF),  // Max value to prevent immediate interrupt
        .reset_lr_reservation_rd(64'h0),    // No LR reservation initially

        // Timer inputs from CLINT (single 64-bit mtime)
        .mtime_rd(mtime_val),
        .mtime_wr(mtime_val),
        .timer_irq_pending_rd(timer_irq_pending),
        .timer_irq_pending_wr(timer_irq_pending)
    );

    // =========================================================================
    // Peripheral Bus Controller
    // Intercepts CPU memory accesses to peripheral ranges
    // =========================================================================

    // Detect store instructions (unified write enable)
    wire store_enable = cpu.umem_write_enable;
    wire load_enable = cpu.ld_enable || cpu.lw_enable || cpu.lwu_enable ||
                       cpu.lh_enable || cpu.lhu_enable ||
                       cpu.lb_enable || cpu.lbu_enable;

    // Get load address for debugging (use umem read address)
    wire [63:0] load_addr = cpu.umem_addr_pa_rd;
    wire is_clint_load = (load_addr >= CLINT_BASE) && (load_addr < (CLINT_BASE + 64'h10000));

    // Get the physical address being accessed (use unified write address)
    wire [63:0] store_addr = cpu.umem_write_addr_mux;
    wire [63:0] store_data = cpu.umem_write_data_mux;

    // Check if access is to peripheral range
    wire is_clint_access = (store_addr >= CLINT_BASE) && (store_addr < (CLINT_BASE + 64'h10000));
    wire is_uart_access = (store_addr >= UART_BASE) && (store_addr < (UART_BASE + 64'h100));

    // MMIO mapping constants for mirroring peripheral values to umem
    // Each umem entry is 8 bytes (64-bit), so byte address >> 3 = umem index
    // CLINT at 0x87F10000: (0x87F10000 - 0x80000000) >> 3 = 0x00FE2000
    localparam [31:0] CLINT_UMEM_BASE = 32'h00FE2000;
    // UART at 0x87F00000: (0x87F00000 - 0x80000000) >> 3 = 0x00FE0000
    localparam [31:0] UART_UMEM_BASE = 32'h00FE0000;

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
                    clint_wdata <= store_data[31:0];  // CLINT uses 32-bit MMIO
                    clint_we <= 1'b1;
                    $display("[%0d] CLINT WRITE: addr=0x%016x data=0x%08x offset=0x%04x",
                             cycle_count, store_addr, store_data[31:0], store_addr[15:0]);
                end else if (is_uart_access) begin
                    uart_addr <= store_addr;
                    uart_wdata <= store_data[31:0];  // UART uses 32-bit MMIO
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
            // 64-bit umem entries: full 64-bit values fit in single entries
            // CLINT register offsets (from BASE_ADDR):
            //   0x0000: MSIP
            //   0x4000: MTIMECMP (64-bit, one umem entry)
            //   0xBFF8: MTIME (64-bit, one umem entry)
            // =========================================================================
            if (cycle_count == 1) begin
                $display("CLINT_UMEM_BASE = 0x%08x (maps to 0x%016x)", CLINT_UMEM_BASE, CLINT_BASE);
                $display("UART_UMEM_BASE = 0x%08x (maps to 0x%016x)", UART_UMEM_BASE, UART_BASE);
                $display("MTIME umem offset = 0x%08x", CLINT_UMEM_BASE + (32'hBFF8 >> 3));
            end
            // MSIP at offset 0x0000 (lower 32 bits of 64-bit umem entry)
            cpu.umem[CLINT_UMEM_BASE + 0] <= {32'b0, 31'b0, clint_inst.msip};
            // MTIMECMP at offset 0x4000 (full 64-bit fits in one entry)
            cpu.umem[CLINT_UMEM_BASE + (32'h4000 >> 3)] <= clint_inst.mtimecmp;
            // MTIME at offset 0xBFF8 (full 64-bit fits in one entry)
            cpu.umem[CLINT_UMEM_BASE + (32'hBFF8 >> 3)] <= clint_inst.mtime;

            // =========================================================================
            // Mirror UART registers to umem for CPU reads
            // All 8 UART byte registers (0-7) map to a single 64-bit umem entry
            // Byte layout in 64-bit word: {SCR, MSR, LSR, MCR, LCR, IIR, IER, RBR}
            // Key registers: LSR (byte 5 = bits [47:40]), IIR (byte 2 = bits [23:16])
            // =========================================================================
            cpu.umem[UART_UMEM_BASE] <= {8'h0, 8'h0, uart_inst.lsr, 8'h0,
                                          8'h0, uart_inst.iir, 8'h0, 8'h0};

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
            fdt_file = "riscv64_mmu.dtb";
        end

        // Get entry point
        if (!$value$plusargs("entry=0x%h", entry_point)) begin
            entry_point = MEMORY_BASE;  // 0x80000000
        end

        // Get FDT address
        if (!$value$plusargs("fdt=0x%h", fdt_addr)) begin
            fdt_addr = FDT_ADDR;
        end

        // Get max cycles (runtime override)
        if ($value$plusargs("max_cycles=%d", max_cycles)) begin
            $display("Max cycles overridden to: %0d", max_cycles);
        end

        $display("==============================================");
        $display("OpenSBI Boot Testbench (RV64IMA)");
        $display("==============================================");
        $display("Firmware: %s", firmware_file);
        $display("FDT file: %s", fdt_file);
        $display("Entry point: 0x%016x", entry_point);
        $display("FDT address: 0x%016x", fdt_addr);
        $display("Max cycles: %0d", max_cycles);
        $display("==============================================");

        // Open UART log file
        uart_log_handle = $fopen("uart_output.txt", "w");
        uart_initialized = 0;

        // Reset sequence
        reset = 1;
        reset_counter = 0;

        // Wait for clock to stabilize
        repeat(10) @(posedge clk);

        // Load firmware into memory (8 bytes per umem entry for 64-bit)
        $display("Loading firmware...");
        file_handle = $fopen(firmware_file, "rb");
        if (file_handle == 0) begin
            $display("ERROR: Cannot open firmware file: %s", firmware_file);
            $finish;
        end

        word_count = 0;
        while (!$feof(file_handle)) begin
            // Read 8 bytes (little-endian) per 64-bit umem entry
            for (j = 0; j < 8; j = j + 1) begin
                bytes_read = $fread(byte_data, file_handle);
                if (bytes_read == 1) begin
                    cpu.umem[word_count][j*8 +: 8] = byte_data;
                end
            end
            word_count = word_count + 1;
        end
        $fclose(file_handle);
        $display("Loaded %0d doublewords (%0d bytes)", word_count, word_count * 8);

        // Load FDT into memory at FDT_ADDR
        $display("Loading FDT...");
        file_handle = $fopen(fdt_file, "rb");
        if (file_handle == 0) begin
            $display("WARNING: Cannot open FDT file: %s (continuing without FDT)", fdt_file);
        end else begin
            // FDT doubleword offset = (FDT_ADDR - MEMORY_BASE) / 8
            fdt_word_offset = (fdt_addr - MEMORY_BASE) >> 3;
            word_count = 0;
            while (!$feof(file_handle)) begin
                for (j = 0; j < 8; j = j + 1) begin
                    bytes_read = $fread(byte_data, file_handle);
                    if (bytes_read == 1) begin
                        cpu.umem[fdt_word_offset + word_count][j*8 +: 8] = byte_data;
                    end
                end
                word_count = word_count + 1;
            end
            $fclose(file_handle);
            $display("Loaded FDT: %0d doublewords (%0d bytes) at 0x%016x", word_count, word_count * 8, fdt_addr);
            // Display FDT magic (should be 0xd00dfeed in big-endian)
            $display("FDT magic: 0x%08x", cpu.umem[fdt_word_offset][31:0]);
        end

        // Set a1 register to FDT address (OpenSBI expects FDT pointer in a1)
        cpu.rf[11] = fdt_addr;
        $display("Set a1 (x11) = 0x%016x (FDT address)", fdt_addr);

        // Timer interrupt test mode: set mtimecmp low to trigger interrupt quickly
        if ($test$plusargs("timer_test")) begin
            $display("TIMER TEST MODE: Setting mtimecmp=100, enabling interrupts");
            clint_inst.mtimecmp = 64'd100;
        end

        // Display first few instructions (lower 32 bits of each doubleword)
        $display("First instructions:");
        for (i = 0; i < 4; i = i + 1) begin
            $display("  [0x%016x]: 0x%08x", MEMORY_BASE + i*8, cpu.umem[i][31:0]);
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
    integer max_cycles = 2_000_000_000;  // 2B cycles max (configurable via +max_cycles=N)
    logic wfi_seen = 0;
    integer fdt_call_count = 0;
    logic [63:0] prev_stimecmp = 64'hFFFFFFFF_FFFFFFFF;  // Track stimecmp changes
    logic prev_timer_irq = 1'b0;  // Track timer_irq_pending transitions
    logic [63:0] prev_mcause = 0;  // Track mcause changes for interrupt detection
    logic [1:0] prev_priv = 2'b11;  // Track privilege mode transitions
    logic [63:0] prev_scause = 0;  // Track S-mode traps
    logic [63:0] prev_sepc = 0;    // Track sepc changes
    logic [63:0] prev_ra = 0;     // Track ra (x1) for corruption detection
    // Circular trace buffer
    logic [63:0] trace_buf_pc[32];
    logic [31:0] trace_buf_instr[32];
    logic [63:0] trace_buf_ra[32];
    logic [63:0] trace_buf_sp[32];
    logic [31:0] trace_buf_cycle[32];
    int trace_idx = 0;
    logic trace_dumped = 0;
    logic [63:0] prev_pc = 0;  // Track PC for jump-to-zero detection
    logic [63:0] prev_sp = 0;  // Track sp for crash debug
    logic [63:0] prev_satp = 0;  // Track satp changes for page table debug
    logic sd_trace_active = 0;  // Enable SD store tracing during kernel setup

    always @(posedge clk) begin
        if (!reset) begin
            cycle_count = cycle_count + 1;

            // Detect privilege mode transitions
            if (cpu.priv_mode_rd != prev_priv) begin
                if (cpu.priv_mode_rd == 2'b11 && prev_priv != 2'b11) begin
                    // Entered M-mode: show trap cause
                    $display("[%0d] TRAP->M: mcause=0x%016x mepc=0x%016x mtvec=0x%016x from_priv=%0d PC=0x%016x",
                             cycle_count, cpu.mcause_rd, cpu.mepc, cpu.mtvec_rd,
                             prev_priv, cpu.pc_rd);
                end else if (prev_priv == 2'b11 && cpu.priv_mode_rd != 2'b11) begin
                    // Left M-mode (MRET)
                    $display("[%0d] MRET->%0d: PC=0x%016x mstatus=0x%016x",
                             cycle_count, cpu.priv_mode_rd, cpu.pc_rd, cpu.mstatus_rd);
                end
                // Detect U-mode entry (SRET from S-mode to U-mode)
                if (cpu.priv_mode_rd == 2'b00 && prev_priv != 2'b00) begin
                    $display("[%0d] ENTER U-MODE: PC=0x%016x from_priv=%0d sepc=0x%016x satp=0x%016x",
                             cycle_count, cpu.pc_rd, prev_priv, cpu.sepc_rd, cpu.satp_rd);
                end else if (prev_priv == 2'b00 && cpu.priv_mode_rd != 2'b00) begin
                    $display("[%0d] LEAVE U-MODE: scause=0x%016x sepc=0x%016x stval=0x%016x PC=0x%016x",
                             cycle_count, cpu.scause_rd, cpu.sepc_rd, cpu.stval_rd, cpu.pc_rd);
                end
                prev_priv = cpu.priv_mode_rd;
            end

            // Detect S-mode traps - when PC matches stvec
            if (cpu.pc_rd == {cpu.stvec_rd[63:2], 2'b00} && prev_pc != {cpu.stvec_rd[63:2], 2'b00} && cpu.priv_mode_rd == 2'b01) begin
                $display("[%0d] S-TRAP: scause=0x%016x sepc=0x%016x stval=0x%016x PC=0x%016x stvec=0x%016x",
                         cycle_count, cpu.scause_rd, cpu.sepc_rd, cpu.stval_rd, cpu.pc_rd, cpu.stvec_rd);
            end

            // Detect when ra (x1) becomes 0 in S-mode - track corruption
            if (cpu.rf[1] == 0 && prev_ra != 0 && cpu.priv_mode_rd == 2'b01) begin
                $display("[%0d] *** RA ZEROED: PC=0x%016x prev_PC=0x%016x sp=0x%016x s0=0x%016x scause=0x%016x sepc=0x%016x",
                         cycle_count, cpu.pc_rd, prev_pc, cpu.rf[2], cpu.rf[8], cpu.scause_rd, cpu.sepc_rd);
                $display("[%0d]   a0=0x%016x a1=0x%016x a2=0x%016x a3=0x%016x a4=0x%016x a5=0x%016x",
                         cycle_count, cpu.rf[10], cpu.rf[11], cpu.rf[12], cpu.rf[13], cpu.rf[14], cpu.rf[15]);
                $display("[%0d]   s1=0x%016x s2=0x%016x s3=0x%016x rd_instr=0x%08x",
                         cycle_count, cpu.rf[9], cpu.rf[18], cpu.rf[19], cpu.instr);
            end
            prev_ra = cpu.rf[1];

            // Detect jump to address 0 (NULL function pointer)
            if (cpu.pc_rd == 0 && prev_pc != 0) begin
                $display("[%0d] *** JUMP TO ZERO: from PC=0x%016x priv=%0d ra=0x%016x sp=0x%016x",
                         cycle_count, prev_pc, cpu.priv_mode_rd, cpu.rf[1], cpu.rf[2]);
            end
            prev_pc <= cpu.pc_rd;

            // Print PC periodically
            if (cycle_count <= 100 || cycle_count % 1_000_000 == 0) begin
                $display("[%0d] PC=0x%016x priv=%0d mstatus=0x%016x mcause=0x%016x timer_irq=%0b",
                         cycle_count, cpu.pc_rd, cpu.priv_mode_rd, cpu.mstatus_rd,
                         cpu.mcause_rd, timer_irq_pending);
            end

            // Debug: Per-instruction trace for kernel boot region 0xffffffff80000150-0xffffffff80000190
            if (cpu.pc_rd >= 64'hffffffff80000150 && cpu.pc_rd <= 64'hffffffff80000190) begin
                $display("[%0d] BOOT: PC=0x%016x instr=0x%08x ra=0x%016x t1=0x%016x sp=0x%016x tp=0x%016x",
                         cycle_count, cpu.pc_rd, cpu.instr, cpu.rf[1], cpu.rf[6], cpu.rf[2], cpu.rf[4]);
            end

            // Debug: Detect NEW instruction page faults (scause=12, sepc changed)
            if (cpu.scause_rd == 64'd12 && (prev_scause != 64'd12 || cpu.sepc_rd != prev_sepc)) begin
                $display("[%0d] *** INSTR PAGE FAULT: sepc=0x%016x stval=0x%016x stvec=0x%016x PC=0x%016x satp=0x%016x",
                         cycle_count, cpu.sepc_rd, cpu.stval_rd, cpu.stvec_rd, cpu.pc_rd, cpu.satp_rd);
            end
            prev_scause <= cpu.scause_rd;
            prev_sepc <= cpu.sepc_rd;

            // Debug: Detect when first virtual address is used (PC > 0xffffffff00000000)
            if (cpu.pc_rd > 64'hffffffff00000000 && prev_pc < 64'hffffffff00000000 && prev_pc != 0) begin
                $display("[%0d] *** VIRTUAL ADDR: PC=0x%016x prev_PC=0x%016x satp=0x%016x",
                         cycle_count, cpu.pc_rd, prev_pc, cpu.satp_rd);
            end

            // Detect PC leaving the 0x80XXXXXX range (up to 0x87FFFFFF for 128MB)
            if (cpu.pc_rd < 64'h80000000 && cpu.pc_rd != 0) begin
                $display("[%0d] *** BAD PC: 0x%016x priv=%0d mstatus=0x%016x mepc=0x%016x mtvec=0x%016x mcause=0x%016x",
                         cycle_count, cpu.pc_rd, cpu.priv_mode_rd, cpu.mstatus_rd,
                         cpu.mepc, cpu.mtvec_rd, cpu.mcause_rd);
            end

            // Detect WFI (OpenSBI idle) - just log, don't terminate
            if (cpu.instr == 32'h10500073 && !wfi_seen) begin  // WFI instruction encoding
                $display("[%0d] WFI instruction executed at PC=0x%016x (continuing simulation)", cycle_count, cpu.pc_rd);
                wfi_seen = 1;
            end

            // Detect stimecmp CSR writes (sstc extension)
            if (cpu.stimecmp_rd != prev_stimecmp) begin
                $display("[%0d] STIMECMP: 0x%016x mtime=0x%016x PC=0x%016x",
                         cycle_count, cpu.stimecmp_rd, mtime_val, cpu.pc_rd);
                prev_stimecmp = cpu.stimecmp_rd;
            end

            // Debug: detect timer_irq_pending transitions
            if (timer_irq_pending && !prev_timer_irq) begin
                $display("[%0d] MTIP ASSERTED: mtime=0x%016x mtimecmp=0x%016x timer_irq=%b",
                         cycle_count, mtime_val,
                         clint_inst.mtimecmp,
                         timer_irq_pending);
            end
            prev_timer_irq <= timer_irq_pending;

            // Debug: Track satp changes and dump page table entries
            if (cpu.satp_rd != prev_satp) begin
                $display("[%0d] SATP CHANGED: 0x%016x -> 0x%016x PC=0x%016x priv=%0d",
                         cycle_count, prev_satp, cpu.satp_rd, cpu.pc_rd, cpu.priv_mode_rd);
                if (cpu.satp_rd[63:60] == 4'd8) begin  // Sv39 mode
                    // Dump root page table entries at VPN[2]=2 (identity mapping for 0x80000000)
                    // and VPN[2]=510/0x1FE (high mapping for 0xFFFFFFFF80000000)
                    // Root PPN -> physical address, then umem index = (phys - 0x80000000) >> 3
                    $display("[%0d]   Sv39 PPN=0x%011x root_phys=0x%016x",
                             cycle_count, cpu.satp_rd[43:0],
                             {20'b0, cpu.satp_rd[43:0], 12'b0});
                    // VPN[2]=2: umem[(root_phys + 16 - 0x80000000) >> 3]
                    $display("[%0d]   PTE[VPN2=0] = 0x%016x", cycle_count,
                             cpu.umem[((cpu.satp_rd[43:0] << 12) - 64'h80000000) >> 3]);
                    $display("[%0d]   PTE[VPN2=1] = 0x%016x", cycle_count,
                             cpu.umem[(((cpu.satp_rd[43:0] << 12) + 64'd8) - 64'h80000000) >> 3]);
                    $display("[%0d]   PTE[VPN2=2] = 0x%016x", cycle_count,
                             cpu.umem[(((cpu.satp_rd[43:0] << 12) + 64'd16) - 64'h80000000) >> 3]);
                    $display("[%0d]   PTE[VPN2=3] = 0x%016x", cycle_count,
                             cpu.umem[(((cpu.satp_rd[43:0] << 12) + 64'd24) - 64'h80000000) >> 3]);
                    // VPN[2]=510 (0x1FE): kernel mapping
                    $display("[%0d]   PTE[VPN2=510] = 0x%016x", cycle_count,
                             cpu.umem[(((cpu.satp_rd[43:0] << 12) + 64'd4080) - 64'h80000000) >> 3]);
                    $display("[%0d]   PTE[VPN2=511] = 0x%016x", cycle_count,
                             cpu.umem[(((cpu.satp_rd[43:0] << 12) + 64'd4088) - 64'h80000000) >> 3]);
                end
                prev_satp = cpu.satp_rd;
            end

            // Log SD stores in S-mode that write near page table root area
            if (cpu.sd_enable && store_enable && cpu.priv_mode_rd == 2'b01) begin
                // Log stores to page table areas (near satp PPN * 4096)
                if (store_addr >= 64'h80e00000 && store_addr < 64'h80f00000) begin
                    $display("[%0d] SD-PT: PC=0x%016x addr=0x%016x data=0x%016x vm=%0b satp=0x%016x",
                             cycle_count, cpu.pc_rd, store_addr, store_data,
                             cpu.addr_vm_enabled, cpu.satp_rd);
                end
            end

            // Timeout
            if (cycle_count >= max_cycles) begin
                $display("==============================================");
                $display("TIMEOUT after %0d cycles", cycle_count);
                $display("Final PC: 0x%016x", cpu.pc_rd);
                $display("==============================================");
                $finish;
            end
        end
    end

endmodule
