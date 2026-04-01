// J4 Linux Boot Testbench (Internal Memory)
// Loads and boots Linux kernel in Verilator simulation
//
// Memory Map (from device tree):
//   0x00000000 - 0x03FFFFFF: Main RAM (64MB)
//   0x03F00100: UARTLite
//   0x03F00200: AIC + PIT
//
// The kernel is loaded at 0x00000000, entry point at 0x00002000

`timescale 1ns/1ps

module linux_boot_tb;
    // Early debug
    initial $display("VERY EARLY DEBUG");

    // Self-generated clock for Verilator 5+
    reg clk = 0;
    always #10 clk = ~clk;  // 50MHz

    // Reset - active high, deasserted after reset_counter expires
    reg reset;
    reg [7:0] reset_counter;

    // Constants - Memory Layout
    localparam MEMORY_BASE = 32'h00000000;
    localparam MEMORY_SIZE = 32'h04000000;  // 64MB
    localparam KERNEL_ENTRY = 32'h00002000; // Linux kernel entry (_stext)
    localparam VBR_INIT    = 32'h00000000;  // VBR at start of RAM

    // Entry point - set via plusarg
    reg [31:0] entry_point;

    // Constants - Peripheral Base Addresses (in internal memory range)
    localparam UART_BASE   = 32'h03F00100;
    localparam UART_TX     = 32'h03F00104;
    localparam PERIPH_BASE = 32'h03F00200;  // AIC and PIT share this base

    // =========================================================================
    // Peripheral Signals
    // =========================================================================
    // Peripheral bus
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

    // IRQ sources to AIC
    wire [111:0] irq_sources;
    assign irq_sources = {55'd0, pit_timer_irq, 56'd0};  // Timer at IRQ 72 (index 56)

    // =========================================================================
    // AIC - Advanced Interrupt Controller
    // =========================================================================
    jcore_aic #(
        .BASE_ADDR(PERIPH_BASE)
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
        .BASE_ADDR(PERIPH_BASE),
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
    // J4 Processor Core (Internal Memory)
    // =========================================================================
    // Extract priority from PIT's PITEN register (bits 23:20)
    wire [3:0] irq_priority = pit.piten[23:20];

    j4_complete cpu (
        .clk(clk),
        .reset(reset),

        // Reset state - standard values
        .reset_pc(entry_point),
        .reset_pr(32'd0),
        .reset_t(1'b0),
        .reset_delay_slot(1'b0),
        .reset_branch_target_rd(32'd0),
        .reset_macl(32'd0),
        .reset_mach(32'd0),
        .reset_gbr(32'd0),
        .reset_sr(32'h40000000),  // MD=1 (privileged mode)
        .reset_vbr(VBR_INIT),

        // J4-specific reset state - MMU/FPU registers
        .reset_mmucr(32'h00000000),  // MMU disabled
        .reset_pteh(32'h00000000),
        .reset_ptel(32'h00000000),
        .reset_ttb(32'h00000000),
        .reset_tea(32'h00000000),
        .reset_ssr(32'h00000000),
        .reset_spc(32'h00000000),
        .reset_sgr(32'h00000000),
        .reset_dbr(32'h00000000),
        .reset_fpscr(32'h00040001),  // Default FPSCR
        .reset_fpul(32'h00000000),

        // Interrupt inputs from AIC/PIT
        .irq_i_rd(aic_irq_out),
        .irq_i_wr(1'b0)              // Not used (input-only)
    );

    // =========================================================================
    // Peripheral Bus Controller
    // Intercepts CPU accesses to 0x03F00200 - 0x03F0022F
    // =========================================================================
    localparam PERIPH_RANGE_START = 32'h03F00200;
    localparam PERIPH_RANGE_END   = 32'h03F00230;  // 48 bytes for PIT

    // Convert CPU umem address to peripheral address
    wire [31:0] cpu_write_addr = cpu.umem_write_addr_mux;
    wire [31:0] cpu_write_data = cpu.umem_write_data_mux;
    wire cpu_write_periph = (cpu_write_addr >= PERIPH_RANGE_START) &&
                            (cpu_write_addr < PERIPH_RANGE_END);

    // Forward writes to peripheral bus
    always @(posedge clk) begin
        if (reset) begin
            periph_we <= 1'b0;
            periph_re <= 1'b0;
            periph_addr <= 32'd0;
            periph_wdata <= 32'd0;
        end else begin
            // Default: no bus operation
            periph_we <= 1'b0;
            periph_re <= 1'b0;

            // Detect writes to peripheral range
            if (store_enable && cpu_write_periph) begin
                periph_addr <= cpu_write_addr;
                periph_wdata <= cpu_write_data;
                periph_we <= 1'b1;
            end
        end
    end

    // Mirror peripheral read values back to umem
    // This allows the CPU to read peripheral registers via umem
    always @(posedge clk) begin
        if (!reset) begin
            // Update umem with PIT register values
            // PITEN at offset 0x00
            cpu.umem[(PERIPH_RANGE_START >> 2)] <= pit.piten;
            // THROT at offset 0x10
            cpu.umem[(PERIPH_RANGE_START >> 2) + 4] <= pit.throt;
            // COUNT at offset 0x14
            cpu.umem[(PERIPH_RANGE_START >> 2) + 5] <= pit.count;
            // BUSPD at offset 0x18
            cpu.umem[(PERIPH_RANGE_START >> 2) + 6] <= 32'd20;  // 20ns = 50MHz
            // SECHI at offset 0x20
            cpu.umem[(PERIPH_RANGE_START >> 2) + 8] <= pit.sec_hi;
            // SECLO at offset 0x24
            cpu.umem[(PERIPH_RANGE_START >> 2) + 9] <= pit.sec_lo;
            // NSEC at offset 0x28
            cpu.umem[(PERIPH_RANGE_START >> 2) + 10] <= pit.nsec;

            // Update umem with AIC register values
            // INTPRI at offset 0x08
            cpu.umem[(PERIPH_RANGE_START >> 2) + 2] <= aic.intpri;
        end
    end

    // =========================================================================
    // UART Monitor - watch for writes to UART TX register
    // =========================================================================
    wire [31:0] write_addr = cpu.umem_write_addr_mux;
    wire [31:0] write_data = cpu.umem_write_data_mux;

    // Use the unified umem write enable from the CPU
    wire store_enable = cpu.umem_write_enable;

    reg [31:0] last_write_addr;

    always @(posedge clk) begin
        if (!reset && store_enable) begin
            // Check if writing to UART TX register
            if (write_addr == UART_TX) begin
                $write("%c", write_data[7:0]);
                $fflush();
            end
            // Trace writes to PIT/AIC registers
            if (write_addr >= 32'h03F00200 && write_addr < 32'h03F00230) begin
                $display("[%0d] PERIPH_WRITE: PC=%08x Addr=%08x Data=%08x",
                         cycle_count, cpu_pc, write_addr, write_data);
            end
            // Trace ANY writes to the crash stack address
            if (write_addr >= 32'h00461d10 && write_addr <= 32'h00461d20) begin
                $display("[%0d] MEM_WRITE @461d1X: PC=%08x Addr=%08x Data=%08x",
                         cycle_count, cpu_pc, write_addr, write_data);
            end
            last_write_addr <= write_addr;
        end
    end

    // Debug: trace PIT and AIC state
    reg pit_irq_prev;
    reg aic_irq_prev;
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
        end
    end

    // =========================================================================
    // PR Save/Restore Tracing (debug STS.L PR / LDS.L PR)
    // =========================================================================
    wire stsl_pr_active = cpu.stsl_pr_enable;
    wire ldsl_pr_active = cpu.ldsl_pr_enable;
    wire [31:0] pr_value = cpu.pr;
    wire [31:0] umem_rn_data = cpu.umem_Rn_rd;

    // Track last few STS.L PR operations
    reg [31:0] last_stsl_addr;
    reg [31:0] last_stsl_data;
    reg [31:0] last_ldsl_addr;
    reg [31:0] last_ldsl_data;

    // Track R15 changes
    reg [31:0] prev_r15;
    wire [31:0] curr_r15 = cpu.rf[15];
    reg r15_tracking_started;
    wire [15:0] curr_instr = (cpu_pc[1] == 0) ? cpu.umem[cpu_pc[23:2]][31:16] : cpu.umem[cpu_pc[23:2]][15:0];

    // Debug: trace exception signals for movw_postinc
    wire movw_pi_en = cpu.movw_postinc_enable;
    wire movw_en = cpu.movw_enable;
    wire movw_pi_exc = cpu.movw_postinc_exc_taken;
    wire [31:0] r0_val = cpu.rf[0];
    wire rf_wr_en = cpu.rf_write_enable;
    wire rf_wr_en_1 = cpu.rf_write_enable_1;
    wire rf_wr_en_2 = cpu.rf_write_enable_2;
    wire [3:0] rf_wr_addr = cpu.rf_write_addr_mux;
    wire [31:0] rf_wr_data = cpu.rf_write_data_mux;
    wire [31:0] rf_wr_addr_1 = cpu.rf_write_addr_mux_1;
    wire [31:0] rf_wr_data_1 = cpu.rf_write_data_mux_1;

    // Debug: trace movw_indexed_store signals
    wire movw_idx_st_en = cpu.movw_indexed_store_enable;
    wire movw_idx_st_exc = cpu.movw_indexed_store_exc_taken;
    wire [31:0] movw_idx_st_addr = cpu.movw_indexed_store_store_addr;
    wire movw_idx_st_addr_0 = cpu.movw_indexed_store_store_addr_0_0;
    wire movw_idx_st_word_bad = cpu.movw_indexed_store_addr_err_store_word_bad;
    wire movw_idx_st_long_bad = cpu.movw_indexed_store_addr_err_store_long_bad;
    wire rf_movw_idx_st_guarded = cpu.rf_movw_indexed_store_exc_taken_guarded_enable;

    // Debug: trace other instruction decodes that might conflict
    wire div1_en = cpu.div1_enable;
    wire movb_idx_en = cpu.movb_indexed_enable;
    wire movw_idx_en = cpu.movw_indexed_enable;
    wire movb_idx_st_en = cpu.movb_indexed_store_enable;

    // Debug: trace the movb_indexed guarded enable (which uses rn_bk_eq_0)
    wire rf_movb_idx_guarded = cpu.rf_movb_indexed_rn_bk_eq_0_guarded_enable;
    wire movb_indexed_rn_bk_eq_0 = cpu.movb_indexed_rn_bk_eq_0;

    always @(posedge clk) begin
        if (!reset && cycle_count > 396970 && cycle_count < 397000) begin
            // Trace when movw_indexed_store executes
            if (movw_idx_st_en) begin
                $display("[%0d] movw_idx_st: PC=%08x instr=%04x store_addr=%08x addr[0]=%b word_bad=%b long_bad=%b exc_taken=%b guarded_en=%b div1=%b",
                         cycle_count, cpu_pc, curr_instr, movw_idx_st_addr, movw_idx_st_addr_0,
                         movw_idx_st_word_bad, movw_idx_st_long_bad, movw_idx_st_exc, rf_movw_idx_st_guarded, div1_en);
                // Dump more enable states to find what's making rf_write_enable true
                $display("  [%0d] enables: movb_idx=%b movw_idx=%b movb_idx_st=%b movw_idx_st=%b",
                         cycle_count, movb_idx_en, movw_idx_en, movb_idx_st_en, movw_idx_st_en);
            end
            // Trace ANY writes that might go to R15
            if ((rf_wr_en && rf_wr_addr == 15) ||
                (rf_wr_en_1 && rf_wr_addr_1 == 15) ||
                rf_wr_en_2) begin
                $display("[%0d] R15_WRITE: PC=%08x instr=%04x rf_wr0=%b addr0=%d data0=%08x | rf_wr1=%b addr1=%d data1=%08x | rf_wr2=%b",
                         cycle_count, cpu_pc, curr_instr, rf_wr_en, rf_wr_addr, rf_wr_data, rf_wr_en_1, rf_wr_addr_1, rf_wr_data_1, rf_wr_en_2);
            end
        end
        if (!reset && cycle_count > 100) begin
            // Start tracking after initialization
            if (!r15_tracking_started && curr_r15 != 0) begin
                r15_tracking_started <= 1;
                prev_r15 <= curr_r15;
                $display("[%0d] R15 INIT: PC=%08x R15=%08x", cycle_count, cpu_pc, curr_r15);
            end
            else if (r15_tracking_started && curr_r15 != prev_r15) begin
                // Log ANY R15 change with instruction opcode
                $display("[%0d] R15: PC=%08x instr=%04x %08x -> %08x (delta=%d)",
                         cycle_count, cpu_pc, curr_instr, prev_r15, curr_r15,
                         $signed(curr_r15 - prev_r15));
                prev_r15 <= curr_r15;
            end
        end
    end

    always @(posedge clk) begin
        if (!reset) begin
            // Trace STS.L PR, @-Rn (save PR to stack)
            if (stsl_pr_active) begin
                last_stsl_addr <= write_addr;
                last_stsl_data <= write_data;
                // Trace ALL stores to find which one should have saved to 0x461d18
                if (write_addr >= 32'h00461d00 && write_addr <= 32'h00461d30) begin
                    $display("[%0d] STS.L PR @461dXX: PC=%08x Addr=%08x Data=%08x PR=%08x",
                             cycle_count, cpu_pc, write_addr, write_data, pr_value);
                end else if (cycle_count > 390000 && cycle_count < 398000) begin
                    $display("[%0d] STS.L PR,@-Rn: PC=%08x Addr=%08x Data=%08x PR=%08x",
                             cycle_count, cpu_pc, write_addr, write_data, pr_value);
                end
            end

            // Trace LDS.L @Rn+, PR (load PR from stack)
            if (ldsl_pr_active) begin
                last_ldsl_addr <= cpu.umem_Rn_rd_addr_mux;
                last_ldsl_data <= umem_rn_data;
                // Trace loads near crash or crash address
                if ((cpu.umem_Rn_rd_addr_mux >= 32'h00461d00 && cpu.umem_Rn_rd_addr_mux <= 32'h00461d30) ||
                    (cycle_count > 390000 && cycle_count < 398000)) begin
                    $display("[%0d] LDS.L @Rn+,PR: PC=%08x Addr=%08x Data=%08x PR_before=%08x",
                             cycle_count, cpu_pc, cpu.umem_Rn_rd_addr_mux, umem_rn_data, pr_value);
                end
            end
        end
    end

    // =========================================================================
    // Reset Logic and Simulation Control
    // =========================================================================
    integer cycle_count;
    wire [31:0] cpu_pc = cpu.pc;
    reg [31:0] last_pc;
    reg initialized;

    // History buffer to track last N PCs before crash
    reg [31:0] pc_history [0:15];
    reg [31:0] instr_history [0:15];
    integer history_idx = 0;

    // Reset and cycle counter
    always @(posedge clk) begin
        if (!initialized) begin
            // First clock - stay in reset
            reset <= 1'b1;
            reset_counter <= 8'd10;
            cycle_count <= 0;
            initialized <= 1'b1;
        end else if (reset_counter > 0) begin
            // Count down reset
            reset_counter <= reset_counter - 1;
            if (reset_counter == 1) begin
                reset <= 1'b0;
                $display("");
                $display("=== J4 Linux Boot Started ===");
            end
        end else begin
            // Normal operation
            cycle_count <= cycle_count + 1;
            last_pc <= cpu_pc;

            // Record PC history
            if (cycle_count > 10) begin
                pc_history[history_idx] <= cpu_pc;
                if (cpu_pc[1] == 0)
                    instr_history[history_idx] <= cpu.umem[cpu_pc[23:2]][31:16];
                else
                    instr_history[history_idx] <= cpu.umem[cpu_pc[23:2]][15:0];
                history_idx <= (history_idx + 1) & 15;
            end

            // Detect when PC becomes 0 or goes to low address (unexpected)
            if (last_pc > 32'h1000 && cpu_pc < 32'h1000 && cycle_count > 1000) begin
                $display("");
                $display("*** PC WENT TO LOW ADDRESS at cycle %0d ***", cycle_count);
                $display("  Before: PC=0x%08x", last_pc);
                $display("  After:  PC=0x%08x SR=0x%08x R15=0x%08x", cpu_pc, cpu.sr, cpu.rf[15]);
                $display("  PC History (last 16 instructions):");
                for (int h = 0; h < 16; h++) begin
                    int idx = (history_idx - 16 + h) & 15;
                    $display("    [%2d] PC=%08x instr=%04x", h, pc_history[idx], instr_history[idx][15:0]);
                end
                $finish;
            end

            // Periodic progress report every 10M cycles
            if (cycle_count[23:0] == 0 && cycle_count > 0) begin
                $display("[%0d] PROGRESS: PC=%08x R15=%08x SR=%08x",
                         cycle_count, cpu_pc, cpu.rf[15], cpu.sr);
                $fflush();
            end

            // Timeout (500 million cycles)
            if (cycle_count >= 500000000) begin
                $display("");
                $display("=== Simulation Timeout (500M cycles) ===");
                $display("Final PC: 0x%08x SR=0x%08x", cpu_pc, cpu.sr);
                $finish;
            end
        end
    end

    // =========================================================================
    // Initialization - Memory loaded via $readmemh in j4_complete.v
    // =========================================================================
    initial begin
        $display("DEBUG: initial block starting");
        $fflush();

        // Initialize state
        initialized = 0;
        reset = 1;
        reset_counter = 10;
        cycle_count = 0;

        // Get entry point from plusargs (default to 0 for boot ROM)
        if (!$value$plusargs("entry=%h", entry_point)) begin
            entry_point = 32'h00000000;
        end

        $display("DEBUG: About to load boot.bin (binary)");
        $fflush();

        // Load memory from binary file (much faster than $readmemh)
        begin
            integer boot_file;
            integer word_count;
            reg [7:0] byte_data;
            integer j;
            integer bytes_read;
            string boot_image;

            if (!$value$plusargs("boot_image=%s", boot_image)) begin
                boot_image = "../boot/boot.bin";
            end

            boot_file = $fopen(boot_image, "rb");
            if (boot_file == 0) begin
                $display("ERROR: Could not open boot image: %s", boot_image);
                $finish;
            end

            word_count = 0;
            while (!$feof(boot_file)) begin
                // Load 4 bytes in big-endian order (SH-4 is big-endian)
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
        $display("J4 (SH-4) Linux Boot Simulation");
        $display("===========================================");
        $display("Memory loaded from boot.bin via binary load");
        $display("-------------------------------------------");
        $display("Memory Layout:");
        $display("  0x%08x - RAM Base / VBR", MEMORY_BASE);
        $display("  0x%08x - Kernel entry (_stext)", KERNEL_ENTRY);
        $display("  0x%08x - Boot ROM entry (PC starts here)", entry_point);
        $display("  0x%08x - RAM End", MEMORY_BASE + MEMORY_SIZE - 1);
        $display("  0x%08x - UART TX", UART_TX);
        $display("  0x%08x - AIC/PIT", PERIPH_BASE);
        $display("-------------------------------------------");
        $display("Boot sequence:");
        $display("  1. CPU starts at 0x%08x (boot ROM)", entry_point);
        $display("  2. Boot ROM loads R4 = FDT address");
        $display("  3. Boot ROM jumps to kernel at 0x%08x", KERNEL_ENTRY);
        $display("-------------------------------------------");

        // Verify first few words loaded correctly
        $display("First 4 words of boot image:");
        $display("  [0x00000000] = 0x%08x", cpu.umem[0]);
        $display("  [0x00000004] = 0x%08x", cpu.umem[1]);
        $display("  [0x00000008] = 0x%08x", cpu.umem[2]);
        $display("  [0x0000000C] = 0x%08x", cpu.umem[3]);
        $display("Kernel entry (0x00002000):");
        $display("  [0x00002000] = 0x%08x", cpu.umem[32'h800]);
        $display("  [0x00002004] = 0x%08x", cpu.umem[32'h801]);
        $display("FDT at 0x00000100:");
        $display("  [0x00000100] = 0x%08x (should be d00dfeed)", cpu.umem[32'h100 >> 2]);
        $display("  [0x00000104] = 0x%08x", cpu.umem[(32'h100 >> 2) + 1]);
        $display("-------------------------------------------");
    end

    // Waveform dumping
    initial begin
        if ($test$plusargs("trace")) begin
            $dumpfile("linux_boot.vcd");
            $dumpvars(0, linux_boot_tb);
        end
    end

endmodule
