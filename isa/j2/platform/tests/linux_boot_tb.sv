// J2 Linux Boot Testbench (Internal Memory)
// Loads and boots Linux kernel in Verilator simulation
//
// Memory Map (from device tree):
//   0x00000000 - 0x03FFFFFF: Main RAM (64MB)
//   0xABCD0100: UARTLite
//   0xABCD0200: AIC + PIT
//
// The kernel is loaded at 0x00000000, entry point at 0x00002000

`timescale 1ns/1ps

module linux_boot_tb;
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
    // J2 Processor Core (Internal Memory)
    // =========================================================================
    // Extract priority from PIT's PITEN register (bits 23:20)
    wire [3:0] irq_priority = pit.piten[23:20];

    j2_complete cpu (
        .clk(clk),
        .reset(reset),

        // Reset state
        .reset_pc(entry_point),
        .reset_pr(32'd0),
        .reset_t_rd(1'b0),
        .reset_delay_slot(1'b0),
        .reset_branch_target_rd(32'd0),
        .reset_macl(32'd0),
        .reset_mach(32'd0),
        .reset_gbr(32'd0),
        .reset_sr(32'h40000000),  // MD=1 (privileged mode)
        .reset_vbr(VBR_INIT),

        // Interrupt inputs from AIC/PIT
        .irq_i_rd(aic_irq_out),
        .irq_i_wr(1'b0),              // Not used (input-only)
        .irq_vector_rd(aic_irq_vector),
        .irq_vector_wr(8'd0),         // Not used (input-only)
        .irq_priority_rd(irq_priority),
        .irq_priority_wr(4'd0)        // Not used (input-only)
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
                // $display("[%0d] PERIPH WRITE: @0x%08x = 0x%08x (PC=0x%08x)",
                //          cycle_count, cpu_write_addr, cpu_write_data, cpu.pc);
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
            // INTST at offset 0x00 - overlaps with PITEN, but read gives vector
            // We prioritize PIT's PITEN for offset 0 since AIC reads use offset 0x00 for INTST
            // Actually, let's put INTST at the same location - the CPU reads will get this
            // For reads, we want the vector number
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
            last_write_addr <= write_addr;
        end
    end

    // =========================================================================
    // CAS.L Instruction Tracing
    // =========================================================================
    wire casl_active = cpu.casl_enable;
    wire [31:0] casl_r0 = cpu.casl_r0_bk ? cpu.rf_bank[0] : cpu.rf[0];
    wire [31:0] casl_rn_val = cpu.casl_Rn;
    wire [31:0] casl_rm_val = cpu.casl_Rm;
    wire [31:0] casl_mem_val = cpu.mem_val;
    wire casl_match = cpu.mem_val_eq_Rm;  // Now compares against Rm (correct IBM 360 semantics)
    wire [3:0] casl_rn_idx = cpu.instr_11_8;
    wire [3:0] casl_rm_idx = cpu.instr_7_4;

    // CAS.L tracing disabled - working correctly now

    // Division tracing disabled

    // =========================================================================
    // Timer/Interrupt Debug
    // =========================================================================
    reg [31:0] last_piten;
    reg [31:0] last_throt;
    reg last_timer_irq;
    reg last_aic_irq_out;
    reg [31:0] irq_cycle_count;

    initial begin
        last_piten = 0;
        last_throt = 0;
        last_timer_irq = 0;
        last_aic_irq_out = 0;
        irq_cycle_count = 0;
    end

    always @(posedge clk) begin
        if (!reset) begin
            // Track state changes silently (for debugging if needed)
            last_piten <= pit.piten;
            last_throt <= pit.throt;
            last_timer_irq <= pit_timer_irq;
            last_aic_irq_out <= aic_irq_out;

            // Debug output disabled - interrupts working correctly
            // Uncomment below to trace timer interrupts:
            // if (cycle_count >= 14000000 && pit_timer_irq && !last_timer_irq)
            //     $display("[%0d] TIMER IRQ", cycle_count);
        end
    end

    // =========================================================================
    // Exception Detection and Comprehensive Instruction Tracing
    // =========================================================================
    reg [31:0] last_sr;
    reg [31:0] last_r15;
    reg [31:0] last_vbr;
    reg pc_zero_detected = 0;
    reg r15_zero_detected = 0;

    // History buffer to track last N PCs before crash
    reg [31:0] pc_history [0:15];
    reg [31:0] instr_history [0:15];
    integer history_idx = 0;

    always @(posedge clk) begin
        last_sr <= cpu.sr;
        last_r15 <= cpu.rf[15];
        last_vbr <= cpu.vbr;

        // Record PC history
        if (!reset && cycle_count > 10) begin
            pc_history[history_idx] <= cpu.pc;
            if (cpu.pc[1] == 0)
                instr_history[history_idx] <= cpu.umem[cpu.pc[23:2]][31:16];
            else
                instr_history[history_idx] <= cpu.umem[cpu.pc[23:2]][15:0];
            history_idx <= (history_idx + 1) & 15;
        end

        // Trace VBR changes
        if (!reset && cpu.vbr != last_vbr && cycle_count > 10) begin
            $display("[%0d] VBR CHANGED: 0x%08x -> 0x%08x at PC=0x%08x",
                     cycle_count, last_vbr, cpu.vbr, cpu.pc);
        end

        // Detect when PC becomes 0 or goes to low address (unexpected)
        if (!reset && last_pc > 32'h1000 && cpu.pc < 32'h1000 && !pc_zero_detected && cycle_count > 1000) begin
            pc_zero_detected <= 1'b1;
            $display("");
            $display("*** PC WENT TO LOW ADDRESS at cycle %0d ***", cycle_count);
            $display("  Before: PC=0x%08x SR=0x%08x R15=0x%08x VBR=0x%08x", last_pc, last_sr, last_r15, cpu.vbr);
            $display("  After:  PC=0x%08x SR=0x%08x R15=0x%08x", cpu.pc, cpu.sr, cpu.rf[15]);
            $display("  Instruction at last PC: 0x%08x", cpu.umem[last_pc[23:2]]);
            $display("  R0-R7: %08x %08x %08x %08x %08x %08x %08x %08x",
                     cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3],
                     cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
            $display("  R8-R15: %08x %08x %08x %08x %08x %08x %08x %08x",
                     cpu.rf[8], cpu.rf[9], cpu.rf[10], cpu.rf[11],
                     cpu.rf[12], cpu.rf[13], cpu.rf[14], cpu.rf[15]);
            $display("  PR=0x%08x VBR=0x%08x GBR=0x%08x", cpu.pr, cpu.vbr, cpu.gbr);
            $display("  PC History (last 16 instructions):");
            for (int h = 0; h < 16; h++) begin
                int idx = (history_idx - 16 + h) & 15;
                $display("    [%2d] PC=%08x instr=%04x", h, pc_history[idx], instr_history[idx][15:0]);
            end
            $finish;
        end

        // Detect when R15 (SP) becomes 0 (likely context switch issue)
        if (!reset && last_r15 != 0 && cpu.rf[15] == 0 && !r15_zero_detected && cycle_count > 1000) begin
            r15_zero_detected <= 1'b1;
            $display("");
            $display("*** R15 (SP) WENT TO ZERO at cycle %0d ***", cycle_count);
            $display("  PC=0x%08x SR=0x%08x VBR=0x%08x", cpu.pc, cpu.sr, cpu.vbr);
            $display("  Before R15=0x%08x, After R15=0x%08x", last_r15, cpu.rf[15]);
            $display("  Instruction at PC: 0x%08x", cpu.umem[cpu.pc[23:2]]);
            $display("  R0-R7: %08x %08x %08x %08x %08x %08x %08x %08x",
                     cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3],
                     cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
            $display("  R8-R15: %08x %08x %08x %08x %08x %08x %08x %08x",
                     cpu.rf[8], cpu.rf[9], cpu.rf[10], cpu.rf[11],
                     cpu.rf[12], cpu.rf[13], cpu.rf[14], cpu.rf[15]);
            $display("  PR=0x%08x", cpu.pr);
        end
    end

    // =========================================================================
    // Reset Logic and Simulation Control
    // =========================================================================
    integer cycle_count;
    wire [31:0] cpu_pc = cpu.pc;
    reg [31:0] last_pc;
    reg initialized;

    // Exception tracking for verification
    reg exc_taken_last;
    reg [31:0] exc_push_addr_last;

    // Detailed tracing for address error exception
    reg trace_after_exc;
    integer trace_countdown;

    // Reset and cycle counter
    always @(posedge clk) begin
        if (!initialized) begin
            // First clock - stay in reset
            reset <= 1'b1;
            reset_counter <= 8'd10;
            cycle_count <= 0;
            initialized <= 1'b1;
            exc_taken_last <= 0;
            trace_after_exc <= 0;
            trace_countdown <= 0;
        end else if (reset_counter > 0) begin
            // Count down reset
            reset_counter <= reset_counter - 1;
            if (reset_counter == 1) begin
                reset <= 1'b0;
                $display("");
                $display("=== Linux Boot Started ===");
            end
        end else begin
            // Normal operation
            cycle_count <= cycle_count + 1;
            last_pc <= cpu_pc;

            // // Print PC every 1M cycles to show progress (every cycle near crash)
            // if (cycle_count % 1000000 == 0) begin
            //     $display("[%0d] PC=0x%08x SR=0x%08x R15=0x%08x PR=0x%08x", cycle_count, cpu_pc, cpu.sr, cpu.rf[15], cpu.pr);
            // end
            // Trace important instructions for debugging
            // SH is 16-bit instructions, need to extract based on PC alignment
            begin
                reg [15:0] current_instr;
                reg [3:0] instr_top4;
                reg [3:0] instr_rn;
                reg [3:0] instr_rm;
                reg [3:0] instr_bot4;

                // Get 16-bit instruction at current PC (big-endian)
                if (cpu_pc[1] == 0)
                    current_instr = cpu.umem[cpu_pc[23:2]][31:16];
                else
                    current_instr = cpu.umem[cpu_pc[23:2]][15:0];

                instr_top4 = current_instr[15:12];
                instr_rn   = current_instr[11:8];
                instr_rm   = current_instr[7:4];
                instr_bot4 = current_instr[3:0];

                // Check for mov.l @Rm, R15 (opcode: 0110 1111 mmmm 0010 = 0x6Fm2)
                // Only log if source register is 0 or near zero (suspicious)
                if (instr_top4 == 4'h6 && instr_rn == 4'hF && instr_bot4 == 4'h2 && cpu.rf[instr_rm] < 32'h100) begin
                    $display("[%0d] MOV.L @R%0d,R15 SUSPICIOUS: PC=%08x instr=%04x R%0d=%08x (loading to R15)",
                             cycle_count, instr_rm, cpu_pc, current_instr, instr_rm, cpu.rf[instr_rm]);
                end

                // Check for RTE (only show during trace mode for address error debugging)
                // if (current_instr == 16'h002B && trace_after_exc) begin
                //     $display("[%0d] RTE: PC=%08x R15=%08x -> new_PC=@[%08x]=%08x new_SR=@[%08x]=%08x",
                //              cycle_count, cpu_pc, cpu.rf[15],
                //              cpu.rf[15], cpu.umem[cpu.rf[15][23:2]],
                //              cpu.rf[15]+4, cpu.umem[(cpu.rf[15]+4) >> 2]);
                // end

                // Trace exception handling when it occurs
                // if (cpu.select_exc_handler_addr_pc_merged) begin
                //     // Track for verification next cycle
                //     exc_taken_last <= 1;
                //     exc_push_addr_last <= cpu.exc_new_sp;
                //     // Only print details for address error exception (handler 0x4ba8)
                //     if (cpu.exc_handler_addr == 32'h4ba8) begin
                //         $display("[%0d] EXCEPTION TAKEN: PC=%08x -> handler=%08x SR=%08x->%08x R15=%08x->%08x",
                //                  cycle_count, cpu_pc, cpu.exc_handler_addr,
                //                  cpu.sr, cpu.exc_new_sr,
                //                  cpu.rf[15], cpu.exc_new_sp);
                //         $display("  exc_saved_pc=%08x exc_saved_sr=%08x push_addr=%08x instr=%04x",
                //                  cpu.exc_saved_pc, cpu.exc_saved_sr, cpu.exc_new_sp, current_instr);
                //         $display("  write_enables: port0=%b port1=%b port2=%b",
                //                  cpu.umem_write_enable, cpu.umem_write_enable_1, cpu.umem_write_enable_2);
                //         $display("  port1: @%08x <- %08x (SR push)",
                //                  cpu.umem_write_addr_mux_1, cpu.umem_write_data_mux_1);
                //         $display("  port2: @%08x <- %08x (PC push)",
                //                  cpu.exc_new_sp, cpu.exc_saved_pc);
                //         // Print all registers at exception time
                //         $display("  Registers at exception:");
                //         $display("  R0=%08x R1=%08x R2=%08x R3=%08x R4=%08x R5=%08x R6=%08x R7=%08x",
                //                  cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3],
                //                  cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
                //         $display("  R8=%08x R9=%08x R10=%08x R11=%08x R12=%08x R13=%08x R14=%08x R15=%08x",
                //                  cpu.rf[8], cpu.rf[9], cpu.rf[10], cpu.rf[11],
                //                  cpu.rf[12], cpu.rf[13], cpu.rf[14], cpu.rf[15]);
                //         trace_after_exc <= 1;
                //         trace_countdown <= 50;
                //     end // else begin
                //         // One cycle after exception, verify what's in memory
                //         //$display("  VERIFY: umem[@%08x]=%08x (should be PC) umem[@%08x]=%08x (should be SR)",
                //         //         exc_push_addr_last, cpu.umem[exc_push_addr_last[23:2]],
                //         //         exc_push_addr_last+4, cpu.umem[(exc_push_addr_last+4)>>2]);
                //     end
                // end else begin
                //     exc_taken_last <= 0;
                // end

                // Trace instructions after address error exception
                // if (trace_after_exc && trace_countdown > 0) begin
                //     $display("[%0d] TRACE: PC=%08x instr=%04x R15=%08x PR=%08x",
                //              cycle_count, cpu_pc, current_instr, cpu.rf[15], cpu.pr);
                //     // On first trace cycle, verify what was pushed to stack
                //     if (trace_countdown == 50) begin
                //         $display("  STACK CHECK: @%08x=%08x (PC?) @%08x=%08x (SR?)",
                //                  exc_push_addr_last, cpu.umem[exc_push_addr_last[23:2]],
                //                  exc_push_addr_last+4, cpu.umem[(exc_push_addr_last+4)>>2]);
                //     end
                //     // Check MOV.L @-Rn stores (opcode 0010 nnnn mmmm 0110)
                //     if (current_instr[15:12] == 4'h2 && current_instr[3:0] == 4'h6) begin
                //         $display("  MOVL_PREDEC: wr_en=%b addr=%08x data=%08x no_err=%b",
                //                  cpu.umem_write_enable, cpu.umem_write_addr_mux,
                //                  cpu.umem_write_data_mux, cpu.movl_predec_no_error);
                //         $display("    R%0d=%08x R%0d=%08x predec_addr=%08x",
                //                  current_instr[11:8], cpu.rf[current_instr[11:8]],
                //                  current_instr[7:4], cpu.rf[current_instr[7:4]],
                //                  cpu.movl_predec_addr);
                //     end
                //     trace_countdown <= trace_countdown - 1;
                //     if (trace_countdown == 1) begin
                //         trace_after_exc <= 0;
                //     end
                // end

                // Verify exception push on cycle after exception taken (only for address error)
                // Disabled - too verbose
                // if (exc_taken_last && exc_push_addr_last < 32'h00660000) begin
                //     $display("[%0d] EXC VERIFY: @[%08x]=%08x (PC) @[%08x]=%08x (SR)",
                //              cycle_count, exc_push_addr_last, cpu.umem[exc_push_addr_last[23:2]],
                //              exc_push_addr_last+4, cpu.umem[(exc_push_addr_last+4)>>2]);
                //     $display("  t_rd=%b sr[0]=%b sr=%08x", cpu.t_rd, cpu.sr[0], cpu.sr);
                // end

                // Check for JMP @Rm jumping to address 0 (opcode: 0100 mmmm 0010 1011 = 0x4m2B)
                // if (instr_top4 == 4'h4 && current_instr[7:0] == 8'h2B && cpu.rf[instr_rn] == 0) begin
                //     $display("[%0d] JMP @R%0d TO ZERO: PC=%08x R%0d=%08x",
                //              cycle_count, instr_rn, cpu_pc, instr_rn, cpu.rf[instr_rn]);
                // end

                // Detect PC becoming 0 or very low (potential crash)
                if (cpu_pc < 32'h1000 && cpu_pc != 0) begin
                    $display("[%0d] WARNING: PC in low memory: PC=%08x SR=%08x R15=%08x instr=%04x",
                             cycle_count, cpu_pc, cpu.sr, cpu.rf[15], current_instr);
                end
                if (cpu_pc == 0 && cpu.sr != 32'h40000000) begin
                    $display("[%0d] CRITICAL: PC=0 with non-reset SR! SR=%08x R15=%08x",
                             cycle_count, cpu.sr, cpu.rf[15]);
                    $display("  All registers: R0=%08x R1=%08x R2=%08x R3=%08x",
                             cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3]);
                    $display("  R4=%08x R5=%08x R6=%08x R7=%08x",
                             cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
                end

                // JSR/RTS tracing disabled - too verbose
                // Uncomment for detailed call tracing:
                // if (instr_top4 == 4'h4 && current_instr[7:0] == 8'h0B) begin
                //     $display("[%0d] JSR @R%0d: PC=%08x R%0d=%08x PR=%08x",
                //              cycle_count, instr_rn, cpu_pc, instr_rn, cpu.rf[instr_rn], cpu.pr);
                // end
                // if (current_instr == 16'h000B) begin
                //     $display("[%0d] RTS: PC=%08x PR=%08x (returning to)",
                //              cycle_count, cpu_pc, cpu.pr);
                // end
            end

            // Timeout (50 million cycles)
            if (cycle_count >= 500000000) begin
                $display("");
                $display("=== Simulation Timeout (50M cycles) ===");
                $display("Final PC: 0x%08x SR=0x%08x", cpu_pc, cpu.sr);
                $finish;
            end
        end
    end

    // =========================================================================
    // Initialization - Load boot image and initrd
    // =========================================================================
    integer boot_file;
    integer initrd_file;
    integer bytes_read;
    reg [7:0] byte_data;
    integer i, j;
    string boot_path;
    string initrd_path;
    integer word_count;
    integer initrd_word_count;

    // Initrd location - must match bootrom.S
    localparam INITRD_BASE = 32'h03800000;  // 56MB

    initial begin
        // Initialize state
        initialized = 0;
        reset = 1;
        reset_counter = 10;
        cycle_count = 0;
        pc_zero_detected = 0;

        // Get entry point from plusargs (required)
        if (!$value$plusargs("entry=%h", entry_point)) begin
            $display("ERROR: Must specify +entry=<hex_addr>");
            $display("Usage: ./Vlinux_boot_tb +boot=boot.bin +entry=00545004");
            $finish;
        end

        // Get boot image path from plusargs
        if (!$value$plusargs("boot=%s", boot_path)) begin
            boot_path = "boot.bin";
        end

        // Get initrd path from plusargs (optional)
        if (!$value$plusargs("initrd=%s", initrd_path)) begin
            initrd_path = "";
        end

        $display("===========================================");
        $display("J2 Linux Boot Simulation");
        $display("===========================================");
        $display("Loading boot image from: %s", boot_path);

        boot_file = $fopen(boot_path, "rb");
        if (boot_file == 0) begin
            $display("ERROR: Cannot open boot image: %s", boot_path);
            $display("");
            $display("To create a boot image, run:");
            $display("  cd j2/platform/boot && make");
            $display("");
            $finish;
        end

        // Load boot image directly into CPU's internal memory
        word_count = 0;
        while (!$feof(boot_file)) begin
            // Read 4 bytes in big-endian order
            for (j = 3; j >= 0; j = j - 1) begin
                bytes_read = $fread(byte_data, boot_file);
                if (bytes_read == 1) begin
                    cpu.umem[word_count][j*8 +: 8] = byte_data;
                end
            end
            word_count = word_count + 1;
        end
        $fclose(boot_file);
        $display("Loaded %0d words (%0d KB) at umem[0]", word_count, (word_count * 4) / 1024);

        // Load initrd if specified
        if (initrd_path != "") begin
            $display("Loading initrd from: %s", initrd_path);
            initrd_file = $fopen(initrd_path, "rb");
            if (initrd_file == 0) begin
                $display("ERROR: Cannot open initrd: %s", initrd_path);
                $finish;
            end

            // Load initrd at INITRD_BASE
            initrd_word_count = 0;
            while (!$feof(initrd_file)) begin
                // Read 4 bytes in big-endian order
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, initrd_file);
                    if (bytes_read == 1) begin
                        cpu.umem[(INITRD_BASE >> 2) + initrd_word_count][j*8 +: 8] = byte_data;
                    end
                end
                initrd_word_count = initrd_word_count + 1;
            end
            $fclose(initrd_file);
            $display("Loaded initrd: %0d words (%0d KB) at 0x%08x",
                     initrd_word_count, (initrd_word_count * 4) / 1024, INITRD_BASE);
        end

        // Display memory map
        $display("-------------------------------------------");
        $display("Memory Layout:");
        $display("  0x%08x - RAM Base / VBR", MEMORY_BASE);
        $display("  0x%08x - Kernel entry (_stext)", KERNEL_ENTRY);
        $display("  0x%08x - Boot ROM entry (PC starts here)", entry_point);
        $display("  0x%08x - RAM End", MEMORY_BASE + MEMORY_SIZE - 1);
        $display("  0x%08x - UART TX", UART_TX);
        $display("  0x%08x - AIC/PIT", PERIPH_BASE);
        $display("-------------------------------------------");
        $display("");
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
        $display("Boot ROM entry (0x%08x):", entry_point);
        $display("  [0x%08x] = 0x%08x", entry_point, cpu.umem[entry_point[23:2]]);
        $display("  [0x%08x] = 0x%08x", entry_point+4, cpu.umem[entry_point[23:2]+1]);
        $display("FDT at 0x00000100:");
        $display("  [0x00000100] = 0x%08x (should be d00dfeed)", cpu.umem[32'h100 >> 2]);
        $display("  [0x00000104] = 0x%08x", cpu.umem[(32'h100 >> 2) + 1]);
    end

    // Waveform dumping
    initial begin
        if ($test$plusargs("trace")) begin
            $dumpfile("linux_boot.vcd");
            $dumpvars(0, linux_boot_tb);
        end
    end

endmodule
