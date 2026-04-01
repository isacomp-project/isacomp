// J4 Linux Boot Testbench (MMU Mode)
// Loads and boots SH4 Linux kernel with MMU enabled in Verilator simulation
//
// SH-4 Address Space Regions:
//   P0/U0: 0x00000000-0x7FFFFFFF - User/Kernel, TRANSLATED (uses TLB)
//   P1:    0x80000000-0x9FFFFFFF - Kernel, CACHED, UNTRANSLATED
//   P2:    0xA0000000-0xBFFFFFFF - Kernel, UNCACHED, UNTRANSLATED
//   P3:    0xC0000000-0xDFFFFFFF - Kernel, TRANSLATED (uses TLB)
//   P4:    0xE0000000-0xFFFFFFFF - Control regs, UNTRANSLATED
//
// Memory Map (physical addresses):
//   0x00000000 - 0x03FFFFFF: Main RAM (64MB)
//   0x03F00100: UARTLite (via P2: 0xA3F00100)
//   0x03F00200: AIC + PIT (via P2: 0xA3F00200)
//
// Boot ROM starts at P2: 0xA0000000 (physical 0x00000000)
// Kernel runs at P1: 0x80002000 (physical 0x00002000)

`timescale 1ns/1ps

module linux_boot_mmu_tb;
    // Self-generated clock for Verilator 5+
    reg clk = 0;
    always #10 clk = ~clk;  // 50MHz

    // Reset - active high, deasserted after reset_counter expires
    reg reset;
    reg [7:0] reset_counter;

    // Constants - Memory Layout (Physical)
    localparam MEMORY_BASE = 32'h00000000;
    localparam MEMORY_SIZE = 32'h04000000;  // 64MB
    localparam KERNEL_ENTRY_P1 = 32'h80002000; // Linux kernel entry in P1
    localparam BOOT_ROM_P2 = 32'hA0000000;    // Boot ROM entry in P2

    // Entry point - P2 address for boot ROM
    reg [31:0] entry_point;

    // Constants - Peripheral Base Addresses
    // Physical addresses: 0x03F00100 (UART), 0x03F00200 (AIC/PIT)
    // P2 addresses: 0xA3F00100 (UART), 0xA3F00200 (AIC/PIT)
    localparam UART_BASE_PHYS   = 32'h03F00100;
    localparam UART_TX_PHYS     = 32'h03F00104;
    localparam PERIPH_BASE_PHYS = 32'h03F00200;

    localparam UART_BASE_P2   = 32'hA3F00100;
    localparam UART_TX_P2     = 32'hA3F00104;
    localparam PERIPH_BASE_P2 = 32'hA3F00200;

    // =========================================================================
    // Peripheral Signals
    // =========================================================================
    reg [31:0] periph_addr;
    reg [31:0] periph_wdata;
    reg        periph_we;
    reg        periph_re;
    wire [31:0] aic_rdata;
    wire        aic_ack;
    wire [31:0] pit_rdata;
    wire        pit_ack;

    // Interrupt signals
    wire aic_irq_out;
    wire [7:0] aic_irq_vector;
    wire pit_timer_irq;

    // UART output file handle
    integer uart_file;

    // IRQ sources to AIC
    wire [111:0] irq_sources;
    assign irq_sources = {55'd0, pit_timer_irq, 56'd0};  // Timer at IRQ 72

    // =========================================================================
    // AIC - Advanced Interrupt Controller
    // =========================================================================
    jcore_aic #(
        .BASE_ADDR(PERIPH_BASE_PHYS)
    ) aic (
        .clk(clk),
        .reset(reset),
        .bus_addr(periph_addr),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_re(periph_re),
        .bus_rdata(aic_rdata),
        .bus_ack(aic_ack),
        .irq_sources(irq_sources),
        .irq_out(aic_irq_out),
        .irq_vector(aic_irq_vector)
    );

    // =========================================================================
    // PIT - Programmable Interval Timer
    // =========================================================================
    jcore_pit #(
        .BASE_ADDR(PERIPH_BASE_PHYS),
        .BUS_PERIOD_NS(20)  // 50 MHz
    ) pit (
        .clk(clk),
        .reset(reset),
        .bus_addr(periph_addr),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_re(periph_re),
        .bus_rdata(pit_rdata),
        .bus_ack(pit_ack),
        .timer_irq(pit_timer_irq)
    );

    // =========================================================================
    // UARTLite - Serial Console
    // =========================================================================
    wire [31:0] uart_rdata;
    wire uart_ack;
    wire uart_irq;

    uartlite #(
        .BASE_ADDR(UART_BASE_PHYS)  // 0x03F00100
    ) uart (
        .clk(clk),
        .reset(reset),
        .bus_addr(periph_addr),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_re(periph_re),
        .bus_rdata(uart_rdata),
        .bus_ack(uart_ack),
        .uart_irq(uart_irq),
        .sim_rx_data(8'd0),
        .sim_rx_valid(1'b0),
        .sim_rx_ready()
    );

    // =========================================================================
    // J4 Processor Core (MMU Mode)
    // =========================================================================
    wire [3:0] irq_priority = pit.piten[23:20];

    j4_complete cpu (
        .clk(clk),
        .reset(reset),

        // Reset state - start at P2 address for uncached boot
        .reset_pc(entry_point),
        .reset_pr(32'd0),
        .reset_t(1'b0),
        .reset_delay_slot(1'b0),
        .reset_branch_target_rd(32'd0),
        .reset_macl(32'd0),
        .reset_mach(32'd0),
        .reset_gbr(32'd0),
        .reset_sr(32'h600000F0),  // MD=1 (bit 30), BL=1 (bit 29), RB=0 (bit 28), IMASK=F
        .reset_vbr(32'h80000000), // VBR in P1 space

        // J4-specific reset state - MMU/FPU registers
        .reset_mmucr_rd(32'h00000000),   // MMU disabled at reset
        .reset_pteh_rd(32'h00000000),
        .reset_ptel_rd(32'h00000000),
        .reset_ptea_rd(32'h00000000),
        .reset_ttb_rd(32'h00000000),
        .reset_tea_rd(32'h00000000),
        .reset_ssr(32'h00000000),
        .reset_spc(32'h00000000),
        .reset_sgr(32'h00000000),
        .reset_dbr(32'h00000000),
        .reset_expevt_rd(32'h00000000),  // Exception event register
        .reset_tra_rd(32'h00000000),     // TRAPA exception register
        .reset_intevt_rd(32'h00000000),  // Interrupt event register
        .reset_fpscr(32'h00040001),  // Default FPSCR
        .reset_fpul(32'h00000000),

        // Interrupt inputs from AIC/PIT
        .irq_i_rd(aic_irq_out),
        .irq_i_wr(1'b0),
        .irq_vector_rd(aic_irq_vector),
        .irq_vector_wr(8'b0),
        .irq_priority_rd(irq_priority),
        .irq_priority_wr(4'b0)
    );

    // =========================================================================
    // Address Translation Helper Functions
    // Convert virtual addresses to physical for peripheral detection
    // =========================================================================
    function [31:0] to_physical;
        input [31:0] va;
        begin
            // P1: 0x80000000-0x9FFFFFFF -> physical
            // P2: 0xA0000000-0xBFFFFFFF -> physical
            if (va[31:29] == 3'b100 || va[31:29] == 3'b101)
                to_physical = {3'b000, va[28:0]};
            else
                to_physical = va;  // P0/P4 unchanged (P0 needs TLB in real SH4)
        end
    endfunction

    // =========================================================================
    // Peripheral Bus Controller
    // Intercepts CPU accesses to peripheral addresses
    // =========================================================================
    // Include UART (0x100-0x110) and AIC/PIT (0x200-0x230)
    localparam PERIPH_RANGE_START_PHYS = 32'h03F00100;
    localparam PERIPH_RANGE_END_PHYS   = 32'h03F00230;

    // Get physical write address
    wire [31:0] cpu_write_addr = cpu.umem_write_addr_mux;
    wire [31:0] cpu_write_addr_phys = to_physical(cpu_write_addr);
    wire [31:0] cpu_write_data = cpu.umem_write_data_mux;
    wire cpu_write_periph = (cpu_write_addr_phys >= PERIPH_RANGE_START_PHYS) &&
                            (cpu_write_addr_phys < PERIPH_RANGE_END_PHYS);

    wire store_enable = cpu.umem_write_enable;

    // Forward writes to peripheral bus
    always @(posedge clk) begin
        if (reset) begin
            periph_we <= 1'b0;
            periph_re <= 1'b0;
            periph_addr <= 32'd0;
            periph_wdata <= 32'd0;
        end else begin
            periph_we <= 1'b0;
            periph_re <= 1'b0;

            if (store_enable && cpu_write_periph) begin
                periph_addr <= cpu_write_addr_phys;
                periph_wdata <= cpu_write_data;
                periph_we <= 1'b1;
            end
        end
    end

    // Mirror peripheral read values back to umem
    // Physical address >> 2 = word index in umem
    localparam PIT_BASE_WORD  = 32'h03F00200 >> 2;  // 0x00FC0080
    localparam UART_BASE_WORD = 32'h03F00100 >> 2;  // 0x00FC0040

    always @(posedge clk) begin
        if (!reset) begin
            // PIT registers (at 0x03F00200)
            cpu.umem[PIT_BASE_WORD + 0]  <= pit.piten;    // 0x00: PITEN
            cpu.umem[PIT_BASE_WORD + 4]  <= pit.throt;    // 0x10: THROT
            cpu.umem[PIT_BASE_WORD + 5]  <= pit.count;    // 0x14: COUNT
            cpu.umem[PIT_BASE_WORD + 6]  <= 32'd20;       // 0x18: BUSPD
            cpu.umem[PIT_BASE_WORD + 8]  <= pit.sec_hi;   // 0x20: SEC_HI
            cpu.umem[PIT_BASE_WORD + 9]  <= pit.sec_lo;   // 0x24: SEC_LO
            cpu.umem[PIT_BASE_WORD + 10] <= pit.nsec;     // 0x28: NSEC

            // AIC INTPRI (at 0x03F00200 + 8 = 0x03F00208)
            cpu.umem[PIT_BASE_WORD + 2] <= aic.intpri;

            // UART registers (at 0x03F00100)
            // RX data at offset 0x00 (word 0)
            // TX data at offset 0x04 (word 1) - write only
            // Status at offset 0x08 (word 2)
            // Control at offset 0x0C (word 3) - write only
            // Status bits: 0=RX_VALID, 1=RX_FULL, 2=TX_EMPTY, 3=TX_FULL
            cpu.umem[UART_BASE_WORD + 2] <= {28'd0, uart.tx_full, uart.tx_empty, uart.rx_full, uart.rx_valid};

            // P4 Control Registers (SH-4 specific)
            // P4 addresses (0xE0000000-0xFFFFFFFF) are mapped to physical 0x03FF0000 region
            // P4 addr 0xFFxxxxxx -> physical 0x03FFxxxx, word addr = 0x00FFCxxx

            // MMU Registers (0xFF000000-0xFF00000F)
            // PTEH, PTEL, TTB are written by kernel via P4 stores directly to umem.
            // LDTLB reads them from umem. No testbench mirroring needed.
            // MMUCR is written by ldc_mmucr (which writes to both internal reg and umem)
            // and by kernel via P4 stores. No testbench mirroring needed.
            // TEA at 0xFF00000C -> word addr 0x00FFC003
            cpu.umem[32'h00FFC003] <= cpu.tea_rd;    // TLB Exception Address

            // CCR at 0xFF00001C -> word addr 0x00FFC007
            // CCR: Cache Control Register
            // Bit 0: OCE - Operand Cache Enable (0=disabled)
            // Bit 1: WT - Write-Through (1=write-through, 0=copy-back)
            // Bit 2: CB - Copy-Back (1=copy-back enabled)
            // Bit 8: ICE - Instruction Cache Enable (0=disabled)
            // For simulation, cache is disabled (0x00000000)
            cpu.umem[32'h00FFC007] <= 32'h00000000;  // CCR - Cache disabled

            // TRA at 0xFF000020 -> physical 0x03FF0020 -> word addr 0x00FFC008
            cpu.umem[32'h00FFC008] <= cpu.tra_rd;
            // EXPEVT at 0xFF000024 -> physical 0x03FF0024 -> word addr 0x00FFC009
            cpu.umem[32'h00FFC009] <= cpu.expevt_rd;
            // INTEVT at 0xFF000028 -> physical 0x03FF0028 -> word addr 0x00FFC00A
            cpu.umem[32'h00FFC00A] <= cpu.intevt_rd;
            // PTEA at 0xFF00002C -> word addr 0x00FFC00B
            // PTEA mirroring removed - no compiled instruction declares ptea
            cpu.umem[32'h00FFC00B] <= 32'h00000000;  // PTEA - not used

            // CPU identification registers (required for kernel boot)
            // CCN_PVR at 0xFF000030 -> word addr 0x00FFC00C
            // Linux kernel probe.c detects CPUs by: pvr = (PVR >> 8) & 0xffff
            //   case 0x1100: CPU_SH7751 (direct match, no PRR needed)
            // Use SH7751 (PVR=0x04110000) since kernel doesn't check PRR for this case
            cpu.umem[32'h00FFC00C] <= 32'h04110000;  // PVR - SH7751

            // MMUCR mirroring removed - written by ldc_mmucr to umem and by kernel P4 stores

            // QACR0 at 0xFF000038 -> word addr 0x00FFC00E
            cpu.umem[32'h00FFC00E] <= 32'h00000000;  // Queue Address Control 0
            // QACR1 at 0xFF00003C -> word addr 0x00FFC00F
            cpu.umem[32'h00FFC00F] <= 32'h00000000;  // Queue Address Control 1

            // CCN_CVR at 0xFF000040 -> word addr 0x00FFC010
            cpu.umem[32'h00FFC010] <= 32'h00000000;  // CVR - Cache Version Register
            // CCN_PRR at 0xFF000044 -> word addr 0x00FFC011
            cpu.umem[32'h00FFC011] <= 32'h00000000;  // PRR - not checked for SH7751

            // =========================================================================
            // TMU (Timer Unit) Emulation - Required for kernel scheduler
            // SH-4 TMU is at P4 address 0xFFD80000-0xFFD800FF
            // P4 addr 0xFFD8xxxx -> physical 0x03FD8xxx -> word addr 0x00FF6xxx
            // =========================================================================
            // TMU TOCR at 0xFFD80000 -> word addr 0x00FF6000
            cpu.umem[32'h00FF6000] <= 32'h00000000;  // TOCR - Timer Output Control
            // TMU TSTR at 0xFFD80004 -> word addr 0x00FF6001
            cpu.umem[32'h00FF6001] <= tmu_tstr;      // TSTR - Timer Start Register
            // TMU Channel 0 registers (most important for kernel)
            // TCOR0 at 0xFFD80008 -> word addr 0x00FF6002
            cpu.umem[32'h00FF6002] <= tmu_tcor0;     // TCOR0 - Timer Constant
            // TCNT0 at 0xFFD8000C -> word addr 0x00FF6003
            cpu.umem[32'h00FF6003] <= tmu_tcnt0;     // TCNT0 - Timer Counter
            // TCR0 at 0xFFD80010 -> word addr 0x00FF6004
            cpu.umem[32'h00FF6004] <= tmu_tcr0;      // TCR0 - Timer Control
            // TMU Channel 1 registers
            cpu.umem[32'h00FF6005] <= 32'hFFFFFFFF;  // TCOR1
            cpu.umem[32'h00FF6006] <= 32'hFFFFFFFF;  // TCNT1
            cpu.umem[32'h00FF6007] <= 32'h00000000;  // TCR1
            // TMU Channel 2 registers
            cpu.umem[32'h00FF6008] <= 32'hFFFFFFFF;  // TCOR2
            cpu.umem[32'h00FF6009] <= 32'hFFFFFFFF;  // TCNT2
            cpu.umem[32'h00FF600A] <= 32'h00000000;  // TCR2
        end
    end

    // =========================================================================
    // TMU State Registers and Timer Logic
    // =========================================================================
    reg [31:0] tmu_tstr;     // Timer Start Register (bit 0 = TMU0 enable)
    reg [31:0] tmu_tcor0;    // Timer Constant Register 0
    reg [31:0] tmu_tcnt0;    // Timer Counter 0 (counts down)
    reg [31:0] tmu_tcr0;     // Timer Control Register 0
    reg tmu0_underflow;      // TMU0 underflow interrupt flag

    initial begin
        tmu_tstr = 0;
        tmu_tcor0 = 32'hFFFFFFFF;
        tmu_tcnt0 = 32'hFFFFFFFF;
        tmu_tcr0 = 0;
        tmu0_underflow = 0;
    end

    // TMU register write handling
    always @(posedge clk) begin
        if (reset) begin
            tmu_tstr <= 0;
            tmu_tcor0 <= 32'hFFFFFFFF;
            tmu_tcnt0 <= 32'hFFFFFFFF;
            tmu_tcr0 <= 0;
            tmu0_underflow <= 0;
        end else if (cpu.umem_write_enable) begin
            // Check for TMU register writes (P4 addr 0xFFD8xxxx)
            // These come through as physical 0x03FD8xxx
            case (to_physical(cpu.umem_write_addr_mux))
                32'h03FD8004: begin  // TSTR
                    tmu_tstr <= cpu.umem_write_data_mux;
                    if (cycle_count < 500000)
                        $display("[%0d] TMU_WRITE: TSTR=%08x (TMU0 %s)",
                                 cycle_count, cpu.umem_write_data_mux,
                                 cpu.umem_write_data_mux[0] ? "START" : "STOP");
                end
                32'h03FD8008: begin  // TCOR0
                    tmu_tcor0 <= cpu.umem_write_data_mux;
                    if (cycle_count < 500000)
                        $display("[%0d] TMU_WRITE: TCOR0=%08x", cycle_count, cpu.umem_write_data_mux);
                end
                32'h03FD800C: begin  // TCNT0
                    tmu_tcnt0 <= cpu.umem_write_data_mux;
                    if (cycle_count < 500000)
                        $display("[%0d] TMU_WRITE: TCNT0=%08x", cycle_count, cpu.umem_write_data_mux);
                end
                32'h03FD8010: begin  // TCR0
                    tmu_tcr0 <= cpu.umem_write_data_mux;
                    // Clear underflow flag if UNF bit (bit 8) is written as 0
                    if (!cpu.umem_write_data_mux[8])
                        tmu0_underflow <= 0;
                    if (cycle_count < 500000)
                        $display("[%0d] TMU_WRITE: TCR0=%08x (UNIE=%b)",
                                 cycle_count, cpu.umem_write_data_mux, cpu.umem_write_data_mux[5]);
                end
            endcase
        end

        // TMU0 counter decrement when enabled
        if (!reset && tmu_tstr[0]) begin
            // Decrement counter (simplified - ignores prescaler for now)
            if (tmu_tcnt0 == 0) begin
                tmu_tcnt0 <= tmu_tcor0;  // Reload from constant register
                tmu0_underflow <= 1;      // Set underflow flag
                // Set UNF bit in TCR0
                tmu_tcr0[8] <= 1;
            end else begin
                tmu_tcnt0 <= tmu_tcnt0 - 1;
            end
        end
    end

    // TMU0 interrupt output (active when underflow and UNIE enabled)
    wire tmu0_irq = tmu0_underflow && tmu_tcr0[5];  // UNIE is bit 5

    // =========================================================================
    // UART Monitor - watch for writes to UART TX register
    // =========================================================================
    wire [31:0] write_addr = cpu.umem_write_addr_mux;
    wire [31:0] write_addr_phys = to_physical(write_addr);
    wire [31:0] write_data = cpu.umem_write_data_mux;

    // Trace kernel entry (PC in range 0x80002000-0x80002100) to see R4 (FDT pointer)
    reg kernel_entry_traced;
    initial kernel_entry_traced = 0;
    always @(posedge clk) begin
        if (!reset && cpu_pc >= 32'h80002000 && cpu_pc < 32'h80002100 && !kernel_entry_traced) begin
            $display("[%0d] KERNEL_ENTRY: PC=%08x R4(FDT)=%08x R5=%08x R6=%08x R7=%08x",
                     cycle_count, cpu_pc, cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
            // Verify FDT magic - physical address = R4 & 0x1FFFFFFF, word index = >> 2
            $display("         FDT at 0x%08x: magic=%08x (should be d00dfeed)",
                     cpu.rf[4], cpu.umem[(cpu.rf[4] & 32'h1FFFFFFF) >> 2]);
            kernel_entry_traced <= 1;
        end
    end

    // Trace PVR register read - CPU ID detection at PC=0x80005012
    reg pvr_traced;
    initial pvr_traced = 0;
    always @(posedge clk) begin
        // mov.l @r1,r5 at PC=0x80005012 reads PVR (r1=0xFF000030)
        if (!reset && cpu_pc == 32'h80005012 && !pvr_traced) begin
            $display("[%0d] PVR_READ: PC=%08x R1(PVR_addr)=%08x R5(before)=%08x",
                     cycle_count, cpu_pc, cpu.rf[1], cpu.rf[5]);
            // Show the value at the word address for PVR (0x03FF0030 >> 2 = 0x00FFC00C)
            $display("         umem[0x00FFC00C]=%08x (PVR value)", cpu.umem[32'h00FFC00C]);
            pvr_traced <= 1;
        end
        // Trace after PVR read to see what value was loaded
        if (!reset && cpu_pc == 32'h80005014 && pvr_traced) begin
            $display("[%0d] PVR_AFTER: PC=%08x R5(PVR_value)=%08x", cycle_count, cpu_pc, cpu.rf[5]);
        end
        // Trace the branch decision point at 0x8000a3f4 (tst r1,r1 - checks BSS value)
        if (!reset && cpu_pc == 32'h8000a3f4) begin
            $display("[%0d] CPU_CHECK: PC=%08x R1(BSS_val)=%08x - checking 0x803130f0",
                     cycle_count, cpu_pc, cpu.rf[1]);
            // Also show what's at the BSS address (0x803130f0 -> physical 0x003130f0 -> word 0x000C4C3C)
            $display("         umem[0x000C4C3C]=%08x (BSS value at 0x803130f0)",
                     cpu.umem[32'h000C4C3C]);
        end
        // Trace the compare at 0x8000a260 (cmp/eq #0x2d,r0)
        if (!reset && cpu_pc == 32'h8000a260) begin
            $display("[%0d] CPU_TYPE: PC=%08x R0=%08x (comparing with 0x2d=45)",
                     cycle_count, cpu_pc, cpu.rf[0]);
        end
        // Trace the branch decision at 0x8000a262
        if (!reset && cpu_pc == 32'h8000a262) begin
            $display("[%0d] CPU_BRANCH: PC=%08x T=%b (bf to 0x8000a268 if T=0)",
                     cycle_count, cpu_pc, cpu.t);
        end
        // Trace the bra to panic at 0x8000a264
        if (!reset && cpu_pc == 32'h8000a264) begin
            $display("[%0d] CPU_PANIC_BRA: PC=%08x - branching to panic 0x8000a520",
                     cycle_count, cpu_pc);
        end
    end

    // Trace panic entry - capture context when entering panic()
    reg panic_traced;
    initial panic_traced = 0;
    always @(posedge clk) begin
        // panic() at 0x80244cac
        if (!reset && cpu_pc == 32'h80244cac && !panic_traced) begin
            $display("[%0d] PANIC: PC=%08x R4(msg?)=%08x R15(SP)=%08x PR(caller)=%08x",
                     cycle_count, cpu_pc, cpu.rf[4], cpu.rf[15], cpu.pr_rd);
            panic_traced <= 1;
        end
        // Trace sh_fdt_init at 0x802495bc
        if (!reset && cpu_pc == 32'h802495bc) begin
            $display("[%0d] SH_FDT_INIT: R4(dt_phys)=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.pr_rd);
        end
        // Trace unflatten_device_tree at 0x80321578
        if (!reset && cpu_pc == 32'h80321578) begin
            $display("[%0d] UNFLATTEN_DEVICE_TREE: PR=%08x",
                     cycle_count, cpu.pr_rd);
        end
        // Trace of_platform_default_populate_init at 0x80320574
        if (!reset && cpu_pc == 32'h80320574) begin
            $display("[%0d] OF_PLATFORM_DEFAULT_POPULATE_INIT: PR=%08x",
                     cycle_count, cpu.pr_rd);
        end
        // Trace aic_irq_of_init at 0x8031c39c
        if (!reset && cpu_pc == 32'h8031c39c) begin
            $display("[%0d] AIC_IRQ_OF_INIT: R4=%08x R5=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.pr_rd);
        end
        // Trace irqchip_init at 0x8031c38c
        if (!reset && cpu_pc == 32'h8031c38c) begin
            $display("[%0d] IRQCHIP_INIT: PR=%08x",
                     cycle_count, cpu.pr_rd);
        end
        // Trace ulite_probe at 0x801d2010
        if (!reset && cpu_pc == 32'h801d2010) begin
            $display("[%0d] ULITE_PROBE: R4=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.pr_rd);
        end
        // Trace uart_register_driver at 0x801d0f9c
        if (!reset && cpu_pc == 32'h801d0f9c) begin
            $display("[%0d] UART_REGISTER_DRIVER: R4=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.pr_rd);
        end
        // Trace uart_add_one_port at 0x801d1168
        if (!reset && cpu_pc == 32'h801d1168) begin
            $display("[%0d] UART_ADD_ONE_PORT: R4(drv)=%08x R5(port)=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.pr_rd);
        end
        // Trace ulite_config_port at 0x801d1ddc
        if (!reset && cpu_pc == 32'h801d1ddc) begin
            $display("[%0d] ULITE_CONFIG_PORT: R4(port)=%08x R5(flags)=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.pr_rd);
        end
        // Trace ulite_request_port at 0x801d1c40
        if (!reset && cpu_pc == 32'h801d1c40) begin
            $display("[%0d] ULITE_REQUEST_PORT: R4(port)=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.pr_rd);
        end
        // Trace ulite_console_setup at 0x801d1d18
        if (!reset && cpu_pc == 32'h801d1d18) begin
            $display("[%0d] ULITE_CONSOLE_SETUP: R4=%08x R5=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.pr_rd);
        end
        // Trace __ioremap_caller at 0x8024960c
        if (!reset && cpu_pc == 32'h8024960c) begin
            $display("[%0d] __IOREMAP_CALLER: R4(phys)=%08x R5(size)=%08x R6(prot)=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.pr_rd);
        end
        // Trace platform_get_resource at 0x801de104
        if (!reset && cpu_pc == 32'h801de104) begin
            $display("[%0d] PLATFORM_GET_RESOURCE: R4=%08x R5=%08x R6=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.pr_rd);
        end
        // Trace platform_get_irq at 0x801de2f8
        if (!reset && cpu_pc == 32'h801de2f8) begin
            $display("[%0d] PLATFORM_GET_IRQ: R4=%08x R5=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.pr_rd);
        end
        // Trace after platform_get_irq returns in ulite_probe at 0x801d21aa
        if (!reset && cpu_pc == 32'h801d21aa) begin
            $display("[%0d] AFTER_GET_IRQ: R0(irq)=%08x T=%b (negative=%b)",
                     cycle_count, cpu.rf[0], cpu.t, cpu.rf[0][31]);
        end
        // Trace after platform_get_resource returns at 0x801d2198
        if (!reset && cpu_pc == 32'h801d2198) begin
            $display("[%0d] AFTER_GET_RESOURCE: R0(res)=%08x (null check: T=%b)",
                     cycle_count, cpu.rf[0], cpu.t);
        end
        // Trace uart_add_one_port call at 0x801d225e
        if (!reset && cpu_pc == 32'h801d225e) begin
            $display("[%0d] CALL_UART_ADD_ONE_PORT: R4=%08x R5=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.pr_rd);
        end
        // Trace after uart_add_one_port returns at 0x801d2262
        if (!reset && cpu_pc == 32'h801d2262) begin
            $display("[%0d] AFTER_UART_ADD_ONE_PORT: R0(ret)=%08x",
                     cycle_count, cpu.rf[0]);
        end
        // Trace devm_clk_get at 0x801a8c7c
        if (!reset && cpu_pc == 32'h801a8c7c) begin
            $display("[%0d] DEVM_CLK_GET: R4=%08x R5=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.pr_rd);
        end
        // Trace after devm_clk_get returns (0x801d21b8)
        if (!reset && cpu_pc == 32'h801d21b8) begin
            $display("[%0d] AFTER_DEVM_CLK_GET: R0=%08x",
                     cycle_count, cpu.rf[0]);
        end
        // Trace console registration: register_console at 0x8003a6d4
        if (!reset && cpu_pc == 32'h8003a6d4) begin
            $display("[%0d] REGISTER_CONSOLE: R4=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.pr_rd);
        end
        // Trace UartLite console write: ulite_console_write at 0x801d1ef0
        if (!reset && cpu_pc == 32'h801d1ef0) begin
            $display("[%0d] ULITE_CONSOLE_WRITE: R4=%08x R5=%08x R6=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.pr_rd);
        end
        // Trace unregister_console at 0x80245514
        if (!reset && cpu_pc == 32'h80245514) begin
            $display("[%0d] UNREGISTER_CONSOLE: R4=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.pr_rd);
        end
        // Trace jcore_pit_init at 0x80320010
        if (!reset && cpu_pc == 32'h80320010) begin
            $display("[%0d] JCORE_PIT_INIT: R4=%08x R5=%08x PR=%08x",
                     cycle_count, cpu.rf[4], cpu.rf[5], cpu.pr_rd);
        end
    end

    // Trace when R0 gets value 0x2d (CPU type unknown)
    reg [31:0] prev_r0;
    reg [31:0] prev_rf_bank7;
    initial prev_r0 = 0;
    initial prev_rf_bank7 = 0;
    always @(posedge clk) begin
        if (!reset) begin
            if (cpu.rf[0] == 32'h0000002d && prev_r0 != 32'h0000002d) begin
                $display("[%0d] R0_BECOMES_2D: PC=%08x R0=%08x prev_r0=%08x",
                         cycle_count, cpu_pc, cpu.rf[0], prev_r0);
            end
            prev_r0 <= cpu.rf[0];
        end
    end

    // Trace CPU detection code flow - extended range
    always @(posedge clk) begin
        if (!reset && cycle_count >= 162560 && cycle_count <= 162660) begin
            // Trace all execution in CPU detection regions
            $display("[%0d] CPUDET: PC=%08x R0=%08x R1=%08x R2=%08x R3=%08x R4=%08x R5=%08x R7=%08x",
                     cycle_count, cpu_pc, cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[7]);
        end
    end

    // Also trace umem writes from the CPU
    reg [31:0] last_umem_write_addr;
    always @(posedge clk) begin
        if (!reset && cpu.umem_write_enable) begin
            // Log writes to high addresses (>= 0xA0000000 which is P2)
            if (cpu.umem_write_addr_mux >= 32'hA0000000 && cycle_count < 500000) begin
                $display("[%0d] UMEM_WRITE: VA=%08x PA=%08x Data=%08x",
                         cycle_count, cpu.umem_write_addr_mux,
                         to_physical(cpu.umem_write_addr_mux),
                         cpu.umem_write_data_mux);
            end
        end
    end

    // Stack watchpoint: monitor writes to corrupted PR stack location
    always @(posedge clk) begin
        if (!reset && store_enable) begin
            // Watch for ANY write to physical address 0x0041fe54 (VA 0x8041fe54)
            // Also watch 0x0041fe50-0x0041fe7f (surrounding stack area)
            if (write_addr_phys >= 32'h0041fe50 && write_addr_phys <= 32'h0041fe7f) begin
                $display("[%0d] STACK_WATCH: PC=%08x VA=%08x PA=%08x Data=%08x SR=%08x",
                         cycle_count, cpu_pc, write_addr, write_addr_phys, write_data,
                         cpu.sr_rd);
            end
        end
    end

    // SPC change trace — detect when SPC register transitions
    reg [31:0] last_spc;
    initial last_spc = 0;
    always @(posedge clk) begin
        if (!reset) begin
            if (cpu.spc_rd != last_spc) begin
                if (cycle_count > 28035000) begin
                    $display("[%0d] SPC_CHANGE: %08x -> %08x PC=%08x SR=%08x BL=%b delay=%b int_take=%b INSTR=%04x",
                             cycle_count, last_spc, cpu.spc_rd, cpu_pc, cpu.sr_rd,
                             cpu.sr_rd[28], cpu.delay_slot, cpu.int_should_take, cpu.instr);
                end
                last_spc <= cpu.spc_rd;
            end
        end
    end

    // Detailed per-cycle trace around corruption window
    always @(posedge clk) begin
        if (!reset && cycle_count > 28036800 && cycle_count < 28037050) begin
            $display("[%0d] CYCLE: PC=%08x INSTR=%04x SPC=%08x SSR=%08x SR=%08x R15=%08x delay=%b int_take=%b",
                     cycle_count, cpu_pc, cpu.instr, cpu.spc_rd, cpu.ssr_rd,
                     cpu.sr_rd, cpu.rf[15], cpu.delay_slot, cpu.int_should_take);
        end
    end

    always @(posedge clk) begin
        if (!reset && store_enable) begin
            // Trace writes in early boot, but skip BSS loop (PC 0x80002018-0x8000201f)
            if (cycle_count < 200000 && cycle_count > 100 &&
                (cpu_pc < 32'h80002018 || cpu_pc >= 32'h80002020)) begin
                $display("[%0d] EARLY_WRITE: PC=%08x VA=%08x PA=%08x Data=%08x",
                         cycle_count, cpu_pc, write_addr, write_addr_phys, write_data);
            end
            // Debug: Log writes to peripheral region (UART at 0x03F00xxx physical)
            if (write_addr_phys >= 32'h03F00000 && write_addr_phys < 32'h04000000 && cycle_count < 500000) begin
                $display("[%0d] PERIPH_WRITE: VA=%08x PA=%08x Data=%08x PC=%08x",
                         cycle_count, write_addr, write_addr_phys, write_data, cpu_pc);
            end
            // Also log P2 region writes (0xA0000000-0xBFFFFFFF)
            if (write_addr >= 32'hA0000000 && write_addr < 32'hC0000000 && cycle_count < 500000) begin
                $display("[%0d] P2_WRITE: VA=%08x PA=%08x Data=%08x PC=%08x",
                         cycle_count, write_addr, write_addr_phys, write_data, cpu_pc);
            end
            // Check if writing to UART TX (physical address 0x03F00104)
            // Note: actual UART output goes to uart_output.txt via UARTLite module
            if (write_addr_phys == 32'h03F00104) begin
                $display("[%0d] UART_TX: '%c' (0x%02x)", cycle_count, write_data[7:0], write_data[7:0]);
            end
            // Trace ALL UART register writes (0x03F00100-0x03F0010F)
            if (write_addr_phys >= 32'h03F00100 && write_addr_phys <= 32'h03F0010F && write_addr_phys != 32'h03F00104) begin
                $display("[%0d] UART_REG_WR: PC=%08x PA=%08x Data=%08x (offset=0x%02x)",
                         cycle_count, cpu_pc, write_addr_phys, write_data, write_addr_phys[3:0]);
            end
            // Trace any writes to high addresses (potential P4 control regs or peripherals)
            if ((write_addr >= 32'hFF000000 || write_addr >= 32'hE0000000) && cycle_count < 500000) begin
                $display("[%0d] P4_WRITE: PC=%08x VA=%08x PA=%08x Data=%08x",
                         cycle_count, cpu_pc, write_addr, write_addr_phys, write_data);
            end
            // (duplicate PERIPH_WRITE trace removed)
            // Watchpoint: trace writes to the stack region around PR save location
            // d_make_root saves PR at 0x802e5f2c (phys 0x002e5f2c)
            // Trace wider range to catch interrupt handler stack operations
            if (write_addr_phys >= 32'h002e5f00 && write_addr_phys <= 32'h002e5f40 && cycle_count > 4000000) begin
                $display("[%0d] STACK_WP: PC=%08x VA=%08x PA=%08x Data=%08x SR=%08x R15=%08x PR=%08x",
                         cycle_count, cpu_pc, write_addr, write_addr_phys, write_data, cpu.sr_rd, cpu.rf[15], cpu.pr_rd);
            end
            // Watchpoint: trace ALL writes to init's pt_regs->pc (phys 0x0041dfe4)
            // pt_regs base at 0x8041dfa4 (R15 at RESUME_USPACE), PC at offset 0x40
            if (write_addr_phys == 32'h0041dfe4) begin
                $display("[%0d] PTREGS_PC_WR: PC=%08x VA=%08x Data=%08x SR=%08x R15=%08x PR=%08x",
                         cycle_count, cpu_pc, write_addr, write_data, cpu.sr_rd, cpu.rf[15], cpu.pr_rd);
            end
            // Watchpoint: trace writes near pt_regs->pc (check for off-by-one)
            if (write_addr_phys >= 32'h0041dfd0 && write_addr_phys <= 32'h0041e000 && write_addr_phys != 32'h0041dfe4) begin
                $display("[%0d] PTREGS_NEAR: PC=%08x VA=%08x PA=%08x Data=%08x",
                         cycle_count, cpu_pc, write_addr, write_addr_phys, write_data);
            end
        end
    end

    // Trace early kernel execution to understand boot sequence
    reg [31:0] last_pc_64k;
    always @(posedge clk) begin
        if (!reset && cycle_count < 400000) begin
            // Trace significant PC changes (different 64KB region)
            if (cpu_pc[31:16] != last_pc_64k && cpu_pc >= 32'h80000000) begin
                $display("[%0d] PC_64K: %08x -> %08x R15=%08x",
                         cycle_count, {last_pc_64k, 16'h0}, cpu_pc, cpu.rf[15]);
                last_pc_64k <= cpu_pc[31:16];
            end
        end
    end

    // Debug: trace PIT and AIC IRQ state
    reg pit_irq_prev;
    reg aic_irq_prev;
    reg [31:0] stuck_counter;
    always @(posedge clk) begin
        if (!reset) begin
            if (pit_timer_irq && !pit_irq_prev)
                $display("[%0d] PIT_IRQ: RAISED - piten=%08x throt=%08x", cycle_count, pit.piten, pit.throt);
            if (!pit_timer_irq && pit_irq_prev)
                $display("[%0d] PIT_IRQ: CLEARED", cycle_count);
            if (aic_irq_out && !aic_irq_prev)
                $display("[%0d] AIC_IRQ: RAISED - intpri=%08x vector=%02x", cycle_count, aic.intpri, aic_irq_vector);
            if (!aic_irq_out && aic_irq_prev)
                $display("[%0d] AIC_IRQ: CLEARED", cycle_count);
            pit_irq_prev <= pit_timer_irq;
            aic_irq_prev <= aic_irq_out;

            // Debug stuck PC at irq_enter (0x8001406a)
            if (cpu_pc == 32'h8001406a) begin
                stuck_counter <= stuck_counter + 1;
                if (stuck_counter < 10 || stuck_counter == 100 || stuck_counter == 1000 || stuck_counter == 10000) begin
                    $display("[%0d] STUCK_IRQ_ENTER: PC=%08x INSTR=%04x R0=%08x R1=%08x R2=%08x R15=%08x",
                             cycle_count, cpu_pc, cpu.instr, cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[15]);
                    $display("         SR=%08x BL=%b RB=%b R7_BANK=%08x delay=%b int_take=%b",
                             cpu.sr_rd, cpu.sr_rd[28], cpu.sr_rd[29], cpu.rf_bank[7],
                             cpu.delay_slot, cpu.int_should_take_mux);
                end
            end else begin
                stuck_counter <= 0;
            end
            // Trace first entry to irq_enter (0x8001405c)
            if (cpu_pc == 32'h8001405c && cycle_count > 100000) begin
                $display("[%0d] IRQ_ENTER_ENTRY: R7_BANK=%08x R15=%08x SR=%08x PR=%08x",
                         cycle_count, cpu.rf_bank[7], cpu.rf[15], cpu.sr_rd, cpu.pr_rd);
            end

            // Trace writes to PIT/timer registers (0x03F00200-0x03F0022F)
            if (store_enable && write_addr_phys >= 32'h03F00200 && write_addr_phys < 32'h03F00230) begin
                $display("[%0d] PIT_ACCESS: WRITE PA=%08x Data=%08x PC=%08x",
                         cycle_count, write_addr_phys, write_data, cpu_pc);
            end
        end
    end


    // =========================================================================
    // Exception Debug - trace exception taken and EXPEVT
    // =========================================================================
    reg [31:0] last_expevt;
    reg [31:0] exception_count;
    reg [31:0] handler_trace_count;
    always @(posedge clk) begin
        if (!reset && cpu.expevt_rd != last_expevt && cpu.expevt_rd != 0) begin
            exception_count <= exception_count + 1;
            // Display more exceptions to debug the recursion
            if (exception_count < 1000 || (exception_count % 10000 == 0)) begin
                $display("[%0d] EXCEPTION #%0d: PC=%08x EXPEVT=%08x->%08x SR=%08x SSR=%08x VBR=%08x R15=%08x TEA=%08x R7_BK=%08x",
                         cycle_count, exception_count, cpu_pc, last_expevt, cpu.expevt_rd,
                         cpu.sr_rd, cpu.ssr_rd, cpu.vbr, cpu.rf[15], cpu.tea_rd, cpu.rf_bank[7]);
            end
        end
        last_expevt <= cpu.expevt_rd;
    end

    // Trace execution in exception handler area to understand flow
    always @(posedge clk) begin
        if (!reset && cpu_pc >= 32'h80007100 && cpu_pc < 32'h80007800) begin
            handler_trace_count <= handler_trace_count + 1;
            // Trace first 500 instructions in handler
            if (handler_trace_count < 500) begin
                $display("[%0d] HANDLER: PC=%08x INSTR=%04x R15=%08x SR=%08x SSR=%08x RB=%b R7_BK=%08x R7=%08x R1=%08x R1_BK=%08x T=%b delay=%b",
                         cycle_count, cpu_pc, cpu.instr, cpu.rf[15], cpu.sr_rd, cpu.ssr_rd, cpu.sr_rd[28],
                         cpu.rf_bank[7], cpu.rf[7], cpu.rf[1], cpu.rf_bank[1], cpu.t, cpu.delay_slot);
            end
        end
        // Also trace execution at 0x800061cc onwards (the handler function)
        if (!reset && cpu_pc >= 32'h800061c0 && cpu_pc < 32'h80006300) begin
            if (handler_trace_count < 600) begin
                $display("[%0d] HANDLER_FN: PC=%08x INSTR=%04x R15=%08x delay=%b branch=%08x EXPEVT=%08x",
                         cycle_count, cpu_pc, cpu.instr, cpu.rf[15],
                         cpu.delay_slot, cpu.branch_target_rd, cpu.expevt_rd);
            end
        end
        // Trace execution at the trapa handler function (0x8001b554)
        if (!reset && cpu_pc >= 32'h8001b550 && cpu_pc < 32'h8001b600 && cycle_count < 165000) begin
            $display("[%0d] TRAPA_FN: PC=%08x INSTR=%04x R1=%08x R4=%08x R0=%08x delay=%b",
                     cycle_count, cpu_pc, cpu.instr, cpu.rf[1], cpu.rf[4], cpu.rf[0],
                     cpu.delay_slot);
            // Extra trace for MOV.W @(disp,PC) instruction
            if (cpu.instr[15:12] == 4'h9) begin
                $display("  -> MOV.W: pc_val=%08x addr=%08x pa=%08x halfsel=%b data16=%04x",
                         cpu.movw_pcrel_pc_val, cpu.movw_pcrel_addr, cpu.movw_pcrel_pa,
                         cpu.umem_movw_pcrel_pa_rd_halfword_select, cpu.movw_pcrel_data16);
            end
        end
    end

    // =========================================================================
    // LDTLB and TLB Miss Debug Traces
    // =========================================================================
    reg [31:0] ldtlb_trace_count;
    reg [31:0] tlb_miss_trace_count;
    reg [31:0] last_tea;
    always @(posedge clk) begin
        if (reset) begin
            ldtlb_trace_count <= 0;
            tlb_miss_trace_count <= 0;
            last_tea <= 0;
        end else begin
            // Trace LDTLB instruction execution (opcode 0x0038)
            if (cpu.instr == 16'h0038 && cpu.ldtlb_enable) begin
                ldtlb_trace_count <= ldtlb_trace_count + 1;
                if (ldtlb_trace_count < 200 || (ldtlb_trace_count % 1000 == 0) || cpu.ldtlb_pteh_val[31] == 1'b0) begin
                    $display("[%0d] LDTLB #%0d: PC=%08x PTEH=%08x PTEL=%08x MMUCR=%08x URC=%0d VPN=%05x PPN=%05x V=%b int_take=%b priv=%b",
                             cycle_count, ldtlb_trace_count, cpu_pc,
                             cpu.ldtlb_pteh_val, cpu.ldtlb_ptel_val, cpu.ldtlb_mmucr_val,
                             cpu.urc, cpu.new_vpn, cpu.new_ppn, cpu.new_v,
                             cpu.int_should_take, cpu.is_privileged);
                end
            end

            // Trace TLB miss exceptions (TEA changes indicate faulting address)
            if (cpu.tea_rd != last_tea && cpu.tea_rd != 0) begin
                tlb_miss_trace_count <= tlb_miss_trace_count + 1;
                if (tlb_miss_trace_count < 100 || (tlb_miss_trace_count % 1000 == 0)) begin
                    $display("[%0d] TLB_MISS #%0d: TEA=%08x->%08x PC=%08x EXPEVT=%08x MMUCR=%08x PTEH=%08x SPC=%08x TTB=%08x",
                             cycle_count, tlb_miss_trace_count, last_tea, cpu.tea_rd,
                             cpu_pc, cpu.expevt_rd, cpu.mmucr_rd,
                             cpu.umem[32'h00FFC000], cpu.spc_rd, cpu.umem[32'h00FFC002]);
                end
            end
            last_tea <= cpu.tea_rd;
        end
    end

    // Trace specific register bank values periodically
    wire [31:0] loop_pc_pa = {3'b000, cpu_pc[28:0]};  // P1 to physical
    wire [31:0] loop_mem_word = cpu.umem[loop_pc_pa >> 2];  // Get memory word
    always @(posedge clk) begin
        // Trace when PC is near the stuck loop
        if (!reset && cpu_pc >= 32'h80157420 && cpu_pc <= 32'h80157440) begin
            if (cycle_count < 2000000 || (cycle_count % 1000000 == 0)) begin
                $display("[%0d] LOOP: PC=%08x MEM=%08x INSTR=%04x delay=%b branch=%08x jmp_en=%b",
                         cycle_count, cpu_pc, loop_mem_word, cpu.instr,
                         cpu.delay_slot, cpu.branch_target_rd,
                         cpu.jmp_enable);
            end
        end
        // Trace delay loop - log PR (return address) to see caller
        if (!reset && cpu_pc >= 32'h801e4ab0 && cpu_pc <= 32'h801e4ac0) begin
            // Log first occurrence and then every 10M cycles
            if (cycle_count < 500000 || (cycle_count % 10000000 == 0)) begin
                $display("[%0d] DELAY_LOOP: PC=%08x PR(ret)=%08x R4=%08x R15(SP)=%08x",
                         cycle_count, cpu_pc, cpu.pr_rd, cpu.rf[4], cpu.rf[15]);
            end
        end
    end

    // Trace memset/bzero function that corrupts kernel text
    // Function at 0x80224258 - logs R4 (dest addr) and PR (return addr)
    always @(posedge clk) begin
        if (!reset && cpu_pc == 32'h80224258) begin
            $display("[%0d] MEMSET_ENTRY: PC=%08x R4=%08x R5=%08x R6=%08x PR=%08x R15=%08x",
                     cycle_count, cpu_pc, cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.pr_rd, cpu.rf[15]);
        end
    end

    // Monitor for writes to the kernel code region that might corrupt it
    wire [31:0] write_addr_pa = to_physical(cpu.umem_write_addr_mux);
    always @(posedge clk) begin
        if (!reset && cpu.umem_write_enable) begin
            // Check if writing to the loop code region (0x157420-0x157440)
            if (write_addr_pa >= 32'h00157420 && write_addr_pa < 32'h00157440) begin
                $display("[%0d] CODE_WRITE: PC=%08x WADDR_VA=%08x WADDR_PA=%08x WDATA=%08x R15=%08x",
                         cycle_count, cpu_pc, cpu.umem_write_addr_mux, write_addr_pa,
                         cpu.umem_write_data_mux, cpu.rf[15]);
            end
            // Watchpoint: catch writes to physical 0x0002a8e8 (word 0x0000AA3A)
            // This is the address of raw_notifier_call_chain where INSTR=0x0000
            if (write_addr_pa >= 32'h0002a8e0 && write_addr_pa < 32'h0002a8f0) begin
                $display("[%0d] *** CODE_CORRUPT: PC=%08x WADDR_PA=%08x WDATA=%08x R15=%08x SR=%08x INSTR=%04x R4=%08x movl_ds_addr=%08x",
                         cycle_count, cpu_pc, write_addr_pa,
                         cpu.umem_write_data_mux, cpu.rf[15], cpu.sr_rd, cpu.instr,
                         cpu.rf[4], cpu.movl_disp_store_mmu_va);
            end
            // Broader watchpoint: catch writes anywhere in kernel text (0x00001000-0x0024f000)
            if (write_addr_pa >= 32'h00001000 && write_addr_pa < 32'h0024f000) begin
                $display("[%0d] KTEXT_WRITE: PC=%08x WADDR_PA=%08x WDATA=%08x R15=%08x SR=%08x",
                         cycle_count, cpu_pc, write_addr_pa,
                         cpu.umem_write_data_mux, cpu.rf[15], cpu.sr_rd);
            end
        end
    end

    // Periodic check of memory at raw_notifier_call_chain (word 0x0000AA3A)
    // Expected content: instruction 0x2f862f96
    reg [31:0] prev_mem_aa3a;
    always @(posedge clk) begin
        if (!reset) begin
            // Detect the exact cycle when memory changes
            if (cpu.umem[32'h0000AA3A] != prev_mem_aa3a && cycle_count > 100) begin
                $display("[%0d] *** MEM_AA3A_CHANGED: %08x -> %08x PC=%08x INSTR=%04x SR=%08x umem_we=%b waddr=%08x wdata=%08x",
                         cycle_count, prev_mem_aa3a, cpu.umem[32'h0000AA3A],
                         cpu_pc, cpu.instr, cpu.sr_rd,
                         cpu.umem_write_enable, cpu.umem_write_addr_mux, cpu.umem_write_data_mux);
            end
            prev_mem_aa3a <= cpu.umem[32'h0000AA3A];
        end
    end

    // =========================================================================
    // TTB Register Watchpoint (P4:0xFF000008 → umem word 0x00FFC002)
    // =========================================================================
    reg [31:0] prev_ttb_val;
    reg [31:0] ttb_write_count;
    // Register write signals to capture what happened in the previous cycle
    reg prev_we;
    reg [31:0] prev_waddr;
    reg [31:0] prev_wdata;
    reg [31:0] prev_pc;
    reg [15:0] prev_instr;
    initial begin
        prev_ttb_val = 0;
        ttb_write_count = 0;
    end
    always @(posedge clk) begin
        if (!reset) begin
            // Detect when TTB umem value changes - show PREVIOUS cycle's write signals
            if (cpu.umem[32'h00FFC002] != prev_ttb_val) begin
                ttb_write_count <= ttb_write_count + 1;
                $display("[%0d] TTB_CHANGE #%0d: %08x -> %08x prev_PC=%08x prev_INSTR=%04x prev_we=%b prev_waddr=%08x prev_wdata=%08x cur_PC=%08x cur_INSTR=%04x",
                         cycle_count, ttb_write_count, prev_ttb_val, cpu.umem[32'h00FFC002],
                         prev_pc, prev_instr, prev_we,
                         prev_waddr, prev_wdata,
                         cpu_pc, cpu.instr);
            end
            prev_ttb_val <= cpu.umem[32'h00FFC002];
            prev_we <= cpu.umem_write_enable;
            prev_waddr <= cpu.umem_write_addr_mux;
            prev_wdata <= cpu.umem_write_data_mux;
            prev_pc <= cpu_pc;
            prev_instr <= cpu.instr;

            // Direct watchpoint: log ANY write whose word address hits TTB
            // TTB is at byte addr 0x03FF0008, word addr 0x00FFC002
            if (cpu.umem_write_enable && ((cpu.umem_write_addr_mux >> 2) == 32'h00FFC002)) begin
                $display("[%0d] TTB_DIRECT_WRITE: PC=%08x INSTR=%04x waddr=%08x wdata=%08x",
                         cycle_count, cpu_pc, cpu.instr,
                         cpu.umem_write_addr_mux, cpu.umem_write_data_mux);
            end
            // Also check for unaligned writes that span into TTB word
            // A write to word addr N with unaligned access could write to N+1
            if (cpu.umem_write_enable && ((cpu.umem_write_addr_mux >> 2) == 32'h00FFC001) && (cpu.umem_write_addr_mux[1:0] != 2'b00)) begin
                $display("[%0d] TTB_UNALIGNED_WRITE: PC=%08x INSTR=%04x waddr=%08x wdata=%08x (spans into TTB word)",
                         cycle_count, cpu_pc, cpu.instr,
                         cpu.umem_write_addr_mux, cpu.umem_write_data_mux);
            end
        end
    end

    // =========================================================================
    // Debug: Trace mov.w (halfword) instructions during string copy
    // =========================================================================
    // Trace movw_postinc (MOV.W @Rm+,Rn - halfword load with post-increment)
    // Trace movw_indexed_store (MOV.W Rm,@(R0,Rn) - halfword store with indexed addressing)
    // Focus on cycles around when UART output starts (cycle ~200000+)
    reg movw_trace_enabled;
    reg [31:0] movw_trace_count;
    initial begin
        movw_trace_enabled = 0;
        movw_trace_count = 0;
    end

    always @(posedge clk) begin
        // NOTE: movw trace disabled - bugs it was debugging (indexed store collisions) are fixed
        // To re-enable: uncomment the condition below
        // if (!reset && store_enable && write_addr_phys == 32'h03F00104 && !movw_trace_enabled) begin
        //     movw_trace_enabled <= 1;
        //     $display("[%0d] MOVW_TRACE: Enabling halfword instruction tracing", cycle_count);
        // end

        // Trace movw_postinc (load halfword with post-increment)
        if (!reset && movw_trace_enabled && cpu.movw_postinc_enable && movw_trace_count < 500) begin
            $display("[%0d] MOVW_POSTINC: PC=%08x Rm[%d]=%08x -> Rn[%d] addr=%08x sign_ext=%08x",
                     cycle_count, cpu_pc,
                     cpu.instr[7:4],   // rm field
                     cpu.movw_postinc_Rm,
                     cpu.instr[11:8],  // rn field
                     cpu.movw_postinc_addr,
                     cpu.movw_postinc_sign_ext_data);
            movw_trace_count <= movw_trace_count + 1;
        end

        // Trace movw_indexed_store (store halfword with indexed addressing)
        if (!reset && movw_trace_enabled && cpu.movw_indexed_store_enable && movw_trace_count < 500) begin
            $display("[%0d] MOVW_IDX_STORE: PC=%08x Rm[%d]=%08x R0=%08x Rn[%d]=%08x -> addr=%08x",
                     cycle_count, cpu_pc,
                     cpu.instr[7:4],   // rm field (source data)
                     cpu.movw_indexed_store_Rm,
                     cpu.movw_indexed_store_r0,
                     cpu.instr[11:8],  // rn field
                     cpu.movw_indexed_store_Rn,
                     cpu.movw_indexed_store_store_addr);
            // Show byte enables and positioned data
            $display("         data16=%04x pos_data=%08x be=%04b be_inv_sel=%b addr[1]=%b",
                     cpu.movw_indexed_store_halfword_data,
                     cpu.movw_indexed_store_positioned_data,
                     cpu.movw_indexed_store_byte_enable,
                     cpu.movw_indexed_store_be_inverted_selector,
                     cpu.movw_indexed_store_store_addr[1]);
            // Show memory before/after
            $display("         mem_before=%08x",
                     cpu.umem[(cpu.movw_indexed_store_store_addr & 32'h1FFFFFFF) >> 2]);
            movw_trace_count <= movw_trace_count + 1;
        end

        // Also trace movw_store (MOV.W Rm,@Rn - simple halfword store)
        if (!reset && movw_trace_enabled && cpu.movw_store_enable && movw_trace_count < 500) begin
            $display("[%0d] MOVW_STORE: PC=%08x Rm[%d]=%08x -> Rn[%d]=@%08x",
                     cycle_count, cpu_pc,
                     cpu.instr[7:4],   // rm field
                     cpu.rf[cpu.instr[7:4]],
                     cpu.instr[11:8],  // rn field
                     cpu.movw_store_Rn);
            movw_trace_count <= movw_trace_count + 1;
        end

        // Trace ALL instructions in the halfword copy loop (PC=801e61da-801e61e4)
        if (!reset && movw_trace_enabled && movw_trace_count < 500 &&
            cpu_pc >= 32'h801e61da && cpu_pc <= 32'h801e61e4) begin
            $display("[%0d] COPY_LOOP: PC=%08x INSTR=%04x R0=%08x R1=%08x R4=%08x SR=%08x RB=%b rf_we=%b rf_addr=%d rf_data=%08x",
                     cycle_count, cpu_pc, cpu.instr, cpu.rf[0], cpu.rf[1], cpu.rf[4],
                     cpu.sr_rd, cpu.sr_rd[29],
                     cpu.rf_write_enable, cpu.rf_write_addr_mux, cpu.rf_write_data_mux);
        end

        // Detect any writes to R4 during the copy loop
        if (!reset && movw_trace_enabled && movw_trace_count < 500 && cpu.rf_write_enable && cpu.rf_write_addr_mux == 4) begin
            $display("[%0d] *** R4_WRITE: PC=%08x INSTR=%04x data=%08x ***",
                     cycle_count, cpu_pc, cpu.instr, cpu.rf_write_data_mux);
            // Trace enable signals for debugging
            $display("         movw_idx_st_en=%b movw_idx_en=%b movb_idx_st_en=%b movl_idx_st_en=%b",
                     cpu.movw_indexed_store_enable, cpu.movw_indexed_enable,
                     cpu.movb_indexed_store_enable, cpu.movl_indexed_store_enable);
            $display("         instr_15_12=%x instr_3_0=%x",
                     cpu.instr[15:12], cpu.instr[3:0]);
            // Check if movw_indexed (load) guarded enable is true when it shouldn't be
            if (cpu.instr[3:0] == 4'h5) begin
                $display("         *** BUG: rf_write_enable=1 for store instruction (instr[3:0]=5) ***");
                // Trace which specific guarded enables might be true
                $display("         movw_idx_en=%b rf_movw_idx_guard=%b",
                         cpu.movw_indexed_enable,
                         cpu.rf_invint_should_take_and_invitlb_exc_actually_taken_and_movw_indexed_no_error_and_movw_indexed_rn_bk_eq_0_and_data_tlb_no_exception_guarded_enable);
                $display("         movw_no_err=%b movw_rn_bk=%b movw_idx_no_err=%b movw_idx_rn_bk=%b",
                         cpu.movw_no_error, cpu.movw_rn_bk,
                         cpu.movw_indexed_no_error, cpu.movw_indexed_rn_bk);
                // Check if movw (simple load) guard is enabled
                $display("         movw_en=%b",
                         cpu.movw_enable);
                // Check first few terms of rf_write_enable
                $display("         div1_en=%b add_en=%b addc_en=%b",
                         cpu.div1_enable, cpu.add_enable, cpu.addc_enable);
                // Check exc_taken as it might disable things
                $display("         exc_taken=%b movw_idx_st_no_err=%b",
                         cpu.movw_indexed_store_exc_taken,
                         cpu.movw_indexed_store_no_error);
                // Check secondary write port
                $display("         rf_we_1=%b rf_addr_1=%d rf_data_1=%08x",
                         cpu.rf_write_enable_1, cpu.rf_write_addr_mux_1, cpu.rf_write_data_mux_1);
            end
        end

        // Trace R8 changes during earlycon output to find string pointer corruption
        if (!reset && cycle_count >= 96350 && cycle_count <= 96550) begin
            $display("[%0d] EARLYCON_TRACE: PC=%08x INSTR=%04x R8=%08x R9=%08x R0=%08x R5=%08x PR=%08x rf_we=%b rf_wa=%0d rf_wd=%08x rf_we1=%b rf_wa1=%0d rf_wd1=%08x",
                     cycle_count, cpu_pc, cpu.instr, cpu.rf[8], cpu.rf[9], cpu.rf[0], cpu.rf[5],
                     cpu.pr_rd, cpu.rf_write_enable, cpu.rf_write_addr_mux, cpu.rf_write_data_mux,
                     cpu.rf_write_enable_1, cpu.rf_write_addr_mux_1, cpu.rf_write_data_mux_1);
            // When movb_postinc is active, dump memory details
            if (cpu.movb_postinc_enable) begin
                $display("  MOVB_POSTINC: Rm=%08x movb_en=%b movw_en=%b fmov_en=%b",
                         cpu.movb_postinc_Rm,
                         cpu.movb_enable, cpu.movw_enable, cpu.fmov_load_enable);
            end
        end
        // Watch for writes to the string region (physical 0x00328bb8 = word 0x000CA2EE)
        if (!reset && cpu.umem_write_enable && cycle_count < 96550) begin
            if ((cpu.umem_write_addr_mux & 32'h1FFFFFFF) >= 32'h00328bb0 &&
                (cpu.umem_write_addr_mux & 32'h1FFFFFFF) < 32'h00328bc0) begin
                $display("[%0d] STRING_WRITE: PC=%08x WADDR=%08x WDATA=%08x",
                         cycle_count, cpu_pc, cpu.umem_write_addr_mux, cpu.umem_write_data_mux);
            end
            // Watch for writes to the SOURCE string (0x8024c060 -> phys 0x0024c060)
            if ((cpu.umem_write_addr_mux & 32'h1FFFFFFF) >= 32'h0024c060 &&
                (cpu.umem_write_addr_mux & 32'h1FFFFFFF) < 32'h0024c080) begin
                $display("[%0d] SRC_WRITE: PC=%08x WADDR=%08x WDATA=%08x INSTR=%04x",
                         cycle_count, cpu_pc, cpu.umem_write_addr_mux, cpu.umem_write_data_mux, cpu.instr);
            end
        end
        // Dump source memory contents periodically to see when it gets corrupted
        if (!reset && (cycle_count == 100 || cycle_count == 10000 || cycle_count == 50000 || cycle_count == 64821 || cycle_count == 67105 || cycle_count == 67106 || cycle_count == 90000 || cycle_count == 94000 || cycle_count == 94500 || cycle_count == 94800)) begin
            $display("[%0d] SRC_MEM_CHECK: word[0x93018]=%08x word[0x93019]=%08x (expect 4c696e75 78207665)",
                     cycle_count, cpu.umem[32'h93018], cpu.umem[32'h93019]);
            // Also check the intermediate buffer at 0x80328ff8 (word 0xCA3FE)
            $display("[%0d] BUF_MEM_CHECK: word[0xCA3FE]=%08x word[0xCA3FF]=%08x (0x80328ff8)",
                     cycle_count, cpu.umem[32'hCA3FE], cpu.umem[32'hCA3FF]);
        end
        // Watch for writes to the intermediate buffer at 0x80328ff8
        if (!reset && cpu.umem_write_enable && cycle_count < 96550) begin
            if ((cpu.umem_write_addr_mux & 32'h1FFFFFFF) >= 32'h00328ff0 &&
                (cpu.umem_write_addr_mux & 32'h1FFFFFFF) < 32'h00329010) begin
                $display("[%0d] BUF_WRITE: PC=%08x WADDR=%08x WDATA=%08x INSTR=%04x",
                         cycle_count, cpu_pc, cpu.umem_write_addr_mux, cpu.umem_write_data_mux, cpu.instr);
            end
        end
        // Trace movw_indexed_store at cycle 67100-67110 to see byte enables
        if (!reset && cycle_count >= 67095 && cycle_count <= 67115) begin
            $display("[%0d] COPY_TRACE: PC=%08x INSTR=%04x R0=%08x R1=%08x R4=%08x R5=%08x rf_we=%b rf_wa=%0d rf_wd=%08x rf_we1=%b rf_wa1=%0d rf_wd1=%08x",
                     cycle_count, cpu_pc, cpu.instr, cpu.rf[0], cpu.rf[1], cpu.rf[4], cpu.rf[5],
                     cpu.rf_write_enable, cpu.rf_write_addr_mux, cpu.rf_write_data_mux,
                     cpu.rf_write_enable_1, cpu.rf_write_addr_mux_1, cpu.rf_write_data_mux_1);
            if (cpu.movw_indexed_store_enable) begin
                $display("  MOVW_IDX_ST: store_addr=%08x halfword=%04x be=%04b pos_data=%08x be_inv_sel=%b addr[1]=%b",
                         cpu.movw_indexed_store_store_addr,
                         cpu.movw_indexed_store_halfword_data,
                         cpu.movw_indexed_store_byte_enable,
                         cpu.movw_indexed_store_positioned_data,
                         cpu.movw_indexed_store_byte_enable_be_inv_sel,
                         cpu.movw_indexed_store_store_addr[1]);
            end
            if (cpu.movw_postinc_enable) begin
                $display("  MOVW_POSTINC: addr=%08x data16=%04x sign_ext=%08x addr[1]=%b",
                         cpu.movw_postinc_addr, cpu.data16,
                         cpu.movw_postinc_sign_ext_data, cpu.movw_postinc_addr[1]);
            end
        end
        // Trace the memcpy inner loop that copies the Linux version string
        // PC 0x80223136-0x80223140 is the inner loop of memcpy
        if (!reset && cpu_pc >= 32'h80223136 && cpu_pc <= 32'h80223142 && cycle_count >= 94700 && cycle_count <= 94800) begin
            $display("[%0d] MEMCPY: PC=%08x INSTR=%04x R0=%08x R2=%08x R3=%08x R5=%08x R6=%08x R7=%08x",
                     cycle_count, cpu_pc, cpu.instr, cpu.rf[0], cpu.rf[2], cpu.rf[3], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
            // When movl_indexed executes, show the load address and data
            if (cpu.movl_indexed_enable) begin
                $display("  MOVL_IDX_LOAD: load_addr=%08x data32=%08x",
                         cpu.movl_indexed_load_addr, cpu.movl_indexed_data32);
            end
        end
    end

    // Trace stack pointer during exception handling to detect stack overflow
    reg [31:0] last_r15;
    reg [31:0] min_r15;
    reg [31:0] rte_count;
    always @(posedge clk) begin
        if (!reset) begin
            // Track minimum stack pointer value
            if (cpu.rf[15] < min_r15 && cpu.rf[15] >= 32'h80100000 && cpu.rf[15] < 32'h80300000) begin
                // Report every 0x10000 (64KB) descent
                if ((min_r15 >> 16) != (cpu.rf[15] >> 16)) begin
                    $display("[%0d] STACK_DESCENT: PC=%08x R15=%08x (was %08x)",
                             cycle_count, cpu_pc, cpu.rf[15], min_r15);
                end
                min_r15 <= cpu.rf[15];
            end
            // Trace when stack descends past kernel code region
            if (cpu.rf[15] < 32'h80158000 && cpu.rf[15] >= 32'h80100000 &&
                (last_r15 >= 32'h80158000 || last_r15 < 32'h80100000)) begin
                $display("[%0d] STACK_LOW: PC=%08x R15=%08x->%08x SR=%08x",
                         cycle_count, cpu_pc, last_r15, cpu.rf[15], cpu.sr_rd);
            end
            last_r15 <= cpu.rf[15];

            // Trace RTE instruction execution
            if (cpu.rte_enable && !cpu.in_delay_slot_eq_1) begin
                rte_count <= rte_count + 1;
                if (rte_count < 20 || (rte_count % 1000 == 0)) begin
                    $display("[%0d] RTE #%0d: PC=%08x delay=%b SSR=%08x SPC=%08x R15=%08x",
                             cycle_count, rte_count, cpu_pc, cpu.delay_slot,
                             cpu.ssr_rd, cpu.spc_rd, cpu.rf[15]);
                end
            end
        end else begin
            min_r15 <= 32'hFFFFFFFF;
            rte_count <= 0;
        end
    end

    // =========================================================================
    // Debug: trace crash area around 0x800d9360
    // =========================================================================
    // Track when rf[7] changes (bank0 R7 used for current thread_info)
    reg [31:0] prev_rf7;
    always @(posedge clk) begin
        prev_rf7 <= cpu.rf[7];
        if (!reset && cpu.rf[7] != prev_rf7 && cycle_count > 1000 && cycle_count < 200000) begin
            $display("[%0d] RF[7] CHANGED: PC=%08x prev=%08x new=%08x",
                     cycle_count, cpu_pc, prev_rf7, cpu.rf[7]);
        end
    end

    // Track when R4_BK changes to the suspicious value
    reg [31:0] prev_r4_bk;
    always @(posedge clk) begin
        prev_r4_bk <= cpu.rf_bank[4];
        // Detect when R4_BK becomes 0xe14f2012
        if (!reset && cpu.rf_bank[4] == 32'he14f2012 && prev_r4_bk != 32'he14f2012) begin
            $display("[%0d] R4_BK CHANGED TO e14f2012: PC=%08x INSTR=%04x prev=%08x R15=%08x PR=%08x",
                     cycle_count, cpu_pc, cpu.instr, prev_r4_bk, cpu.rf[15], cpu.pr_rd);
        end
        // Trace R8 writes - detect when R8 gets value 0x00000001 (corruption)
        if (!reset && cpu.rf_write_enable && cpu.rf_write_addr_mux == 8) begin
            if (cpu.rf_write_data_mux == 32'h00000001) begin
                $display("[%0d] R8_CORRUPT_WRITE: PC=%08x INSTR=%04x data=00000001 R15=%08x PR=%08x delay=%b int_take=%b",
                         cycle_count, cpu_pc, cpu.instr, cpu.rf[15], cpu.pr_rd, cpu.delay_slot, cpu.int_should_take);
                $display("  movl_pi_en=%b movl_pi_no_err=%b rn_bk=%b Rm=%08x data32=%08x",
                         cpu.movl_postinc_enable, cpu.movl_pi_no_error, cpu.movl_pi_rn_bk,
                         cpu.movl_postinc_Rm, cpu.movl_postinc_data32);
            end
        end
        // Also trace when R8 write is attempted by movl_postinc in delay slot
        if (!reset && cpu.movl_postinc_enable && cpu.delay_slot &&
            cpu.instr[11:8] == 4'h8) begin
            $display("[%0d] MOVL_PI_DELAY_R8: PC=%08x INSTR=%04x R8=%08x R15=%08x Rm=%08x data32=%08x",
                     cycle_count, cpu_pc, cpu.instr, cpu.rf[8], cpu.rf[15],
                     cpu.movl_postinc_Rm, cpu.movl_postinc_data32);
            $display("  rf_we=%b rf_wa=%0d rf_wd=%08x no_err=%b rn_bk=%b int_take=%b",
                     cpu.rf_write_enable, cpu.rf_write_addr_mux, cpu.rf_write_data_mux,
                     cpu.movl_pi_no_error, cpu.movl_pi_rn_bk,
                     cpu.int_should_take);
        end
        // Trace register_leaf_sysctl_tables entry/exit
        if (!reset && cpu_pc == 32'h8011b178) begin
            $display("[%0d] SYSCTL_ENTRY: R5(path)=%08x R8=%08x R15=%08x PR=%08x",
                     cycle_count, cpu.rf[5], cpu.rf[8], cpu.rf[15], cpu.pr_rd);
        end
        // Trace crash PC
        if (!reset && cpu_pc == 32'h8011b2b4) begin
            $display("[%0d] SYSCTL_CRASH_PC: R8=%08x R10=%08x R15=%08x PR=%08x delay=%b",
                     cycle_count, cpu.rf[8], cpu.rf[10], cpu.rf[15], cpu.pr_rd, cpu.delay_slot);
        end
        // Trace RTS in sysctl function (0x8011b268 and 0x8011b2e4)
        if (!reset && (cpu_pc == 32'h8011b268 || cpu_pc == 32'h8011b2e4)) begin
            $display("[%0d] SYSCTL_RTS: PC=%08x R8=%08x R15=%08x PR=%08x delay=%b",
                     cycle_count, cpu_pc, cpu.rf[8], cpu.rf[15], cpu.pr_rd, cpu.delay_slot);
        end
        // Trace delay slot instruction after RTS (0x8011b26a and 0x8011b2e6 = mov.l @r15+,r8)
        if (!reset && (cpu_pc == 32'h8011b26a || cpu_pc == 32'h8011b2e6)) begin
            $display("[%0d] SYSCTL_RTS_DS: PC=%08x R8=%08x R15=%08x PR=%08x delay=%b INSTR=%04x",
                     cycle_count, cpu_pc, cpu.rf[8], cpu.rf[15], cpu.pr_rd, cpu.delay_slot, cpu.instr);
        end
        // Trace movl_disp_load memory access at path_put (PC=800cd4ba)
        if (!reset && cpu_pc == 32'h800cd4ba) begin
            $display("[%0d] MOVL_DISP_LOAD at path_put: addr=%08x data32=%08x Rm=%08x",
                     cycle_count, cpu.movl_disp_load_mmu_va,
                     cpu.movl_disp_load_data32, cpu.movl_disp_load_Rm);
        end
        // Trace movl_disp_load at 0x800f113e (loads fs_struct.pwd.dentry)
        if (!reset && cpu_pc == 32'h800f113e) begin
            $display("[%0d] MOVL_DISP_LOAD at set_fs_pwd(fs->pwd.dentry): addr=%08x data32=%08x Rm=%08x",
                     cycle_count, cpu.movl_disp_load_mmu_va,
                     cpu.movl_disp_load_data32, cpu.movl_disp_load_Rm);
        end
        // Trace set_fs_pwd entry to see what R4/R8 values are
        if (!reset && cpu_pc >= 32'h800f1114 && cpu_pc <= 32'h800f1145) begin
            $display("[%0d] SET_FS_PWD: PC=%08x R4_BK=%08x R4=%08x R8=%08x R15=%08x SR=%08x RB=%b",
                     cycle_count, cpu_pc, cpu.rf_bank[4], cpu.rf[4], cpu.rf[8], cpu.rf[15], cpu.sr_rd, cpu.sr_rd[29]);
        end
        // Trace mnt_init before set_fs_pwd call - watch R7_BANK and R1/R4
        // When RB=1: kernel R0-R7 = rf_bank[], R8-R15 = rf[]
        // stc r7_bank reads from rf[7] (opposite bank), stores to rf_bank[1] (current bank R1)
        // When RB=0: kernel R0-R7 = rf[], stc r7_bank reads from rf_bank[7]
        if (!reset && cpu_pc >= 32'h803044d0 && cpu_pc <= 32'h803044f2) begin
            $display("[%0d] MNT_INIT: PC=%08x SR=%08x RB=%b INSTR=%04x rf7=%08x rf_bank7=%08x",
                     cycle_count, cpu_pc, cpu.sr_rd, cpu.sr_rd[29], cpu.instr, cpu.rf[7], cpu.rf_bank[7]);
        end
    end

    // Trace memory writes to the stack region 0x00279f4c-0x00279f54
    always @(posedge clk) begin
        // Check movl_predec (push) writes
        if (!reset && cpu.movl_predec_enable && cpu.movl_pd_no_error) begin
            if ((cpu.movl_predec_mmu_va & 32'h1FFFFFFF) >= 32'h00279f40 && (cpu.movl_predec_mmu_va & 32'h1FFFFFFF) <= 32'h00279f60) begin
                $display("[%0d] MOVL_PREDEC WRITE: addr=%08x data=%08x PC=%08x",
                         cycle_count, cpu.movl_predec_mmu_va,
                         cpu.movl_predec_Rm, cpu_pc);
            end
        end
        // Check movl_disp_store writes
        if (!reset && cpu.movl_disp_store_enable && cpu.movl_disp_store_no_error) begin
            if ((cpu.movl_disp_store_mmu_va & 32'h1FFFFFFF) >= 32'h00279f40 && (cpu.movl_disp_store_mmu_va & 32'h1FFFFFFF) <= 32'h00279f60) begin
                $display("[%0d] MOVL_DISP_STORE WRITE: addr=%08x data=%08x PC=%08x",
                         cycle_count, cpu.movl_disp_store_mmu_va,
                         cpu.movl_disp_store_Rm, cpu_pc);
            end
        end
        // Check movl_store writes
        if (!reset && cpu.movl_store_enable && cpu.movl_st_no_error) begin
            if ((cpu.movl_store_store_addr & 32'h1FFFFFFF) >= 32'h00279f40 && (cpu.movl_store_store_addr & 32'h1FFFFFFF) <= 32'h00279f60) begin
                $display("[%0d] MOVL_STORE WRITE: addr=%08x data=%08x PC=%08x",
                         cycle_count, cpu.movl_store_store_addr,
                         cpu.movl_store_Rm, cpu_pc);
            end
        end
    end

    // =========================================================================
    // MMU Debug - trace TLB misses and exceptions
    // =========================================================================
    wire mmu_enabled = cpu.mmucr_rd[0];
    wire [31:0] cpu_pc = cpu.pc;

    // Track PC region
    wire [2:0] pc_region = cpu_pc[31:29];
    wire pc_is_p0 = (cpu_pc[31] == 1'b0);

    wire pc_is_p1 = (pc_region == 3'b100);
    wire pc_is_p2 = (pc_region == 3'b101);
    wire pc_is_p3 = (pc_region == 3'b110);
    wire pc_is_p4 = (pc_region == 3'b111);

    reg [2:0] last_pc_region;
    always @(posedge clk) begin
        if (!reset && last_pc_region != pc_region && cycle_count > 100) begin
            $display("[%0d] PC REGION CHANGE: %s -> %s (PC=%08x MMU=%b)",
                     cycle_count,
                     last_pc_region == 3'b000 ? "P0" :
                     last_pc_region == 3'b100 ? "P1" :
                     last_pc_region == 3'b101 ? "P2" :
                     last_pc_region == 3'b110 ? "P3" : "P4",
                     pc_region == 3'b000 ? "P0" :
                     pc_region == 3'b100 ? "P1" :
                     pc_region == 3'b101 ? "P2" :
                     pc_region == 3'b110 ? "P3" : "P4",
                     cpu_pc, mmu_enabled);
            last_pc_region <= pc_region;
        end
    end

    // =========================================================================
    // Track SR.RB changes - critical for register banking debugging
    // =========================================================================
    reg prev_sr_rb;
    always @(posedge clk) begin
        if (!reset && cycle_count > 100) begin
            if (cpu.sr_rd[29] != prev_sr_rb) begin
                $display("[%0d] SR.RB CHANGED: %b -> %b PC=%08x SR=%08x INSTR=%04x",
                         cycle_count, prev_sr_rb, cpu.sr_rd[29], cpu_pc, cpu.sr_rd, cpu.instr);
            end
            prev_sr_rb <= cpu.sr_rd[29];
        end
    end

    // Trace ldc_sr executions (bank switch diagnostic) - limited to early boot
    always @(posedge clk) begin
        if (!reset && cpu.ldc_sr_enable && cpu.ldc_sr_no_gated_cond && cycle_count < 200000) begin
            $display("[%0d] LDC_SR: PC=%08x new_SR=%08x (RB=%b BL=%b) curr_SR=%08x INSTR=%04x R8=%08x",
                     cycle_count, cpu_pc, {cpu.ldc_sr_Rm[31:1], 1'b0}, cpu.ldc_sr_Rm[29], cpu.ldc_sr_Rm[28],
                     cpu.sr_rd, cpu.instr, cpu.rf[8]);
        end
        // Also trace when ldc_sr is GATED (blocked by interrupt/exception)
        if (!reset && cpu.ldc_sr_enable && !cpu.ldc_sr_no_gated_cond && cycle_count < 200000) begin
            $display("[%0d] LDC_SR_GATED: PC=%08x INSTR=%04x curr_SR=%08x int_take=%b",
                     cycle_count, cpu_pc, cpu.instr, cpu.sr_rd,
                     cpu.int_should_take_mux);
        end
    end

    // Trace exception handler entry and key points
    always @(posedge clk) begin
        if (!reset) begin
            // general_exception at 0x80007100
            if (cpu_pc == 32'h80007100) begin
                $display("[%0d] GENERAL_EXCEPTION: PC=%08x SR=%08x (RB=%b BL=%b) EXPEVT=%08x",
                         cycle_count, cpu_pc, cpu.sr_rd, cpu.sr_rd[29], cpu.sr_rd[28], cpu.expevt_rd);
            end
            // handle_exception at 0x80007402
            if (cpu_pc == 32'h80007402) begin
                $display("[%0d] HANDLE_EXCEPTION: PC=%08x SR=%08x EXPEVT=%08x",
                         cycle_count, cpu_pc, cpu.sr_rd, cpu.expevt_rd);
            end
            // save_low_regs at 0x80007444
            if (cpu_pc == 32'h80007444) begin
                $display("[%0d] SAVE_LOW_REGS: PC=%08x SR=%08x (RB=%b BL=%b) R8=%08x",
                         cycle_count, cpu_pc, cpu.sr_rd, cpu.sr_rd[29], cpu.sr_rd[28], cpu.rf[8]);
            end
            // handle_interrupt at VBR+0x600 = 0x80007600
            if (cpu_pc == 32'h80007600) begin
                $display("[%0d] HANDLE_INTERRUPT: PC=%08x SR=%08x INTEVT=%08x",
                         cycle_count, cpu_pc, cpu.sr_rd, cpu.intevt_rd);
            end
            // RTE instruction
            if (cpu.rte_enable && !cpu.in_delay_slot_eq_1) begin
                $display("[%0d] RTE: PC=%08x SSR=%08x (RB=%b BL=%b) SPC=%08x curr_SR=%08x",
                         cycle_count, cpu_pc, cpu.ssr_rd, cpu.ssr_rd[29], cpu.ssr_rd[28],
                         cpu.spc_rd, cpu.sr_rd);
            end
            // TRAPA instruction
            if (cpu.trapa_enable) begin
                $display("[%0d] TRAPA: PC=%08x INSTR=%04x exc_taken=%b BL=%b SR=%08x VBR=%08x R4=%08x R9=%08x PR=%08x",
                         cycle_count, cpu_pc, cpu.instr, cpu.trapa_exc_taken, cpu.sr_rd[28],
                         cpu.sr_rd, cpu.vbr, cpu.rf[4], cpu.rf[9], cpu.pr_rd);
            end
        end
    end

    // =========================================================================
    // Reset Logic and Simulation Control
    // =========================================================================
    integer cycle_count;
    reg [31:0] last_pc;
    reg [31:0] stuck_pc_count;
    reg initialized;

    // PC history for debugging
    reg [31:0] pc_history [0:15];
    integer history_idx = 0;

    always @(posedge clk) begin
        if (!initialized) begin
            reset <= 1'b1;
            reset_counter <= 8'd10;
            cycle_count <= 0;
            initialized <= 1'b1;
            last_pc_region <= 3'b101;  // Start in P2
            $display("DEBUG: First clock edge, initializing");
            $fflush();
        end else if (reset_counter > 0) begin
            reset_counter <= reset_counter - 1;
            $display("DEBUG: reset_counter=%0d", reset_counter);
            $fflush();
            if (reset_counter == 1) begin
                reset <= 1'b0;
                $display("");
                $display("=== J4 SH4 MMU Linux Boot Started ===");
                $display("CPU starting at P2 address: 0x%08x", entry_point);
                $fflush();
            end
        end else begin
            // Print first 20 cycles with R7_BANK and rf_bank write signals trace
            if (cycle_count < 20) begin
                $display("[%0d] PC=%08x SR=%08x R7_BANK=%08x WE=%b ADDR=%d DATA=%08x",
                         cycle_count, cpu_pc, cpu.sr_rd, cpu.rf_bank[7],
                         cpu.rf_bank_write_enable, cpu.rf_bank_write_addr_mux, cpu.rf_bank_write_data_mux);
                $fflush();
            end
            // Track when rf_bank[7] VALUE changes (detect corruption)
            if (cpu.rf_bank[7] != prev_rf_bank7) begin
                $display("[%0d] RF_BANK7_CHANGE: %08x -> %08x PC=%08x INSTR=%04x SR=%08x RB=%b rf[7]=%08x we=%b wa=%d wd=%08x",
                         cycle_count, prev_rf_bank7, cpu.rf_bank[7], cpu_pc, cpu.instr, cpu.sr_rd, cpu.sr_rd[29],
                         cpu.rf[7], cpu.rf_bank_write_enable, cpu.rf_bank_write_addr_mux, cpu.rf_bank_write_data_mux);
            end
            prev_rf_bank7 <= cpu.rf_bank[7];
            // Trace kernel entry point execution (0x80002000-0x80002050), but skip BSS loop (0x80002018-0x8000201f)
            if (cpu_pc >= 32'h80002000 && cpu_pc < 32'h80002050 &&
                (cpu_pc < 32'h80002018 || cpu_pc >= 32'h80002020)) begin
                $display("[%0d] KERNEL_ENTRY: PC=%08x INSTR=%04x SR=%08x R0=%08x R15=%08x R7_BK=%08x",
                         cycle_count, cpu_pc, cpu.instr, cpu.sr_rd, cpu.rf[0], cpu.rf[15], cpu.rf_bank[7]);
            end
            // Trace bootrom execution (P2: 0xA0000000-0xA0000080)
            if (cpu_pc >= 32'hA0000000 && cpu_pc < 32'hA0000080) begin
                $display("[%0d] BOOTROM: PC=%08x INSTR=%04x SR=%08x R0=%08x R1=%08x R7_BK=%08x",
                         cycle_count, cpu_pc, cpu.instr, cpu.sr_rd, cpu.rf[0], cpu.rf[1], cpu.rf_bank[7]);
            end
            // Track when rf[7] changes (bank0's R7) - includes ldc R0,R7_BANK when RB=1
            if (cpu.rf_write_enable && cpu.rf_write_addr_mux == 7 && cycle_count < 200000) begin
                $display("[%0d] RF[7] WRITE: PC=%08x SR=%08x RB=%b DATA=%08x prev=%08x rf_bank[7]=%08x",
                         cycle_count, cpu_pc, cpu.sr_rd, cpu.sr_rd[28],
                         cpu.rf_write_data_mux, cpu.rf[7], cpu.rf_bank[7]);
            end
            // =========================================================
            // Debug: Track user-space TLB miss handling path
            // =========================================================
            // TLB miss handler entry when TEA is a user-space address
            if (cpu_pc == 32'h80007400 && cpu.tea_rd[31] == 1'b0 && cpu.tea_rd != 0) begin
                $display("[%0d] U0_TLB_MISS: PC=%08x SSR=%08x SPC=%08x SR=%08x EXPEVT=%08x TEA=%08x R15=%08x",
                         cycle_count, cpu_pc, cpu.ssr_rd, cpu.spc_rd, cpu.sr_rd, cpu.expevt_rd, cpu.tea_rd, cpu.rf[15]);
                $fflush();
            end
            // ret_from_irq - check saved SR on stack (offset 72 = SSR)
            if (cpu_pc == 32'h800060ec) begin
                $display("[%0d] RET_FROM_IRQ: R15=%08x saved_SR=%08x MD=%b SSR=%08x EXPEVT=%08x",
                         cycle_count, cpu.rf[15],
                         cpu.umem[(cpu.rf[15] + 72) >> 2],
                         cpu.umem[(cpu.rf[15] + 72) >> 2] & 32'h40000000 ? 1'b1 : 1'b0,
                         cpu.ssr_rd, cpu.expevt_rd);
                $fflush();
            end
            // resume_userspace entry (MD=0 detected)
            if (cpu_pc == 32'h800060f8) begin
                $display("[%0d] RESUME_USPACE: R15=%08x saved_SR=%08x",
                         cycle_count, cpu.rf[15], cpu.umem[(cpu.rf[15] + 72) >> 2]);
                $fflush();
            end
            // bad_area_nosemaphore
            if (cpu_pc == 32'h8000cd24) begin
                $display("[%0d] BAD_AREA: regs=%08x write=%08x addr=%08x saved_SR=%08x",
                         cycle_count, cpu.rf[4], cpu.rf[5], cpu.rf[6],
                         cpu.umem[(cpu.rf[4] + 72) >> 2]);
                $fflush();
            end
            // do_page_fault entry
            if (cpu_pc == 32'h8000cee4) begin
                $display("[%0d] DO_PAGE_FAULT: regs=%08x write=%08x addr=%08x",
                         cycle_count, cpu.rf[4], cpu.rf[5], cpu.rf[6]);
                $fflush();
            end
            // handle_tlbmiss entry
            if (cpu_pc == 32'h8000d254) begin
                $display("[%0d] HANDLE_TLBMISS: regs=%08x write=%08x addr=%08x",
                         cycle_count, cpu.rf[4], cpu.rf[5], cpu.rf[6]);
                $fflush();
            end
            // force_sig_fault (SIGSEGV delivery)
            if (cpu_pc == 32'h8000cd36) begin
                $display("[%0d] FORCE_SIG_FAULT: SIGSEGV for user addr", cycle_count);
                $fflush();
            end

            cycle_count <= cycle_count + 1;
            last_pc <= cpu_pc;

            // Record PC history
            if (cycle_count > 10) begin
                pc_history[history_idx] <= cpu_pc;
                history_idx <= (history_idx + 1) & 15;
            end

            // Detect PC jumping beyond kernel _end (0x8033f3bc) into unmapped region
            // Kernel text: 0x80001000-0x8024f91c, init: up to 0x8032d000, total up to 0x8033f3bc
            // Exception vectors at VBR+offset are OK (VBR typically 0x80002000)
            // P2 bootrom at 0xA0000000 is OK
            if (cpu_pc >= 32'h80400000 && cpu_pc < 32'hA0000000 && cycle_count > 1000) begin
                $display("");
                $display("*** PC OUTSIDE KERNEL at cycle %0d ***", cycle_count);
                $display("  PC=0x%08x SR=0x%08x R15=0x%08x", cpu_pc, cpu.sr_rd, cpu.rf[15]);
                $display("  PR=0x%08x VBR=0x%08x MMUCR=0x%08x", cpu.pr_rd, cpu.vbr, cpu.mmucr_rd);
                $display("  R0=%08x R1=%08x R2=%08x R3=%08x", cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3]);
                $display("  R4=%08x R5=%08x R6=%08x R7=%08x", cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
                $display("  R8=%08x R9=%08x R10=%08x R11=%08x", cpu.rf[8], cpu.rf[9], cpu.rf[10], cpu.rf[11]);
                $display("  R12=%08x R13=%08x R14=%08x", cpu.rf[12], cpu.rf[13], cpu.rf[14]);
                $display("  PC History:");
                for (int h = 0; h < 16; h++) begin
                    int idx = (history_idx - 16 + h) & 15;
                    $display("    [%2d] PC=%08x", h, pc_history[idx]);
                end
                $finish;
            end

            // Detect unexpected PC values
            if (last_pc > 32'h1000 && cpu_pc < 32'h1000 && cycle_count > 1000) begin
                $display("");
                $display("*** PC WENT TO LOW ADDRESS at cycle %0d ***", cycle_count);
                $display("  Before: PC=0x%08x", last_pc);
                $display("  After:  PC=0x%08x SR=0x%08x MMUCR=0x%08x", cpu_pc, cpu.sr_rd, cpu.mmucr_rd);
                $display("  PC History:");
                for (int h = 0; h < 16; h++) begin
                    int idx = (history_idx - 16 + h) & 15;
                    $display("    [%2d] PC=%08x", h, pc_history[idx]);
                end
                $finish;
            end

            // Progress report - every 1M cycles for first 100M, then every 16M
            if ((cycle_count[19:0] == 0 && cycle_count > 0 && cycle_count < 100000000) ||
                (cycle_count[23:0] == 0 && cycle_count > 0)) begin
                $display("[%0d] PROGRESS: PC=%08x R15=%08x SR=%08x MMUCR=%08x",
                         cycle_count, cpu_pc, cpu.rf[15], cpu.sr_rd, cpu.mmucr_rd);
                $fflush();
            end

            // Detect stuck PC (same PC for 200 consecutive cycles)
            if (cpu_pc == last_pc && cycle_count > 10000) begin
                stuck_pc_count <= stuck_pc_count + 1;
                if (stuck_pc_count == 200) begin
                    $display("");
                    $display("*** PC STUCK for 200 cycles at cycle %0d ***", cycle_count);
                    $display("  PC=0x%08x INSTR=%04x", cpu_pc, cpu.instr);
                    $display("  MEM[word]=%08x", cpu.umem[{3'b000, cpu_pc[28:0]} >> 2]);
                    $display("  SR=0x%08x R15=0x%08x PR=0x%08x", cpu.sr_rd, cpu.rf[15], cpu.pr_rd);
                    $display("  MMUCR=0x%08x delay=%b int_take=%b", cpu.mmucr_rd, cpu.delay_slot, cpu.int_should_take);
                    $finish;
                end
            end else begin
                stuck_pc_count <= 0;
            end

            // Timeout
            if (cycle_count >= 50000000) begin
                $display("");
                $display("=== Simulation Timeout (500M cycles) ===");
                $display("Final PC: 0x%08x SR=0x%08x", cpu_pc, cpu.sr_rd);
                $finish;
            end
        end
    end

    // =========================================================================
    // Initialization - Load boot image from binary file
    // =========================================================================
    initial begin
        $display("DEBUG: initial block starting");
        $fflush();

        initialized = 0;
        reset = 1;
        reset_counter = 10;
        cycle_count = 0;
        stuck_pc_count = 0;

        // Open UART output file
        uart_file = $fopen("uart_output.txt", "w");
        if (uart_file == 0) begin
            $display("WARNING: Could not open uart_output.txt for writing");
        end

        // Entry point in P2 space (uncached)
        if (!$value$plusargs("entry=%h", entry_point)) begin
            entry_point = BOOT_ROM_P2;  // Default to P2 address 0xA0000000
        end

        $display("DEBUG: Loading boot.bin (binary)");
        $fflush();

        // Load memory from binary file
        begin
            integer boot_file;
            integer word_count;
            reg [7:0] byte_data;
            integer j;
            integer bytes_read;
            string boot_image;

            if (!$value$plusargs("boot_image=%s", boot_image)) begin
                boot_image = "../boot/boot_mmu.bin";
            end

            boot_file = $fopen(boot_image, "rb");
            if (boot_file == 0) begin
                $display("ERROR: Could not open boot image: %s", boot_image);
                $finish;
            end

            word_count = 0;
            while (!$feof(boot_file)) begin
                // Load 4 bytes in big-endian order
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, boot_file);
                    if (bytes_read == 1)
                        cpu.umem[word_count][j*8 +: 8] = byte_data;
                end
                word_count = word_count + 1;
            end
            $fclose(boot_file);
            $display("DEBUG: Loaded %0d words (%0d bytes) from %s", word_count, word_count * 4, boot_image);
        end

        $fflush();
        #1;

        $display("===========================================");
        $display("J4 (SH-4) MMU Linux Boot Simulation");
        $display("===========================================");
        $display("Memory loaded from boot.bin via binary load");
        $display("-------------------------------------------");
        $display("Memory Layout:");
        $display("  Physical RAM: 0x%08x - 0x%08x (64MB)", MEMORY_BASE, MEMORY_BASE + MEMORY_SIZE - 1);
        $display("  P1 (cached):  0x%08x - 0x%08x", 32'h80000000, 32'h9FFFFFFF);
        $display("  P2 (uncached):0x%08x - 0x%08x", 32'hA0000000, 32'hBFFFFFFF);
        $display("-------------------------------------------");
        $display("Boot sequence:");
        $display("  1. CPU starts at P2: 0x%08x", entry_point);
        $display("  2. Boot ROM enables MMU, sets up VBR");
        $display("  3. Boot ROM jumps to kernel at P1: 0x%08x", KERNEL_ENTRY_P1);
        $display("-------------------------------------------");

        // Verify memory contents
        $display("First words of boot image (physical addresses):");
        $display("  [0x00000000] = 0x%08x", cpu.umem[0]);
        $display("  [0x00000004] = 0x%08x", cpu.umem[1]);
        $display("Kernel entry (physical 0x00002000):");
        $display("  [0x00002000] = 0x%08x", cpu.umem[32'h800]);
        $display("  [0x00002004] = 0x%08x", cpu.umem[32'h801]);
        $display("FDT at physical 0x00000100:");
        $display("  [0x00000100] = 0x%08x (should be d00dfeed)", cpu.umem[32'h40]);
        $display("raw_notifier_call_chain at phys 0x0002a8e8 (word 0xAA3A):");
        $display("  [0x0002a8e8] = 0x%08x (should be 2f862f96)", cpu.umem[32'h0000AA3A]);
        $display("  [0x0002a8ec] = 0x%08x (should be 2fa62fb6)", cpu.umem[32'h0000AA3B]);
        $display("-------------------------------------------");
    end

    // Waveform dumping
    initial begin
        if ($test$plusargs("trace")) begin
            $dumpfile("linux_boot_mmu.vcd");
            $dumpvars(0, linux_boot_mmu_tb);
        end
    end

endmodule
