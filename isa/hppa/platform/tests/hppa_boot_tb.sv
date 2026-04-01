// HPPA Linux Boot Testbench
// Loads and boots Linux kernel in Verilator simulation
//
// Memory Map:
//   0x00000000 - 0x00000FFF: Page Zero (firmware interface)
//   0x00001000 - 0x000FFFFF: Boot stub / firmware
//   0x00100000 - 0x037FFFFF: Kernel image
//   0x03800000 - 0x03EFFFFF: Initrd
//   0x03F00000 - 0x03FFFFFF: Peripheral I/O
//     0x03F00000: NS16550A UART (word-aligned, reg-shift=2)
//
// PA-RISC is big-endian. The kernel entry point is at 0x00100000.
// The boot stub at 0x00001000 sets up minimal state and jumps to the kernel.
//
// umem is [63:0] (64-bit words), indexed by byte_addr >> 3.
// Within each 64-bit word (big-endian word order):
//   bits[63:32] = 32-bit word at byte address N*8     (addr[2]==0)
//   bits[31:0]  = 32-bit word at byte address N*8+4   (addr[2]==1)
// Big-endian byte ordering within each 32-bit half.

`timescale 1ns/1ps

module hppa_boot_tb;
    // =========================================================================
    // Clock Generation (50MHz = 20ns period)
    // =========================================================================
    reg clk = 0;
    always #10 clk = ~clk;

    // =========================================================================
    // Constants - Memory Layout
    // =========================================================================
    localparam MEMORY_BASE     = 32'h00000000;
    localparam MEMORY_SIZE     = 32'h04000000;  // 64MB
    localparam PAGE_ZERO       = 32'h00000000;
    localparam BOOT_STUB_ADDR  = 32'h00001000;  // Boot stub at 4KB
    localparam KERNEL_LOAD     = 32'h00100000;  // Kernel at 1MB
    localparam INITRD_BASE     = 32'h03800000;  // Initrd at 56MB
    localparam FDT_ADDR        = 32'h00000800;  // FDT at 2KB in page zero area
    localparam PDC_STUB_ADDR   = 32'h0F000000;  // PDC firmware in ROM (outside 64MB RAM)
    localparam IODC_STUB_ADDR  = 32'h0F000400;  // IODC entry in ROM
    localparam PAGE_OFFSET     = 32'h10000000;  // Linux VA base for PA-RISC 32-bit

    // Peripheral addresses (NS16550A, reg-shift=2)
    localparam UART_BASE       = 32'h03F00000;
    localparam UART_THR        = 32'h03F00000;  // +0x00: TX/RX data
    localparam UART_IER        = 32'h03F00004;  // +0x04: Interrupt Enable
    localparam UART_IIR        = 32'h03F00008;  // +0x08: Interrupt Ident (read) / FCR (write)
    localparam UART_LCR        = 32'h03F0000C;  // +0x0C: Line Control
    localparam UART_MCR        = 32'h03F00010;  // +0x10: Modem Control
    localparam UART_LSR        = 32'h03F00014;  // +0x14: Line Status
    localparam UART_MSR        = 32'h03F00018;  // +0x18: Modem Status
    localparam UART_SCR        = 32'h03F0001C;  // +0x1C: Scratch

    // umem index base for UART (UART_BASE >> 3)
    localparam UART_UMEM_BASE  = UART_BASE >> 3;

    // UART register state for 8250 autodetect support
    reg [7:0] uart_ier = 8'h00;    // Interrupt Enable Register
    reg [7:0] uart_iir = 8'h01;    // Interrupt Ident: 0x01 = no interrupt, no FIFO
    reg [7:0] uart_lcr = 8'h00;    // Line Control Register
    reg [7:0] uart_mcr = 8'h00;    // Modem Control Register
    reg [7:0] uart_scr = 8'h00;    // Scratch Register
    reg        uart_fifo_en = 0;    // FIFO enabled flag

    // =========================================================================
    // External interrupt/timer inputs to CPU (driven as ports)
    // =========================================================================
    reg        timer_irq_pending_tb;
    reg [31:0] ext_irq_lines_tb;

    // CR16 write push output from CPU (ext isa_state push)
    wire [31:0] cr16_write_value;
    wire        cr16_write_valid;

    // EIRR (CR23) managed externally - testbench handles set/clear
    reg  [31:0] eirr_reg;
    wire [31:0] cr23_clear_value;
    wire        cr23_clear_valid;

    // =========================================================================
    // Reset and Entry Point
    // =========================================================================
    reg reset;
    integer reset_counter;
    reg [31:0] entry_point;
    integer max_cycles;

    // =========================================================================
    // HPPA CPU Instance
    // =========================================================================
    hppa cpu (
        .clk(clk),
        .reset(reset),

        // Reset state - boot stub entry
        .reset_pc(entry_point),

        // PSW: privileged mode, interrupts disabled (all zeros = safe)
        .reset_psw(32'h00000000),

        // Privilege level: 0 = most privileged (kernel)
        .reset_priv_level_rd(2'b00),

        // Control registers
        .reset_cr0_rd(32'h0),       // Recovery counter
        .reset_cr8_rd(32'h0),       // Protection ID 1
        .reset_cr9_rd(32'h0),       // Protection ID 2
        .reset_cr10_rd(32'h0),      // CCR
        .reset_cr14_rd(32'h0),      // IVA (Linux installs its own)
        .reset_cr15_rd(32'h0),      // EIEM = 0 (all interrupts masked)
        .reset_cr17_rd(32'h0),      // IIASQ front = 0
        .reset_cr17_back(32'h0),    // IIASQ back = 0
        .reset_cr18_rd(32'h0),      // IIAOQ front
        .reset_cr18_back(32'h0),    // IIAOQ back
        .reset_cr19_rd(32'h0),      // IIR
        .reset_cr20_rd(32'h0),      // ISR
        .reset_cr21_rd(32'h0),      // IOR
        .reset_cr22_rd(32'h0),      // IPSW
        .reset_cr24_rd(32'h0),      // TR0
        .reset_cr25_rd(32'h0),      // TR1
        .reset_cr26_rd(32'h0),      // TR2
        .reset_cr27_rd(32'h0),      // TR3
        .reset_cr28_rd(32'h0),      // TR4
        .reset_cr29_rd(32'h0),      // TR5
        .reset_cr30_rd(32'h0),      // TR6 (current task)
        .reset_cr31_rd(32'h0),      // TR7

        // SAR (shift amount)
        .reset_sar_rd(5'h0),

        // Space registers (all zero - flat address space)
        .reset_sr0_rd(32'h0),
        .reset_sr1_rd(32'h0),
        .reset_sr2_rd(32'h0),
        .reset_sr3_rd(32'h0),
        .reset_sr4_rd(32'h0),
        .reset_sr5_rd(32'h0),
        .reset_sr6_rd(32'h0),
        .reset_sr7_rd(32'h0),

        // TLB staging and replacement state (all zero at boot)
        .reset_dtlb_ins_pending_rd(1'b0),
        .reset_dtlb_ins_ppn(20'h0),
        .reset_dtlb_ins_space(32'h0),
        .reset_dtlb_ins_vpn(20'h0),
        .reset_dtlb_next_rd(4'h0),
        .reset_itlb_ins_pending_rd(1'b0),
        .reset_itlb_ins_ppn(20'h0),
        .reset_itlb_ins_space(32'h0),
        .reset_itlb_ins_vpn(20'h0),
        .reset_itlb_next_rd(4'h0),

        // FP status
        .reset_fpsr_rd(32'h0),

        // Shadow registers (PA-RISC 1.1 interruption shadows)
        .reset_shadow_r1(32'h0),
        .reset_shadow_r8(32'h0),
        .reset_shadow_r9(32'h0),
        .reset_shadow_r16(32'h0),
        .reset_shadow_r17(32'h0),
        .reset_shadow_r24(32'h0),
        .reset_shadow_r25(32'h0),

        // Delay slot / branch state
        .reset_delay_slot(1'b0),
        .reset_branch_target_rd(32'h0),
        .reset_branch_target_space_rd(32'h0),
        .reset_code_iasq(32'h0),

        // CR16 free-running cycle counter (ext isa_state - driven from testbench)
        .cr16_rd(timer_counter),
        .cr16_wr(timer_counter),

        // External interrupt inputs (driven from testbench)
        .timer_irq_pending_rd(timer_irq_pending_tb),
        .timer_irq_pending_wr(timer_irq_pending_tb),
        .ext_irq_lines_rd(ext_irq_lines_tb),
        .ext_irq_lines_wr(ext_irq_lines_tb),

        // EIRR (CR23) - externally managed (ext isa_state)
        .cr23_rd(eirr_reg),
        .cr23_wr(eirr_reg),

        // CR16 write push output (CPU -> testbench for timer compare)
        .cr16_write_rd(),              // unused _rd side of push
        .cr16_write_rd_valid(),        // unused _rd side valid
        .cr16_write_wr(cr16_write_value),
        .cr16_write_wr_valid(cr16_write_valid),

        // CR23 clear push output (CPU -> testbench for EIRR write-one-to-clear)
        .cr23_clear_rd(),              // unused _rd side of push
        .cr23_clear_rd_valid(),        // unused _rd side valid
        .cr23_clear_wr(cr23_clear_value),
        .cr23_clear_wr_valid(cr23_clear_valid)
    );

    // =========================================================================
    // Memory access helpers (tasks for 32-bit writes to 64-bit umem)
    // PA-RISC big-endian: addr[2]==0 -> upper [63:32], addr[2]==1 -> lower [31:0]
    // =========================================================================
    task write_mem32(input [31:0] addr, input [31:0] data);
        if (addr[2] == 1'b0)
            cpu.umem[addr[31:3]][63:32] = data;
        else
            cpu.umem[addr[31:3]][31:0] = data;
    endtask

    function automatic [31:0] read_mem32(input [31:0] addr);
        if (addr[2] == 1'b0)
            return cpu.umem[addr[31:3]][63:32];
        else
            return cpu.umem[addr[31:3]][31:0];
    endfunction

    // =========================================================================
    // Free-Running Timer Counter (CR16 is ext isa_state - driven via ports)
    // =========================================================================
    reg [31:0] timer_counter;
    reg [31:0] itmr_compare;
    reg        itmr_armed;

    always @(posedge clk) begin
        if (reset) begin
            timer_counter        <= 32'h0;
            itmr_compare         <= 32'hFFFFFFFF;
            itmr_armed           <= 1'b0;
            timer_irq_pending_tb <= 1'b0;
            ext_irq_lines_tb     <= 32'h0;
            eirr_reg             <= 32'h0;
        end else begin
            timer_counter        <= timer_counter + 1;
            timer_irq_pending_tb <= 1'b0;   // default: clear each cycle

            // EIRR write-one-to-clear from CPU (MTCTL to CR23 pushes clear mask)
            if (cr23_clear_valid)
                eirr_reg <= eirr_reg & ~cr23_clear_value;

            // Arm timer when CPU writes CR16 via MTCTL (push port)
            if (cr16_write_valid) begin
                itmr_compare <= cr16_write_value;
                itmr_armed   <= 1'b1;
            end

            // Timer fires: set EIRR bit 31 and assert timer_irq_pending
            if (itmr_armed && timer_counter == itmr_compare) begin
                eirr_reg             <= eirr_reg | 32'h80000000;
                timer_irq_pending_tb <= 1'b1;   // pulse for one cycle
                itmr_armed           <= 1'b0;
            end
        end
    end

    // =========================================================================
    // UART Monitor - intercept writes to UART TX register
    // =========================================================================
    wire store_enable = cpu.umem_write_enable;
    wire [31:0] cpu_write_addr = cpu.umem_write_addr_mux;
    wire [63:0] cpu_write_data64 = cpu.umem_write_data_mux;

    integer uart_fd;
    initial begin
        uart_fd = $fopen("uart_output.txt", "w");
    end
    final begin
        if (uart_fd) $fclose(uart_fd);
    end

    always @(posedge clk) begin
        if (!reset && store_enable && cpu_write_addr == UART_THR) begin
            // Big-endian PA-RISC with big-endian word order:
            // UART_THR addr[2]=0 → upper word [63:32], byte_offset=0 → bits[63:56]
            if (cpu_write_data64[63:56] >= 8'h20 && cpu_write_data64[63:56] <= 8'h7E ||
                cpu_write_data64[63:56] == 8'h0A || cpu_write_data64[63:56] == 8'h0D) begin
                $write("%c", cpu_write_data64[63:56]);
                $fflush();
                $fwrite(uart_fd, "%c", cpu_write_data64[63:56]);
                $fflush(uart_fd);
            end else if (cpu_write_data64[39:32] >= 8'h20 && cpu_write_data64[39:32] <= 8'h7E ||
                         cpu_write_data64[39:32] == 8'h0A || cpu_write_data64[39:32] == 8'h0D) begin
                // Fallback: try bits[39:32] (word store, byte at [7:0] of upper word)
                $write("%c", cpu_write_data64[39:32]);
                $fflush();
                $fwrite(uart_fd, "%c", cpu_write_data64[39:32]);
                $fflush(uart_fd);
            end
        end
        // Handle UART register writes (for 8250 autodetect support)
        // Extract write byte: big-endian, addr[2]=0 → bits[63:56], addr[2]=1 → bits[31:24]
        // Uses BLOCKING assignments so the umem mirror (below) sees updated values
        // in the same clock cycle — critical for 8250 autoconfig scratch test.
        if (!reset && store_enable && cpu_write_addr[31:12] == 20'h03F00) begin
            reg [7:0] wr_byte;
            wr_byte = cpu_write_addr[2] ? cpu_write_data64[31:24] : cpu_write_data64[63:56];
            case (cpu_write_addr & 32'h03F000FC)
                UART_IER: uart_ier = wr_byte & 8'h0F;  // only low 4 bits writable
                UART_IIR: begin  // Write goes to FCR
                    uart_fifo_en = wr_byte[0];
                    // IIR reflects FIFO status: bits[7:6]=11 when FIFO enabled
                    uart_iir = wr_byte[0] ? 8'hC1 : 8'h01;
                end
                UART_LCR: uart_lcr = wr_byte;
                UART_MCR: uart_mcr = wr_byte;
                UART_SCR: uart_scr = wr_byte;
                default: ;
            endcase
        end

        // Mirror UART registers into umem for CPU reads (same always block).
        // Uses blocking assignments so values written above are immediately
        // visible to CPU loads on the next cycle.
        //
        // BYTE ORDER: PA-RISC is big-endian but UPIO_MEM32 uses writel/readl
        // which do cpu_to_le32/le32_to_cpu byte swaps. So a register value
        // 0xAB is stored in memory as 0xAB000000 (value in MSB of 32-bit word).
        // The mirror must match: {byte, 24'h0} not {24'h0, byte}.
        //
        // NS16550A register layout with reg-shift=2:
        //   umem[(base>>3)+0]: [63:32]=THR/RBR(+0x00)  [31:0]=IER(+0x04)
        //   umem[(base>>3)+1]: [63:32]=IIR(+0x08)      [31:0]=LCR(+0x0C)
        //   umem[(base>>3)+2]: [63:32]=MCR(+0x10)       [31:0]=LSR(+0x14)
        //   umem[(base>>3)+3]: [63:32]=MSR(+0x18)       [31:0]=SCR(+0x1C)
        if (!reset) begin
            cpu.umem[UART_UMEM_BASE + 32'h0][63:32] = 32'h00000000;
            cpu.umem[UART_UMEM_BASE + 32'h0][31:0]  = {uart_ier, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h1][63:32] = {uart_iir, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h1][31:0]  = {uart_lcr, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h2][63:32] = {uart_mcr, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h2][31:0]  = {8'h60, 24'h0};
            // MSR: in loopback mode (MCR[4]), reflect MCR outputs to MSR inputs
            // MCR[3](OUT2)→MSR[7](DCD), MCR[2](OUT1)→MSR[6](RI),
            // MCR[0](DTR)→MSR[5](DSR), MCR[1](RTS)→MSR[4](CTS)
            cpu.umem[UART_UMEM_BASE + 32'h3][63:32] = uart_mcr[4] ?
                {uart_mcr[3], uart_mcr[2], uart_mcr[0], uart_mcr[1], 4'b0000, 24'h0} :
                32'h00000000;
            cpu.umem[UART_UMEM_BASE + 32'h3][31:0]  = {uart_scr, 24'h0};
        end
    end

    // =========================================================================
    // Kernel Debug Locks Disable
    // =========================================================================
    // Set debug_locks=0 at startup to prevent infinite lock-debug error loops.
    // debug_locks is at virtual 0x1100c464 = physical 0x100c464.
    // In umem (64-bit word indexed): addr[31:3]=0x100c464>>3=0x20188c, addr[2]=1.
    initial begin
        @(negedge reset);
        cpu.umem[32'h20188c][31:0] = 32'h0;  // debug_locks = 0
    end

    // =========================================================================
    // Simulation Monitor
    // =========================================================================
    integer cycle_count;
    reg [31:0] last_pc;
    reg [31:0] stuck_counter;
    reg initialized;

    always @(posedge clk) begin
        if (!initialized) begin
            reset         <= 1'b1;
            reset_counter <= 10;
            cycle_count   <= 0;
            initialized   <= 1'b1;
            stuck_counter <= 0;
        end else if (reset_counter > 0) begin
            reset_counter <= reset_counter - 1;
            if (reset_counter == 1) begin
                reset <= 1'b0;
                $display("");
                $display("=== HPPA Linux Boot Started ===");
            end
        end else begin
            cycle_count <= cycle_count + 1;
            last_pc     <= cpu.pc_rd;

            // Periodic progress report
            if ((cycle_count < 1000000 && cycle_count % 100000 == 0 && cycle_count > 0) ||
                (cycle_count >= 1000000 && cycle_count % 5000000 == 0)) begin
                $display("[%0d] PROGRESS: PC=%08x PSW=%08x SP=%08x",
                         cycle_count, cpu.pc_rd, cpu.psw, cpu.rf[30]);
                $fflush();
            end

            // Exception trace
            if (cpu.add_exception_taken) begin
                $display("[%0d] EXCEPTION: trap=%0d PC=%08x PSW=%08x CR18=%08x",
                         cycle_count, cpu.exception_trap_number,
                         cpu.pc_rd, cpu.psw, cpu.cr18_rd);
            end

            // Stuck-at detector: if PC doesn't change for 1000 cycles, dump state
            if (cpu.pc_rd == last_pc && cycle_count > 1000000) begin
                if (stuck_counter < 32'd1002) stuck_counter <= stuck_counter + 1;
                if (stuck_counter == 32'd1000) begin
                    $display("[%0d] STUCK_AT: PC=%08x PSW=%08x R2=%08x SP=%08x",
                             cycle_count, cpu.pc_rd, cpu.psw, cpu.rf[2], cpu.rf[30]);
                    $fflush();
                end
            end else begin
                stuck_counter <= 0;
            end

            // Timeout
            if (cycle_count >= max_cycles) begin
                $display("");
                $display("=== Simulation Timeout (%0d cycles) ===", max_cycles);
                $display("Final PC: 0x%08x PSW: 0x%08x", cpu.pc_rd, cpu.psw);
                $display("Regs: R1=%08x R2=%08x R26=%08x R28=%08x SP=%08x",
                         cpu.rf[1], cpu.rf[2], cpu.rf[26], cpu.rf[28], cpu.rf[30]);
                $finish;
            end
        end
    end

    // =========================================================================
    // Boot Image Loading
    // =========================================================================
    integer boot_file, fdt_file, initrd_file;
    integer bytes_read;
    reg [7:0] byte_data;
    integer i, j;
    string boot_path, fdt_path, initrd_path, firmware_path;
    integer word_count, fdt_word_count, initrd_word_count;

    initial begin
        initialized           = 0;
        reset                 = 1;
        reset_counter         = 10;
        cycle_count           = 0;
        timer_irq_pending_tb  = 0;
        ext_irq_lines_tb      = 0;
        eirr_reg              = 0;

        // Get cycle limit from plusargs (default 200M)
        if (!$value$plusargs("cycles=%d", max_cycles))
            max_cycles = 200000000;

        // Get entry point from plusargs
        if (!$value$plusargs("entry=%h", entry_point))
            entry_point = BOOT_STUB_ADDR;

        // Get boot image path
        if (!$value$plusargs("boot=%s", boot_path))
            boot_path = "boot.bin";

        // Get FDT path
        if (!$value$plusargs("fdt=%s", fdt_path))
            fdt_path = "hppa_isacomp.dtb";

        // Get initrd path (optional)
        if (!$value$plusargs("initrd=%s", initrd_path))
            initrd_path = "";

        // Get firmware path
        if (!$value$plusargs("firmware=%s", firmware_path))
            firmware_path = "firmware.bin";

        $display("===========================================");
        $display("HPPA (PA-RISC 1.1) Linux Boot Simulation");
        $display("===========================================");
        $display("Boot image: %s", boot_path);
        $display("FDT:        %s", fdt_path);
        $display("Entry:      0x%08x", entry_point);
        $display("===========================================");

        // =====================================================================
        // Load boot image into CPU unified memory (64-bit words, big-endian)
        // =====================================================================
        boot_file = $fopen(boot_path, "rb");
        if (boot_file == 0) begin
            $display("ERROR: Cannot open boot image: %s", boot_path);
            $finish;
        end

        word_count = 0;
        while (!$feof(boot_file)) begin
            // Upper 32-bit half [63:32]: bytes 0-3 big-endian
            for (j = 7; j >= 4; j = j - 1) begin
                bytes_read = $fread(byte_data, boot_file);
                if (bytes_read == 1)
                    cpu.umem[word_count][j*8 +: 8] = byte_data;
            end
            // Lower 32-bit half [31:0]: bytes 4-7 big-endian
            for (j = 3; j >= 0; j = j - 1) begin
                bytes_read = $fread(byte_data, boot_file);
                if (bytes_read == 1)
                    cpu.umem[word_count][j*8 +: 8] = byte_data;
            end
            word_count = word_count + 1;
        end
        $fclose(boot_file);
        $display("Loaded boot image: %0d 64-bit words (%0d KB)",
                 word_count, (word_count * 8) / 1024);

        // Load FDT (device tree blob)
        fdt_file = $fopen(fdt_path, "rb");
        if (fdt_file == 0) begin
            $display("WARNING: Cannot open FDT: %s (continuing without FDT)", fdt_path);
        end else begin
            fdt_word_count = FDT_ADDR >> 3;
            while (!$feof(fdt_file)) begin
                for (j = 7; j >= 4; j = j - 1) begin
                    bytes_read = $fread(byte_data, fdt_file);
                    if (bytes_read == 1)
                        cpu.umem[fdt_word_count][j*8 +: 8] = byte_data;
                end
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, fdt_file);
                    if (bytes_read == 1)
                        cpu.umem[fdt_word_count][j*8 +: 8] = byte_data;
                end
                fdt_word_count = fdt_word_count + 1;
            end
            $fclose(fdt_file);
            $display("Loaded FDT: %0d words at 0x%08x",
                     fdt_word_count - (FDT_ADDR >> 3), FDT_ADDR);
            $display("FDT magic: 0x%08x (expect 0xd00dfeed)",
                     cpu.umem[FDT_ADDR >> 3][63:32]);
        end

        // Load initrd if specified
        if (initrd_path != "") begin
            initrd_file = $fopen(initrd_path, "rb");
            if (initrd_file == 0) begin
                $display("ERROR: Cannot open initrd: %s", initrd_path);
                $finish;
            end
            initrd_word_count = INITRD_BASE >> 3;
            while (!$feof(initrd_file)) begin
                for (j = 7; j >= 4; j = j - 1) begin
                    bytes_read = $fread(byte_data, initrd_file);
                    if (bytes_read == 1)
                        cpu.umem[initrd_word_count][j*8 +: 8] = byte_data;
                end
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, initrd_file);
                    if (bytes_read == 1)
                        cpu.umem[initrd_word_count][j*8 +: 8] = byte_data;
                end
                initrd_word_count = initrd_word_count + 1;
            end
            $fclose(initrd_file);
            $display("Loaded initrd: %0d words at 0x%08x",
                     initrd_word_count - (INITRD_BASE >> 3), INITRD_BASE);
        end

        // =====================================================================
        // Load firmware (PDC/IODC) into ROM area at 0x0F000000
        // =====================================================================
        begin
            integer fw_file, fw_word_count;
            fw_file = $fopen(firmware_path, "rb");
            if (fw_file == 0) begin
                $display("ERROR: Cannot open firmware: %s", firmware_path);
                $finish;
            end
            fw_word_count = PDC_STUB_ADDR >> 3;
            while (!$feof(fw_file)) begin
                for (j = 7; j >= 4; j = j - 1) begin
                    bytes_read = $fread(byte_data, fw_file);
                    if (bytes_read == 1)
                        cpu.umem[fw_word_count][j*8 +: 8] = byte_data;
                end
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, fw_file);
                    if (bytes_read == 1)
                        cpu.umem[fw_word_count][j*8 +: 8] = byte_data;
                end
                fw_word_count = fw_word_count + 1;
            end
            $fclose(fw_file);
            $display("Loaded firmware: %0d words at 0x%08x",
                     fw_word_count - (PDC_STUB_ADDR >> 3), PDC_STUB_ADDR);
        end

        // =====================================================================
        // Page Zero dynamic fields
        // =====================================================================
        if (initrd_path != "") begin
            write_mem32(32'h394, INITRD_BASE);
            write_mem32(32'h398, INITRD_BASE +
                        (initrd_word_count - (INITRD_BASE >> 3)) * 8);
        end

        // Display memory layout
        $display("-------------------------------------------");
        $display("Memory Layout:");
        $display("  0x%08x - Page Zero", PAGE_ZERO);
        $display("  0x%08x - FDT", FDT_ADDR);
        $display("  0x%08x - Boot stub (entry)", entry_point);
        $display("  0x%08x - PDC firmware (ROM)", PDC_STUB_ADDR);
        $display("  0x%08x - IODC firmware (ROM)", IODC_STUB_ADDR);
        $display("  0x%08x - Kernel load address", KERNEL_LOAD);
        if (initrd_path != "")
            $display("  0x%08x - Initrd", INITRD_BASE);
        $display("  0x%08x - UART", UART_BASE);
        $display("  0x%08x - RAM end", MEMORY_BASE + MEMORY_SIZE - 1);
        $display("-------------------------------------------");

        // Verify boot stub entry
        $display("Boot stub entry:");
        $display("  [0x%08x] = 0x%08x", entry_point, read_mem32(entry_point));
        $display("  [0x%08x] = 0x%08x", entry_point + 32'd4, read_mem32(entry_point + 32'd4));
        $display("Firmware at PDC entry (0x%08x):", PDC_STUB_ADDR);
        $display("  [0x%08x] = 0x%08x %08x", PDC_STUB_ADDR,
                 cpu.umem[PDC_STUB_ADDR >> 3][63:32], cpu.umem[PDC_STUB_ADDR >> 3][31:0]);
    end

    // =========================================================================
    // Waveform Dumping
    // =========================================================================
    initial begin
        if ($test$plusargs("trace")) begin
            $dumpfile("hppa_boot.vcd");
            $dumpvars(0, hppa_boot_tb);
        end
    end

endmodule
