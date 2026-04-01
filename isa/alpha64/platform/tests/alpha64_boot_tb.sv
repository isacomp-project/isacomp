// Alpha64 Linux Boot Testbench
// =============================
// Loads and boots Alpha64 Linux kernel in Verilator simulation.
//
// Memory Map:
//   0x00000000 - 0x1FFFFFFF: Main RAM (512MB)
//   0x80000000: Interrupt Controller
//   0x80010000: Interval Timer
//   0x80020000: UART (16550-compatible)
//
// Boot flow:
//   1. PALcode at 0x0 initializes IPRs, jumps to boot ROM at 0x8000
//   2. Boot ROM builds HWRPB at 0x10000000, sets command line
//   3. Boot ROM sets a0=HWRPB addr, hw_rei to kernel at 0x01000000
//   4. Kernel boots using PALcode for TLB, interrupts, syscalls

`timescale 1ns/1ps

module alpha64_boot_tb(
    input logic clk,
    input logic rst_n
);

    // =========================================================================
    // Clock and Reset (driven from C++ sim_main.cpp)
    // =========================================================================
    parameter CLK_PERIOD = 20;  // 50 MHz

    // =========================================================================
    // Memory
    // =========================================================================
    // 288MB = 36M quadwords (covers HWRPB at 0x10000000 + padding)
    parameter MEM_SIZE_BYTES = 288 * 1024 * 1024;
    parameter MEM_SIZE_QWORDS = MEM_SIZE_BYTES / 8;
    logic [63:0] memory [0:MEM_SIZE_QWORDS-1];

    // =========================================================================
    // External ISR and PCC signals (connected as module ports via ext isa_state)
    // =========================================================================
    logic [63:0] ext_isr;
    logic [63:0] ext_pcc;

    // =========================================================================
    // CPU External Memory Port Wires (unified memory - umem)
    // =========================================================================

    // Instruction fetch port via physical address (TLB-translated path)
    wire [31:0] umem_pc_pa_read_req_addr;
    wire        umem_pc_pa_read_req_valid;
    logic [63:0] umem_pc_pa_read_resp_data;
    logic        umem_pc_pa_read_resp_ready;


    // Data read port via physical address (TLB-translated path)
    wire [31:0] umem_addr_pa_read_req_addr;
    wire        umem_addr_pa_read_req_valid;
    logic [63:0] umem_addr_pa_read_resp_data;
    logic        umem_addr_pa_read_resp_ready;

    // Data read port via direct address (hw_ld path)
    wire [31:0] umem_addr_read_req_addr;
    wire        umem_addr_read_req_valid;
    logic [63:0] umem_addr_read_resp_data;
    logic        umem_addr_read_resp_ready;

    // Data write port
    wire [31:0] umem_write_req_addr;
    wire [63:0] umem_write_req_data;
    wire [7:0]  umem_write_req_we;
    wire        umem_write_req_valid;
    logic       umem_write_resp_ready;

    // =========================================================================
    // CPU Instance
    // =========================================================================
    alpha64_linux cpu (
        .clk(clk),
        .reset(~rst_n),

        // Reset state - start in PAL mode at address 0
        .reset_pc(64'h0),
        .reset_pal_mode_rd(1'b1),
        .reset_pal_base_rd(64'h0),

        // Reset other IPRs to sensible defaults
        .reset_amask_val_rd(64'h0307),  // BWX + FIX + CIX + MVI
        .reset_aster_rd(64'h0),
        .reset_astrr_rd(64'h0),
        .reset_dtb_asn_rd(64'h0),
        .reset_dtb_cm_rd(64'h0),
        .reset_dtb_idx_rd(3'h0),
        .reset_exc_addr_rd(64'h0),
        .reset_exc_mask_rd(64'h0),
        .reset_exc_sum_rd(64'h0),
        .reset_fen_rd(1'b1),            // FP enabled
        .reset_fpcr(64'h0),
        .reset_hier_rd(64'hFFFFFFFFFFFFFFFF),  // All interrupts enabled
        .reset_implver_rd(64'h2),        // EV6-class
        .reset_ipl_rd(6'h1F),           // Highest priority at boot
        .reset_itb_asn_rd(64'h0),
        .reset_itb_idx_rd(3'h0),
        .reset_mces_rd(64'h0),
        .reset_mm_stat_rd(64'h0),
        .reset_pcbb_rd(64'h0),
        .reset_ps_rd(64'h0),            // Kernel mode
        .reset_pt0_rd(64'h0),
        .reset_pt1_rd(64'h0),
        .reset_pt2_rd(64'h0),
        .reset_pt3_rd(64'h0),
        .reset_pt4_rd(64'h0),
        .reset_pt5_rd(64'h0),
        .reset_pt6_rd(64'h0),
        .reset_pt7_rd(64'h0),
        .reset_pt8_rd(64'h0),
        .reset_pt9_rd(64'h0),
        .reset_pt10_rd(64'h0),
        .reset_pt11_rd(64'h0),
        .reset_pt12_rd(64'h0),
        .reset_pt13_rd(64'h0),
        .reset_pt14_rd(64'h0),
        .reset_pt15_rd(64'h0),
        .reset_pt16_rd(64'h0),
        .reset_pt17_rd(64'h0),
        .reset_pt18_rd(64'h0),
        .reset_pt19_rd(64'h0),
        .reset_pt20_rd(64'h0),
        .reset_pt21_rd(64'h0),
        .reset_pt22_rd(64'h0),
        .reset_pt23_rd(64'h0),
        .reset_ptbr_rd(64'h0),
        .reset_sirr_rd(64'h0),
        .reset_sysval_rd(64'h0),
        .reset_unique_rd(64'h0),
        .reset_va_form_rd(64'h0),
        .reset_va_rd(64'h0),
        .reset_vptptr_rd(64'h0),
        .reset_whami_rd(64'h0),
        .reset_lock_flag_rd(1'b0),

        // External inputs (from ext isa_state)
        .isr_rd(ext_isr),
        .isr_wr(ext_isr),
        .pcc_rd(ext_pcc),
        .pcc_wr(ext_pcc),

        // Instruction fetch via physical address (TLB-translated)
        .umem_pc_pa_read_req_addr(umem_pc_pa_read_req_addr),
        .umem_pc_pa_read_req_valid(umem_pc_pa_read_req_valid),
        .umem_pc_pa_read_resp_data(umem_pc_pa_read_resp_data),
        .umem_pc_pa_read_resp_ready(umem_pc_pa_read_resp_ready),


        // Data read via physical address (TLB-translated)
        .umem_addr_pa_read_req_addr(umem_addr_pa_read_req_addr),
        .umem_addr_pa_read_req_valid(umem_addr_pa_read_req_valid),
        .umem_addr_pa_read_resp_data(umem_addr_pa_read_resp_data),
        .umem_addr_pa_read_resp_ready(umem_addr_pa_read_resp_ready),

        // Data read via direct address (hw_ld)
        .umem_addr_read_req_addr(umem_addr_read_req_addr),
        .umem_addr_read_req_valid(umem_addr_read_req_valid),
        .umem_addr_read_resp_data(umem_addr_read_resp_data),
        .umem_addr_read_resp_ready(umem_addr_read_resp_ready),

        // Data write port
        .umem_write_req_addr(umem_write_req_addr),
        .umem_write_req_data(umem_write_req_data),
        .umem_write_req_we(umem_write_req_we),
        .umem_write_req_valid(umem_write_req_valid),
        .umem_write_resp_ready(umem_write_resp_ready)
    );

    // =========================================================================
    // Memory Read Logic - Instruction Fetch (Combinational)
    // =========================================================================
    // Both instruction fetch ports return full 64-bit quadwords.
    // The CPU internally selects the 32-bit instruction based on addr[2].
    //
    // CRITICAL: To avoid a combinational loop (decode → enables → address mux
    // → memory → decode), the instruction fetch port uses pc_pa (which equals
    // pc_rd when in PAL mode, registered inside the CPU).

    // Instruction read address - always the current PC physical address
    wire [25:0] ifetch_qw_idx = umem_pc_pa_read_req_addr[28:3];

    // Pre-select the 32-bit instruction word based on PC[2], then duplicate it
    // in both halves of the 64-bit response. This is necessary because the
    // generated CPU's opcode decode comparisons reference umem_pc_rd[31:26]
    // (the raw memory output) rather than the byte-muxed instruction word.
    // By duplicating the correct word, both raw and byte-muxed paths see the
    // correct opcode bits regardless of alignment.
    wire [31:0] ifetch_word = umem_pc_pa_read_req_addr[2] ?
        memory[ifetch_qw_idx][63:32] : memory[ifetch_qw_idx][31:0];

    // Port 1: TLB-translated path
    assign umem_pc_pa_read_resp_data = {ifetch_word, ifetch_word};
    assign umem_pc_pa_read_resp_ready = 1'b1;  // Always ready (combinational)

    // =========================================================================
    // Memory Read Logic - Data Access (Combinational)
    // =========================================================================
    // Both data read ports access physical memory or peripherals.
    // Address routing: PA < 0x20000000 -> memory, PA >= 0x80000000 -> peripherals

    // Port 1: TLB-translated physical address
    wire data_pa_is_periph = (umem_addr_pa_read_req_addr >= 32'h80000000);
    wire [25:0] data_pa_qw_idx = umem_addr_pa_read_req_addr[28:3];
    assign umem_addr_pa_read_resp_data = data_pa_is_periph ?
        periph_rdata : memory[data_pa_qw_idx];

    // Port 2: Direct/hw_ld address
    wire data_dir_is_periph = (umem_addr_read_req_addr >= 32'h80000000);
    wire [25:0] data_dir_qw_idx = umem_addr_read_req_addr[28:3];
    assign umem_addr_read_resp_data = data_dir_is_periph ?
        periph_rdata : memory[data_dir_qw_idx];

    // Peripheral reads have 1-cycle latency (registered bus_ack/bus_rdata in peripherals).
    // Stall the CPU for peripheral reads until the peripheral acknowledges.
    // For unmapped peripheral addresses, a default ack fires after 1 cycle to prevent deadlock.
    reg periph_unmapped_ack;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) periph_unmapped_ack <= 0;
        else        periph_unmapped_ack <= periph_re && !periph_ack && !periph_unmapped_ack;
    end
    wire periph_ack_final = periph_ack | periph_unmapped_ack;
    assign umem_addr_pa_read_resp_ready = data_pa_is_periph ?
        periph_ack_final : umem_addr_pa_read_req_valid;
    assign umem_addr_read_resp_ready = data_dir_is_periph ?
        periph_ack_final : umem_addr_read_req_valid;

    // =========================================================================
    // Memory Write Logic - Data Store
    // =========================================================================
    wire data_wr_is_periph = (umem_write_req_addr >= 32'h80000000);
    wire [25:0] data_wr_qw_idx = umem_write_req_addr[28:3];

    // Combinational acknowledge - CPU doesn't stall on writes
    assign umem_write_resp_ready = umem_write_req_valid;

    // Registered write to memory
    // Note: the CPU's instruction fetch stall (umem_pc_addr_changed) causes
    // every instruction to take 2 cycles. Store instructions assert
    // write_req_valid on both cycles with the same address/data, making the
    // second write idempotent for RAM. Peripherals handle this via edge
    // detection (UART) or idempotent register writes (intc, timer).
    // PALcode write protection: block non-PAL-mode writes to PA 0x0000-0x7FFF.
    // The kernel's buddy allocator erroneously hands out pages in this region,
    // and memset zeroing destroys the live PALcode. PAL-mode writes (hw_st)
    // are allowed since PALcode may legitimately update its own scratch area.
    wire pal_region_write = (umem_write_req_addr < 32'h8000) && !cpu_pal_mode;

    always @(posedge clk) begin
        if (umem_write_req_valid && !data_wr_is_periph) begin
            // WATCHPOINT: Detect writes to PALcode region (PA 0x0000-0x7FFF)
            if (umem_write_req_addr < 32'h8000 && !cpu_pal_mode) begin
                $display("[cycle %0d] *** PALCODE WRITE BLOCKED: PA=0x%08x data=0x%016x we=0x%02x pc=0x%016x",
                    cycle, umem_write_req_addr, umem_write_req_data, umem_write_req_we,
                    cpu_pc);
            end
            // Byte-enable write to physical memory (skip PALcode region for non-PAL writes).
            if (!pal_region_write) begin
                if (umem_write_req_we[0]) memory[data_wr_qw_idx][7:0]   <= umem_write_req_data[7:0];
                if (umem_write_req_we[1]) memory[data_wr_qw_idx][15:8]  <= umem_write_req_data[15:8];
                if (umem_write_req_we[2]) memory[data_wr_qw_idx][23:16] <= umem_write_req_data[23:16];
                if (umem_write_req_we[3]) memory[data_wr_qw_idx][31:24] <= umem_write_req_data[31:24];
                if (umem_write_req_we[4]) memory[data_wr_qw_idx][39:32] <= umem_write_req_data[39:32];
                if (umem_write_req_we[5]) memory[data_wr_qw_idx][47:40] <= umem_write_req_data[47:40];
                if (umem_write_req_we[6]) memory[data_wr_qw_idx][55:48] <= umem_write_req_data[55:48];
                if (umem_write_req_we[7]) memory[data_wr_qw_idx][63:56] <= umem_write_req_data[63:56];
            end
        end
    end

    // =========================================================================
    // Peripheral Bus
    // =========================================================================
    // Route data accesses >= 0x80000000 to peripheral bus.
    // Only one data port will be active per cycle (PA or direct), so we OR.
    logic [63:0] periph_addr;
    logic [63:0] periph_wdata;
    logic [63:0] periph_rdata;
    logic        periph_we;
    logic        periph_re;
    logic        periph_valid;
    logic        periph_ack;

    // Combine read/write requests to peripheral bus
    wire periph_rd_pa  = umem_addr_pa_read_req_valid && data_pa_is_periph;
    wire periph_rd_dir = umem_addr_read_req_valid && data_dir_is_periph;
    wire periph_wr     = umem_write_req_valid && data_wr_is_periph;

    assign periph_addr  = periph_wr     ? {32'h0, umem_write_req_addr} :
                          periph_rd_pa  ? {32'h0, umem_addr_pa_read_req_addr} :
                          periph_rd_dir ? {32'h0, umem_addr_read_req_addr} : 64'h0;
    assign periph_wdata = umem_write_req_data;
    assign periph_we    = periph_wr;
    assign periph_re    = periph_rd_pa || periph_rd_dir;
    assign periph_valid = periph_we || periph_re;

    // COM1 I/O port address remapping
    // The 8250 serial driver accesses standard ISA COM1 ports 0x3F8-0x3FF.
    // ioportmap() maps these to PA 0x800003F8-0x800003FF (KSEG + IO_BASE + port).
    // Our UART is at PA 0x80020000 with 8-byte register spacing.
    // Remap: PA 0x800003F8 + n -> PA 0x80020000 + (n << 3)
    wire com1_port_remap = (periph_addr[31:3] == 29'h1000007f);
    wire [63:0] periph_addr_mapped = com1_port_remap ?
        {32'h0, 32'h80020000 | ({29'h0, periph_addr[2:0]} << 3)} :
        periph_addr;

    // Peripheral read data mux
    assign periph_rdata = intc_ack  ? intc_rdata :
                          timer_ack ? timer_rdata :
                          uart_ack  ? uart_rdata : 64'h0;
    assign periph_ack   = intc_ack | timer_ack | uart_ack;

    // =========================================================================
    // Interrupt Controller
    // =========================================================================
    logic [15:0] device_irqs;
    logic [63:0] ext_isr_bits;
    logic        intc_ack;
    logic [63:0] intc_rdata;

    alpha_intc #(.BASE_ADDR(64'h0000000080000000)) intc (
        .clk(clk),
        .rst_n(rst_n),
        .bus_addr(periph_addr_mapped),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_re(periph_re),
        .bus_valid(periph_valid),
        .bus_rdata(intc_rdata),
        .bus_ack(intc_ack),
        .irq_sources(device_irqs),
        .ext_isr_bits(ext_isr_bits)
    );

    // =========================================================================
    // Timer
    // =========================================================================
    logic        timer_irq;
    logic [63:0] cycle_count;
    logic        timer_ack;
    logic [63:0] timer_rdata;

    alpha_timer #(.BASE_ADDR(64'h0000000080010000)) timer (
        .clk(clk),
        .rst_n(rst_n),
        .bus_addr(periph_addr_mapped),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_re(periph_re),
        .bus_valid(periph_valid),
        .bus_rdata(timer_rdata),
        .bus_ack(timer_ack),
        .timer_irq(timer_irq),
        .cycle_count(cycle_count)
    );

    // =========================================================================
    // UART
    // =========================================================================
    logic        uart_irq;
    logic        uart_ack;
    logic [63:0] uart_rdata;

    uart16550_alpha #(.BASE_ADDR(64'h0000000080020000)) uart (
        .clk(clk),
        .rst_n(rst_n),
        .bus_addr(periph_addr_mapped),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_re(periph_re),
        .bus_valid(periph_valid),
        .bus_rdata(uart_rdata),
        .bus_ack(uart_ack),
        .uart_irq(uart_irq),
        .sim_rx_data(8'h00),
        .sim_rx_valid(1'b0),
        .sim_rx_ready()
    );

    // Device IRQ mapping
    assign device_irqs[0] = timer_irq;
    assign device_irqs[1] = uart_irq;
    assign device_irqs[15:2] = 14'd0;

    // =========================================================================
    // ISR / PCC External Signals
    // =========================================================================
    // ISR: Combine external device interrupts with software interrupt bits
    // ext_isr_bits from intc maps device IRQs to Alpha ISR bit positions.
    // Software interrupts (SIRR) are internal to the CPU, read via hw_mfpr.
    assign ext_isr = ext_isr_bits;

    // PCC: Free-running cycle counter - multiplied to speed up udelay in simulation
    // Alpha udelay reads rpcc and busy-waits. At 50MHz real freq, delays are
    // proportionally long in simulation. Scale by 1024x to make delays tractable.
    assign ext_pcc = cycle_count << 10;

    // =========================================================================
    // Boot Image Loading
    // =========================================================================
    initial begin
        string boot_file;
        integer fd, r;
        integer i;
        logic [7:0] byte_val;

        // Memory is zero-initialized by the simulator, no explicit loop needed.

        // Load boot image
        if ($value$plusargs("boot=%s", boot_file)) begin
            fd = $fopen(boot_file, "rb");
            if (fd == 0) begin
                $display("ERROR: Cannot open boot file: %s", boot_file);
                $display("");
                $display("To create a boot image, run:");
                $display("  cd isa/alpha64/platform/boot && make");
                $finish;
            end

            i = 0;
            while (!$feof(fd)) begin
                r = $fread(byte_val, fd);
                if (r == 1) begin
                    // Little-endian byte ordering into 64-bit quadwords
                    case (i % 8)
                        0: memory[i/8][7:0]   = byte_val;
                        1: memory[i/8][15:8]  = byte_val;
                        2: memory[i/8][23:16] = byte_val;
                        3: memory[i/8][31:24] = byte_val;
                        4: memory[i/8][39:32] = byte_val;
                        5: memory[i/8][47:40] = byte_val;
                        6: memory[i/8][55:48] = byte_val;
                        7: memory[i/8][63:56] = byte_val;
                    endcase
                    i = i + 1;
                end
            end
            $fclose(fd);
            $display("Loaded %0d bytes from %s", i, boot_file);

            // Display memory layout
            $display("-------------------------------------------");
            $display("Memory Layout:");
            $display("  0x00000000 - PALcode entry");
            $display("  0x00008000 - Boot ROM");
            $display("  0x0100A000 - Kernel command line");
            $display("  0x01010000 - Kernel entry point (.text)");
            $display("  0x10000000 - HWRPB");
            $display("  0x1FFFFFFF - End of RAM (512MB)");
            $display("  0x80000000 - Interrupt Controller");
            $display("  0x80010000 - Timer");
            $display("  0x80020000 - UART");
            $display("-------------------------------------------");

            // Verify first few quadwords
            $display("First 4 quadwords of boot image:");
            $display("  [0x00000000] = 0x%016x", memory[0]);
            $display("  [0x00000008] = 0x%016x", memory[1]);
            $display("  [0x00000010] = 0x%016x", memory[2]);
            $display("  [0x00000018] = 0x%016x", memory[3]);
            $display("Boot ROM entry (0x8000):");
            $display("  [0x00008000] = 0x%016x", memory[32'h8000/8]);
            $display("  [0x00008008] = 0x%016x", memory[32'h8000/8 + 1]);

            // HWRPB numpages now set correctly in bootrom.S (8184 for 64MB).

        end else begin
            $display("Usage: +boot=<boot.bin> [+kernel=<vmlinux.bin>]");
            $finish;
        end

        // Load kernel image at physical address 0x01010000 (if provided)
        begin
            string kernel_file;
            integer kfd, kr, ki;
            logic [7:0] kbyte;

            if ($value$plusargs("kernel=%s", kernel_file)) begin
                kfd = $fopen(kernel_file, "rb");
                if (kfd == 0) begin
                    $display("WARNING: Cannot open kernel file: %s", kernel_file);
                end else begin
                    ki = 0;
                    while (!$feof(kfd)) begin
                        kr = $fread(kbyte, kfd);
                        if (kr == 1) begin
                            // Load at PA 0x01010000 + ki
                            case ((32'h01010000 + ki) % 8)
                                0: memory[(32'h01010000 + ki)/8][7:0]   = kbyte;
                                1: memory[(32'h01010000 + ki)/8][15:8]  = kbyte;
                                2: memory[(32'h01010000 + ki)/8][23:16] = kbyte;
                                3: memory[(32'h01010000 + ki)/8][31:24] = kbyte;
                                4: memory[(32'h01010000 + ki)/8][39:32] = kbyte;
                                5: memory[(32'h01010000 + ki)/8][47:40] = kbyte;
                                6: memory[(32'h01010000 + ki)/8][55:48] = kbyte;
                                7: memory[(32'h01010000 + ki)/8][63:56] = kbyte;
                            endcase
                            ki = ki + 1;
                        end
                    end
                    $fclose(kfd);
                    $display("Loaded %0d bytes (%0d KB) kernel at PA 0x01010000 from %s",
                             ki, ki/1024, kernel_file);
                    $display("Kernel entry first 2 quadwords:");
                    $display("  [0x01010000] = 0x%016x", memory[32'h01010000/8]);
                    $display("  [0x01010008] = 0x%016x", memory[32'h01010000/8 + 1]);

                    // Binary patches removed: kernel addresses changed after
                    // CONFIG_ALPHA_ISACOMP rebuild. NR_IRQS is now 16 at compile
                    // time. Accelerators are disabled below; loops run natively.

                end
            end else begin
                $display("NOTE: No kernel image provided (+kernel=<vmlinux.bin>)");
                $display("      CPU will halt at kernel entry point.");
            end
        end

        // Save PALcode region for write protection.
        // The kernel may allocate and zero page 0 (PA 0x0000), overwriting
        // PALcode handlers. We save the first 0x5000 bytes (exception handlers,
        // call_pal entries, and extended handlers) and restore on corruption.
        for (int pi = 0; pi < PAL_BACKUP_QWORDS; pi++)
            palcode_backup[pi] = memory[pi];
        $display("PALcode backup: saved %0d qwords (%0d bytes) from PA 0x0000",
                 PAL_BACKUP_QWORDS, PAL_BACKUP_QWORDS * 8);
    end

    // PALcode write protection
    localparam PAL_BACKUP_QWORDS = 32'h5000 / 8;  // 0x5000 bytes = 2560 qwords
    logic [63:0] palcode_backup [0:PAL_BACKUP_QWORDS-1];

    // Restore PALcode if any qword in the region was modified.
    // Only check a few critical handler entry points each cycle for speed.
    always @(posedge clk) begin
        if (rst_n) begin
            // Check critical PALcode entry points (one per cycle, rotating)
            // INTERRUPT=0x180, D_FAULT=0x200, ITB_MISS=0x280, pal_halt=0x2000
            begin
                integer pal_check_idx;
                case (cycle[1:0])
                    0: pal_check_idx = 32'h0180 / 8;  // INTERRUPT handler
                    1: pal_check_idx = 32'h0200 / 8;  // D_FAULT handler
                    2: pal_check_idx = 32'h0280 / 8;  // ITB_MISS handler
                    3: pal_check_idx = 32'h2000 / 8;  // pal_halt
                endcase
                if (memory[pal_check_idx] != palcode_backup[pal_check_idx]) begin
                    $display("[cycle %0d] PALGUARD: PALcode corruption detected at PA 0x%04x! Restoring entire region.",
                        cycle, pal_check_idx * 8);
                    $fflush;
                    for (int pi = 0; pi < PAL_BACKUP_QWORDS; pi++)
                        memory[pi] = palcode_backup[pi];
                end
            end
        end
    end

    // =========================================================================
    // Debug Monitoring
    // =========================================================================

    // PC history for crash diagnosis (non-PAL kernel PCs only)
    logic [63:0] pc_history [0:63];
    integer pc_hist_idx = 0;

    // Exception counters
    integer itb_miss_count = 0;
    integer dtb_miss_count = 0;
    integer interrupt_count = 0;
    integer callpal_count = 0;

    // Cycle counter and state tracking
    longint unsigned cycle = 0;
    logic prev_pal_mode = 1;
    logic user_mode_seen = 0;
    integer user_instr_logged = 0;
    logic prev_uart_irq_sig = 0;
    logic prev_is_user_mode = 0;

    // Read PC from CPU via hierarchical access
    wire [63:0] cpu_pc = cpu.pc;
    wire        cpu_pal_mode = cpu.pal_mode_rd;

    // Track stall signal and instruction word
    wire cpu_mem_stall = cpu.mem_ext_stall;
    wire [31:0] cpu_instr = umem_pc_pa_read_req_addr[2] ?
        umem_pc_pa_read_resp_data[63:32] : umem_pc_pa_read_resp_data[31:0];
    // User-mode PC: not in PAL mode and PC bit 47 = 0 (user-space VAs like 0x120000000)
    // KSEG/kernel VAs have bit 47 = 1 (0xfffffc00...). PAL mode is also excluded.
    wire is_user_mode_pc = !cpu_pal_mode && !cpu_pc[47];

    always @(posedge clk) begin
        if (rst_n) begin
            if (cycle == 0) begin
                $display("");
                $display("=== Alpha64 Linux Boot Started ===");
            end
            cycle <= cycle + 1;

            // Record PC history (non-PAL kernel PCs only, skip stalls)
            if (!cpu_pal_mode && !cpu_mem_stall) begin
                pc_history[pc_hist_idx] <= cpu_pc;
                pc_hist_idx <= (pc_hist_idx + 1) & 63;
            end

            // Count exceptions via PC matching (on entry edge only)
            if (cpu_pal_mode && !prev_pal_mode) begin
                if (cpu_pc == cpu.pal_base_rd + 64'h0280)
                    itb_miss_count <= itb_miss_count + 1;
                if (cpu_pc == cpu.pal_base_rd + 64'h0200)
                    dtb_miss_count <= dtb_miss_count + 1;
                if (cpu_pc == cpu.pal_base_rd + 64'h0180)
                    interrupt_count <= interrupt_count + 1;
                if (cpu_pc >= cpu.pal_base_rd + 64'h2000 && cpu_pc < cpu.pal_base_rd + 64'h4000)
                    callpal_count <= callpal_count + 1;
            end

            // Early-cycle debug (first 20 cycles to catch PAL init)
            if (cycle < 20)
                $display("[cycle %0d] pc=0x%016x pal=%0b stall=%0b instr=0x%08x",
                    cycle, cpu_pc, cpu_pal_mode, cpu_mem_stall, cpu_instr);

            prev_pal_mode <= cpu_pal_mode;
            prev_is_user_mode <= is_user_mode_pc;
            prev_uart_irq_sig <= uart_irq;

            // Detailed trace when PC goes to a very low non-PAL address
            // (catches the pal_halt crash where PC ends up at 0x0-0x1c)
            if (!cpu_pal_mode && cpu_pc < 64'h100 && cycle > 200) begin
                $display("[cycle %0d] *** LOW PC detected: pc=0x%016x stall=%0b instr=0x%08x ipl=%0d",
                    cycle, cpu_pc, cpu_mem_stall, cpu_instr, cpu.ipl_rd);
                $display("  umem_pc_pa_read_req_addr=0x%08x",
                    umem_pc_pa_read_req_addr);
                $display("  umem_pc_pa_read_resp_data=0x%016x",
                    umem_pc_pa_read_resp_data);
                $display("  v0(rf0)=0x%016x t0(rf1)=0x%016x t1(rf2)=0x%016x t2(rf3)=0x%016x",
                    cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3]);
                $display("  t3(rf4)=0x%016x t4(rf5)=0x%016x t5(rf6)=0x%016x t6(rf7)=0x%016x",
                    cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
                $display("  t7(rf8)=0x%016x s0(rf9)=0x%016x s1(rf10)=0x%016x s2(rf11)=0x%016x",
                    cpu.rf[8], cpu.rf[9], cpu.rf[10], cpu.rf[11]);
                $display("  s3(rf12)=0x%016x s4(rf13)=0x%016x s5(rf14)=0x%016x fp(rf15)=0x%016x",
                    cpu.rf[12], cpu.rf[13], cpu.rf[14], cpu.rf[15]);
                $display("  a0(rf16)=0x%016x a1(rf17)=0x%016x a2(rf18)=0x%016x a3(rf19)=0x%016x",
                    cpu.rf[16], cpu.rf[17], cpu.rf[18], cpu.rf[19]);
                $display("  a4(rf20)=0x%016x a5(rf21)=0x%016x t8(rf22)=0x%016x t9(rf23)=0x%016x",
                    cpu.rf[20], cpu.rf[21], cpu.rf[22], cpu.rf[23]);
                $display("  t10(rf24)=0x%016x t11(rf25)=0x%016x ra(rf26)=0x%016x t12(rf27)=0x%016x",
                    cpu.rf[24], cpu.rf[25], cpu.rf[26], cpu.rf[27]);
                $display("  at(rf28)=0x%016x gp(rf29)=0x%016x sp(rf30)=0x%016x",
                    cpu.rf[28], cpu.rf[29], cpu.rf[30]);
                $display("  memory[0]=0x%016x memory[1]=0x%016x", memory[0], memory[1]);
                // Dump recent PC history to identify what led here
                $display("  Recent kernel PCs before crash:");
                for (int j = 0; j < 8; j++)
                    $display("    [-%0d] 0x%016x", j, pc_history[(pc_hist_idx - 1 - j) & 63]);
                // Print once then stop sim (to avoid flooding)
                $display("");
                $display("=== LOW PC CRASH - stopping simulation ===");
                $fflush;
                $finish;
            end

            if (cycle > 300000000) begin
                $display("[cycle %0d] CYCLE LIMIT - stopping", cycle);
                $fflush;
                $finish;
            end

            // Progress counter: every 100K cycles, written to progress.log for reliable flushing
            if (cycle > 0 && cycle % 100000 == 0) begin
                $display("[cycle %0d] PROGRESS: pc=0x%016x pal=%0b ipl=%0d uart_chars=%0d callpal=%0d dtb=%0d",
                    cycle, cpu_pc, cpu_pal_mode, cpu.ipl_rd, uart.uart_char_count,
                    callpal_count, dtb_miss_count);
                begin
                    integer pfd;
                    pfd = $fopen("progress.log", "w");
                    if (pfd) begin
                        $fwrite(pfd, "cycle=%0d pc=0x%016x pal=%0b ipl=%0d uart=%0d\n",
                            cycle, cpu_pc, cpu_pal_mode, cpu.ipl_rd, uart.uart_char_count);
                        $fclose(pfd);
                    end
                end
            end

            // UART IER write: shows when serial8250_startup (IER[0]) / start_tx (IER[1]) run
            if (periph_we && periph_valid && periph_addr_mapped == 64'h80020008) begin
                $display("[cycle %0d] UART_IER_WR: ier=0x%02x (TX=%0b RX=%0b) pc=0x%016x pal=%0b",
                    cycle, periph_wdata[7:0], periph_wdata[1], periph_wdata[0], cpu_pc, cpu_pal_mode);
                $fflush;
            end
            // UART IRQ transitions (shows when TX interrupt fires/clears)
            if (uart_irq && !prev_uart_irq_sig) begin
                $display("[cycle %0d] UART_IRQ_RISE: uart_chars=%0d pc=0x%016x pal=%0b",
                    cycle, uart.uart_char_count, cpu_pc, cpu_pal_mode);
                $fflush;
            end
            if (!uart_irq && prev_uart_irq_sig) begin
                $display("[cycle %0d] UART_IRQ_FALL: uart_chars=%0d pc=0x%016x pal=%0b",
                    cycle, uart.uart_char_count, cpu_pc, cpu_pal_mode);
                $fflush;
            end

            // =========================================================
            // USER-MODE INSTRUCTION TRACE
            // Detect when CPU first enters user-mode (non-KSEG VA, !pal_mode),
            // log first 32 instructions, and trace any PAL entries (exceptions)
            // that fire after user mode starts. This diagnoses SIGILL in /init.
            // =========================================================
            // First user-mode instruction: set user_mode_seen regardless of stall.
            // The CPU may be in user mode for only 1 stall-cycle before an ITB miss
            // re-enters PAL mode. Checking regardless of stall catches this case.
            if (is_user_mode_pc && !user_mode_seen) begin
                user_mode_seen <= 1;
                $display("[cycle %0d] *** FIRST USER-MODE PC: 0x%016x instr=0x%08x stall=%0b",
                    cycle, cpu_pc, cpu_instr, cpu_mem_stall);
                $display("  v0=$0=0x%016x  a0=$16=0x%016x  a1=$17=0x%016x  a2=$18=0x%016x",
                    cpu.rf[0], cpu.rf[16], cpu.rf[17], cpu.rf[18]);
                $display("  gp=$29=0x%016x  sp=$30=0x%016x  ra=$26=0x%016x  t12=$27=0x%016x",
                    cpu.rf[29], cpu.rf[30], cpu.rf[26], cpu.rf[27]);
                $display("  exc_addr=0x%016x  va=0x%016x  ipl=%0d",
                    cpu.exc_addr_rd, cpu.va_rd, cpu.ipl_rd);
                $display("  pc_pa=0x%08x  ifetch_qw_idx=0x%x  ifetch_word=0x%08x  memory[qw]=0x%016x",
                    umem_pc_pa_read_req_addr, ifetch_qw_idx, ifetch_word, memory[ifetch_qw_idx]);
                $fflush;
            end
            if (!cpu_mem_stall) begin
                // Log first 32 user-mode instructions
                if (is_user_mode_pc && user_instr_logged < 32) begin
                    user_instr_logged <= user_instr_logged + 1;
                    $display("[cycle %0d] USER[%0d]: pc=0x%016x instr=0x%08x  $27=0x%016x  $0=0x%016x",
                        cycle, user_instr_logged, cpu_pc, cpu_instr, cpu.rf[27], cpu.rf[0]);
                    $fflush;
                end
            end
            // After user mode started, trace PAL entries from user-space
            // Filter: only log when previous cycle was user-mode (not kernel PAL entries like swpipl)
            if (user_mode_seen && cpu_pal_mode && !prev_pal_mode && prev_is_user_mode) begin
                begin : pal_after_user_blk
                    logic [63:0] exc_off;
                    exc_off = cpu_pc - cpu.pal_base_rd;
                    $display("[cycle %0d] *** PAL_AFTER_USER: pal_pc=0x%016x off=0x%04x exc_addr=0x%016x va=0x%016x",
                        cycle, cpu_pc, exc_off[15:0], cpu.exc_addr_rd, cpu.va_rd);
                    if (exc_off == 64'h0480)
                        $display("  >> OPCDEC (Illegal Instruction) at exc_addr=0x%016x", cpu.exc_addr_rd);
                    else if (exc_off == 64'h0500)
                        $display("  >> FEN (FP Disabled) at exc_addr=0x%016x", cpu.exc_addr_rd);
                    else if (exc_off == 64'h0280)
                        $display("  >> ITB_MISS va=0x%016x", cpu.va_rd);
                    else if (exc_off == 64'h0200)
                        $display("  >> DTB_MISS va=0x%016x", cpu.va_rd);
                    else if (exc_off == 64'h0180)
                        $display("  >> INTERRUPT");
                    else if (exc_off == 64'h0300)
                        $display("  >> ITB_ACV va=0x%016x", cpu.va_rd);
                    else if (exc_off == 64'h0400)
                        $display("  >> UNALIGN va=0x%016x", cpu.va_rd);
                    else if (exc_off >= 64'h3000 && exc_off < 64'h4000)
                        $display("  >> UNPRIV CALL_PAL func=0x%02x",
                            (exc_off - 64'h3000) >> 6);
                    else if (exc_off >= 64'h2000 && exc_off < 64'h3000)
                        $display("  >> PRIV CALL_PAL func=0x%02x (from non-PAL?)",
                            (exc_off - 64'h2000) >> 6);
                    $fflush;
                end
            end

            // Periodic status (every 1M cycles)
            if (cycle % 1000000 == 0 && cycle > 0) begin
                $display("[cycle %0d] STATUS: pc=0x%016x pal=%0b ipl=%0d itb=%0d dtb=%0d int=%0d callpal=%0d isr=0x%04x timer=%0b/%0b sp=0x%016x ra=0x%016x",
                    cycle, cpu_pc, cpu_pal_mode, cpu.ipl_rd,
                    itb_miss_count, dtb_miss_count,
                    interrupt_count, callpal_count,
                    ext_isr[19:0], timer.timer_enable, timer.timer_irq_pending,
                    cpu.rf[30], cpu.rf[26]);
                $fflush;
            end

            // Timeout
            if (cycle >= 1_000_000_000) begin
                $display("");
                $display("=== Simulation Timeout (%0d cycles) ===", cycle);
                $display("Final PC: 0x%016x  PAL: %0b", cpu_pc, cpu_pal_mode);
                $display("Last 32 kernel PCs (most recent first):");
                for (int j = 0; j < 32; j++)
                    $display("  [%2d] 0x%016x", j, pc_history[(pc_hist_idx - 1 - j) & 63]);
                $fflush;
                $finish;
            end
        end
    end

    // (Accelerators removed - memset/memcpy/memmap_init_range disabled)

    // UART Output Monitor
    // =========================================================================
    // Watch for CPU writes to UART THR register (0x80020000)
    // Output to both console and uart_output.log file
    integer uart_fd;
    initial begin
        uart_fd = $fopen("uart_output.log", "w");
        if (uart_fd == 0) begin
            $display("WARNING: Could not open uart_output.log for writing");
        end
    end

    // UART monitor edge detection - only log once per store (the CPU's stall
    // mechanism causes write_req_valid to be asserted for 2 cycles per store)
    reg uart_wr_prev;
    wire uart_wr_match = umem_write_req_valid && data_wr_is_periph &&
                         (umem_write_req_addr == 32'h80020000);
    always @(posedge clk)
        if (~rst_n) uart_wr_prev <= 1'b0;
        else        uart_wr_prev <= uart_wr_match;

    // UART output to log file only (the UART module itself does $write to stdout)
    always @(posedge clk) begin
        if (rst_n && uart_wr_match && !uart_wr_prev) begin
            if (uart_fd != 0) begin
                $fwrite(uart_fd, "%c", umem_write_req_data[7:0]);
                $fflush(uart_fd);
            end
        end
    end

    final begin
        if (uart_fd != 0) $fclose(uart_fd);
    end

    // =========================================================================
    // VCD Trace
    // =========================================================================
    initial begin
        if ($test$plusargs("trace")) begin
            $dumpfile("alpha64_boot.vcd");
            $dumpvars(0, alpha64_boot_tb);
        end
    end

endmodule
