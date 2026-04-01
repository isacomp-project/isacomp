// M68K Linux Boot Testbench with Goldfish Peripherals
// Loads and boots Linux kernel in Verilator simulation
//
// Memory Map:
//   0x00000000 - 0x03FFFFFF: Main RAM (64MB)
//   0x04000000 - 0x04005FFF: Goldfish PICs (6 x 4KB, one per IPL level)
//   0x04006000 - 0x04006FFF: Goldfish Timer (RTC)
//   0x04007000 - 0x04007FFF: Goldfish RTC (wall clock, registered by virt/platform.c)
//   0x04008000 - 0x04008FFF: Goldfish TTY (console)
//
// Interrupt routing:
//   PIC #0 (0x04000000) -> IPL 1 : TTY
//   PIC #1 (0x04001000) -> IPL 2 : Virtio 1-32 (unused)
//   PIC #2 (0x04002000) -> IPL 3 : Virtio 33-64 (unused)
//   PIC #3 (0x04003000) -> IPL 4 : Virtio 65-96 (unused)
//   PIC #4 (0x04004000) -> IPL 5 : Virtio 97-128 (unused)
//   PIC #5 (0x04005000) -> IPL 6 : Timer, RTC

`timescale 1ns/1ps

module m68k_linux_boot_tb;

    // Clock generation
    reg clk = 0;
    always #10 clk = ~clk;  // 50 MHz (20ns period)

    // Reset control
    reg reset;
    reg [7:0] reset_counter;

    // Memory layout
    localparam MEMORY_BASE     = 32'h00000000;
    localparam MEMORY_SIZE     = 32'h04000000;  // 64MB

    // Goldfish device base addresses
    localparam GF_PIC_BASE     = 32'h04000000;  // 6 PICs, 0x1000 apart
    localparam GF_TIMER_BASE   = 32'h04006000;
    localparam GF_RTC_BASE     = 32'h04007000;
    localparam GF_TTY_BASE     = 32'h04008000;
    localparam GF_MMIO_END     = 32'h0401a000;  // past virtio range

    // Bootinfo (at kernel _end address, matching gen_hex.py)
    localparam BOOTINFO_ADDR   = 32'h001ae000;
    localparam BOOTINFO_DMEM   = BOOTINFO_ADDR >> 2;  // dmem word index (32-bit)

    // Entry point from command line
    reg [31:0] entry_point;
    reg [31:0] initial_ssp;

    // =========================================================================
    // Goldfish PIC Instances (6 PICs, one per autovector level)
    // =========================================================================
    wire [5:0]  pic_irq_out;
    reg  [4:0]  pic_reg_addr [0:5];
    reg  [31:0] pic_wdata    [0:5];
    reg         pic_we       [0:5];
    wire [31:0] pic_irq_sources [0:5];

    // Collect internal state for dmem mirroring
    wire [5:0]  pic_active_count [0:5];
    wire [31:0] pic_active_irqs  [0:5];

    // Timer IRQ
    wire timer_irq;
    // TTY IRQ (unused for now)
    wire tty_irq = 1'b0;

    // PIC interrupt source routing
    assign pic_irq_sources[0] = {31'd0, tty_irq};     // IPL 1: TTY
    assign pic_irq_sources[1] = 32'd0;                 // IPL 2: Virtio (unused)
    assign pic_irq_sources[2] = 32'd0;                 // IPL 3: Virtio (unused)
    assign pic_irq_sources[3] = 32'd0;                 // IPL 4: Virtio (unused)
    assign pic_irq_sources[4] = 32'd0;                 // IPL 5: Virtio (unused)
    assign pic_irq_sources[5] = {31'd0, timer_irq};           // IPL 6: Timer on bit 0 (IRQ 168 = IRQ_USER + 5*32)

    genvar gi;
    generate
        for (gi = 0; gi < 6; gi = gi + 1) begin : pic_inst
            goldfish_pic pic (
                .clk(clk),
                .reset(reset),
                .reg_addr(pic_reg_addr[gi]),
                .wdata(pic_wdata[gi]),
                .we(pic_we[gi]),
                .re(1'b0),
                .rdata(),
                .irq_sources(pic_irq_sources[gi]),
                .irq_out(pic_irq_out[gi])
            );
            assign pic_active_count[gi] = pic_inst[gi].pic.active_count;
            assign pic_active_irqs[gi]  = pic_inst[gi].pic.active_irqs;
        end
    endgenerate

    // IPL priority encoder: highest active PIC level wins
    wire [2:0] cpu_ipl;
    assign cpu_ipl = pic_irq_out[5] ? 3'd6 :
                     pic_irq_out[4] ? 3'd5 :
                     pic_irq_out[3] ? 3'd4 :
                     pic_irq_out[2] ? 3'd3 :
                     pic_irq_out[1] ? 3'd2 :
                     pic_irq_out[0] ? 3'd1 : 3'd0;

    // =========================================================================
    // Goldfish Timer
    // =========================================================================
    reg  [4:0]  timer_reg_addr;
    reg  [31:0] timer_wdata;
    reg         timer_we;
    wire [31:0] timer_rdata;

    goldfish_timer #(
        .CLK_PERIOD_NS(20)  // 50 MHz clock
    ) timer (
        .clk(clk),
        .reset(reset),
        .reg_addr(timer_reg_addr),
        .wdata(timer_wdata),
        .we(timer_we),
        .re(1'b0),
        .rdata(timer_rdata),
        .irq(timer_irq)
    );

    // =========================================================================
    // Goldfish TTY State (handled in testbench, no separate module)
    // =========================================================================
    reg [31:0] tty_data_ptr;
    reg [31:0] tty_data_len;
    reg [31:0] tty_version;  // Always 1

    // =========================================================================
    // M68K Processor Core
    // =========================================================================
    cpu_m68k_linux cpu (
        .clk(clk),
        .reset(reset),
        .reset_pc(entry_point),
        .reset_flag_C(1'b0),
        .reset_flag_N(1'b0),
        .reset_flag_V(1'b0),
        .reset_flag_X(1'b0),
        .reset_flag_Z(1'b0),
        .reset_sr(16'h2700),          // S=1, IPL mask=7
        .reset_vbr_rd(32'h00000000),
        .reset_ssp(32'h03FFFFF0),
        .reset_usp(32'h00000000),
        .reset_msp_rd(32'h00000000),
        .reset_caar_rd(32'h00000000),
        .reset_cacr_rd(32'h00000000),
        .reset_sfc_rd(3'b000),
        .reset_dfc_rd(3'b000),
        .reset_crp_rd(64'h0),
        .reset_srp_rd(64'h0),
        .reset_halted_rd(1'b0),
        .reset_mmusr(16'h0),
        .reset_tc_rd(32'h0),
        .reset_tt0_rd(32'h0400C080),  // TT0: transparent map 0x04xxxxxx (supervisor, CI)
        .reset_tt1_rd(32'h0),
        .ipl_rd(cpu_ipl),
        .ipl_wr(cpu_ipl)
    );

    // =========================================================================
    // Memory Write Detection
    // =========================================================================
    // Standard write ports: unsuffixed + _1 through _21
    // (Data exception frame push now goes through regular m68k_exception)
    localparam NUM_PORTS = 28;

    wire [31:0] wr_addr [0:NUM_PORTS-1];
    wire [31:0] wr_data [0:NUM_PORTS-1];
    wire        wr_en   [0:NUM_PORTS-1];

    // Standard ports
    assign wr_addr[0]  = cpu.dmem_write_addr_mux;     assign wr_data[0]  = cpu.dmem_write_data_mux;                    assign wr_en[0]  = cpu.dmem_write_enable;
    assign wr_addr[1]  = cpu.dmem_write_addr_mux_1;   assign wr_data[1]  = cpu.dmem_write_data_mux_1;                  assign wr_en[1]  = cpu.dmem_write_enable_1;
    assign wr_addr[2]  = cpu.dmem_write_addr_mux_2;   assign wr_data[2]  = cpu.dmem_write_data_mux_2;                  assign wr_en[2]  = cpu.dmem_write_enable_2;
    assign wr_addr[3]  = cpu.dmem_write_addr_mux_3;   assign wr_data[3]  = cpu.dmem_write_data_mux_3;                  assign wr_en[3]  = cpu.dmem_write_enable_3;
    assign wr_addr[4]  = cpu.dmem_write_addr_mux_4;   assign wr_data[4]  = cpu.dmem_write_data_mux_4;                  assign wr_en[4]  = cpu.dmem_write_enable_4;
    assign wr_addr[5]  = cpu.dmem_write_addr_mux_5;   assign wr_data[5]  = cpu.dmem_write_data_mux_5;                  assign wr_en[5]  = cpu.dmem_write_enable_5;
    assign wr_addr[6]  = cpu.dmem_write_addr_mux_6;   assign wr_data[6]  = cpu.dmem_write_data_mux_6;                  assign wr_en[6]  = cpu.dmem_write_enable_6;
    assign wr_addr[7]  = cpu.dmem_write_addr_mux_7;   assign wr_data[7]  = cpu.dmem_write_data_mux_7;                  assign wr_en[7]  = cpu.dmem_write_enable_7;
    assign wr_addr[8]  = cpu.dmem_write_addr_mux_8;   assign wr_data[8]  = cpu.dmem_write_data_mux_8;                  assign wr_en[8]  = cpu.dmem_write_enable_8;
    assign wr_addr[9]  = cpu.dmem_write_addr_mux_9;   assign wr_data[9]  = cpu.dmem_write_data_mux_9;                  assign wr_en[9]  = cpu.dmem_write_enable_9;
    assign wr_addr[10] = cpu.dmem_write_addr_mux_10;  assign wr_data[10] = cpu.dmem_write_data_mux_10;                 assign wr_en[10] = cpu.dmem_write_enable_10;
    assign wr_addr[11] = cpu.dmem_write_addr_mux_11;  assign wr_data[11] = cpu.dmem_write_data_mux_11;                 assign wr_en[11] = cpu.dmem_write_enable_11;
    assign wr_addr[12] = cpu.dmem_write_addr_mux_12;  assign wr_data[12] = cpu.dmem_write_data_mux_12;                 assign wr_en[12] = cpu.dmem_write_enable_12;
    assign wr_addr[13] = cpu.dmem_write_addr_mux_13;  assign wr_data[13] = cpu.dmem_write_data_mux_13;                 assign wr_en[13] = cpu.dmem_write_enable_13;
    assign wr_addr[14] = cpu.dmem_write_addr_mux_14;  assign wr_data[14] = cpu.dmem_write_data_mux_14;                 assign wr_en[14] = cpu.dmem_write_enable_14;
    assign wr_addr[15] = cpu.dmem_write_addr_mux_15;  assign wr_data[15] = cpu.dmem_write_data_mux_15;                 assign wr_en[15] = cpu.dmem_write_enable_15;
    assign wr_addr[16] = cpu.dmem_write_addr_mux_16;  assign wr_data[16] = cpu.dmem_write_data_mux_16;                 assign wr_en[16] = cpu.dmem_write_enable_16;
    assign wr_addr[17] = cpu.dmem_write_addr_mux_17;  assign wr_data[17] = cpu.dmem_write_data_mux_17;                 assign wr_en[17] = cpu.dmem_write_enable_17;
    assign wr_addr[18] = cpu.dmem_write_addr_mux_18;  assign wr_data[18] = cpu.dmem_write_data_mux_18;                 assign wr_en[18] = cpu.dmem_write_enable_18;
    assign wr_addr[19] = cpu.dmem_write_addr_mux_19;  assign wr_data[19] = cpu.dmem_write_data_mux_19;                 assign wr_en[19] = cpu.dmem_write_enable_19;
    assign wr_addr[20] = cpu.dmem_write_addr_mux_20;  assign wr_data[20] = cpu.dmem_write_data_mux_20;                 assign wr_en[20] = cpu.dmem_write_enable_20;
    assign wr_addr[21] = cpu.dmem_write_addr_mux_21;  assign wr_data[21] = cpu.dmem_write_data_mux_21;                 assign wr_en[21] = cpu.dmem_write_enable_21;
    assign wr_addr[22] = cpu.dmem_write_addr_mux_22;  assign wr_data[22] = cpu.dmem_write_data_mux_22;                 assign wr_en[22] = cpu.dmem_write_enable_22;
    assign wr_addr[23] = cpu.dmem_write_addr_mux_23;  assign wr_data[23] = 32'b0;                                      assign wr_en[23] = cpu.dmem_write_enable_23;
    assign wr_addr[24] = cpu.dmem_write_addr_mux_24;  assign wr_data[24] = cpu.dmem_write_data_mux_24;                 assign wr_en[24] = cpu.dmem_write_enable_24;
    assign wr_addr[25] = cpu.dmem_write_addr_mux_25;  assign wr_data[25] = 32'b0;                                      assign wr_en[25] = cpu.dmem_write_enable_25;
    assign wr_addr[26] = cpu.dmem_write_addr_mux_26;  assign wr_data[26] = 32'b0;                                      assign wr_en[26] = cpu.dmem_write_enable_26;
    assign wr_addr[27] = cpu.dmem_write_addr_mux_27;  assign wr_data[27] = 32'b0;                                      assign wr_en[27] = cpu.dmem_write_enable_27;

    // =========================================================================
    // MMIO Write Detection
    // =========================================================================
    // Data muxes are now 32-bit. A MOVE.L produces a full 32-bit write on
    // a single port. We detect and forward the 32-bit value here.
    reg        mmio_wr_valid;
    reg [31:0] mmio_wr_addr;   // 4-byte aligned register address
    reg [31:0] mmio_wr_data;   // Reconstructed 32-bit write data
    // Also detect any IO write for logging
    reg        io_hit;
    reg [31:0] io_hit_addr;
    reg [31:0] io_hit_data;
    integer wp;

    // Count MMIO contributing ports for debug
    integer mmio_port_count;
    reg [31:0] mmio_port_mask;  // bitmask of contributing ports

    always @* begin
        mmio_wr_valid = 0;
        mmio_wr_addr  = 32'd0;
        mmio_wr_data  = 32'd0;
        io_hit = 0;
        io_hit_addr = 32'd0;
        io_hit_data = 32'd0;
        mmio_port_count = 0;
        mmio_port_mask = 32'd0;

        for (wp = 0; wp < NUM_PORTS; wp = wp + 1) begin
            if (wr_en[wp] && wr_addr[wp] >= GF_PIC_BASE && wr_addr[wp] < GF_MMIO_END) begin
                mmio_wr_valid = 1;
                mmio_wr_addr = {wr_addr[wp][31:2], 2'b00};
                // OR data from all matching ports to reconstruct full 32-bit
                // value from two 16-bit writes (MOVE.L splits into upper/lower
                // half writes with positioned data in non-overlapping lanes).
                mmio_wr_data = mmio_wr_data | wr_data[wp];
                mmio_port_count = mmio_port_count + 1;
                mmio_port_mask = mmio_port_mask | (32'd1 << wp);
            end
            // Broader check: any write above RAM
            if (wr_en[wp] && wr_addr[wp] >= 32'h04000000) begin
                io_hit = 1;
                io_hit_addr = wr_addr[wp];
                io_hit_data = io_hit_data | wr_data[wp];
            end
        end
    end

    // Device selection from reconstructed address
    wire [31:0] mmio_dev_offset = mmio_wr_addr - GF_PIC_BASE;
    wire [2:0]  mmio_pic_idx    = mmio_dev_offset[14:12];
    wire        mmio_is_pic     = mmio_wr_valid && (mmio_wr_addr >= GF_PIC_BASE) && (mmio_wr_addr < GF_PIC_BASE + 32'h6000);
    wire        mmio_is_timer   = mmio_wr_valid && (mmio_wr_addr >= GF_TIMER_BASE) && (mmio_wr_addr < GF_TIMER_BASE + 32'h1000);
    wire        mmio_is_rtc     = mmio_wr_valid && (mmio_wr_addr >= GF_RTC_BASE) && (mmio_wr_addr < GF_RTC_BASE + 32'h1000);
    wire        mmio_is_tty     = mmio_wr_valid && (mmio_wr_addr >= GF_TTY_BASE) && (mmio_wr_addr < GF_TTY_BASE + 32'h1000);

    // =========================================================================
    // MMIO Write Forwarding to Goldfish Devices
    // =========================================================================
    integer i;
    always @(posedge clk) begin
        // Default: deassert all write enables
        for (i = 0; i < 6; i = i + 1) begin
            pic_we[i] <= 0;
            pic_reg_addr[i] <= 5'd0;
            pic_wdata[i] <= 32'd0;
        end
        timer_we <= 0;
        timer_reg_addr <= 5'd0;
        timer_wdata <= 32'd0;

        // DEBUG: log MMIO writes to timer/PIC (disabled to reduce output)
        //if (!reset && io_hit && io_hit_addr < 32'h04007000) begin
        //    $display("[%0d] IO_HIT: addr=0x%08x data=0x%08x PC=0x%08x",
        //             cycle_count, io_hit_addr, io_hit_data, cpu.pc_rd);
        //end

        if (!reset && mmio_wr_valid) begin
            if (mmio_is_pic && mmio_pic_idx < 6) begin
                pic_reg_addr[mmio_pic_idx] <= mmio_wr_addr[4:0];
                pic_wdata[mmio_pic_idx]    <= mmio_wr_data;
                pic_we[mmio_pic_idx]       <= 1;
            end else if (mmio_is_timer) begin
                timer_reg_addr <= mmio_wr_addr[4:0];
                timer_wdata    <= mmio_wr_data;
                timer_we       <= 1;
                // TIMER WRITE trace disabled to reduce output
                //  $display("[%0d] TIMER WRITE: reg=0x%02x data=0x%08x PC=0x%08x tmr_ns=0x%016x armed=%0d pending=%0d",
                //           cycle_count, mmio_wr_addr[4:0], mmio_wr_data, cpu.pc_rd,
                //           timer.current_time, timer.alarm_armed, timer.irq_pending);
            end
            // TTY writes handled in the TTY output section below
        end
    end

    // =========================================================================
    // MMIO Read Value Mirroring into CPU dmem
    // =========================================================================
    // dmem is 32-bit, indexed by (byte_addr >> 2)
    // Each 32-bit device register maps to one dmem word

    // PIC dmem base indices (byte_addr >> 2)
    localparam PIC0_DMEM = (GF_PIC_BASE) >> 2;
    localparam PIC1_DMEM = (GF_PIC_BASE + 32'h1000) >> 2;
    localparam PIC2_DMEM = (GF_PIC_BASE + 32'h2000) >> 2;
    localparam PIC3_DMEM = (GF_PIC_BASE + 32'h3000) >> 2;
    localparam PIC4_DMEM = (GF_PIC_BASE + 32'h4000) >> 2;
    localparam PIC5_DMEM = (GF_PIC_BASE + 32'h5000) >> 2;

    // Timer dmem base index
    localparam TMR_DMEM  = GF_TIMER_BASE >> 2;

    // Goldfish RTC dmem base index
    localparam RTC_DMEM  = GF_RTC_BASE >> 2;

    // TTY dmem base index
    localparam TTY_DMEM  = GF_TTY_BASE >> 2;

    always @(posedge clk) begin
        if (!reset) begin
            // --- PIC #0 (IPL 1) ---
            // STATUS (0x00): active interrupt count
            cpu.dmem[PIC0_DMEM]     <= {26'd0, pic_active_count[0]};
            // IRQ_PENDING (0x04): pending & enabled (matches QEMU)
            cpu.dmem[PIC0_DMEM + 1] <= pic_active_irqs[0];

            // --- PIC #1 (IPL 2) ---
            cpu.dmem[PIC1_DMEM]     <= {26'd0, pic_active_count[1]};
            cpu.dmem[PIC1_DMEM + 1] <= pic_active_irqs[1];

            // --- PIC #2 (IPL 3) ---
            cpu.dmem[PIC2_DMEM]     <= {26'd0, pic_active_count[2]};
            cpu.dmem[PIC2_DMEM + 1] <= pic_active_irqs[2];

            // --- PIC #3 (IPL 4) ---
            cpu.dmem[PIC3_DMEM]     <= {26'd0, pic_active_count[3]};
            cpu.dmem[PIC3_DMEM + 1] <= pic_active_irqs[3];

            // --- PIC #4 (IPL 5) ---
            cpu.dmem[PIC4_DMEM]     <= {26'd0, pic_active_count[4]};
            cpu.dmem[PIC4_DMEM + 1] <= pic_active_irqs[4];

            // --- PIC #5 (IPL 6) ---
            cpu.dmem[PIC5_DMEM]     <= {26'd0, pic_active_count[5]};
            cpu.dmem[PIC5_DMEM + 1] <= pic_active_irqs[5];

            // --- Timer ---
            // TIME_LOW (0x00): current_time[31:0]
            cpu.dmem[TMR_DMEM]      <= timer.current_time[31:0];
            // TIME_HIGH (0x04): current_time[63:32]
            cpu.dmem[TMR_DMEM + 1]  <= timer.current_time[63:32];
            // ALARM_STATUS (0x18): armed flag (offset 0x18 >> 2 = +6)
            cpu.dmem[TMR_DMEM + 6]  <= {31'd0, timer.alarm_armed};

            // --- Goldfish RTC ---
            // TIME_LOW (0x00): current wall-clock time low 32 bits (nanoseconds)
            // Use timer.current_time as wall-clock proxy (monotonic, good enough)
            cpu.dmem[RTC_DMEM]      <= timer.current_time[31:0];
            // TIME_HIGH (0x04): current wall-clock time high 32 bits
            cpu.dmem[RTC_DMEM + 1]  <= timer.current_time[63:32];
            // ALARM_LOW (0x08): not used in read path
            // ALARM_HIGH (0x0C): not used in read path
            // IRQ_ENABLED (0x10): 0 (no RTC IRQ)
            cpu.dmem[RTC_DMEM + 4]  <= 32'd0;
            // ALARM_STATUS (0x18): 0 (no alarm set)
            cpu.dmem[RTC_DMEM + 6]  <= 32'd0;

            // --- TTY ---
            // BYTES_READY (0x04): always 0 (no input) (offset 0x04 >> 2 = +1)
            cpu.dmem[TTY_DMEM + 1]  <= 32'd0;
            // VERSION (0x20): 0 = legacy (no DMA mapping needed) (offset 0x20 >> 2 = +8)
            cpu.dmem[TTY_DMEM + 8]  <= 32'd0;
        end
    end

    // =========================================================================
    // TTY Output Monitor
    // =========================================================================
    integer uart_fd;
    integer ti;
    reg [7:0] tty_ch;
    reg [31:0] tty_byte_addr;
    integer putchar_count;
    integer mas_entry_count;
    integer mas_loop_count;

    reg tty_dma_active;  // Set once CMD_WRITE_BUFFER fires; suppresses PUT_CHAR from file

    initial begin
        uart_fd = $fopen("uart_output.txt", "w");
        tty_data_ptr = 32'd0;
        tty_data_len = 32'd0;
        tty_version  = 32'd1;
        tty_dma_active = 0;
        putchar_count = 0;
        mas_entry_count = 0;
        mas_loop_count = 0;
    end

    always @(posedge clk) begin
        if (!reset && mmio_is_tty) begin
            case (mmio_wr_addr[4:0])
                5'h00: begin  // PUT_CHAR
                    putchar_count = putchar_count + 1;
                    if (putchar_count <= 20) begin
                        $display("[%0d] PUT_CHAR #%0d: data=0x%08x byte=0x%02x '%c' PC=0x%08x ports=%0d mask=0x%05x",
                                 cycle_count, putchar_count, mmio_wr_data,
                                 mmio_wr_data[7:0],
                                 (mmio_wr_data[7:0] >= 8'h20 && mmio_wr_data[7:0] < 8'h7f) ? mmio_wr_data[7:0] : 8'h2e,
                                 cpu.pc_rd, mmio_port_count, mmio_port_mask[21:0]);
                        // If upper bits are non-zero, dump each contributing port
                        if (mmio_wr_data[31:8] != 24'd0) begin
                            for (ti = 0; ti < NUM_PORTS; ti = ti + 1) begin
                                if (mmio_port_mask[ti])
                                    $display("  PORT[%0d]: addr=0x%08x data=0x%08x",
                                             ti, wr_addr[ti], wr_data[ti]);
                            end
                        end
                    end
                    // Detect null bytes being sent to UART
                    if (mmio_wr_data[7:0] == 8'h00) begin
                        $display("[%0d] PUT_CHAR_NULL #%0d: data=0x%08x PC=0x%08x ports=%0d mask=0x%05x",
                                 cycle_count, putchar_count, mmio_wr_data,
                                 cpu.pc_rd, mmio_port_count, mmio_port_mask[21:0]);
                        for (ti = 0; ti < NUM_PORTS; ti = ti + 1) begin
                            if (mmio_port_mask[ti])
                                $display("  NULL_PORT[%0d]: addr=0x%08x data=0x%08x en=%0d",
                                         ti, wr_addr[ti], wr_data[ti], wr_en[ti]);
                        end
                    end
                    if (!tty_dma_active) begin
                        // Only write PUT_CHAR to output before full console (DMA) takes over
                        $write("%c", mmio_wr_data[7:0]);
                        $fwrite(uart_fd, "%c", mmio_wr_data[7:0]);
                        $fflush();
                        $fflush(uart_fd);
                    end
                end
                5'h08: begin  // CMD
                    $display("[%0d] TTY CMD = %0d (0x%08x) PC=0x%08x ptr=0x%08x len=%0d",
                             cycle_count, mmio_wr_data, mmio_wr_data, cpu.pc_rd,
                             tty_data_ptr, tty_data_len);
                    if (mmio_wr_data == 32'd2) begin  // CMD_WRITE_BUFFER
                        if (!tty_dma_active) begin
                            $display("[%0d] WRITE_BUFFER: DMA console now active, suppressing PUT_CHAR", cycle_count);
                            tty_dma_active = 1;
                        end
                        $display("[%0d] WRITE_BUFFER: ptr=0x%08x len=%0d PC=0x%08x",
                                 cycle_count, tty_data_ptr, tty_data_len, cpu.pc_rd);
                        for (ti = 0; ti < tty_data_len && ti < 4096; ti = ti + 1) begin
                            tty_byte_addr = tty_data_ptr + ti;
                            // dmem is 32-bit: extract byte using big-endian byte lane
                            // byte_offset = 3 - tty_byte_addr[1:0] for big-endian
                            tty_ch = cpu.dmem[tty_byte_addr >> 2][(3 - tty_byte_addr[1:0]) * 8 +: 8];
                            if (ti < 256)
                                $display("  WBUF[%0d] baddr=0x%08x widx=0x%08x dmem=0x%08x lane=%0d byte=0x%02x '%c'",
                                         ti, tty_byte_addr, tty_byte_addr >> 2,
                                         cpu.dmem[tty_byte_addr >> 2],
                                         3 - tty_byte_addr[1:0], tty_ch,
                                         (tty_ch >= 8'h20 && tty_ch < 8'h7f) ? tty_ch : 8'h2e);
                            $write("%c", tty_ch);
                            $fwrite(uart_fd, "%c", tty_ch);
                        end
                        $fflush();
                        $fflush(uart_fd);
                        // WRITE_BUFFER processed - continue boot
                    end
                end
                5'h10: begin
                    tty_data_ptr <= mmio_wr_data;  // DATA_PTR
                    $display("[%0d] TTY DATA_PTR = 0x%08x PC=0x%08x", cycle_count, mmio_wr_data, cpu.pc_rd);
                end
                5'h14: begin
                    tty_data_len <= mmio_wr_data;  // DATA_LEN
                    $display("[%0d] TTY DATA_LEN = %0d PC=0x%08x", cycle_count, mmio_wr_data, cpu.pc_rd);
                end
                default: begin
                    $display("[%0d] TTY_UNKNOWN_REG: offset=0x%02x data=0x%08x PC=0x%08x",
                             cycle_count, mmio_wr_addr[4:0], mmio_wr_data, cpu.pc_rd);
                end
            endcase
        end
    end

    // =========================================================================
    // Debug and Progress Tracking
    // =========================================================================
    reg [31:0] last_pc;
    reg [31:0] prev_watchpoint_val = 0;
    reg [31:0] last_tc = 0;
    integer cycle_count;
    integer stuck_count;
    integer trap_entry_count;
    integer zero_run_count;
    reg initialized;
    reg [2:0] last_sr_mask;
    reg [2:0] last_ipl;
    reg verbose_trace;
    reg [31:0] trace_count;
    reg last_was_supervisor;
    integer usermode_instr_count;
    integer merge_loop_count;
    integer merge_call_count;
    reg [31:0] list_walk_ptr;
    integer list_walk_i;
    reg watchpoint_armed;
    reg [31:0] watch_dmem_801;
    reg [31:0] watch_dmem_802;
    // Watchpoint for RTS return address corruption
    reg [31:0] watch_rts_addr;
    localparam RTS_WATCH_IDX = 32'h120EAA;  // dmem index for crash frame (stale, update if needed)
    // Track MMU register changes
    reg [31:0] prev_tc;
    reg [63:0] prev_srp;
    reg [63:0] prev_crp;
    // Previous-cycle state for write port debugging
    reg [31:0] prev_pc;
    reg [15:0] prev_instr;
    reg [31:0] prev_sp;
    reg [31:0] prev_root_entry = 0;
    reg [31:0] prev_orig_root0 = 0;  // dmem[0x400] = original root table[0] at 0x00001000
    reg [31:0] prev_ptrtbl0 = 0;    // dmem[0x480] = pointer table[0] at 0x00001200
    reg [31:0] prev_a1;
    reg [31:0] prev_a6;
    reg [15:0] prev_sr;
    reg [20:0] prev_wr_en;  // packed write enables for ports 1-21
    reg [31:0] prev_wr_addr1;  // port 1 address from previous cycle
    reg [31:0] prev_node_parent = 0;  // watch for maple tree node parent changes
    integer mlmg_loop_count = 0;  // mas_leaf_max_gap loop iteration counter
    integer ret_exc_count = 0;     // limit ret_from_exception logging
    integer ret_exc_trace_start = 0;  // cycle to start PC trace
    integer ret_exc_trace_count = 0;  // how many trace PCs printed

    // PC history for debugging
    reg [31:0] pc_history [0:63];
    integer history_idx = 0;
    integer j;

    // Odd-SP detection
    reg odd_sp_detected = 0;
    // Data-section execution detection
    reg data_exec_detected = 0;

    // memset fast-forward: skip the memset loop by performing the fill
    // directly in dmem, saving millions of cycles during paging_init
    localparam MEMSET_ADDR = 32'h00155164;
    localparam MEMSET_SKIP_ENABLE = 0;  // Disabled — breaks blake2s (called from setup_arch)
    reg [31:0] memset_skip_ret;
    reg [31:0] memset_skip_dest;
    reg [31:0] memset_skip_cnt;  // count in bytes
    integer memset_skip_total = 0;  // total skipped calls
    integer memset_mi;  // loop variable for dmem fill
    integer bswap_trace_count = 0; // byte-swap loop trace counter

    // UNIMP skip logic: collect all unimplemented instructions
    reg unimp_skip_pending;
    reg [31:0] unimp_skip_pc;
    reg [15:0] unimp_seen [0:255];  // track unique UNIMP opcodes
    integer unimp_count = 0;
    integer unimp_total = 0;  // total UNIMP hits (including repeats)
    integer unimp_k;
    reg unimp_already_seen;

    // Track last "valid" kernel PC for escape detection
    reg [31:0] last_kernel_pc;
    integer last_kernel_cycle;
    reg escape_detected;
    reg prev_exc_taken;

    always @(posedge clk) begin
        if (!initialized) begin
            reset <= 1'b1;
            reset_counter <= 8'd10;
            cycle_count <= 0;
            last_sr_mask <= 3'd7;
            last_ipl <= 3'd0;
            verbose_trace <= 1'b0;
            trace_count <= 0;
            last_was_supervisor <= 1'b1;
            usermode_instr_count <= 0;
            merge_call_count <= 0;
            watchpoint_armed <= 1'b0;
            initialized <= 1'b1;
        end else if (reset_counter > 0) begin
            reset_counter <= reset_counter - 1;
            if (reset_counter == 1) begin
                reset <= 1'b0;
                $display("");
                $display("=== M68K Linux Boot Started ===");
            end
        end else begin
            cycle_count <= cycle_count + 1;
            last_pc <= cpu.pc_rd;
            last_was_supervisor <= cpu.sr_rd[13];

            // PC trace for ret_from_exception loop debugging — disabled (use PIC_IRQ_ENTRY instead)
            // if (ret_exc_trace_start > 0 && cycle_count >= ret_exc_trace_start && ret_exc_trace_count < 200) begin
            //     $display("[%0d] TRACE: PC=0x%08x INSTR=0x%04x SR=0x%04x SP=0x%08x",
            //              cycle_count, cpu.pc_rd, cpu.instr, cpu.sr_rd, cpu.aregs[7]);
            //     ret_exc_trace_count <= ret_exc_trace_count + 1;
            //     if (ret_exc_trace_count == 199) $finish;
            // end

            // Userspace tracing: detect supervisor→user transition and log first instructions
            if (last_was_supervisor && !cpu.sr_rd[13]) begin
                $display("[%0d] >>> ENTERING USER MODE: PC=0x%08x SP=0x%08x SR=0x%04x",
                         cycle_count, cpu.pc_rd, cpu.aregs[7], cpu.sr_rd);
                $display("  D0=0x%08x D1=0x%08x D2=0x%08x D3=0x%08x A0=0x%08x A1=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.dregs[2], cpu.dregs[3],
                         cpu.aregs[0], cpu.aregs[1]);
                $display("  MMU: TC=0x%08x TT0=0x%08x TT1=0x%08x",
                         cpu.tc_rd, cpu.tt0_rd, cpu.tt1_rd);
                $display("  CRP=0x%016x SSP=0x%08x USP=0x%08x",
                         cpu.crp_rd, cpu.ssp_rd, cpu.usp_rd);
                // Dump PGD entries for VA 0x00001000 (pgd index = VA >> 25 on 68030 with 8K IS)
                // CRP[31:0] = root table base address (upper 32 bits has limit/DT)
                // PGD[0] covers VA 0x00000000 - 0x01FFFFFF
                $display("  PGD base (CRP[31:4])=0x%08x", {cpu.crp_rd[31:4], 4'b0000});
                $display("  dmem[PGD+0]=0x%08x dmem[PGD+4]=0x%08x dmem[PGD+8]=0x%08x",
                         cpu.dmem[{cpu.crp_rd[31:4], 4'b0000} >> 2],
                         cpu.dmem[({cpu.crp_rd[31:4], 4'b0000} + 4) >> 2],
                         cpu.dmem[({cpu.crp_rd[31:4], 4'b0000} + 8) >> 2]);
                usermode_instr_count <= 0;
            end
            if (!cpu.sr_rd[13]) begin
                usermode_instr_count <= usermode_instr_count + 1;
                if (usermode_instr_count < 100 || (usermode_instr_count < 500 && usermode_instr_count % 10 == 0)) begin
                    $display("[%0d] USER[%0d]: PC=0x%08x INSTR=0x%04x SP=0x%08x D0=0x%08x SR=0x%04x pc_wr=0x%08x exc=%0d",
                             cycle_count, usermode_instr_count, cpu.pc_rd, cpu.instr,
                             cpu.aregs[7], cpu.dregs[0], cpu.sr_rd, cpu.pc_wr_mux,
                             1'b0 /* data_exc now via m68k_exc */);
                    // On first few user instructions, show MMU walk details
                    if (usermode_instr_count < 20) begin
                        $display("  MMU: pc_pa=0x%08x walk_fault=%0d instr_exc=%0d walk_succ=%0d",
                                 cpu.pc_pa,
                                 cpu.walk_fault,
                                 cpu.instr_access_exception,
                                 cpu.walk_success);
                        $display("  MMU: root_desc=0x%08x transparent=%0d need_walk=%0d",
                                 cpu.root_desc,
                                 cpu.transparent,
                                 cpu.need_walk);
                    end
                end
            end
            // Detect user→supervisor transition (exception/trap entry from userspace)
            if (!last_was_supervisor && cpu.sr_rd[13]) begin
                $display("[%0d] >>> RETURNING TO SUPERVISOR: PC=0x%08x SP=0x%08x SR=0x%04x from_user_pc=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.aregs[7], cpu.sr_rd, last_pc);
                $display("  D0=0x%08x D1=0x%08x D2=0x%08x D3=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.dregs[2], cpu.dregs[3]);
                $display("  exc_taken=%0d SSP=0x%08x USP=0x%08x",
                         1'b0 /* data_exc now via m68k_exc */,
                         cpu.ssp_rd, cpu.usp_rd);
                // Stack dump to see exception frame
                $display("  Exception frame (SP):");
                for (j = 0; j < 12; j = j + 1) begin
                    $display("    [SP+0x%03x] = 0x%08x",
                             j*4, cpu.dmem[(cpu.aregs[7] + j*4) >> 2]);
                end
            end

            // Record PC history
            pc_history[history_idx] <= cpu.pc_rd;
            history_idx <= (history_idx + 1) & 63;

            // Verbose trace when enabled (between setup_arch and panic/stuck)
            if (verbose_trace) begin
                $display("[%0d] PC=0x%08x INSTR=0x%04x pc_wr=0x%08x SP=0x%08x D0=0x%08x D3=0x%08x SR=0x%04x A0=0x%08x A2=0x%08x A3=0x%08x A5=0x%08x A6=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.instr, cpu.pc_wr_mux,
                         cpu.aregs[7], cpu.dregs[0], cpu.dregs[3], cpu.sr_rd,
                         cpu.aregs[0], cpu.aregs[2], cpu.aregs[3], cpu.aregs[5], cpu.aregs[6]);
                trace_count <= trace_count + 1;
            end

            // Track MMU register changes (TC, SRP, CRP)
            if (cpu.tc_rd != prev_tc) begin
                $display("[%0d] TC_CHANGE: 0x%08x -> 0x%08x PC=0x%08x",
                         cycle_count, prev_tc, cpu.tc_rd, cpu.pc_rd);
                // Debug page table walk when MMU enables
                if (cpu.tc_rd[31]) begin : mmu_walk_debug
                    reg [31:0] walk_root_base, walk_la_addr, walk_la_desc;
                    reg [31:0] walk_lb_base, walk_lb_addr, walk_lb_desc;
                    reg [31:0] walk_lc_base, walk_lc_addr, walk_lc_desc;
                    reg [6:0] walk_tia, walk_tib;
                    reg [5:0] walk_tic;
                    reg [31:0] walk_va;

                    walk_va = cpu.pc_rd;
                    $display("  MMU DEBUG: SRP=0x%016x CRP=0x%016x", cpu.srp_rd, cpu.crp_rd);
                    $display("  MMU DEBUG: TC=0x%08x SRE=%0d E=%0d", cpu.tc_rd, cpu.tc_rd[30], cpu.tc_rd[31]);
                    $display("  MMU DEBUG: pc_pa=0x%08x pc_pa_delta=0x%08x", cpu.pc_pa, cpu.pc_pa_delta);

                    // Walk for VA=PC
                    walk_root_base = {cpu.srp_rd[31:2], 2'b00};
                    walk_tia = walk_va[31:25];
                    walk_la_addr = walk_root_base + {23'b0, walk_tia, 2'b00};
                    walk_la_desc = cpu.dmem[walk_la_addr >> 2];
                    $display("  WALK[VA=0x%08x]: root_base=0x%08x TIA=%0d", walk_va, walk_root_base, walk_tia);
                    $display("  WALK: Level A addr=0x%08x (dmem[0x%06x]) desc=0x%08x DT=%0d",
                             walk_la_addr, walk_la_addr >> 2, walk_la_desc, walk_la_desc[1:0]);

                    walk_lb_base = {walk_la_desc[31:4], 4'b0000};
                    walk_tib = walk_va[24:18];
                    walk_lb_addr = walk_lb_base + {23'b0, walk_tib, 2'b00};
                    walk_lb_desc = cpu.dmem[walk_lb_addr >> 2];
                    $display("  WALK: Level B base=0x%08x TIB=%0d addr=0x%08x (dmem[0x%06x]) desc=0x%08x DT=%0d",
                             walk_lb_base, walk_tib, walk_lb_addr, walk_lb_addr >> 2, walk_lb_desc, walk_lb_desc[1:0]);

                    walk_lc_base = {walk_lb_desc[31:4], 4'b0000};
                    walk_tic = walk_va[17:12];
                    walk_lc_addr = walk_lc_base + {24'b0, walk_tic, 2'b00};
                    walk_lc_desc = cpu.dmem[walk_lc_addr >> 2];
                    $display("  WALK: Level C base=0x%08x TIC=%0d addr=0x%08x (dmem[0x%06x]) desc=0x%08x DT=%0d",
                             walk_lc_base, walk_tic, walk_lc_addr, walk_lc_addr >> 2, walk_lc_desc, walk_lc_desc[1:0]);
                    $display("  WALK: Final PA=0x%08x%03x (if walk_ok)", walk_lc_desc[31:12], walk_va[11:0]);

                    // Also walk for exception vector address (0x0000043c for bus error handler)
                    walk_va = 32'h0000043c;
                    walk_tia = walk_va[31:25];
                    walk_la_addr = walk_root_base + {23'b0, walk_tia, 2'b00};
                    walk_la_desc = cpu.dmem[walk_la_addr >> 2];
                    $display("  WALK[VA=0x%08x (exc handler)]: Level A desc=0x%08x DT=%0d",
                             walk_va, walk_la_desc, walk_la_desc[1:0]);
                    walk_lb_base = {walk_la_desc[31:4], 4'b0000};
                    walk_tib = walk_va[24:18];
                    walk_lb_addr = walk_lb_base + {23'b0, walk_tib, 2'b00};
                    walk_lb_desc = cpu.dmem[walk_lb_addr >> 2];
                    $display("  WALK[exc]: Level B base=0x%08x TIB=%0d desc=0x%08x DT=%0d",
                             walk_lb_base, walk_tib, walk_lb_desc, walk_lb_desc[1:0]);
                    walk_lc_base = {walk_lb_desc[31:4], 4'b0000};
                    walk_tic = walk_va[17:12];
                    walk_lc_addr = walk_lc_base + {24'b0, walk_tic, 2'b00};
                    walk_lc_desc = cpu.dmem[walk_lc_addr >> 2];
                    $display("  WALK[exc]: Level C base=0x%08x TIC=%0d desc=0x%08x DT=%0d",
                             walk_lc_base, walk_tic, walk_lc_desc, walk_lc_desc[1:0]);

                    // Dump level B table entries 0-15
                    $display("  Level B table dump (base=0x%08x):", {walk_la_desc[31:4], 4'b0000});
                    for (j = 0; j < 16; j = j + 1) begin
                        $display("    [%0d] addr=0x%08x = 0x%08x",
                                 j, {walk_la_desc[31:4], 4'b0000} + j*4,
                                 cpu.dmem[({walk_la_desc[31:4], 4'b0000} + j*4) >> 2]);
                    end
                end
                prev_tc <= cpu.tc_rd;
            end
            if (cpu.srp_rd != prev_srp) begin
                $display("[%0d] SRP_CHANGE: 0x%016x -> 0x%016x PC=0x%08x",
                         cycle_count, prev_srp, cpu.srp_rd, cpu.pc_rd);
                prev_srp <= cpu.srp_rd;
            end
            if (cpu.crp_rd != prev_crp) begin
                $display("[%0d] CRP_CHANGE: 0x%016x -> 0x%016x PC=0x%08x",
                         cycle_count, prev_crp, cpu.crp_rd, cpu.pc_rd);
                prev_crp <= cpu.crp_rd;
            end

            // MOVEM push/pop debug, find_mergeable, list_add, watchpoint traces DISABLED for speed

            // Save previous-cycle state for write port debugging
            prev_pc <= cpu.pc_rd;
            prev_instr <= cpu.instr;
            prev_sp <= cpu.aregs[7];
            prev_exc_taken <= 1'b0 /* data_exc now via m68k_exc */;
            prev_a1 <= cpu.aregs[1];
            prev_a6 <= cpu.aregs[6];
            prev_sr <= cpu.sr_rd;
            prev_wr_addr1 <= cpu.dmem_write_addr_mux_1;
            prev_wr_en <= {cpu.dmem_write_enable_21,
                           cpu.dmem_write_enable_20, cpu.dmem_write_enable_19,
                           cpu.dmem_write_enable_18, cpu.dmem_write_enable_17,
                           cpu.dmem_write_enable_16, cpu.dmem_write_enable_15,
                           cpu.dmem_write_enable_14, cpu.dmem_write_enable_13,
                           cpu.dmem_write_enable_12, cpu.dmem_write_enable_11,
                           cpu.dmem_write_enable_10, cpu.dmem_write_enable_9,
                           cpu.dmem_write_enable_8, cpu.dmem_write_enable_7,
                           cpu.dmem_write_enable_6, cpu.dmem_write_enable_5,
                           cpu.dmem_write_enable_4, cpu.dmem_write_enable_3,
                           cpu.dmem_write_enable_2, cpu.dmem_write_enable_1};

            // Watchpoint: detect writes to SR position in crash frame (DISABLED for speed)
            // if (cycle_count > 100000) begin ... end
            watch_rts_addr <= cpu.dmem[RTS_WATCH_IDX];

            // Debug: watch root table entry and PMOVE scratch buffer
            // dmem[0x6bc00] = temp root table entry 0 at addr 0x001af000
            // dmem[0x400] = original root table entry 0 at addr 0x00001000
            if (cpu.dmem[32'h6bc00] != prev_root_entry) begin
                $display("[%0d] TEMP_ROOT[0] CHANGED: 0x%08x -> 0x%08x PC=0x%08x INSTR=0x%04x",
                         cycle_count, prev_root_entry, cpu.dmem[32'h6bc00], cpu.pc_rd, cpu.instr);
                prev_root_entry <= cpu.dmem[32'h6bc00];
            end
            if (cpu.dmem[32'h400] != prev_orig_root0) begin
                $display("[%0d] ORIG_ROOT[0] CHANGED: 0x%08x -> 0x%08x PC=0x%08x INSTR=0x%04x A0=0x%08x A1=0x%08x D0=0x%08x",
                         cycle_count, prev_orig_root0, cpu.dmem[32'h400], cpu.pc_rd, cpu.instr,
                         cpu.aregs[0], cpu.aregs[1], cpu.dregs[0]);
                prev_orig_root0 <= cpu.dmem[32'h400];
            end
            // Watchpoint: pointer table entry[0] at byte addr 0x00001200 = dmem[0x480]
            if (cpu.dmem[32'h480] != prev_ptrtbl0) begin
                $display("[%0d] PTRTBL[0] CHANGED: 0x%08x -> 0x%08x PC=0x%08x INSTR=0x%04x A0=0x%08x A1=0x%08x D0=0x%08x SP=0x%08x",
                         cycle_count, prev_ptrtbl0, cpu.dmem[32'h480], cpu.pc_rd, cpu.instr,
                         cpu.aregs[0], cpu.aregs[1], cpu.dregs[0], cpu.aregs[7]);
                prev_ptrtbl0 <= cpu.dmem[32'h480];
            end
            if (cycle_count >= 340 && cycle_count <= 370) begin
                $display("[%0d] TRACE: PC=0x%08x INSTR=0x%04x D0=0x%08x D1=0x%08x A3=0x%08x A6=0x%08x SP=0x%08x arg1_0x3FC=0x%08x arg2_0x3FD=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.instr,
                         cpu.dregs[0], cpu.dregs[1],
                         cpu.aregs[3], cpu.aregs[6], cpu.aregs[7],
                         cpu.dmem[32'h3FC], cpu.dmem[32'h3FD]);
            end
            // Trace TST.L (A0) at PC=0x0019b48e and nearby instructions
            if (cpu.pc_rd == 32'h0019b48e) begin
                $display("[%0d] MMU_MAP: PC=0x%08x INSTR=0x%04x A0=0x%08x *A0=0x%08x Z_mux=0x%04x tst_en=%0d eq0=%0d sel=%0d exc=%0d",
                         cycle_count, cpu.pc_rd, cpu.instr,
                         cpu.aregs[0],
                         cpu.dmem[cpu.aregs[0] >> 2],
                         cpu.flag_Z_wr_mux,
                         cpu.tst_l_an_ind_enable,
                         cpu.tst_l_abs_l_val_eq_0,
                         cpu.select_tst_l_abs_l_val_eq_0_flag_Z_merged,
                         1'b0 /* m68k_exc_taken now per-instr */);
                // Check the 4A90-adjacent enables: TST.L An (0x4A88), TST.L (An)+ (0x4A98)
                $display("  TST_ENABLES: an=%0d an_ind=%0d an_postinc=%0d abs_l=%0d an_disp=%0d an_idx=%0d dn=%0d an_an=%0d",
                         cpu.tst_l_an_enable,
                         cpu.tst_l_an_ind_enable,
                         cpu.tst_l_an_postinc_enable,
                         cpu.tst_l_abs_l_enable,
                         cpu.tst_l_an_disp_enable,
                         cpu.tst_l_an_idx_enable,
                         cpu.tst_l_dn_enable,
                         cpu.tst_l_an_enable);
                // Check a few high-priority branches in the flag_Z mux
                $display("  INSTR_BITS: 15_8=%02x 7_6=%0d 5_3=%0d 2_0=%0d",
                         cpu.instr[15:8], cpu.instr[7:6], cpu.instr[5:3], cpu.instr[2:0]);
            end
            if (cpu.pc_rd == 32'h0019b490) begin
                $display("[%0d] MMU_MAP: PC=0x%08x INSTR=0x%04x Z_rd=%0d Z_wr=%0d",
                         cycle_count, cpu.pc_rd, cpu.instr,
                         cpu.flag_Z_rd, cpu.flag_Z_wr);
            end

            // NEW_SLAB, early boot cycle traces DISABLED for speed

            // Detect odd SP (stack corruption)
            if (cpu.aregs[7][0] && !odd_sp_detected && cycle_count > 1000) begin
                odd_sp_detected <= 1;
                $display("=== ODD SP DETECTED at cycle %0d ===", cycle_count);
                $display("  SP=0x%08x (was 0x%08x) PC=0x%08x INSTR=0x%04x",
                         cpu.aregs[7], prev_sp, cpu.pc_rd, cpu.instr);
                $display("  prev_PC=0x%08x prev_INSTR=0x%04x",
                         prev_pc, prev_instr);
                $display("  D0=0x%08x D1=0x%08x D2=0x%08x D3=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.dregs[2], cpu.dregs[3]);
                $display("  D4=0x%08x D5=0x%08x D6=0x%08x D7=0x%08x",
                         cpu.dregs[4], cpu.dregs[5], cpu.dregs[6], cpu.dregs[7]);
                $display("  A0=0x%08x A1=0x%08x A2=0x%08x A3=0x%08x",
                         cpu.aregs[0], cpu.aregs[1], cpu.aregs[2], cpu.aregs[3]);
                $display("  A4=0x%08x A5=0x%08x A6=0x%08x A7=0x%08x",
                         cpu.aregs[4], cpu.aregs[5], cpu.aregs[6], cpu.aregs[7]);
                $display("  SR=0x%04x SSP=0x%08x IPL=%0d",
                         cpu.sr_rd, cpu.ssp_rd, cpu_ipl);
                $display("  PC history (last 16):");
                for (j = 0; j < 16; j = j + 1) begin
                    $display("    [%0d] PC=0x%08x", j, pc_history[(history_idx - 16 + j) & 63]);
                end
                $display("  Stack around SP:");
                for (j = 0; j < 20; j = j + 1) begin
                    $display("    [SP+0x%03x] = 0x%08x", j*4,
                             cpu.dmem[(cpu.aregs[7] + j*4) >> 2]);
                end
            end

            // Detect PC entering .data/.rodata/.bss section (_etext=0x183eb0 < PC < _sinittext=0x1cc000)
            if (cpu.pc_rd > 32'h00183eb0 && cpu.pc_rd < 32'h001cc000 &&
                !data_exec_detected && cycle_count > 1000) begin
                data_exec_detected <= 1;
                $display("=== DATA SECTION EXEC at cycle %0d ===", cycle_count);
                $display("  PC=0x%08x INSTR=0x%04x prev_PC=0x%08x prev_INSTR=0x%04x",
                         cpu.pc_rd, cpu.instr, prev_pc, prev_instr);
                $display("  SP=0x%08x SR=0x%04x SSP=0x%08x",
                         cpu.aregs[7], cpu.sr_rd, cpu.ssp_rd);
                $display("  D0=0x%08x D1=0x%08x D2=0x%08x D3=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.dregs[2], cpu.dregs[3]);
                $display("  A0=0x%08x A1=0x%08x A2=0x%08x A3=0x%08x",
                         cpu.aregs[0], cpu.aregs[1], cpu.aregs[2], cpu.aregs[3]);
                $display("  A4=0x%08x A5=0x%08x A6=0x%08x",
                         cpu.aregs[4], cpu.aregs[5], cpu.aregs[6]);
                $display("  PC history (last 32):");
                for (j = 0; j < 32; j = j + 1) begin
                    $display("    [%0d] PC=0x%08x", j, pc_history[(history_idx - 32 + j) & 63]);
                end
            end

            // Debug unimplemented instructions (PC goes to 0)
            if (cpu.pc_wr_mux == 32'h0 && cpu.pc_rd != 32'h0 && cycle_count > 10) begin
                // Check if this opcode was already seen
                unimp_already_seen = 0;
                for (unimp_k = 0; unimp_k < unimp_count && unimp_k < 256; unimp_k = unimp_k + 1) begin
                    if (unimp_seen[unimp_k] == cpu.instr)
                        unimp_already_seen = 1;
                end
                if (!unimp_already_seen && unimp_count < 256) begin
                    unimp_seen[unimp_count] = cpu.instr;
                    unimp_count = unimp_count + 1;
                    $display("[%0d] UNIMP #%0d: PC=0x%08x INSTR=0x%04x dmem[pc+2]=0x%08x dmem[pc+4]=0x%08x",
                             cycle_count, unimp_count, cpu.pc_rd, cpu.instr,
                             cpu.dmem[(cpu.pc_rd + 2) >> 2], cpu.dmem[(cpu.pc_rd + 4) >> 2]);
                end
                unimp_total = unimp_total + 1;
                // Schedule skip: advance PC past the unimplemented instruction
                unimp_skip_pending <= 1;
                unimp_skip_pc <= cpu.pc_rd + 2;
            end else begin
                unimp_skip_pending <= 0;
            end

            // Force-skip unimplemented instruction by overwriting PC register
            if (unimp_skip_pending) begin
                cpu.pc <= unimp_skip_pc;
            end

            // memset fast-forward: detect memset entry and perform fill in dmem
            // At entry (PC=0x17b63c): SP+0=retaddr, SP+4=dest, SP+8=fill, SP+12=count
            // Only handles fill=0 with 4-byte-aligned dest and count (common case)
            // Uses immediate NBA override (same cycle) — testbench NBA fires after
            // CPU NBA, so our writes win. No pending delay = no rogue instructions.
            if (MEMSET_SKIP_ENABLE && cpu.pc_rd == MEMSET_ADDR && cycle_count > 100) begin
                // Read args from stack (blocking — immediate)
                memset_skip_ret  = cpu.dmem[cpu.aregs[7] >> 2];
                memset_skip_dest = cpu.dmem[(cpu.aregs[7] + 4) >> 2];
                memset_skip_cnt  = cpu.dmem[(cpu.aregs[7] + 12) >> 2];
                if (cpu.dmem[(cpu.aregs[7] + 8) >> 2] == 32'd0 &&
                    memset_skip_cnt > 32'd0 &&
                    memset_skip_cnt <= 32'h00100000 &&
                    memset_skip_dest[1:0] == 2'b00 &&
                    memset_skip_cnt[1:0] == 2'b00) begin
                    // Zero-fill aligned range directly in dmem (blocking)
                    for (memset_mi = 0; memset_mi < memset_skip_cnt; memset_mi = memset_mi + 4) begin
                        cpu.dmem[(memset_skip_dest + memset_mi) >> 2] = 32'd0;
                    end
                    // Override registers immediately via NBA (testbench wins over CPU)
                    cpu.dregs[0] <= memset_skip_dest;  // return value = dest
                    cpu.pc <= memset_skip_ret;          // return to caller
                    cpu.aregs[7] <= cpu.aregs[7] + 4;  // pop return address
                    memset_skip_total = memset_skip_total + 1;
                    if (memset_skip_total <= 20)
                        $display("[%0d] MEMSET_SKIP #%0d: dest=0x%08x count=%0d ret=0x%08x SP=0x%08x",
                                 cycle_count, memset_skip_total, memset_skip_dest,
                                 memset_skip_cnt, memset_skip_ret, cpu.aregs[7]);
                end
            end

            // (memset skip debug traces removed)

            // IO write logging (DISABLED for speed)
            //if (io_hit) begin
            //    $display("[%0d] IO WRITE: addr=0x%08x data=0x%08x PC=0x%08x INSTR=0x%04x",
            //             cycle_count, io_hit_addr, io_hit_data, cpu.pc_rd, cpu.instr);
            //end

            // RTE and supervisor->user transition traces DISABLED for speed

            // Track every A6 change during the 3rd timer IRQ (DISABLED for speed)
            //if (cpu.aregs[6] != prev_a6 && cycle_count > 8090000 && cycle_count < 8100000) begin
            //    $display("[%0d] A6_CHG: 0x%08x -> 0x%08x PC=0x%08x INSTR=0x%04x prev_PC=0x%08x prev_INSTR=0x%04x",
            //             cycle_count, prev_a6, cpu.aregs[6], cpu.pc_rd, cpu.instr, prev_pc, prev_instr);
            //end

            // Interrupt activity logging (disabled to reduce output)
            if (cpu_ipl != last_ipl) begin
                //  $display("[%0d] IPL CHANGE: %0d -> %0d (SR mask=%0d) PC=0x%08x timer_irq=%0d",
                //           cycle_count, last_ipl, cpu_ipl, cpu.sr_rd[10:8], cpu.pc_rd, timer_irq);
                last_ipl <= cpu_ipl;
            end

            // Exception taken logging (ENABLED for early-boot debugging, first 20K cycles only)
            if (1'b0 /* data_exc now via m68k_exc */ && cycle_count < 20000) begin
                $display("[%0d] EXCEPTION TAKEN: PC=0x%08x INSTR=0x%04x SR=0x%04x ipl=%0d exc_handler_pc=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.instr, cpu.sr_rd,
                         cpu_ipl, cpu.pc_wr_mux);
                $display("  instr_exc=%0d walk_fault=%0d need_walk=%0d transparent=%0d",
                         cpu.instr_access_exception,
                         cpu.walk_fault,
                         cpu.need_walk,
                         cpu.transparent);
                $display("  TC=0x%08x CRP=0x%016x SRP=0x%016x",
                         cpu.tc_rd, cpu.crp_rd, cpu.srp_rd);
                $display("  pc_pa=0x%08x root_desc=0x%08x root_dt=%0d root_valid=%0d",
                         cpu.pc_pa,
                         cpu.root_desc,
                         cpu.root_dt,
                         cpu.root_valid);
                $display("  la_addr=0x%08x la_desc=0x%08x la_valid=%0d lb_valid=%0d lc_page=%0d",
                         cpu.level_a_desc_addr,
                         cpu.level_a_desc,
                         cpu.level_a_valid,
                         cpu.level_b_valid,
                         cpu.level_c_is_page);
            end

            // --- vsnprintf buffer tracking (disabled for speed) ---
            // To re-enable, uncomment the VSNP/NUM_CALL/NUM_RET/MEMCPY/LITCOPY_ADV traces below
            /*
            if (cpu.pc_rd == 32'h003cfa3e) begin
                $display("[%0d] VSNP: D0=%0d A3=0x%08x A1=0x%08x type=%0d D7_buf=0x%08x",
                         cycle_count, cpu.dregs[0], cpu.aregs[3],
                         cpu.aregs[1], cpu.dregs[0],
                         cpu.dregs[7]);
            end
            if (cpu.pc_rd == 32'h003cfec4 || cpu.pc_rd == 32'h003cfd18 ||
                cpu.pc_rd == 32'h003cff0e || cpu.pc_rd == 32'h003cff44) begin
                $display("[%0d] NUM_CALL: PC=0x%08x D7_buf=0x%08x A5_end=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.dregs[7], cpu.aregs[5]);
            end
            if (cpu.pc_rd == 32'h003cfec8 || cpu.pc_rd == 32'h003cfd1c ||
                cpu.pc_rd == 32'h003cff12 || cpu.pc_rd == 32'h003cff48) begin
                $display("[%0d] NUM_RET: PC=0x%08x A0_newbuf=0x%08x D7_oldbuf=0x%08x chars=%0d",
                         cycle_count, cpu.pc_rd, cpu.aregs[0], cpu.dregs[7],
                         cpu.aregs[0] - cpu.dregs[7]);
            end
            if (cpu.pc_rd == 32'h003cfcdc) begin
                $display("[%0d] MEMCPY: dst=0x%08x src=0x%08x copy_count=%0d fmtdec_ret=%0d A1=0x%08x",
                         cycle_count, cpu.dregs[7], cpu.aregs[3],
                         cpu.dregs[1], cpu.dregs[0], cpu.aregs[1]);
            end
            if (cpu.pc_rd == 32'h003cfcee) begin
                $display("[%0d] LITCOPY_ADV: D7_before=0x%08x D0_advance=%0d D7_after=0x%08x",
                         cycle_count, cpu.dregs[7], cpu.dregs[0],
                         cpu.dregs[7] + cpu.dregs[0]);
            end
            */

            // --- Boot Milestone Watchpoints ---
            if (cpu.pc_rd == 32'h0019bcda) begin
                $display("[%0d] >>> HIT start_kernel", cycle_count);
                // verbose_trace <= 1'b1;  // Disabled to reduce output volume
                // trace_count <= 0;
            end
            // Auto-disable verbose trace after 600 cycles
            if (verbose_trace && trace_count > 600) verbose_trace <= 1'b0;
            if (cpu.pc_rd == 32'h0019dc90) begin
                $display("[%0d] >>> HIT setup_arch", cycle_count);
            end
            if (cpu.pc_rd == 32'h0019e6ec) $display("[%0d] >>> HIT config_virt", cycle_count);
            // Trace ALL instructions in config_virt range
            if (cpu.pc_rd >= 32'h0019e6ec && cpu.pc_rd <= 32'h0019e72a)
                $display("[%0d] config_virt_flow: PC=0x%08x SP=0x%08x INSTR=0x%04x D0=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.aregs[7], cpu.instr, cpu.dregs[0]);
            // movel 1904e0,-(sp) at 0x19e708: push tty.mmio for snprintf
            if (cpu.pc_rd == 32'h0019e708)
                $display("[%0d] >>> config_virt: movel tty.mmio dmem_val=0x%08x",
                         cycle_count, cpu.dmem[32'h001904e0 >> 2]);
            // After movel push, before pea at 0x19e70e
            if (cpu.pc_rd == 32'h0019e70e)
                $display("[%0d] >>> config_virt: after push tty.mmio, SP=0x%08x stack_top=0x%08x",
                         cycle_count, cpu.aregs[7], cpu.dmem[cpu.aregs[7] >> 2]);
            // snprintf entry at 0x14d97a
            if (cpu.pc_rd == 32'h0014d97a)
                $display("[%0d] >>> HIT snprintf SP=0x%08x buf=0x%08x size=0x%08x fmt=0x%08x mmio_arg=0x%08x",
                         cycle_count, cpu.aregs[7],
                         cpu.dmem[(cpu.aregs[7]+4) >> 2],
                         cpu.dmem[(cpu.aregs[7]+8) >> 2],
                         cpu.dmem[(cpu.aregs[7]+12) >> 2],
                         cpu.dmem[(cpu.aregs[7]+16) >> 2]);
            // number() hex loop: trace each iteration
            // 0x149e3e = loop top, 0x149e44 = moveb d1,d4, 0x149e46 = andl d6,d4
            // 0x149e4c = orb lookup, 0x149e50 = store digit
            if (cpu.pc_rd == 32'h00149e3e)
                $display("[%0d] number_loop: d0=0x%08x d1=0x%08x d6=0x%08x",
                         cycle_count, cpu.dregs[0], cpu.dregs[1], cpu.dregs[6]);
            if (cpu.pc_rd == 32'h00149e46)
                $display("[%0d] number_and: d4=0x%08x (after moveb d1,d4)", cycle_count, cpu.dregs[4]);
            if (cpu.pc_rd == 32'h00149e48)
                $display("[%0d] number_post_and: d4=0x%08x (nibble)", cycle_count, cpu.dregs[4]);
            if (cpu.pc_rd == 32'h00149e50)
                $display("[%0d] number_store: d5=0x%08x (char='%c')", cycle_count, cpu.dregs[5], cpu.dregs[5][7:0]);
            // After shift at 0x149e5e
            if (cpu.pc_rd == 32'h00149e5e)
                $display("[%0d] number_shifted: d4=0x%08x d5=0x%08x (new d1,d0)", cycle_count, cpu.dregs[4], cpu.dregs[5]);
            // Copy loop: moveb a1@,a0@ at 0x149f22 and zero-padding at 0x149f04
            if (cpu.pc_rd == 32'h00149f04 && cycle_count > 43500 && cycle_count < 44000)
                $display("[%0d] number_pad0: A3(buf)=0x%08x writing '0' word_before=0x%08x",
                         cycle_count, cpu.aregs[3], cpu.dmem[cpu.aregs[3] >> 2]);
            if (cpu.pc_rd == 32'h00149f22 && cycle_count > 43500 && cycle_count < 44000)
                $display("[%0d] number_copy: src(A1)=0x%08x dst(A0)=0x%08x src_byte=0x%02x('%c') dst_word_before=0x%08x",
                         cycle_count, cpu.aregs[1], cpu.aregs[0],
                         cpu.dmem[cpu.aregs[1] >> 2] >> ((3 - (cpu.aregs[1] & 2'b11)) * 8) & 8'hff,
                         cpu.dmem[cpu.aregs[1] >> 2] >> ((3 - (cpu.aregs[1] & 2'b11)) * 8) & 8'hff,
                         cpu.dmem[cpu.aregs[0] >> 2]);
            // After copy, check the word at buf+18 (where '8' should be)
            if (cpu.pc_rd == 32'h00149f24 && cycle_count > 43500 && cycle_count < 44000)
                $display("[%0d] number_post_copy: A0=0x%08x dst_word_after=0x%08x",
                         cycle_count, cpu.aregs[0], cpu.dmem[(cpu.aregs[0] - 1) >> 2]);
            if (cpu.pc_rd == 32'h001a5aea) begin
                automatic logic [31:0] buf_addr = cpu.dmem[(cpu.aregs[7]+4) >> 2];
                $display("[%0d] >>> HIT setup_earlycon buf=0x%08x", cycle_count, buf_addr);
                $display("[%0d]   buf[0..3]='%c%c%c%c' buf[4..7]='%c%c%c%c'",
                         cycle_count,
                         cpu.dmem[buf_addr >> 2][31:24], cpu.dmem[buf_addr >> 2][23:16],
                         cpu.dmem[buf_addr >> 2][15:8], cpu.dmem[buf_addr >> 2][7:0],
                         cpu.dmem[(buf_addr+4) >> 2][31:24], cpu.dmem[(buf_addr+4) >> 2][23:16],
                         cpu.dmem[(buf_addr+4) >> 2][15:8], cpu.dmem[(buf_addr+4) >> 2][7:0]);
                $display("[%0d]   buf[8..11]='%c%c%c%c' buf[12..15]='%c%c%c%c'",
                         cycle_count,
                         cpu.dmem[(buf_addr+8) >> 2][31:24], cpu.dmem[(buf_addr+8) >> 2][23:16],
                         cpu.dmem[(buf_addr+8) >> 2][15:8], cpu.dmem[(buf_addr+8) >> 2][7:0],
                         cpu.dmem[(buf_addr+12) >> 2][31:24], cpu.dmem[(buf_addr+12) >> 2][23:16],
                         cpu.dmem[(buf_addr+12) >> 2][15:8], cpu.dmem[(buf_addr+12) >> 2][7:0]);
                $display("[%0d]   buf[16..19]='%c%c%c%c' buf[20..23]='%c%c%c%c'",
                         cycle_count,
                         cpu.dmem[(buf_addr+16) >> 2][31:24], cpu.dmem[(buf_addr+16) >> 2][23:16],
                         cpu.dmem[(buf_addr+16) >> 2][15:8], cpu.dmem[(buf_addr+16) >> 2][7:0],
                         cpu.dmem[(buf_addr+20) >> 2][31:24], cpu.dmem[(buf_addr+20) >> 2][23:16],
                         cpu.dmem[(buf_addr+20) >> 2][15:8], cpu.dmem[(buf_addr+20) >> 2][7:0]);
            end
            // Also catch the JSR to setup_earlycon at 0x19e722
            if (cpu.pc_rd == 32'h0019e722) begin
                $display("[%0d] >>> config_virt calling setup_earlycon, tty_mmio=0x%08x",
                         cycle_count, cpu.dmem[32'h001904e0 >> 2]);
                // Dump JSR extension word signals
                $display("[%0d] JSR_DIAG: pc_pa=0x%08x pc_pa_delta=0x%08x",
                         cycle_count, cpu.pc_pa, cpu.pc_pa_delta);
                $display("[%0d] JSR_DIAG: pc_add_2_add_pc_pa_delta=0x%08x pc_add_4_add_pc_pa_delta=0x%08x",
                         cycle_count, cpu.pc_add_2_add_pc_pa_delta, cpu.pc_add_4_add_pc_pa_delta);
                $display("[%0d] JSR_DIAG: dmem[0x67B9C8]=0x%08x dmem[0x67B9C9]=0x%08x dmem[0x67B9CA]=0x%08x",
                         cycle_count, cpu.dmem[32'h67B9C8], cpu.dmem[32'h67B9C9], cpu.dmem[32'h67B9CA]);
                $display("[%0d] JSR_DIAG: addr_hi_mux=0x%08x addr_lo_mux=0x%08x",
                         cycle_count,
                         cpu.dmem_pc_add_2_add_pc_pa_delta_rd_aligned_mux_16b,
                         cpu.dmem_pc_add_4_add_pc_pa_delta_rd_aligned_mux_16b);
                $display("[%0d] JSR_DIAG: addr_lo_word=0x%08x addr_lo_sel0=%0b addr_lo_sel2=%0b",
                         cycle_count,
                         cpu.dmem_pc_add_4_add_pc_pa_delta_rd_word,
                         cpu.dmem_pc_add_4_add_pc_pa_delta_rd_sel_16b_0,
                         cpu.dmem_pc_add_4_add_pc_pa_delta_rd_sel_16b_2);
            end
            // Trace PCs around the earlycon call
            if (cycle_count >= 32'd44200 && cycle_count <= 32'd44230)
                $display("[%0d] EARLYCON_TRACE: PC=0x%08x INSTR=0x%04x SP=0x%08x D0=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.instr, cpu.aregs[7], cpu.dregs[0]);
            // Trace PCs around gf_earlycon_setup
            if (cycle_count >= 32'd49620 && cycle_count <= 32'd49650)
                $display("[%0d] EARLYCON_TRACE: PC=0x%08x INSTR=0x%04x SP=0x%08x D0=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.instr, cpu.aregs[7], cpu.dregs[0]);
            // Check early_con.write after setup
            if (cycle_count == 32'd44422)
                $display("[%0d] EARLYCON: early_con.write=0x%08x (at 0x18e488)", cycle_count, cpu.dmem[32'h0018e488 >> 2]);
            // setup_earlycon return at 0x1a5e18: check D0
            if (cpu.pc_rd == 32'h001a5e18) $display("[%0d] >>> setup_earlycon RETURN D0=%0d", cycle_count, $signed(cpu.dregs[0]));
            // console_is_registered check: reads early_con+0x50 (node.pprev)
            if (cpu.pc_rd == 32'h001a5b14) $display("[%0d] >>> setup_earlycon: console_is_registered D2=0x%08x (early_con.node.pprev)", cycle_count, cpu.dregs[2]);
            if (cpu.pc_rd == 32'h001a5e3e) begin
                // gf_earlycon_setup: a0 = sp@(4) = earlycon_device*
                // device->port.membase = device@(8) (what's tested for NULL)
                $display("[%0d] >>> HIT gf_earlycon_setup device=0x%08x membase_at=0x%08x membase_val=0x%08x",
                         cycle_count, cpu.dmem[(cpu.aregs[7]+4) >> 2],
                         cpu.dmem[(cpu.aregs[7]+4) >> 2] + 8,
                         cpu.dmem[(cpu.dmem[(cpu.aregs[7]+4) >> 2] + 8) >> 2]);
            end
            // Trace ioremap call from setup_earlycon (0x1a5cb2: jsr __ioremap)
            if (cpu.pc_rd == 32'h001a5cb2) begin
                $display("[%0d] >>> setup_earlycon calling __ioremap: mapbase=0x%08x (D0) size=0x40 cache=1",
                         cycle_count, cpu.dregs[0]);
            end
            // __ioremap entry at 0x5994
            if (cpu.pc_rd == 32'h00005994)
                $display("[%0d] >>> HIT __ioremap physaddr=0x%08x",
                         cycle_count, cpu.dmem[(cpu.aregs[7]+4) >> 2]);
            // Check mapbase load at 0x1a5c9c
            if (cpu.pc_rd == 32'h001a5c9c)
                $display("[%0d] >>> setup_earlycon: mapbase at 18e3ba = 0x%08x",
                         cycle_count, cpu.dmem[32'h0018e3ba >> 2]);
            // ioremap return: A0 = membase (at 0x1a5cb8: moveal %a0,%a4)
            if (cpu.pc_rd == 32'h001a5cb8)
                $display("[%0d] >>> __ioremap returned membase A0=0x%08x",
                         cycle_count, cpu.aregs[0]);
            // membase store at 0x1a5cdc: movel %a4,18e2f0
            if (cpu.pc_rd == 32'h001a5cdc)
                $display("[%0d] >>> setup_earlycon: storing membase=0x%08x to 18e2f0",
                         cycle_count, cpu.aregs[4]);
            // uart_parse_earlycon entry at 0x1140e2
            if (cpu.pc_rd == 32'h001140e2) begin
                $display("[%0d] >>> HIT uart_parse_earlycon buf_ptr=0x%08x",
                         cycle_count, cpu.dmem[(cpu.aregs[7]+4) >> 2]);
                // Dump first 16 bytes of buffer string
                $display("[%0d]   buf bytes: %08x %08x %08x %08x",
                         cycle_count,
                         cpu.dmem[cpu.dmem[(cpu.aregs[7]+4) >> 2] >> 2],
                         cpu.dmem[(cpu.dmem[(cpu.aregs[7]+4) >> 2] + 4) >> 2],
                         cpu.dmem[(cpu.dmem[(cpu.aregs[7]+4) >> 2] + 8) >> 2],
                         cpu.dmem[(cpu.dmem[(cpu.aregs[7]+4) >> 2] + 12) >> 2]);
            end
            // simple_strtoull entry at 0x148db8
            if (cpu.pc_rd == 32'h00148db8) begin
                // First arg is the string pointer (sp+4)
                $display("[%0d] >>> HIT simple_strtoull str=0x%08x bytes: %08x %08x",
                         cycle_count,
                         cpu.dmem[(cpu.aregs[7]+4) >> 2],
                         cpu.dmem[cpu.dmem[(cpu.aregs[7]+4) >> 2] >> 2],
                         cpu.dmem[(cpu.dmem[(cpu.aregs[7]+4) >> 2] + 4) >> 2]);
            end
            // uart_parse_earlycon: after simple_strtoull at 0x11411c (moveal %sp@(32),%a0)
            if (cpu.pc_rd == 32'h0011411c)
                $display("[%0d] >>> uart_parse: strtoull returned D0:D1=0x%08x:%08x",
                         cycle_count, cpu.dregs[0], cpu.dregs[1]);
            // uart_parse_earlycon: store addr at 0x114120 (movel %d1,%a0@)
            if (cpu.pc_rd == 32'h00114120)
                $display("[%0d] >>> uart_parse: storing addr D1=0x%08x to A0=0x%08x",
                         cycle_count, cpu.dregs[1], cpu.aregs[0]);
            // uart_parse_earlycon: return at 0x114140
            if (cpu.pc_rd == 32'h00114140)
                $display("[%0d] >>> uart_parse_earlycon RETURN D0=%0d", cycle_count, $signed(cpu.dregs[0]));
            // setup_earlycon: after uart_parse returns, check iotype+addr
            // At 0x1a5b9a (tstl %d0 — test uart_parse return)
            if (cpu.pc_rd == 32'h001a5b9a)
                $display("[%0d] >>> setup_earlycon: uart_parse returned D0=%0d iotype=0x%02x addr(fp-4)=0x%08x",
                         cycle_count, $signed(cpu.dregs[0]),
                         cpu.dmem[32'h0018e352 >> 2],
                         cpu.dmem[(cpu.aregs[6] - 4) >> 2]);
            // setup_earlycon: iotype switch at 0x1a5bba (jmp)
            if (cpu.pc_rd == 32'h001a5bba)
                $display("[%0d] >>> setup_earlycon: iotype switch D0=%0d",
                         cycle_count, cpu.dregs[0]);
            // setup_earlycon: mapbase store at 0x1a5bd6 (case UPIO_MEM)
            if (cpu.pc_rd == 32'h001a5bd6)
                $display("[%0d] >>> setup_earlycon: case UPIO_MEM: storing addr fp(-4)=0x%08x to 18e3ba",
                         cycle_count, cpu.dmem[(cpu.aregs[6] - 4) >> 2]);
            // gf_earlycon_setup returns at 0x1a5e58: D0=0 success, D0=-19 fail
            if (cpu.pc_rd == 32'h001a5e58) $display("[%0d] >>> gf_earlycon_setup RETURN D0=0x%08x (%0d)", cycle_count, cpu.dregs[0], $signed(cpu.dregs[0]));
            if (cpu.pc_rd == 32'h00119016) $display("[%0d] >>> HIT gf_early_write", cycle_count);
            if (cpu.pc_rd == 32'h0011903a) $display("[%0d] >>> HIT gf_early_console_putchar", cycle_count);
            if (cpu.pc_rd == 32'h00041de4) $display("[%0d] >>> HIT register_console con=0x%08x name=0x%08x%08x%08x%08x", cycle_count,
                         cpu.dmem[(cpu.aregs[7]+4) >> 2],
                         cpu.dmem[cpu.dmem[(cpu.aregs[7]+4) >> 2] >> 2],
                         cpu.dmem[(cpu.dmem[(cpu.aregs[7]+4) >> 2] + 4) >> 2],
                         cpu.dmem[(cpu.dmem[(cpu.aregs[7]+4) >> 2] + 8) >> 2],
                         cpu.dmem[(cpu.dmem[(cpu.aregs[7]+4) >> 2] + 12) >> 2]);
            if (cpu.pc_rd == 32'h000411b6) $display("[%0d] >>> HIT console_flush_all", cycle_count);
            if (cpu.pc_rd == 32'h000416ac) $display("[%0d] >>> HIT vprintk_emit", cycle_count);
            if (cpu.pc_rd == 32'h0019df66) $display("[%0d] >>> HIT trap_init", cycle_count);
            if (cpu.pc_rd == 32'h001a2fb4) $display("[%0d] >>> HIT setup_per_cpu_areas", cycle_count);
            if (cpu.pc_rd == 32'h0019fdfa) $display("[%0d] >>> HIT sched_init", cycle_count);
            if (cpu.pc_rd == 32'h0019de7e) $display("[%0d] >>> HIT time_init", cycle_count);
            if (cpu.pc_rd == 32'h001a08ac) $display("[%0d] >>> HIT console_init", cycle_count);
            if (cpu.pc_rd == 32'h0019e1d0) $display("[%0d] >>> HIT paging_init", cycle_count);
            if (cpu.pc_rd == 32'h0019de86) $display("[%0d] >>> HIT init_IRQ", cycle_count);
            if (cpu.pc_rd == 32'h0019e7d8) $display("[%0d] >>> HIT virt_init_IRQ", cycle_count);
            // MAS_ENTRY/MAS_LOOP traces DISABLED for speed
            // Functions between init_IRQ and softirq_init in start_kernel()
            if (cpu.pc_rd == 32'h001a10d0) $display("[%0d] >>> HIT tick_init", cycle_count);
            if (cpu.pc_rd == 32'h001a0bce) $display("[%0d] >>> HIT init_timers", cycle_count);
            if (cpu.pc_rd == 32'h001a0a06) $display("[%0d] >>> HIT srcu_init", cycle_count);
            if (cpu.pc_rd == 32'h001a0c1e) $display("[%0d] >>> HIT hrtimers_init", cycle_count);
            if (cpu.pc_rd == 32'h001a0c90) $display("[%0d] >>> HIT timekeeping_init", cycle_count);
            if (cpu.pc_rd == 32'h001a0a58) $display("[%0d] >>> HIT rcu_init", cycle_count);
            // Panic-related
            if (cpu.pc_rd == 32'h00019e8e) $display("[%0d] >>> HIT make_task_dead SP=0x%08x", cycle_count, cpu.aregs[7]);
            if (cpu.pc_rd == 32'h000195b0) begin
                $display("[%0d] >>> HIT do_exit SP=0x%08x SR=0x%04x", cycle_count, cpu.aregs[7], cpu.sr_rd);
                $display("  exit_code(SP+4)=0x%08x D0=0x%08x D1=0x%08x",
                         cpu.dmem[(cpu.aregs[7]+4)>>2], cpu.dregs[0], cpu.dregs[1]);
            end
            // Signal/fault handlers for userspace debugging
            if (cpu.pc_rd == 32'h00002378) $display("[%0d] >>> HIT buserr PC_from=0x%08x SR=0x%04x SP=0x%08x", cycle_count, last_pc, cpu.sr_rd, cpu.aregs[7]);
            if (cpu.pc_rd == 32'h00004a9a) begin
                $display("[%0d] >>> HIT buserr_c SP=0x%08x SR=0x%04x", cycle_count, cpu.aregs[7], cpu.sr_rd);
                $display("  D0=0x%08x D1=0x%08x A0=0x%08x A1=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.aregs[0], cpu.aregs[1]);
                // Dump the exception frame area on stack
                $display("  Exception frame dump (SP to SP+60):");
                $display("    [SP+ 0]=0x%08x [SP+ 4]=0x%08x [SP+ 8]=0x%08x [SP+12]=0x%08x",
                         cpu.dmem[(cpu.aregs[7] +  0) >> 2], cpu.dmem[(cpu.aregs[7] +  4) >> 2],
                         cpu.dmem[(cpu.aregs[7] +  8) >> 2], cpu.dmem[(cpu.aregs[7] + 12) >> 2]);
                $display("    [SP+16]=0x%08x [SP+20]=0x%08x [SP+24]=0x%08x [SP+28]=0x%08x",
                         cpu.dmem[(cpu.aregs[7] + 16) >> 2], cpu.dmem[(cpu.aregs[7] + 20) >> 2],
                         cpu.dmem[(cpu.aregs[7] + 24) >> 2], cpu.dmem[(cpu.aregs[7] + 28) >> 2]);
                $display("    [SP+32]=0x%08x [SP+36]=0x%08x [SP+40]=0x%08x [SP+44]=0x%08x",
                         cpu.dmem[(cpu.aregs[7] + 32) >> 2], cpu.dmem[(cpu.aregs[7] + 36) >> 2],
                         cpu.dmem[(cpu.aregs[7] + 40) >> 2], cpu.dmem[(cpu.aregs[7] + 44) >> 2]);
                $display("    [SP+48]=0x%08x [SP+52]=0x%08x [SP+56]=0x%08x [SP+60]=0x%08x",
                         cpu.dmem[(cpu.aregs[7] + 48) >> 2], cpu.dmem[(cpu.aregs[7] + 52) >> 2],
                         cpu.dmem[(cpu.aregs[7] + 56) >> 2], cpu.dmem[(cpu.aregs[7] + 60) >> 2]);
            end
            if (cpu.pc_rd == 32'h0000571a) begin
                $display("[%0d] >>> HIT do_page_fault SP=0x%08x", cycle_count, cpu.aregs[7]);
                $display("  D0=0x%08x D1=0x%08x A0=0x%08x A1=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.aregs[0], cpu.aregs[1]);
            end
            if (cpu.pc_rd == 32'h00021474) $display("[%0d] >>> HIT force_sig signo(SP+4)=0x%08x", cycle_count, cpu.dmem[(cpu.aregs[7]+4)>>2]);
            if (cpu.pc_rd == 32'h000214b2) $display("[%0d] >>> HIT force_sig_fault signo(SP+4)=0x%08x code(SP+8)=0x%08x addr(SP+12)=0x%08x", cycle_count, cpu.dmem[(cpu.aregs[7]+4)>>2], cpu.dmem[(cpu.aregs[7]+8)>>2], cpu.dmem[(cpu.aregs[7]+12)>>2]);
            if (cpu.pc_rd == 32'h00004a7e) $display("[%0d] >>> HIT die_if_kernel SP=0x%08x", cycle_count, cpu.aregs[7]);
            if (cpu.pc_rd == 32'h000024dc) $display("[%0d] >>> HIT do_signal_return SP=0x%08x", cycle_count, cpu.aregs[7]);
            if (cpu.pc_rd == 32'h00002438) $display("[%0d] >>> HIT system_call D0=0x%08x (syscall#) SP=0x%08x SR=0x%04x", cycle_count, cpu.dregs[0], cpu.aregs[7], cpu.sr_rd);
            if (cpu.pc_rd == 32'h000024a8) begin
                ret_exc_count <= ret_exc_count + 1;
                // Start PC trace on 2nd hit (first loop iteration)
                if (ret_exc_count == 1 && ret_exc_trace_start == 0)
                    ret_exc_trace_start <= cycle_count;
                if (ret_exc_count < 10 || (ret_exc_count < 100 && ret_exc_count % 10 == 0) || ret_exc_count % 1000 == 0) begin
                    $display("[%0d] >>> HIT ret_from_exception[%0d] SP=0x%08x SR=0x%04x", cycle_count, ret_exc_count, cpu.aregs[7], cpu.sr_rd);
                    // Linux pt_regs: stkadj at SP+0x28, SR(16) at SP+0x2C, PC(32) at SP+0x2E, FMT/VEC(16) at SP+0x32
                    $display("  pt_regs: SR=0x%04x PC=0x%04x%04x FMT/VEC=0x%04x",
                             cpu.dmem[(cpu.aregs[7] + 32'h2C) >> 2][31:16],
                             cpu.dmem[(cpu.aregs[7] + 32'h2C) >> 2][15:0],
                             cpu.dmem[(cpu.aregs[7] + 32'h30) >> 2][31:16],
                             cpu.dmem[(cpu.aregs[7] + 32'h30) >> 2][15:0]);
                    // Full pt_regs dump (13 longs = 52 bytes)
                    $display("  pt_regs dump (SP=0x%08x):", cpu.aregs[7]);
                    for (j = 0; j < 14; j = j + 1) begin
                        $display("    [SP+0x%02x] = 0x%08x",
                                 j*4, cpu.dmem[(cpu.aregs[7] + j*4) >> 2]);
                    end
                    $display("  D0=0x%08x D1=0x%08x A0=0x%08x A1=0x%08x",
                             cpu.dregs[0], cpu.dregs[1], cpu.aregs[0], cpu.aregs[1]);
                    // Show last 8 PCs to understand loop
                    $display("  pc_hist[-8..-1]: %08x %08x %08x %08x %08x %08x %08x %08x",
                             pc_history[(history_idx-8) & 63], pc_history[(history_idx-7) & 63],
                             pc_history[(history_idx-6) & 63], pc_history[(history_idx-5) & 63],
                             pc_history[(history_idx-4) & 63], pc_history[(history_idx-3) & 63],
                             pc_history[(history_idx-2) & 63], pc_history[(history_idx-1) & 63]);
                end
            end
            if (cpu.pc_rd == 32'h000ee214) $display("[%0d] >>> HIT load_elf_binary SP=0x%08x", cycle_count, cpu.aregs[7]);
            if (cpu.pc_rd == 32'h00002762) $display("[%0d] >>> HIT flush_thread SP=0x%08x", cycle_count, cpu.aregs[7]);
            if (cpu.pc_rd == 32'h0019e038) $display("[%0d] >>> HIT mem_init", cycle_count);
            if (cpu.pc_rd == 32'h001a429a) $display("[%0d] >>> HIT kmem_cache_init", cycle_count);
            if (cpu.pc_rd == 32'h001579d4) $display("[%0d] >>> HIT rest_init", cycle_count);
            if (cpu.pc_rd == 32'h0000209e) $display("[%0d] >>> HIT calibrate_delay", cycle_count);
            if (cpu.pc_rd == 32'h001a5fdc) $display("[%0d] >>> HIT random_init", cycle_count);
            if (cpu.pc_rd == 32'h001572fe) $display("[%0d] >>> HIT try_to_generate_entropy", cycle_count);
            if (cpu.pc_rd == 32'h0019e8e6) $display("[%0d] >>> HIT virt_platform_init", cycle_count);
            if (cpu.pc_rd == 32'h00119388) $display("[%0d] >>> HIT goldfish_tty_probe", cycle_count);
            if (cpu.pc_rd == 32'h001a5e5a) $display("[%0d] >>> HIT goldfish_tty_platform_driver_init", cycle_count);
            if (cpu.pc_rd == 32'h0019c218) $display("[%0d] >>> HIT do_one_initcall fn=0x%08x", cycle_count, cpu.dmem[(cpu.aregs[7]+4) >> 2]);
            // Timer setup debugging
            if (cpu.pc_rd == 32'h0019e63e) $display("[%0d] >>> HIT virt_sched_init", cycle_count);
            if (cpu.pc_rd == 32'h001a678c) begin
                // m68k stack ABI: SP+4 = arg1 (irq), SP+8 = arg2 (base)
                $display("[%0d] >>> HIT goldfish_timer_init SP=0x%08x irq=%0d base=0x%08x",
                         cycle_count, cpu.aregs[7],
                         cpu.dmem[(cpu.aregs[7]+4) >> 2],
                         cpu.dmem[(cpu.aregs[7]+8) >> 2]);
            end
            // goldfish_pic_irq entry — show full PIC5/timer state
            if (cpu.pc_rd == 32'h000147d0 && ret_exc_count > 0 && ret_exc_count < 20) begin
                $display("[%0d] >>> PIC_IRQ_ENTRY: PIC5 en=0x%08x active=0x%08x irq_out=%0d",
                         cycle_count,
                         pic_inst[5].pic.irq_enabled,
                         pic_active_irqs[5],
                         pic_irq_out[5]);
                $display("  timer: irq=%0d pending=%0d enabled=%0d armed=%0d time=0x%016x alarm=0x%016x",
                         timer_irq, timer.irq_pending, timer.irq_enabled, timer.alarm_armed,
                         timer.current_time, timer.alarm_time);
                $display("  dmem[PIC5+0]=0x%08x dmem[PIC5+1]=0x%08x",
                         cpu.dmem[PIC5_DMEM], cpu.dmem[PIC5_DMEM + 1]);
                $display("  cpu_ipl=%0d SR_mask=%0d SR=0x%04x",
                         cpu_ipl, cpu.sr_rd[10:8], cpu.sr_rd);
            end
            // goldfish_timer_irq entry (updated address from System.map)
            if (cpu.pc_rd == 32'h0012f3d8 && ret_exc_count > 0 && ret_exc_count < 20)
                $display("[%0d] >>> goldfish_timer_irq ENTERED", cycle_count);
            // goldfish_timer_next_event entry (updated address)
            if (cpu.pc_rd == 32'h0012f47e && ret_exc_count > 0 && ret_exc_count < 20)
                $display("[%0d] >>> goldfish_timer_next_event ENTERED", cycle_count);
            // virt_bi_data base address check (once, on first PIC_IRQ entry)
            if (cpu.pc_rd == 32'h000147d0 && ret_exc_count == 1) begin
                $display("  virt_bi_data+4 (dmem[0x%08x]) = 0x%08x",
                         32'h001904d0 >> 2, cpu.dmem[32'h001904d0 >> 2]);
            end
            if (cpu.pc_rd == 32'h0019efac) $display("[%0d] >>> HIT softirq_init", cycle_count);
            if (cpu.pc_rd == 32'h0019d900) $display("[%0d] >>> HIT populate_rootfs", cycle_count);
            if (cpu.pc_rd == 32'h0019dbc2)
                $display("[%0d] >>> HIT do_populate_rootfs", cycle_count);
            if (cpu.pc_rd == 32'h001552c0) $display("[%0d] >>> HIT run_init_process", cycle_count);
            if (cpu.pc_rd == 32'h00157a54) $display("[%0d] >>> HIT kernel_init", cycle_count);

            // ROOTFS/UNPACK detailed traces DISABLED for speed

            // mas_update_gap / maple tree internal traces disabled (init_IRQ hang fixed)

            // === TRACE: SRP changes ===
            if (cpu.srp_rd != cpu.srp_wr) begin
                $display("[%0d] SRP CHANGE: 0x%016x -> 0x%016x PC=0x%08x INSTR=0x%04x",
                         cycle_count, cpu.srp_rd, cpu.srp_wr, cpu.pc_rd, cpu.instr);
            end
            // === TRACE: walk debug DISABLED (signals now per-instruction) ===

            // clocksource register/mult_shift traces DISABLED for speed

            // TRAP entry detailed dump DISABLED for speed

            // Panic detection - dump stack trace
            if (cpu.pc_rd == 32'h001557fe) begin
                $display("[%0d] >>> HIT panic (0x1557fe) SP=0x%08x SR=0x%04x", cycle_count, cpu.aregs[7], cpu.sr_rd);
                $display("  D0=0x%08x D1=0x%08x D2=0x%08x D3=0x%08x D4=0x%08x D5=0x%08x D6=0x%08x D7=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.dregs[2], cpu.dregs[3],
                         cpu.dregs[4], cpu.dregs[5], cpu.dregs[6], cpu.dregs[7]);
                $display("  A0=0x%08x A1=0x%08x A2=0x%08x A3=0x%08x A4=0x%08x A5=0x%08x A6=0x%08x",
                         cpu.aregs[0], cpu.aregs[1], cpu.aregs[2], cpu.aregs[3],
                         cpu.aregs[4], cpu.aregs[5], cpu.aregs[6]);
                $display("  Stack dump (SP to SP+60):");
                $display("    [SP+ 0]=0x%08x [SP+ 4]=0x%08x [SP+ 8]=0x%08x [SP+12]=0x%08x",
                         cpu.dmem[(cpu.aregs[7] +  0) >> 2], cpu.dmem[(cpu.aregs[7] +  4) >> 2],
                         cpu.dmem[(cpu.aregs[7] +  8) >> 2], cpu.dmem[(cpu.aregs[7] + 12) >> 2]);
                $display("    [SP+16]=0x%08x [SP+20]=0x%08x [SP+24]=0x%08x [SP+28]=0x%08x",
                         cpu.dmem[(cpu.aregs[7] + 16) >> 2], cpu.dmem[(cpu.aregs[7] + 20) >> 2],
                         cpu.dmem[(cpu.aregs[7] + 24) >> 2], cpu.dmem[(cpu.aregs[7] + 28) >> 2]);
                $display("    [SP+32]=0x%08x [SP+36]=0x%08x [SP+40]=0x%08x [SP+44]=0x%08x",
                         cpu.dmem[(cpu.aregs[7] + 32) >> 2], cpu.dmem[(cpu.aregs[7] + 36) >> 2],
                         cpu.dmem[(cpu.aregs[7] + 40) >> 2], cpu.dmem[(cpu.aregs[7] + 44) >> 2]);
                $display("    [SP+48]=0x%08x [SP+52]=0x%08x [SP+56]=0x%08x [SP+60]=0x%08x",
                         cpu.dmem[(cpu.aregs[7] + 48) >> 2], cpu.dmem[(cpu.aregs[7] + 52) >> 2],
                         cpu.dmem[(cpu.aregs[7] + 56) >> 2], cpu.dmem[(cpu.aregs[7] + 60) >> 2]);
                $finish;
            end

            // do_exit, make_task_dead, die_if_kernel, clocksource traces DISABLED for speed

            // Progress indicator
            if ((cycle_count < 100000 && cycle_count % 5000 == 0) ||
                (cycle_count >= 100000 && cycle_count < 1000000 && cycle_count % 100000 == 0) ||
                (cycle_count >= 1000000 && cycle_count % 1000000 == 0)) begin
                $display("[%0d] PC=0x%08x SP=0x%08x D0=0x%08x INSTR=0x%04x IPL=%0d tmr_irq=%0d",
                         cycle_count, cpu.pc_rd, cpu.aregs[7], cpu.dregs[0], cpu.instr,
                         cpu_ipl, timer_irq);
                // pcpu_alloc_area detail DISABLED for speed
                $fflush();
            end

            // PT_WRITE and PTR_TBL_WRITE watchpoints DISABLED for speed
            // (were generating thousands of lines during ioremap, slowing sim 10x)

            // TC change detection — MMU enable/disable
            if (cpu.tc_rd != last_tc) begin
                $display("[%0d] TC CHANGED: 0x%08x -> 0x%08x (MMU %s) PC=0x%08x",
                         cycle_count, last_tc, cpu.tc_rd,
                         cpu.tc_rd[31] ? "ENABLED" : "disabled", cpu.pc_rd);
                $display("  CRP=0x%016x SRP=0x%016x", cpu.crp_rd, cpu.srp_rd);
                $display("  use_srp=%0d root_valid=%0d walk_ok=%0d need_walk=%0d walk_fault=%0d",
                         cpu.use_srp, cpu.root_valid, cpu.walk_ok, cpu.need_walk, cpu.walk_fault);
                // Dump SRP page table (first 4 entries at SRP table base)
                if (cpu.tc_rd[31]) begin
                    $display("  SRP table base=0x%08x (from srp[31:0]=0x%08x)",
                             {cpu.srp_rd[31:2], 2'b00}, cpu.srp_rd[31:0]);
                    for (j = 0; j < 4; j = j + 1)
                        $display("    SRP_L_A[%0d]=0x%08x (VA %08x-%08x)",
                                 j, cpu.dmem[({cpu.srp_rd[31:2], 2'b00} >> 2) + j],
                                 j << 25, ((j + 1) << 25) - 1);
                end
                last_tc <= cpu.tc_rd;
            end
            // Trace: transition to exception handler area
            if (last_pc >= 32'h1000 && cpu.pc_rd >= 32'h0400 && cpu.pc_rd < 32'h0450) begin
                $display("[%0d] TRANSITION: last_pc=0x%08x -> exc handler PC=0x%08x VBR=0x%08x exc_vector=0x%02x",
                         cycle_count, last_pc, cpu.pc_rd, cpu.vbr_rd, 8'd0 /* exc_vector now per-instr */);
                // Full 3-level walk trace using SRP (since use_srp=1)
                begin
                    reg [31:0] tb_root_base, tb_la_addr, tb_la_desc, tb_lb_base, tb_lb_addr, tb_lb_desc;
                    reg [31:0] tb_lc_base, tb_lc_addr, tb_lc_desc;
                    // Level A
                    tb_root_base = {cpu.srp_rd[31:2], 2'b00};
                    tb_la_addr = tb_root_base + {23'b0, last_pc[31:25], 2'b00};
                    tb_la_desc = cpu.dmem[tb_la_addr >> 2];
                    $display("  WALK[VA=0x%08x] use_srp=%0d srp_dt=%0d", last_pc, cpu.use_srp, cpu.srp_rd[33:32]);
                    $display("    L_A: root=0x%08x idx=%0d addr=0x%08x desc=0x%08x DT=%0d",
                             tb_root_base, last_pc[31:25], tb_la_addr, tb_la_desc, tb_la_desc[1:0]);
                    // Level B
                    tb_lb_base = {tb_la_desc[31:4], 4'b0000};
                    tb_lb_addr = tb_lb_base + {23'b0, last_pc[24:18], 2'b00};
                    tb_lb_desc = cpu.dmem[tb_lb_addr >> 2];
                    $display("    L_B: base=0x%08x idx=%0d addr=0x%08x desc=0x%08x DT=%0d",
                             tb_lb_base, last_pc[24:18], tb_lb_addr, tb_lb_desc, tb_lb_desc[1:0]);
                    // Level C
                    tb_lc_base = {tb_lb_desc[31:4], 4'b0000};
                    tb_lc_addr = tb_lc_base + {24'b0, last_pc[17:12], 2'b00};
                    tb_lc_desc = cpu.dmem[tb_lc_addr >> 2];
                    $display("    L_C: base=0x%08x idx=%0d addr=0x%08x desc=0x%08x DT=%0d",
                             tb_lc_base, last_pc[17:12], tb_lc_addr, tb_lc_desc, tb_lc_desc[1:0]);
                end
            end

            // --- Stuck Detection ---
            if (cycle_count > 1000 && cpu.pc_rd == last_pc) begin
                stuck_count <= stuck_count + 1;
                if (stuck_count == 10) begin
                    $display("[%0d] STUCK: PC=0x%08x INSTR=0x%04x for 10+ cycles IPL=%0d",
                             cycle_count, cpu.pc_rd, cpu.instr, cpu_ipl);
                    $display("  D0=0x%08x D1=0x%08x D2=0x%08x D3=0x%08x",
                             cpu.dregs[0], cpu.dregs[1], cpu.dregs[2], cpu.dregs[3]);
                    $display("  A0=0x%08x A1=0x%08x A6=0x%08x SP=0x%08x SR=0x%04x",
                             cpu.aregs[0], cpu.aregs[1], cpu.aregs[6], cpu.aregs[7], cpu.sr_rd);
                    // Stack dump
                    $display("  Stack dump (SP=0x%08x):", cpu.aregs[7]);
                    for (j = 0; j < 16; j = j + 1) begin
                        $display("    [SP+0x%03x] = 0x%08x",
                                 j*4, cpu.dmem[(cpu.aregs[7] + j*4) >> 2]);
                    end
                    // Exception-related state
                    $display("  VBR=0x%08x",
                             cpu.vbr_rd);
                    $display("  pc_pa=0x%08x pc_pa_delta=0x%08x tc=0x%08x",
                             cpu.pc_pa, cpu.pc_pa_delta, cpu.tc_rd);
                    // Extension word and raw dmem at PC
                    $display("  dmem[(PC>>2)]=0x%08x dmem[((PC+2)>>2)]=0x%08x",
                             cpu.dmem[cpu.pc_rd >> 2], cpu.dmem[(cpu.pc_rd + 2) >> 2]);
                    // PC history
                    $display("  PC history:");
                    for (j = 0; j < 64; j = j + 1)
                        $display("    [-%0d] PC=0x%08x", 64-j, pc_history[(history_idx + j) & 63]);
                    if (unimp_count > 0) begin
                        $display("  UNIMP summary: %0d unique opcodes, %0d total hits", unimp_count, unimp_total);
                        for (unimp_k = 0; unimp_k < unimp_count && unimp_k < 256; unimp_k = unimp_k + 1)
                            $display("    UNIMP opcode: 0x%04x", unimp_seen[unimp_k]);
                    end
                    $finish;
                end
            end else begin
                stuck_count <= 0;
            end

            // --- Crash Detection ---
            // PC at 0 after boot — skip if caused by UNIMP
            if (cycle_count > 100 && cpu.pc_rd == 0 && !unimp_skip_pending) begin
                $display("[%0d] CRASH: PC=0x00000000 (not UNIMP-related)", cycle_count);
                $display("  Last PC: 0x%08x", last_pc);
                $display("  D0=0x%08x D1=0x%08x D2=0x%08x D3=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.dregs[2], cpu.dregs[3]);
                $display("  A0=0x%08x A1=0x%08x A6=0x%08x SP=0x%08x SR=0x%04x",
                         cpu.aregs[0], cpu.aregs[1], cpu.aregs[6], cpu.aregs[7], cpu.sr_rd);
                // Stack dump
                $display("  Stack dump (SP=0x%08x):", cpu.aregs[7]);
                for (j = 0; j < 8; j = j + 1) begin
                    $display("    [SP+0x%03x] = 0x%08x",
                             j*4, cpu.dmem[(cpu.aregs[7] + j*4) >> 2]);
                end
                // PC history
                $display("  PC history:");
                for (j = 0; j < 64; j = j + 1)
                    $display("    [-%0d] PC=0x%08x", 64-j, pc_history[(history_idx + j) & 63]);
                if (unimp_count > 0) begin
                    $display("  UNIMP summary: %0d unique opcodes, %0d total hits", unimp_count, unimp_total);
                    for (unimp_k = 0; unimp_k < unimp_count && unimp_k < 256; unimp_k = unimp_k + 1)
                        $display("    UNIMP opcode: 0x%04x", unimp_seen[unimp_k]);
                end
                $finish;
            end

            // Track last kernel PC (below 0x00213000 = _end)
            if (cpu.pc_rd < 32'h001e1000 && cpu.pc_rd > 32'h00001000) begin
                last_kernel_pc <= cpu.pc_rd;
                last_kernel_cycle <= cycle_count;
            end

            // EXC_TAKEN/EXC_FRAME traces DISABLED for speed

            // CALLTRACE removed - relying on 64-entry PC history in ESCAPE dump

            // Maple tree, memory watchpoint, RTE, and function marker debug (DISABLED for speed)

            // Escape detection: PC jumps above kernel _end (0x00213000)
            if (cycle_count > 100000 && !escape_detected && cpu.pc_rd >= 32'h001e1000) begin
                escape_detected <= 1;
                $display("[%0d] ESCAPE: PC=0x%08x jumped past kernel _end!", cycle_count, cpu.pc_rd);
                $display("  Last kernel PC: 0x%08x at cycle %0d", last_kernel_pc, last_kernel_cycle);
                $display("  INSTR=0x%04x SP=0x%08x SR=0x%04x", cpu.instr, cpu.aregs[7], cpu.sr_rd);
                $display("  D0=0x%08x D1=0x%08x D2=0x%08x D3=0x%08x",
                         cpu.dregs[0], cpu.dregs[1], cpu.dregs[2], cpu.dregs[3]);
                $display("  D4=0x%08x D5=0x%08x D6=0x%08x D7=0x%08x",
                         cpu.dregs[4], cpu.dregs[5], cpu.dregs[6], cpu.dregs[7]);
                $display("  A0=0x%08x A1=0x%08x A2=0x%08x A3=0x%08x",
                         cpu.aregs[0], cpu.aregs[1], cpu.aregs[2], cpu.aregs[3]);
                $display("  A4=0x%08x A5=0x%08x A6=0x%08x A7=0x%08x",
                         cpu.aregs[4], cpu.aregs[5], cpu.aregs[6], cpu.aregs[7]);
                $display("  SSP=0x%08x USP=0x%08x", cpu.ssp_rd, cpu.usp_rd);
                $display("  PC history (last 64 PCs):");
                for (j = 0; j < 64; j = j + 1)
                    $display("    [-%0d] PC=0x%08x", 64-j, pc_history[(history_idx + j) & 63]);
                $display("  Stack dump (SSP=0x%08x):", cpu.ssp_rd);
                for (j = 0; j < 16; j = j + 1) begin
                    $display("    [SSP+0x%03x] = 0x%08x",
                             j*4, cpu.dmem[(cpu.ssp_rd + j*4) >> 2]);
                end
                $display("  Stack dump (SP=0x%08x):", cpu.aregs[7]);
                for (j = 0; j < 16; j = j + 1) begin
                    $display("    [SP+0x%03x] = 0x%08x",
                             j*4, cpu.dmem[(cpu.aregs[7] + j*4) >> 2]);
                end
                $finish;
            end

            // STOP instruction
            if (cycle_count > 100 && cpu.instr == 16'h4e72) begin
                $display("[%0d] STOP instruction at PC=0x%08x SR=0x%04x",
                         cycle_count, cpu.pc_rd, cpu.sr_rd);
                // With interrupts, STOP is normal (wait for interrupt)
                // Don't finish - the CPU should wake on next interrupt
            end

            // Stop after too many UNIMP hits (state too corrupted to continue)
            if (unimp_total > 1000) begin
                $display("");
                $display("=== Too many UNIMP hits (%0d total, %0d unique) - stopping ===", unimp_total, unimp_count);
                $display("Final PC: 0x%08x  Cycle: %0d", cpu.pc_rd, cycle_count);
                for (unimp_k = 0; unimp_k < unimp_count && unimp_k < 256; unimp_k = unimp_k + 1)
                    $display("  UNIMP opcode: 0x%04x", unimp_seen[unimp_k]);
                $finish;
            end

            // Timeout
            if (cycle_count >= 500000000) begin
                $display("");
                $display("=== Simulation Timeout (500M cycles) ===");
                $display("Final PC: 0x%08x", cpu.pc_rd);
                if (unimp_count > 0) begin
                    $display("  UNIMP summary: %0d unique opcodes, %0d total hits", unimp_count, unimp_total);
                    for (unimp_k = 0; unimp_k < unimp_count && unimp_k < 256; unimp_k = unimp_k + 1)
                        $display("    UNIMP opcode: 0x%04x", unimp_seen[unimp_k]);
                end
                $finish;
            end
        end
    end

    // =========================================================================
    // DMEM write watchpoint — catch byte corruption "self-testt0"
    // Track prev_pc to identify the WRITING instruction (watchpoint fires 1 cycle late)
    // Watch ALL words from 0x647ec to 0x64800 (the full snprintf output buffer)
    // =========================================================================
    reg [31:0] prev_watch_647ff;
    reg [31:0] prev_watch_647fe;
    reg [31:0] prev_watch_647f6;
    reg watch_initialized;

    always @(posedge clk) begin
        if (!watch_initialized) begin
            prev_watch_647ff <= cpu.dmem[32'h647ff];
            prev_watch_647fe <= cpu.dmem[32'h647fe];
            prev_watch_647f6 <= cpu.dmem[32'h647f6];
            watch_initialized <= 1'b1;
        end else if (cycle_count > 5000000) begin
            // Watch dmem[0x647ff] — the corrupted word in msg1
            if (cpu.dmem[32'h647ff] !== prev_watch_647ff) begin
                $display("[%0d] WATCH647ff: 0x%08x -> 0x%08x PREV_PC=0x%08x PREV_INSTR=0x%04x CUR_PC=0x%08x D0=0x%08x D1=0x%08x A0=0x%08x A1=0x%08x A2=0x%08x A3=0x%08x",
                         cycle_count, prev_watch_647ff, cpu.dmem[32'h647ff],
                         prev_pc, prev_instr, cpu.pc_rd,
                         cpu.dregs[0], cpu.dregs[1],
                         cpu.aregs[0], cpu.aregs[1], cpu.aregs[2], cpu.aregs[3]);
                prev_watch_647ff <= cpu.dmem[32'h647ff];
            end
            // Watch dmem[0x647fe] — the "test" word
            if (cpu.dmem[32'h647fe] !== prev_watch_647fe) begin
                $display("[%0d] WATCH647fe: 0x%08x -> 0x%08x PREV_PC=0x%08x PREV_INSTR=0x%04x CUR_PC=0x%08x D0=0x%08x D1=0x%08x A0=0x%08x A1=0x%08x A2=0x%08x A3=0x%08x",
                         cycle_count, prev_watch_647fe, cpu.dmem[32'h647fe],
                         prev_pc, prev_instr, cpu.pc_rd,
                         cpu.dregs[0], cpu.dregs[1],
                         cpu.aregs[0], cpu.aregs[1], cpu.aregs[2], cpu.aregs[3]);
                prev_watch_647fe <= cpu.dmem[32'h647fe];
            end
            // Watch dmem[0x647f6] — corrupted word in msg2 ("stt0" case)
            if (cpu.dmem[32'h647f6] !== prev_watch_647f6) begin
                $display("[%0d] WATCH647f6: 0x%08x -> 0x%08x PREV_PC=0x%08x PREV_INSTR=0x%04x CUR_PC=0x%08x D0=0x%08x D1=0x%08x A0=0x%08x A1=0x%08x A2=0x%08x A3=0x%08x",
                         cycle_count, prev_watch_647f6, cpu.dmem[32'h647f6],
                         prev_pc, prev_instr, cpu.pc_rd,
                         cpu.dregs[0], cpu.dregs[1],
                         cpu.aregs[0], cpu.aregs[1], cpu.aregs[2], cpu.aregs[3]);
                prev_watch_647f6 <= cpu.dmem[32'h647f6];
            end
        end
    end

    // =========================================================================
    // Initialization and Bootinfo Patching
    // =========================================================================
    initial begin
        initialized = 0;
        reset = 1;
        reset_counter = 10;
        cycle_count = 0;
        stuck_count = 0;
        trap_entry_count = 0;
        zero_run_count = 0;
        last_kernel_pc = 0;
        last_kernel_cycle = 0;
        escape_detected = 0;
        unimp_skip_pending = 0;
        unimp_skip_pc = 0;
        unimp_count = 0;
        unimp_total = 0;
        prev_exc_taken = 0;
        last_ipl = 0;
        watch_initialized = 0;

        // Get entry point from plusargs
        if (!$value$plusargs("entry=%h", entry_point))
            entry_point = 32'h00000400;  // Boot ROM entry

        // Get initial SSP from plusargs
        if (!$value$plusargs("ssp=%h", initial_ssp))
            initial_ssp = 32'h03FFFFF0;

        $display("===========================================");
        $display("M68K Linux Boot Simulation (Goldfish)");
        $display("===========================================");
        $display("Entry point: 0x%08x  SSP: 0x%08x", entry_point, initial_ssp);
        $display("Memory Layout:");
        $display("  0x%08x - RAM (64MB)", MEMORY_BASE);
        $display("  0x%08x - Goldfish PICs (6x)", GF_PIC_BASE);
        $display("  0x%08x - Goldfish Timer", GF_TIMER_BASE);
        $display("  0x%08x - Goldfish RTC", GF_RTC_BASE);
        $display("  0x%08x - Goldfish TTY", GF_TTY_BASE);
        $display("-------------------------------------------");

        // Wait for memory to be loaded (after #1 delay)
        #1;

        // ----- Register Initialization -----
        // M68K Linux boot protocol: A0 = pointer to bootinfo
        cpu.aregs[0] = BOOTINFO_ADDR;
        $display("Set A0 = 0x%08x (bootinfo)", BOOTINFO_ADDR);

        // ----- Direct kernel variable patching -----
        // Patch m68k_machtype (at 0x001900a4) to MACH_VIRT(14)
        // This is needed because bootinfo parsing may not set it correctly
        // dmem is 32-bit wide, indexed at (byte_addr - MEM_BASE) >> 2
        cpu.dmem[32'h001900a4 >> 2] = 32'h0000000E;  // MACH_VIRT = 14
        $display("Patched m68k_machtype at 0x001900a4 = 14 (MACH_VIRT)");

        // ----- Bootinfo -----
        // Bootinfo records (BI_MACHTYPE, BI_CPUTYPE, BI_MEMCHUNK, goldfish devices,
        // BI_COMMAND_LINE, BI_LAST) are all generated by gen_hex.py in dmem.hex
        // at the _end address (0x2a0000).
        $display("Bootinfo at 0x%08x (from gen_hex.py in dmem.hex)", BOOTINFO_ADDR);

        // memset is left unpatched - the slab allocator reuses memory, so
        // kzalloc/memset(0) must actually clear memory at runtime.
        $display("memset@0x3d327c: unpatched (working normally)");
    end

    // Waveform dumping
    initial begin
        if ($test$plusargs("trace")) begin
            $dumpfile("m68k_linux_boot.vcd");
            $dumpvars(0, m68k_linux_boot_tb);
        end
    end

endmodule
