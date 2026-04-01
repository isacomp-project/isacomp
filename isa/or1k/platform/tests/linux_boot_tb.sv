// OR1K Linux Boot Testbench with Externalized Memory
// ======================================================
// This testbench uses the proper SoC memory bus model with externalized memory.
// The CPU exposes read/write ports for umem via valid-ready handshakes,
// and the testbench routes accesses to either main RAM or peripherals
// based on address decode. No Verilog force/release is used.
//
// Memory Map:
//   0x00000000 - 0x03FFFFFF: Main RAM (64MB, 16M x 32-bit words)
//   0x90000000 - 0x900000FF: PIC registers (Programmable Interrupt Controller)
//   0x90000100 - 0x900001FF: UART (NS16550A compatible)
//   0x90000200 - 0x900002FF: Tick Timer (TTMR/TTCR)
//
// External Memory Ports (from ISA umem access patterns):
//   umem_pc_pa_read_*         - Instruction fetch via ITLB physical address
//   umem_addr_pa_read_*       - Data load via DTLB physical address
//   umem_store_addr_pa_read_* - RMW read for byte/halfword stores via DTLB PA
//   umem_write_*              - Data write (all stores)
//
// OR1K Linux Boot Protocol:
//   r3 = pointer to FDT (device tree blob)
//   r4 = 0, r5 = 0 (reserved)
//   Kernel entry at configurable address (default 0x00000000)

`timescale 1ns/1ps
`default_nettype none

module linux_boot_tb;

    // =========================================================================
    // Parameters
    // =========================================================================
    parameter CLK_PERIOD = 20;  // 50 MHz
    parameter MEMORY_SIZE = 32'h08000000;  // 128MB

    localparam [31:0] MEMORY_BASE  = 32'h00000000;
    localparam [31:0] PIC_BASE     = 32'h90000000;
    localparam [31:0] UART_BASE    = 32'h90000100;
    localparam [31:0] TIMER_BASE   = 32'h90000200;
    localparam [31:0] PERIPH_START = 32'h90000000;
    localparam [31:0] PERIPH_END   = 32'h90000300;
    localparam [31:0] FDT_ADDR_DEFAULT = 32'h03F00000;

    // =========================================================================
    // Clock and Reset
    // =========================================================================
    logic clk = 0;
    logic reset = 1;

    always #(CLK_PERIOD/2) clk = ~clk;

    // =========================================================================
    // Main Memory (64MB, word-addressed)
    // =========================================================================
    localparam MEM_WORDS = MEMORY_SIZE / 4;
    logic [31:0] main_memory [0:MEM_WORDS-1];

    // =========================================================================
    // Address Decode
    // =========================================================================
    function automatic logic is_peripheral(input logic [31:0] addr);
        return (addr >= PERIPH_START) && (addr < PERIPH_END);
    endfunction

    function automatic logic is_memory(input logic [31:0] addr);
        return (addr < MEMORY_SIZE);
    endfunction

    // =========================================================================
    // Configuration (plusargs)
    // =========================================================================
    reg [31:0] entry_point;
    reg [31:0] fdt_addr;
    integer max_cycles;
    logic debug_enable = 0;
    logic bad_pc_triggered = 0;
    int   stuck_count = 0;

    // =========================================================================
    // Interrupt Wiring
    // =========================================================================
    logic        pic_irq_pending;
    logic [31:0] irq_sources;

    // Tick timer is now internal to CPU (ISA-level ttmr/ttcr state).
    // Derive tick_irq_pending for testbench monitoring only.
    wire tick_irq_pending = cpu.ttmr_rd[28] & cpu.ttmr_rd[29];  // IP & IE

    // Wire UART IRQ to PIC input 2 (matches device tree interrupts = <2>)
    logic uart_irq;
    assign irq_sources = {29'b0, uart_irq, 2'b0};

    // =========================================================================
    // Peripheral Bus
    // =========================================================================
    logic [31:0] periph_addr;
    logic [31:0] periph_wdata;
    logic        periph_we;
    logic        periph_re;

    // Per-peripheral read data (always driven combinationally)
    wire [31:0] pic_bus_rdata;
    wire [31:0] uart_bus_rdata;
    wire         uart_bus_ack;

    // Peripheral read data mux based on address
    // Note: Tick timer is now internal to CPU (SPR-based), not memory-mapped
    wire [31:0] periph_rdata =
        (periph_addr >= UART_BASE  && periph_addr < UART_BASE  + 256) ? uart_bus_rdata  :
        (periph_addr >= PIC_BASE   && periph_addr < PIC_BASE   + 256) ? pic_bus_rdata   :
        32'hDEADBEEF;

    // Peripheral ack: PIC/Timer are combinational (immediate), UART is registered
    wire is_uart_periph = (periph_addr >= UART_BASE) && (periph_addr < UART_BASE + 256);
    wire periph_read_ack = is_uart_periph ? uart_bus_ack : periph_re;

    // =========================================================================
    // UART Instance
    // =========================================================================
    fake_uart #(
        .BASE_ADDR(UART_BASE)
    ) uart_inst (
        .clk      (clk),
        .reset    (reset),
        .bus_addr (periph_addr),
        .bus_wdata(periph_wdata),
        .bus_we   (periph_we && (periph_addr >= UART_BASE) && (periph_addr < UART_BASE + 256)),
        .bus_re   (periph_re && (periph_addr >= UART_BASE) && (periph_addr < UART_BASE + 256)),
        .bus_rdata(uart_bus_rdata),
        .bus_ack  (uart_bus_ack),
        .tx_valid (),
        .tx_data  (),
        .lsr      (),
        .irq      (uart_irq)
    );

    // =========================================================================
    // PIC Instance
    // =========================================================================
    or1k_pic #(
        .BASE_ADDR(PIC_BASE),
        .NUM_IRQS(32)
    ) pic_inst (
        .clk        (clk),
        .reset      (reset),
        .bus_addr   (periph_addr),
        .bus_wdata  (periph_wdata),
        .bus_we     (periph_we && (periph_addr >= PIC_BASE) && (periph_addr < PIC_BASE + 256)),
        .bus_rdata  (pic_bus_rdata),
        .irq_sources(irq_sources),
        .irq_pending(pic_irq_pending)
    );

    // =========================================================================
    // Tick Timer: Now internal to CPU (ISA-level ttmr/ttcr isa_state)
    // The kernel accesses TTMR/TTCR via l.mtspr/l.mfspr (SPR 0x5000/0x5001)
    // =========================================================================

    // =========================================================================
    // External Memory Port Signals - Instruction Fetch (PC)
    // =========================================================================
    wire [31:0] umem_pc_pa_read_req_addr;
    wire        umem_pc_pa_read_req_valid;
    wire [31:0] umem_pc_pa_read_resp_data;
    wire        umem_pc_pa_read_resp_ready;

    // Instruction fetch always from RAM (never from peripheral space)
    assign umem_pc_pa_read_resp_data  = main_memory[umem_pc_pa_read_req_addr[26:2]];
    assign umem_pc_pa_read_resp_ready = umem_pc_pa_read_req_valid;

    // =========================================================================
    // External Memory Port Signals - Data Load
    // =========================================================================
    wire [31:0] umem_addr_pa_read_req_addr;
    wire        umem_addr_pa_read_req_valid;
    wire [31:0] umem_addr_pa_read_resp_data;
    wire        umem_addr_pa_read_resp_ready;

    wire data_read_is_periph = is_peripheral(umem_addr_pa_read_req_addr);

    assign umem_addr_pa_read_resp_data = data_read_is_periph ?
        periph_rdata : main_memory[umem_addr_pa_read_req_addr[26:2]];
    assign umem_addr_pa_read_resp_ready = data_read_is_periph ?
        periph_read_ack : umem_addr_pa_read_req_valid;

    // =========================================================================
    // External Memory Port Signals - Store RMW Read
    // (Used by l.sb/l.sh to read existing word before merging byte/halfword)
    // =========================================================================
    wire [31:0] umem_store_addr_pa_read_req_addr;
    wire        umem_store_addr_pa_read_req_valid;
    wire [31:0] umem_store_addr_pa_read_resp_data;
    wire        umem_store_addr_pa_read_resp_ready;

    wire rmw_read_is_periph = is_peripheral(umem_store_addr_pa_read_req_addr);

    assign umem_store_addr_pa_read_resp_data = rmw_read_is_periph ?
        periph_rdata : main_memory[umem_store_addr_pa_read_req_addr[26:2]];
    assign umem_store_addr_pa_read_resp_ready = rmw_read_is_periph ?
        periph_read_ack : umem_store_addr_pa_read_req_valid;

    // =========================================================================
    // External Memory Port Signals - Write
    // =========================================================================
    wire [31:0] umem_write_req_addr;
    wire [31:0] umem_write_req_data;
    wire [3:0]  umem_write_req_we;
    wire        umem_write_req_valid;
    wire        umem_write_resp_ready;

    wire write_is_periph = is_peripheral(umem_write_req_addr);

    // Write accepted immediately
    assign umem_write_resp_ready = umem_write_req_valid;

    // =========================================================================
    // Peripheral Bus Routing
    // =========================================================================
    // Multiplex peripheral bus: writes have priority over reads.
    // Only one type of peripheral access can be active at a time because
    // the CPU stalls waiting for resp_ready on read ports.

    // Track write requests to prevent duplicate peripheral writes
    logic write_req_prev;
    wire  write_req_rising = umem_write_req_valid && !write_req_prev;
    always_ff @(posedge clk) begin
        if (reset)
            write_req_prev <= 1'b0;
        else
            write_req_prev <= umem_write_req_valid;
    end

    always_comb begin
        periph_addr  = 32'h0;
        periph_wdata = 32'h0;
        periph_we    = 1'b0;
        periph_re    = 1'b0;

        // Peripheral write (rising edge to prevent duplicate side effects)
        if (write_req_rising && write_is_periph) begin
            periph_addr  = umem_write_req_addr;
            periph_wdata = umem_write_req_data;
            periph_we    = 1'b1;
        end
        // Peripheral data load read
        else if (umem_addr_pa_read_req_valid && data_read_is_periph) begin
            periph_addr = umem_addr_pa_read_req_addr;
            periph_re   = 1'b1;
        end
        // Peripheral RMW read (byte/halfword store)
        else if (umem_store_addr_pa_read_req_valid && rmw_read_is_periph) begin
            periph_addr = umem_store_addr_pa_read_req_addr;
            periph_re   = 1'b1;
        end
    end

    // =========================================================================
    // Memory Write Handler
    // =========================================================================
    // Use addr[26:2] (128MB address space) so kernel virtual addresses
    // (e.g., 0xC0281E14) correctly map to physical memory when MMU is disabled.
    // Only skip peripheral addresses, which have their own write handling.
    always_ff @(posedge clk) begin
        if (!reset && umem_write_req_valid && !write_is_periph) begin
            if (umem_write_req_we[0])
                main_memory[umem_write_req_addr[26:2]][7:0]   <= umem_write_req_data[7:0];
            if (umem_write_req_we[1])
                main_memory[umem_write_req_addr[26:2]][15:8]  <= umem_write_req_data[15:8];
            if (umem_write_req_we[2])
                main_memory[umem_write_req_addr[26:2]][23:16] <= umem_write_req_data[23:16];
            if (umem_write_req_we[3])
                main_memory[umem_write_req_addr[26:2]][31:24] <= umem_write_req_data[31:24];
        end
    end

    // =========================================================================
    // Memory Write Watchpoint: detect when code at 0xc0249e60 gets overwritten
    // Physical word address = 0x00249e60 >> 2 = 0x092798
    // =========================================================================
    localparam WATCH_WORD_ADDR = 24'h092798;
    logic [31:0] watch_original_value;
    logic watch_initialized = 0;
    integer watch_log;

    // Capture original value after firmware load (in initial block, see below)
    // Monitor writes to the watched address
    always @(posedge clk) begin
        if (!reset && umem_write_req_valid && !write_is_periph &&
            umem_write_req_addr[26:2] == WATCH_WORD_ADDR) begin
            $display("=== WATCHPOINT HIT at cycle %0d ===", cycle_count);
            $display("  Write to phys word 0x%06x (addr=0x%08x)", WATCH_WORD_ADDR, umem_write_req_addr);
            $display("  PC=0x%08x instr=0x%08x SR=0x%08x", cpu.pc_rd, cpu.instr, cpu.sr_rd);
            $display("  Write data=0x%08x byte_en=%04b", umem_write_req_data, umem_write_req_we);
            $display("  Old value at addr=0x%08x", main_memory[WATCH_WORD_ADDR]);
            $display("  r1(sp)=0x%08x r3=0x%08x r9(lr)=0x%08x", cpu.rf[1], cpu.rf[3], cpu.rf[9]);
            $display("  EPCR0=0x%08x ESR0=0x%08x EEAR0=0x%08x", cpu.epcr0_rd, cpu.esr0_rd, cpu.eear0_rd);
            $display("  delay_slot=%0d branch_target=0x%08x", cpu.delay_slot, cpu.branch_target_rd);
            $display("=== END WATCHPOINT ===");
        end
    end

    // =========================================================================
    // UART Console Output Capture
    // =========================================================================
    integer uart_log_handle;
    logic   uart_initialized = 0;

    // Detect UART THR writes for console logging
    always @(posedge clk) begin
        if (!reset && write_req_rising &&
            umem_write_req_addr >= UART_BASE && umem_write_req_addr < UART_BASE + 256) begin
            // Big-endian: byte stores via RMW put data in MSByte [31:24]
            // LCR write with DLAB=0 marks UART initialization (reg 3, word-aligned)
            if (umem_write_req_addr[4:2] == 3'h3 && umem_write_req_data[31] == 1'b0)
                uart_initialized <= 1'b1;
            // THR write (reg 0, word-aligned) after initialization
            if (umem_write_req_addr[4:2] == 3'h0 && uart_initialized) begin
                $fwrite(uart_log_handle, "%c", umem_write_req_data[31:24]);
                $fflush(uart_log_handle);
            end
        end
    end

    // =========================================================================
    // CPU Instance (or1k_mmu with externalized memory)
    // =========================================================================
    or1k_mmu cpu (
        .clk    (clk),
        .reset  (reset),

        // Reset values
        .reset_pc               (entry_point),
        .reset_sr               (32'h0000_8001),    // SM=1, FO=1
        .reset_flag_rd          (1'b0),
        .reset_epcr0_rd         (32'h0),
        .reset_esr0_rd          (32'h0),
        .reset_eear0_rd         (32'h0),
        .reset_atomic_flag_rd   (1'b0),
        .reset_atomic_reserve_rd(32'h0),
        .reset_fpcsr            (32'h0),
        .reset_delay_slot       (1'b0),
        .reset_branch_target_rd (32'h0),
        .reset_ttmr_rd          (32'h0),
        .reset_ttcr_rd          (32'h0),
        .reset_picmr_rd         (32'h0),
        .reset_picsr_rd         (32'h0),

        // External interrupt inputs
        .irq_pending_rd      (irq_sources),
        .irq_pending_wr      (irq_sources),
        // tick_irq_pending is now computed internally from ttmr[28] & ttmr[29]

        // Instruction fetch port
        .umem_pc_pa_read_req_addr   (umem_pc_pa_read_req_addr),
        .umem_pc_pa_read_req_valid  (umem_pc_pa_read_req_valid),
        .umem_pc_pa_read_resp_data  (umem_pc_pa_read_resp_data),
        .umem_pc_pa_read_resp_ready (umem_pc_pa_read_resp_ready),

        // Data load port
        .umem_addr_pa_read_req_addr   (umem_addr_pa_read_req_addr),
        .umem_addr_pa_read_req_valid  (umem_addr_pa_read_req_valid),
        .umem_addr_pa_read_resp_data  (umem_addr_pa_read_resp_data),
        .umem_addr_pa_read_resp_ready (umem_addr_pa_read_resp_ready),

        // Store RMW read port
        .umem_store_addr_pa_read_req_addr   (umem_store_addr_pa_read_req_addr),
        .umem_store_addr_pa_read_req_valid  (umem_store_addr_pa_read_req_valid),
        .umem_store_addr_pa_read_resp_data  (umem_store_addr_pa_read_resp_data),
        .umem_store_addr_pa_read_resp_ready (umem_store_addr_pa_read_resp_ready),

        // Write port
        .umem_write_req_addr  (umem_write_req_addr),
        .umem_write_req_data  (umem_write_req_data),
        .umem_write_req_we    (umem_write_req_we),
        .umem_write_req_valid (umem_write_req_valid),
        .umem_write_resp_ready(umem_write_resp_ready)
    );

    // =========================================================================
    // Debug: FDT Read Trace (during early init)
    // =========================================================================
    always @(posedge clk) begin
        if (!reset && cycle_count > 197000 && cycle_count < 215000) begin
            // Trace data loads from FDT area (physical 0x03F00000 - 0x03F003FF)
            if (umem_addr_pa_read_req_valid &&
                umem_addr_pa_read_req_addr >= 32'h03F00000 &&
                umem_addr_pa_read_req_addr < 32'h03F00400) begin
                $display("[%0d] FDT_READ: addr=0x%08x data=0x%08x PC=0x%08x",
                         cycle_count, umem_addr_pa_read_req_addr,
                         umem_addr_pa_read_resp_data, cpu.pc_rd);
            end
            // Also trace reads from RMW port (l.sb/l.sh store path)
            if (umem_store_addr_pa_read_req_valid &&
                umem_store_addr_pa_read_req_addr >= 32'h03F00000 &&
                umem_store_addr_pa_read_req_addr < 32'h03F00400) begin
                $display("[%0d] FDT_RMW_READ: addr=0x%08x data=0x%08x PC=0x%08x",
                         cycle_count, umem_store_addr_pa_read_req_addr,
                         umem_store_addr_pa_read_resp_data, cpu.pc_rd);
            end
        end
    end

    // =========================================================================
    // Debug: fdt_next_node instruction-level trace
    // Trace the switch-case on fdt_next_tag return value in fdt_next_node
    // =========================================================================
    always @(posedge clk) begin
        if (!reset && cycle_count > 197000 && cycle_count < 215000) begin
            case (cpu.pc_rd)
                // fdt_next_tag return -> fdt_next_node switch
                32'hc0217008: // l.sfeqi r11,2 (check FDT_END_NODE)
                    $display("[%0d] FDT_NEXT_NODE_SWITCH: tag(r11)=%0d flag_rd=%0d delay_slot=%0d",
                             cycle_count, cpu.rf[11], cpu.flag_rd, cpu.delay_slot);
                32'hc021700c: // l.bf c0217058 (branch if FDT_END_NODE)
                    $display("[%0d]   bf_END_NODE: flag_rd=%0d (will branch=%0d)",
                             cycle_count, cpu.flag_rd, cpu.flag_rd);
                32'hc0217010: // l.sfeqi r11,9 (delay slot: check FDT_END)
                    $display("[%0d]   sfeqi_FDT_END: r11=%0d delay_slot=%0d",
                             cycle_count, cpu.rf[11], cpu.delay_slot);
                32'hc0217014: // l.bf c0217080 (branch if FDT_END)
                    $display("[%0d]   bf_FDT_END: flag_rd=%0d (will branch=%0d)",
                             cycle_count, cpu.flag_rd, cpu.flag_rd);
                32'hc0217018: // l.sfnei r11,1 (delay slot: check not FDT_BEGIN_NODE)
                    $display("[%0d]   sfnei_BEGIN_NODE: r11=%0d delay_slot=%0d",
                             cycle_count, cpu.rf[11], cpu.delay_slot);
                32'hc021701c: // l.bf c0217078 (branch if tag != FDT_BEGIN_NODE -> loop)
                    $display("[%0d]   bf_NOT_BEGIN: flag_rd=%0d (should branch if tag!=1)",
                             cycle_count, cpu.flag_rd);
                32'hc0217020: // l.sfeqi r18,0 (FDT_BEGIN_NODE: check depth==NULL)
                    $display("[%0d]   ** FDT_BEGIN_NODE handler entered! r16(offset)=%0d r18(depth)=0x%08x",
                             cycle_count, cpu.rf[16], cpu.rf[18]);
                32'hc0217078: // Loop continuation target
                    $display("[%0d]   LOOP_CONTINUE: going back to do-while",
                             cycle_count);
                32'hc021703c: // Function return path
                    $display("[%0d]   RETURN: r11(offset)=%0d r16=%0d",
                             cycle_count, cpu.rf[11], cpu.rf[16]);
                default: ;
            endcase
        end
    end

    // =========================================================================
    // Debug: Peripheral Access Trace
    // =========================================================================
    always @(posedge clk) begin
        if (debug_enable && periph_we)
            $display("[%0t] PERIPH WRITE: addr=0x%08x data=0x%08x we=%b",
                     $time, periph_addr, periph_wdata, umem_write_req_we);
        if (debug_enable && periph_re)
            $display("[%0t] PERIPH READ: addr=0x%08x data=0x%08x",
                     $time, periph_addr, periph_rdata);
    end

    // =========================================================================
    // Boot Image Loading
    // =========================================================================
    string  firmware_file;
    string  fdt_file;
    integer file_handle;
    integer bytes_read;
    reg [7:0]  byte_data;
    integer word_count;
    integer fdt_word_offset;
    integer i, j;

    initial begin
        // Parse plusargs
        if (!$value$plusargs("firmware=%s", firmware_file))
            firmware_file = "vmlinux.bin";
        if (!$value$plusargs("fdt_file=%s", fdt_file))
            fdt_file = "or1k_isacomp.dtb";
        if (!$value$plusargs("entry=0x%h", entry_point))
            entry_point = 32'h00000100;  // OR1K reset vector
        if (!$value$plusargs("fdt=0x%h", fdt_addr))
            fdt_addr = FDT_ADDR_DEFAULT;
        if (!$value$plusargs("max_cycles=%d", max_cycles))
            max_cycles = 1_500_000_000;
        if ($test$plusargs("debug")) debug_enable = 1;

        // Display boot configuration
        $display("==============================================");
        $display("OR1K Linux Boot Testbench (Externalized Memory)");
        $display("==============================================");
        $display("Firmware:    %s", firmware_file);
        $display("FDT file:    %s", fdt_file);
        $display("Entry point: 0x%08x", entry_point);
        $display("FDT address: 0x%08x", fdt_addr);
        $display("Max cycles:  %0d", max_cycles);
        $display("Memory:      %0dMB at 0x%08x", MEMORY_SIZE / (1024*1024), MEMORY_BASE);
        $display("PIC:         0x%08x", PIC_BASE);
        $display("UART:        0x%08x", UART_BASE);
        $display("Timer:       0x%08x", TIMER_BASE);
        $display("==============================================");

        // Open UART log file
        uart_log_handle = $fopen("uart_output.txt", "w");
        if (uart_log_handle == 0)
            $display("WARNING: Cannot open uart_output.txt for writing");

        // Initialize memory
        for (i = 0; i < MEM_WORDS; i = i + 1)
            main_memory[i] = 32'h15000000;  // l.nop 0

        // Load firmware binary (big-endian)
        $display("Loading firmware: %s", firmware_file);
        file_handle = $fopen(firmware_file, "rb");
        if (file_handle == 0) begin
            $display("ERROR: Cannot open firmware file: %s", firmware_file);
            $finish;
        end

        word_count = 0;
        while (!$feof(file_handle)) begin
            for (j = 3; j >= 0; j = j - 1) begin
                bytes_read = $fread(byte_data, file_handle);
                if (bytes_read == 1)
                    main_memory[word_count][j*8 +: 8] = byte_data;
            end
            word_count = word_count + 1;
        end
        $fclose(file_handle);
        $display("Loaded %0d words (%0d bytes) into memory", word_count, word_count * 4);

        // Load FDT
        $display("Loading FDT: %s", fdt_file);
        file_handle = $fopen(fdt_file, "rb");
        if (file_handle == 0) begin
            $display("WARNING: Cannot open FDT file: %s (continuing without FDT)", fdt_file);
        end else begin
            fdt_word_offset = (fdt_addr - MEMORY_BASE) >> 2;
            word_count = 0;
            while (!$feof(file_handle)) begin
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, file_handle);
                    if (bytes_read == 1)
                        main_memory[fdt_word_offset + word_count][j*8 +: 8] = byte_data;
                end
                word_count = word_count + 1;
            end
            $fclose(file_handle);
            $display("Loaded FDT: %0d words (%0d bytes) at 0x%08x",
                     word_count, word_count * 4, fdt_addr);
            $display("FDT magic: 0x%08x (expect 0xD00DFEED)",
                     main_memory[fdt_word_offset]);
        end

        // Set up OR1K Linux boot protocol registers
        // r3 = FDT pointer, r4 = 0, r5 = 0
        cpu.rf[3] = fdt_addr;
        cpu.rf[4] = 32'h0;
        cpu.rf[5] = 32'h0;
        $display("Set r3 = 0x%08x (FDT address)", fdt_addr);

        // Timer test mode - set ISA-level timer registers directly
        if ($test$plusargs("timer_test")) begin
            $display("TIMER TEST MODE: Setting TTMR for quick interrupt");
            cpu.ttmr_rd = {2'b01, 1'b1, 1'b0, 28'd100};  // Restart mode, IE=1, period=100
            cpu.ttcr_rd = 32'h0;
        end

        // Verify FDT structure block in memory
        begin
            integer fdt_struct_off;
            fdt_struct_off = main_memory[fdt_word_offset + 2]; // off_dt_struct from header
            $display("FDT verification: off_dt_struct=0x%08x off_dt_strings=0x%08x",
                     main_memory[fdt_word_offset + 2], main_memory[fdt_word_offset + 3]);
            $display("FDT structure block first 20 words:");
            for (i = 0; i < 20; i = i + 1)
                $display("  [struct+0x%02x] = 0x%08x (file offset 0x%03x)",
                         i*4, main_memory[fdt_word_offset + fdt_struct_off/4 + i],
                         fdt_struct_off + i*4);
        end

        // Display first instructions
        $display("First instructions at entry point 0x%08x:", entry_point);
        for (i = 0; i < 8; i = i + 1)
            $display("  [0x%08x]: 0x%08x",
                     MEMORY_BASE + (entry_point[26:2] + i) * 4,
                     main_memory[entry_point[26:2] + i]);

        // Reset sequence
        reset = 1;
        repeat (20) @(posedge clk);
        reset = 0;

        // Initialize SPR values after reset
        // SPR[0] = VR (Version Register): OR1200 compatible
        cpu.spr[0]  = 32'h12000001;
        // SPR[1] = UPR (Unit Present Register):
        //   bit 0:  UP  (UPR present)
        //   bit 3:  DMP (Data MMU Present)
        //   bit 4:  IMP (Instruction MMU Present)
        //   bit 8:  PICP (PIC Present)
        //   bit 10: TTP (Tick Timer Present)
        cpu.spr[1]  = 32'h00000519;
        // SPR[2] = CPUCFGR: ORBIS32 supported, no delay-slot exception model
        cpu.spr[2]  = 32'h00000020;

        $display("Reset released, starting execution at PC=0x%08x", entry_point);
        $display("==============================================");
    end

    // =========================================================================
    // Simulation Monitor
    // =========================================================================
    integer cycle_count = 0;

    // Previous state for transition detection
    logic [31:0] prev_pc       = 0;
    logic [31:0] prev_sr       = 0;
    logic        prev_tick_irq = 0;
    logic        prev_ext_irq  = 0;
    logic [31:0] prev_r9       = 0;
    logic [31:0] prev_ttmr     = 0;
    logic [31:0] prev_ttcr     = 0;
    logic [31:0] prev_r1       = 0;
    logic [31:0] prev_softirq_pending = 0;
    logic [31:0] prev_next_expiry = 0;
    logic [31:0] prev_kthreadd_state = 0;
    logic [63:0] pc_dump_start = 0;
    logic        pc_dump_enable = 0;
    logic        nop_halt_seen = 0;
    logic        r1_overflow_reported = 0;

    // Circular trace buffer - records only PC CHANGES (not every cycle)
    localparam TRACE_DEPTH = 2048;
    logic [31:0] trace_pc    [TRACE_DEPTH];
    logic [31:0] trace_instr [TRACE_DEPTH];
    logic [31:0] trace_sr    [TRACE_DEPTH];
    logic [31:0] trace_cycle [TRACE_DEPTH];
    int          trace_idx = 0;
    int          trace_count = 0;
    int          user_trace_count = 0;
    int          sys_trap_debug_count = 0;
    int          sr_change_count = 0;
    logic [31:0] prev_sr_dbg = 32'h00008001;
    logic        panic_detected = 0;

    always @(posedge clk) begin
        if (!reset) begin
            cycle_count = cycle_count + 1;

            // Unconditional early boot trace
            if (cycle_count <= 30 || (cycle_count >= 2536780 && cycle_count <= 2536900))
                $display("[%0d] TRACE: PC=0x%08x SR=0x%08x new_sr=0x%08x sr_wr=0x%08x exc=%0d sel_new=%0d l_rfe=%0d l_mtspr=%0d sel_load=%0d sel_store=%0d l_sys=%0d l_trap=%0d instr=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.sr_rd, cpu.new_sr, cpu.sr_wr, cpu.l_add_exception_taken_mux, cpu.select_new_sr_sr_merged,
                         cpu.l_rfe_enable, cpu.l_mtspr_enable,
                         cpu.select_load_exc_new_sr_sr_merged, cpu.select_store_exc_new_sr_sr_merged,
                         cpu.l_sys_enable, cpu.l_trap_enable, cpu.instr);

            // Debug: detect l.sys/l.trap enable during boot
            if ((cpu.l_sys_enable || cpu.l_trap_enable) && sys_trap_debug_count < 50) begin
                $display("[%0d] SYS_TRAP_DEBUG: PC=0x%08x SR=0x%08x instr=0x%08x l_sys=%0d l_trap=%0d",
                         cycle_count, cpu.pc_rd, cpu.sr_rd, cpu.instr, cpu.l_sys_enable, cpu.l_trap_enable);
                sys_trap_debug_count <= sys_trap_debug_count + 1;
            end

            // Debug: trace l.mtspr writes to EPCR (SPR 0x0020) and l.rfe
            if (cpu.l_mtspr_enable && cpu.l_mtspr_is_epcr0 && cycle_count > 21450000) begin
                $display("[%0d] MTSPR_EPCR: PC=0x%08x data=0x%08x epcr0_rd=0x%08x epcr0_wr=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.l_mtspr_data, cpu.epcr0_rd, cpu.epcr0_wr_mux);
            end
            if (cpu.l_rfe_enable && cycle_count > 21450000) begin
                $display("[%0d] L_RFE: PC=0x%08x epcr0_rd=0x%08x esr0_rd=0x%08x pc_wr=0x%08x sr_wr=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.epcr0_rd, cpu.esr0_rd, cpu.pc_wr_mux, cpu.sr_wr_mux);
            end

            // Debug: detect SR changes and which mux branch is active
            if (cpu.sr_rd != prev_sr_dbg && sr_change_count < 200) begin
                $display("[%0d] SR_CHANGE: 0x%08x -> 0x%08x PC=0x%08x instr=0x%08x exc_taken=%0d l_rfe=%0d l_mtspr=%0d sel_load=%0d sel_new_sr=%0d sel_store=%0d l_sys=%0d l_trap=%0d",
                         cycle_count, prev_sr_dbg, cpu.sr_rd, cpu.pc_rd, cpu.instr,
                         cpu.l_add_exception_taken_mux,
                         cpu.l_rfe_enable,
                         cpu.l_mtspr_enable,
                         cpu.select_load_exc_new_sr_sr_merged,
                         cpu.select_new_sr_sr_merged,
                         cpu.select_store_exc_new_sr_sr_merged,
                         cpu.l_sys_enable,
                         cpu.l_trap_enable);
                sr_change_count <= sr_change_count + 1;
            end
            prev_sr_dbg <= cpu.sr_rd;

            // Record trace buffer (only on PC changes)
            if (cpu.pc_rd != prev_pc) begin
                trace_pc[trace_idx]    <= cpu.pc_rd;
                trace_instr[trace_idx] <= cpu.instr;
                trace_sr[trace_idx]    <= cpu.sr_rd;
                trace_cycle[trace_idx] <= cycle_count;
                trace_idx <= (trace_idx + 1) % TRACE_DEPTH;
                trace_count <= trace_count + 1;
            end

            // Detailed register debug (enable with +debug)
            if (debug_enable && cycle_count <= 200)
                $display("[%0d] PC=0x%08x instr=0x%08x r1=0x%08x r3=0x%08x r9=0x%08x r13=0x%08x r15=0x%08x SR=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.instr,
                         cpu.rf[1], cpu.rf[3], cpu.rf[9], cpu.rf[13], cpu.rf[15],
                         cpu.sr_rd);

            // Log first user mode entry and nearby transitions
            if (cpu.sr_rd[0] != prev_sr[0]) begin
                if (!cpu.sr_rd[0]) begin
                    $display("[%0d] ENTER USER MODE: PC=0x%08x SR=0x%08x EPCR=0x%08x ESR=0x%08x instr=0x%08x",
                             cycle_count, cpu.pc_rd, cpu.sr_rd, cpu.epcr0_rd, cpu.esr0_rd, cpu.instr);
                    $display("  r1=0x%08x r3=0x%08x r9=0x%08x r11=0x%08x r13=0x%08x",
                             cpu.rf[1], cpu.rf[3], cpu.rf[9], cpu.rf[11], cpu.rf[13]);
                end else if (!prev_sr[0]) begin
                    $display("[%0d] LEAVE USER MODE: PC=0x%08x SR=0x%08x EPCR=0x%08x ESR=0x%08x instr=0x%08x prev_pc=0x%08x",
                             cycle_count, cpu.pc_rd, cpu.sr_rd, cpu.epcr0_rd, cpu.esr0_rd, cpu.instr, prev_pc);
                end
            end
            // Trace first 50 cycles after entering user mode
            if (!cpu.sr_rd[0] || (!prev_sr[0] && cpu.sr_rd[0])) begin
                if (user_trace_count < 200) begin
                    $display("[%0d] USER_TRACE: PC=0x%08x SR=0x%08x instr=0x%08x EPCR=0x%08x delay_slot=%0d",
                             cycle_count, cpu.pc_rd, cpu.sr_rd, cpu.instr, cpu.epcr0_rd, cpu.delay_slot_rd);
                    user_trace_count <= user_trace_count + 1;
                end
            end

            // MMU enable transitions (disabled - too noisy)
            // if (cpu.sr_rd[5] != prev_sr[5])
            //     $display("[%0d] IME ...");
            // if (cpu.sr_rd[4] != prev_sr[4])
            //     $display("[%0d] DME ...");

            // Interrupt enable transitions (disabled - too noisy)
            // if (cpu.sr_rd[2] != prev_sr[2])
            //     $display("[%0d] IEE %s: PC=0x%08x SR=0x%08x",
            //              cycle_count, cpu.sr_rd[2] ? "ENABLED" : "DISABLED",
            //              cpu.pc_rd, cpu.sr_rd);
            // if (cpu.sr_rd[1] != prev_sr[1])
            //     $display("[%0d] TEE %s: PC=0x%08x SR=0x%08x",
            //              cycle_count, cpu.sr_rd[1] ? "ENABLED" : "DISABLED",
            //              cpu.pc_rd, cpu.sr_rd);

            // Exception vector detection
            if (cpu.pc_rd != prev_pc) begin
                if ((cpu.pc_rd[31:12] == 20'h0 || cpu.pc_rd[31:12] == 20'hF0000) &&
                    cpu.pc_rd[7:0] == 8'h00 &&
                    cpu.pc_rd[11:8] >= 4'h1 && cpu.pc_rd[11:8] <= 4'hE) begin
                    case (cpu.pc_rd[11:8])
                        // Only log important exceptions (skip TLB miss, page faults, tick timer - too frequent)
                        4'h2: $display("[%0d] EXCEPTION: Bus Error       PC=0x%08x epcr0=0x%08x eear0=0x%08x",
                                       cycle_count, cpu.pc_rd, cpu.epcr0_rd, cpu.eear0_rd);
                        4'h6: $display("[%0d] EXCEPTION: Alignment       PC=0x%08x epcr0=0x%08x eear0=0x%08x",
                                       cycle_count, cpu.pc_rd, cpu.epcr0_rd, cpu.eear0_rd);
                        4'h7: $display("[%0d] EXCEPTION: Illegal Instr   PC=0x%08x epcr0=0x%08x instr=0x%08x",
                                       cycle_count, cpu.pc_rd, cpu.epcr0_rd, cpu.instr);
                        4'hC: $display("[%0d] EXCEPTION: System Call     PC=0x%08x epcr0=0x%08x r11=0x%08x r3=0x%08x",
                                       cycle_count, cpu.pc_rd, cpu.epcr0_rd, cpu.rf[11], cpu.rf[3]);
                        4'hE: $display("[%0d] EXCEPTION: Trap            PC=0x%08x epcr0=0x%08x",
                                       cycle_count, cpu.pc_rd, cpu.epcr0_rd);
                        default: ;
                    endcase
                end
            end

            // Timer interrupt transitions
            prev_tick_irq <= tick_irq_pending;
            prev_ttmr <= cpu.ttmr_rd;
            prev_ttcr <= cpu.ttcr_rd;
            prev_ext_irq <= uart_irq;

            // UART IRQ debug: trace when uart_irq changes or ext interrupt taken
            if (cycle_count > 21000000) begin
                if (uart_irq != prev_ext_irq || cpu.l_add_take_ext_interrupt_mux) begin
                    $display("[%0d] UART_IRQ: uart_irq=%b picsr=0x%08x picmr=0x%08x ier=0x%02x thr_int=%b sr_iee=%b take_ext=%b",
                             cycle_count, uart_irq,
                             cpu.picsr_rd, cpu.picmr_rd,
                             uart_inst.ier, uart_inst.thr_int_pending,
                             cpu.sr_rd[2], cpu.l_add_take_ext_interrupt_mux);
                end
            end

            prev_r9 <= cpu.rf[9];

            // l.nop special codes
            if (cpu.instr[31:16] == 16'h1500) begin
                case (cpu.instr[15:0])
                    16'h0001: begin
                        if (!nop_halt_seen) begin
                            $display("[%0d] *** NOP HALT at PC=0x%08x r3=0x%08x",
                                     cycle_count, cpu.pc_rd, cpu.rf[3]);
                            $display("  r1(sp)=0x%08x r9(lr)=0x%08x r11=0x%08x",
                                     cpu.rf[1], cpu.rf[9], cpu.rf[11]);
                            $display("  SR=0x%08x EPCR0=0x%08x ESR0=0x%08x EEAR0=0x%08x",
                                     cpu.sr_rd, cpu.epcr0_rd, cpu.esr0_rd, cpu.eear0_rd);
                            for (i = 0; i < 32; i = i + 1)
                                $display("  r%0d=0x%08x", i, cpu.rf[i]);
                            $display("Trace buffer (last %0d PC changes before halt):",
                                     trace_count < TRACE_DEPTH ? trace_count : TRACE_DEPTH);
                            for (i = 0; i < TRACE_DEPTH; i = i + 1) begin
                                j = (trace_idx + i) % TRACE_DEPTH;
                                if (trace_cycle[j] != 0)
                                    $display("  [%0d] PC=0x%08x instr=0x%08x SR=0x%08x",
                                             trace_cycle[j], trace_pc[j], trace_instr[j], trace_sr[j]);
                            end
                            $display("=== END NOP HALT TRACE ===");
                            nop_halt_seen = 1;
                            $finish;
                        end
                    end
                    16'h0002: $display("[%0d] NOP REPORT: r3=0x%08x at PC=0x%08x",
                                       cycle_count, cpu.rf[3], cpu.pc_rd);
                    16'h0003, 16'h0004: begin
                        $write("%c", cpu.rf[3][7:0]);
                        $fflush();
                    end
                    default: ;
                endcase
            end

            // Periodic progress
            if (cycle_count % 5_000_000 == 0) begin
                $display("[%0d] PC=0x%08x SR=0x%08x instr=0x%08x r1=0x%08x r9=0x%08x tick=%0b ext=%0b TTMR=0x%08x TTCR=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.sr_rd, cpu.instr,
                         cpu.rf[1], cpu.rf[9], tick_irq_pending, uart_irq,
                         cpu.ttmr_rd, cpu.ttcr_rd);
                // jiffies_64 low at phys 0x0029B024, high at 0x0029B020
                // local_softirq_pending at phys 0x0029F9A0
                // tick_do_timer_cpu at phys 0x0029C06C
                // TIF_NEED_RESCHED: thread_info->flags (r10+4) bit 3
                $display("[%0d]   jiffies_lo=0x%08x next_expiry=0x%08x softirq_pending=0x%08x tick_do_timer_cpu=%0d ti_flags=0x%08x",
                         cycle_count,
                         main_memory[32'h0029B024 >> 2],
                         main_memory[32'h0029B038 >> 2],
                         main_memory[32'h0029F9A0 >> 2],
                         main_memory[32'h0029C06C >> 2],
                         main_memory[(cpu.rf[10] + 4 - 32'hC0000000) >> 2]);
            end

            // Softirq pending watchpoint: report whenever it changes
            if (main_memory[32'h0029F9A0 >> 2] != prev_softirq_pending) begin
                $display("[%0d] SOFTIRQ_PENDING changed: 0x%08x -> 0x%08x  PC=0x%08x",
                         cycle_count, prev_softirq_pending,
                         main_memory[32'h0029F9A0 >> 2], cpu.pc_rd);
                prev_softirq_pending <= main_memory[32'h0029F9A0 >> 2];
            end
            // next_expiry watchpoint (timer_bases[0].next_expiry at phys 0x0029B038)
            if (main_memory[32'h0029B038 >> 2] != prev_next_expiry) begin
                $display("[%0d] NEXT_EXPIRY changed: 0x%08x -> 0x%08x  PC=0x%08x",
                         cycle_count, prev_next_expiry,
                         main_memory[32'h0029B038 >> 2], cpu.pc_rd);
                prev_next_expiry <= main_memory[32'h0029B038 >> 2];
            end

            // kthreadd task state watchpoint (kthreadd task_struct at phys 0x0080cb50, __state at offset 0)
            if (main_memory[32'h0080cb50 >> 2] != prev_kthreadd_state) begin
                $display("[%0d] KTHREADD_STATE changed: 0x%08x -> 0x%08x  PC=0x%08x",
                         cycle_count, prev_kthreadd_state,
                         main_memory[32'h0080cb50 >> 2], cpu.pc_rd);
                prev_kthreadd_state <= main_memory[32'h0080cb50 >> 2];
            end

            // PC dump (triggered by specific events)
            if (pc_dump_enable && (cycle_count - pc_dump_start) < 100) begin
                $display("[%0d] PC_DUMP: PC=0x%08x instr=0x%08x SR=0x%08x r9=0x%08x r3=0x%08x",
                         cycle_count, cpu.pc_rd,
                         (cpu.pc_rd >= 32'hC0000000) ? main_memory[(cpu.pc_rd - 32'hC0000000) >> 2] : 32'h0,
                         cpu.sr_rd, cpu.rf[9], cpu.rf[3]);
            end else if (pc_dump_enable) begin
                pc_dump_enable <= 0;
            end

            // Bad PC detection (kernel virtual addresses 0xC0000000+ are valid)
            if (cpu.pc_rd > MEMORY_SIZE && cpu.pc_rd < 32'hC0000000 && cycle_count > 20)
                $display("[%0d] *** BAD PC: 0x%08x sr=0x%08x epcr0=0x%08x",
                         cycle_count, cpu.pc_rd, cpu.sr_rd, cpu.epcr0_rd);

            // ============================================================
            // Function entry tracing for FDT/memblock initialization path
            // ============================================================
            if (cpu.pc_rd != prev_pc) begin
                case (cpu.pc_rd)
                    // panic() entry
                    32'hc02488e4: begin
                        if (!panic_detected) begin
                            panic_detected <= 1;
                            $display("=== PANIC() ENTRY at cycle %0d ===", cycle_count);
                            $display("  r3(msg)=0x%08x r9(lr)=0x%08x r1(sp)=0x%08x",
                                     cpu.rf[3], cpu.rf[9], cpu.rf[1]);
                            for (i = 0; i < 32; i = i + 1)
                                $display("  r%0d=0x%08x", i, cpu.rf[i]);
                            $display("Trace buffer (last %0d entries):",
                                     trace_count < TRACE_DEPTH ? trace_count : TRACE_DEPTH);
                            for (i = 0; i < TRACE_DEPTH; i = i + 1) begin
                                j = (trace_idx + i) % TRACE_DEPTH;
                                if (trace_cycle[j] != 0)
                                    $display("  [%0d] PC=0x%08x instr=0x%08x SR=0x%08x",
                                             trace_cycle[j], trace_pc[j], trace_instr[j], trace_sr[j]);
                            end
                            $display("=== END PANIC TRACE ===");
                        end
                    end
                    // early_init_dt_scan_nodes
                    32'hc02b9758: $display("[%0d] FUNC: early_init_dt_scan_nodes() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // of_scan_flat_dt
                    32'hc02b8438: $display("[%0d] FUNC: of_scan_flat_dt(fn=0x%08x, data=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // early_init_dt_scan_memory (callback)
                    32'hc02b9484: $display("[%0d] FUNC: early_init_dt_scan_memory(node=0x%08x, uname=%08x, depth=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[9]);
                    // early_init_dt_add_memory_arch
                    32'hc02b933c: $display("[%0d] FUNC: early_init_dt_add_memory_arch(base=0x%08x, size=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // early_init_dt_alloc_memory_arch
                    32'hc02b8148: $display("[%0d] FUNC: early_init_dt_alloc_memory_arch(size=0x%08x, align=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // memblock_add
                    32'hc02bffdc: $display("[%0d] FUNC: memblock_add(base=0x%08x, size=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // memblock_add_range
                    32'hc02bfc9c: $display("[%0d] FUNC: memblock_add_range(base=0x%08x, size=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // memblock_reserve
                    32'hc02bff3c: $display("[%0d] FUNC: memblock_reserve(base=0x%08x, size=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // fdt_check_header
                    32'hc0216988: $display("[%0d] FUNC: fdt_check_header(fdt=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);
                    // of_flat_dt_is_compatible
                    32'hc02b8660: $display("[%0d] FUNC: of_flat_dt_is_compatible(node=0x%08x, compat=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // early_init_fdt_reserve_self
                    32'hc02b83cc: $display("[%0d] FUNC: early_init_fdt_reserve_self() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // of_get_flat_dt_root
                    32'hc02b8604: $display("[%0d] FUNC: of_get_flat_dt_root() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // of_get_flat_dt_prop
                    32'hc02b8628: $display("[%0d] FUNC: of_get_flat_dt_prop(node=0x%08x, name=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // early_init_dt_scan_chosen
                    32'hc02b9098: $display("[%0d] FUNC: early_init_dt_scan_chosen(node=0x%08x, uname=0x%08x, depth=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[9]);
                    // early_init_dt_scan_root
                    32'hc02b8a7c: $display("[%0d] FUNC: early_init_dt_scan_root(node=0x%08x, uname=0x%08x, depth=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[9]);
                    // fdt_next_node
                    32'hc0216fc4: $display("[%0d] FUNC: fdt_next_node(fdt=0x%08x, offset=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // fdt_get_name
                    32'hc021798c: $display("[%0d] FUNC: fdt_get_name(fdt=0x%08x, offset=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // fdt_next_tag
                    32'hc0216d54: $display("[%0d] FUNC: fdt_next_tag(fdt=0x%08x, offset=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // unflatten_device_tree
                    32'hc02b97f4: $display("[%0d] FUNC: unflatten_device_tree() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // early_init_devtree
                    32'hc02a9ccc: $display("[%0d] FUNC: early_init_devtree(params=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);
                    // or1k_early_setup
                    32'hc02a96e4: $display("[%0d] FUNC: or1k_early_setup() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);

                    // ============================================================
                    // Page fault / exception tracing
                    // ============================================================
                    // do_page_fault(regs, address, vector, write)
                    32'hc00084a0: $display("[%0d] FUNC: do_page_fault(regs=0x%08x, addr=0x%08x, vector=0x%08x, write=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[9]);
                    // die(str, regs, err)
                    32'hc0005580: $display("[%0d] FUNC: die(str=0x%08x, regs=0x%08x, err=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[9]);
                    // do_bus_fault(regs, vector)
                    32'hc0005668: $display("[%0d] FUNC: do_bus_fault(regs=0x%08x, vector=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // show_registers(regs)
                    32'hc02480dc: $display("[%0d] FUNC: show_registers(regs=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);
                    // _printk
                    32'hc0249e60: $display("[%0d] FUNC: _printk(fmt=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);

                    // ============================================================
                    // Percpu / bitmap debugging
                    // ============================================================
                    // __bitmap_set(bitmap, start, nbits)
                    32'hc0175b18: $display("[%0d] FUNC: __bitmap_set(bitmap=0x%08x, start=%0d, nbits=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[9]);
                    // pcpu_alloc_first_chunk(base_addr, start, map_size, region_size)
                    32'hc02ae7e0: $display("[%0d] FUNC: pcpu_alloc_first_chunk(base=0x%08x, start=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // memblock_alloc_try_nid(size, align, ...)
                    32'hc02b2064: $display("[%0d] FUNC: memblock_alloc_try_nid(size=0x%08x, align=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);

                    // Per-instruction traces for pcpu nr_pages computation
                    // After lcm returns, executing l.add r18,r18,r11
                    32'hc02ae83c: $display("[%0d] PCPU_TRACE @83c: r11(lcm)=0x%08x r18(offset+sz-1)=0x%08x r22(off+map)=0x%08x",
                                           cycle_count, cpu.rf[11], cpu.rf[18], cpu.rf[22]);
                    // After l.add, executing l.sub r11,r0,r11
                    32'hc02ae840: $display("[%0d] PCPU_TRACE @840: r18(after add)=0x%08x r11=0x%08x",
                                           cycle_count, cpu.rf[18], cpu.rf[11]);
                    // After l.sub, executing l.and r18,r18,r11
                    32'hc02ae844: $display("[%0d] PCPU_TRACE @844: r11(negated)=0x%08x r18=0x%08x",
                                           cycle_count, cpu.rf[11], cpu.rf[18]);
                    // After l.and, executing l.srai r30,r18,0xd
                    32'hc02ae848: $display("[%0d] PCPU_TRACE @848: r18(aligned)=0x%08x",
                                           cycle_count, cpu.rf[18]);
                    // After l.srai: r30 = nr_pages
                    32'hc02ae84c: $display("[%0d] PCPU_TRACE @84c: r30(nr_pages)=%0d r18=0x%08x",
                                           cycle_count, cpu.rf[30], cpu.rf[18]);

                    // lcm() internal traces
                    // lcm entry
                    32'hc0188ce0: $display("[%0d] LCM_TRACE entry: r3=0x%08x r4=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4]);
                    // Before gcd call
                    32'hc0188d28: $display("[%0d] LCM_TRACE before_gcd: r3=0x%08x r4=0x%08x r16=0x%08x r18=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[16], cpu.rf[18]);
                    // After gcd returns: l.divu r11,r16,r11
                    32'hc0188d30: $display("[%0d] LCM_TRACE divu: r16=0x%08x r11(gcd)=0x%08x r18=0x%08x",
                                           cycle_count, cpu.rf[16], cpu.rf[11], cpu.rf[18]);
                    // After l.divu: l.mul r11,r11,r18
                    32'hc0188d34: $display("[%0d] LCM_TRACE mul: r11(div_result)=0x%08x r18=0x%08x",
                                           cycle_count, cpu.rf[11], cpu.rf[18]);
                    // After l.mul: restore r16
                    32'hc0188d38: $display("[%0d] LCM_TRACE after_mul: r11(lcm_result)=0x%08x",
                                           cycle_count, cpu.rf[11]);
                    // lcm return-0 path (r3==0)
                    32'hc0188d50: $display("[%0d] LCM_TRACE return_zero: r3=0x%08x r4=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4]);
                    // lcm early return (r4==0)
                    32'hc0188d0c: $display("[%0d] LCM_TRACE r4_zero_path: r11=0x%08x",
                                           cycle_count, cpu.rf[11]);

                    // gcd() internal traces
                    // gcd entry
                    32'hc0188c10: $display("[%0d] GCD entry: r3=0x%08x r4=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4]);
                    // After l.ff1 r17,r4 (c0188c38), at l.addi
                    32'hc0188c3c: $display("[%0d] GCD after ff1(r4): r17(ff1)=%0d r4=0x%08x r11=0x%08x",
                                           cycle_count, cpu.rf[17], cpu.rf[4], cpu.rf[11]);
                    // l.srl r4,r4,r17 at c0188c40 - trace DURING execution
                    32'hc0188c40: begin
                        $display("[%0d] SRL_EXEC: pc=0x%08x instr=0x%08x instr_9_8=%0d",
                                 cycle_count, cpu.pc_rd, cpu.instr, cpu.instr[9:8]);
                        $display("  sll_en=%0d srl_en=%0d sra_en=%0d",
                                 cpu.l_sll_enable, cpu.l_srl_enable, cpu.l_sra_enable);
                        $display("  instr_9_8_eq_0=%0d instr_9_8_eq_1=%0d instr_9_8_eq_2=%0d",
                                 cpu.instr_9_8_eq_0, cpu.instr_9_8_eq_1, cpu.instr_9_8_eq_2);
                        $display("  rA_rd=0x%08x rB_rd=0x%08x srl_res=0x%08x sll_res=0x%08x",
                                 cpu.rf_rA_rd, cpu.rf_rB_rd, cpu.l_srl_res, cpu.l_sll_res);
                        $display("  rf_write_data=0x%08x rf_write_addr=%0d",
                                 cpu.rf_write_data_mux[31:0], cpu.rf_write_addr_mux);
                    end
                    // After l.srl r4,r4,r17, at l.sfnei
                    32'hc0188c44: $display("[%0d] GCD after srl: r4(shifted)=0x%08x r17=%0d",
                                           cycle_count, cpu.rf[4], cpu.rf[17]);
                    // At l.bnf c0188cb0 - branch decision point
                    32'hc0188c48: $display("[%0d] GCD bnf_check: r4=%0d flag=%0d",
                                           cycle_count, cpu.rf[4], cpu.flag_rd);
                    // After l.ff1 r17,r3 (c0188c50) at l.addi
                    32'hc0188c54: $display("[%0d] GCD after ff1(r3): r17(ff1)=%0d r3=0x%08x",
                                           cycle_count, cpu.rf[17], cpu.rf[3]);
                    // l.and r11,r11,r17 at c0188cb0
                    32'hc0188cb0: $display("[%0d] GCD and_result: r11=0x%08x r17=0x%08x => r11&r17=0x%08x",
                                           cycle_count, cpu.rf[11], cpu.rf[17], cpu.rf[11] & cpu.rf[17]);
                    // gcd alternative return path at c0188cc4
                    32'hc0188cc4: $display("[%0d] GCD alt_return: r3=0x%08x r4=0x%08x r11=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[11]);

                    // ============================================================
                    // start_kernel() initialization milestone tracing
                    // ============================================================
                    // start_kernel
                    32'hc02a6874: $display("[%0d] FUNC: start_kernel() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // setup_arch
                    32'hc02a9a7c: $display("[%0d] FUNC: setup_arch() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // setup_per_cpu_areas
                    32'hc02af5a8: $display("[%0d] FUNC: setup_per_cpu_areas() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // mem_init
                    32'hc02a9fd8: $display("[%0d] FUNC: mem_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // kmem_cache_init
                    32'hc02b28a8: $display("[%0d] FUNC: kmem_cache_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // vmalloc_init
                    32'hc02af9b4: $display("[%0d] FUNC: vmalloc_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // init_IRQ
                    32'hc02a9ca8: $display("[%0d] FUNC: init_IRQ() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // console_init
                    32'hc02ad2d4: $display("[%0d] FUNC: console_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // rest_init (called at end of start_kernel)
                    32'hc024f8cc: $display("[%0d] FUNC: rest_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // machine_halt
                    32'hc0247f3c: $display("[%0d] FUNC: machine_halt() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // sched_init
                    32'hc02ac350: $display("[%0d] FUNC: sched_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // trap_init
                    32'hc02a6854: $display("[%0d] FUNC: trap_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // time_init
                    32'hc02a9c28: $display("[%0d] FUNC: time_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // early_irq_init
                    32'hc02ad48c: $display("[%0d] FUNC: early_irq_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // tick_init
                    32'hc02ae178: $display("[%0d] FUNC: tick_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // arch_call_rest_init
                    32'hc02a67a0: $display("[%0d] FUNC: arch_call_rest_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);

                    // Scheduler and context switch tracing
                    32'hc0250488: $display("[%0d] FUNC: __schedule() lr=0x%08x", cycle_count, cpu.rf[9]);
                    32'hc025094c: $display("[%0d] FUNC: schedule() lr=0x%08x", cycle_count, cpu.rf[9]);
                    32'hc0250a78: $display("[%0d] FUNC: schedule_idle() lr=0x%08x", cycle_count, cpu.rf[9]);
                    32'hc0250afc: $display("[%0d] FUNC: schedule_preempt_disabled() lr=0x%08x", cycle_count, cpu.rf[9]);
                    32'hc00051f0: $display("[%0d] FUNC: __switch_to(old=0x%08x, new=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    32'hc000737c: $display("[%0d] FUNC: ret_from_fork() lr=0x%08x r3=0x%08x r20=0x%08x r22=0x%08x",
                                           cycle_count, cpu.rf[9], cpu.rf[3], cpu.rf[20], cpu.rf[22]);
                    // l.jalr r20 in ret_from_fork (kernel thread function call)
                    32'hc0007390: $display("[%0d] FUNC: ret_from_fork JALR r20=0x%08x r22(arg)=0x%08x",
                                           cycle_count, cpu.rf[20], cpu.rf[22]);
                    32'hc0042f2c: $display("[%0d] FUNC: do_idle() lr=0x%08x", cycle_count, cpu.rf[9]);
                    // kernel_init
                    32'hc024f97c: $display("[%0d] FUNC: kernel_init() lr=0x%08x r3=0x%08x",
                                           cycle_count, cpu.rf[9], cpu.rf[3]);
                    // kernel_init_freeable
                    32'hc02a7390: $display("[%0d] FUNC: kernel_init_freeable() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // cpu_startup_entry
                    32'hc00433b0: $display("[%0d] FUNC: cpu_startup_entry() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // rest_init
                    32'hc024f8cc: $display("[%0d] FUNC: rest_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);

                    // timer_interrupt calls clockevent handler via l.jalr r17
                    32'hc02570d8: $display("[%0d] FUNC: timer_interrupt JALR handler=0x%08x (r17)",
                                           cycle_count, cpu.rf[17]);

                    // tick_handle_periodic
                    32'hc007749c: $display("[%0d] FUNC: tick_periodic() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // tick_periodic after loading tick_do_timer_cpu into r17
                    32'hc00774b4: $display("[%0d] FUNC: tick_periodic tick_do_timer_cpu=0x%08x (r17) at branch",
                                           cycle_count, cpu.rf[17]);
                    // update_process_times
                    32'hc00638ec: $display("[%0d] FUNC: update_process_times() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // scheduler_tick
                    32'hc0039fd8: $display("[%0d] FUNC: scheduler_tick() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // do_timer path in tick_periodic (address after branch-not-taken)
                    32'hc00774ec: $display("[%0d] FUNC: tick_periodic->do_timer_path entered",
                                           cycle_count);

                    // run_local_timers entry
                    32'hc0065224: $display("[%0d] FUNC: run_local_timers() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // run_local_timers comparison point: r17 vs r18 before sfgts
                    32'hc00652a4: $display("[%0d] FUNC: run_local_timers cmp: r17(base_field)=0x%08x r18(jiffies?)=0x%08x r12=0x%08x",
                                           cycle_count, cpu.rf[17], cpu.rf[18], cpu.rf[12]);
                    // raise_softirq_irqoff called with r3=softirq_nr
                    32'hc00652e0: $display("[%0d] FUNC: run_local_timers->raise_softirq(nr=%0d)",
                                           cycle_count, cpu.rf[3]);
                    // run_local_timers return without raising
                    32'hc00652ec: $display("[%0d] FUNC: run_local_timers->skip_to_hrtimer r6=%0d",
                                           cycle_count, cpu.rf[6]);

                    // update_process_times: before l.sub (jiffies - next_expiry)
                    // r17 = jiffies, r19 = next_expiry (from timer_bases[0])
                    32'hc006392c: $display("[%0d] FUNC: update_process_times cmp: jiffies=0x%08x next_expiry=0x%08x",
                                           cycle_count, cpu.rf[17], cpu.rf[19]);
                    // update_process_times: raise_softirq(TIMER_SOFTIRQ) call reached
                    32'hc006393c: $display("[%0d] FUNC: update_process_times->raise_softirq(TIMER_SOFTIRQ) REACHED! r3=%0d",
                                           cycle_count, cpu.rf[3]);
                    // update_process_times: skip TIMER_SOFTIRQ (jiffies < next_expiry)
                    32'hc0063944: $display("[%0d] FUNC: update_process_times->skip_TIMER_SOFTIRQ",
                                           cycle_count);

                    // raise_softirq_irqoff entry - capture ALL softirq raises
                    32'hc0011234: $display("[%0d] FUNC: raise_softirq_irqoff(nr=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);
                    // raise_softirq (with local_irq_save wrapper) at 0xc00112bc
                    32'hc00112bc: $display("[%0d] FUNC: raise_softirq(nr=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);

                    // do_wait_for_common: call to schedule function (captures completion info)
                    32'hc0250f50: $display("[%0d] FUNC: do_wait_for_common JALR r22=0x%08x r16(timeout)=0x%08x r18(completion)=0x%08x lr=0x%08x",
                                           cycle_count, cpu.rf[22], cpu.rf[16], cpu.rf[18], cpu.rf[9]);
                    // complete() - traces which completions are signaled
                    32'hc00473ec: $display("[%0d] FUNC: complete(completion=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);

                    // do_one_initcall - traces which init function is called
                    32'hc02a7014: $display("[%0d] FUNC: do_one_initcall(fn=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);

                    // wait_for_completion entry - capture caller
                    32'hc02510a4: $display("[%0d] FUNC: wait_for_completion(completion=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);
                    // __wait_for_common entry - catches ALL wait variants
                    32'hc0250ebc: $display("[%0d] FUNC: __wait_for_common(completion=0x%08x, timeout=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                    // wait_for_completion_killable entry - captures caller
                    32'hc02511f0: $display("[%0d] FUNC: wait_for_completion_killable(completion=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);
                    // wake_up_process entry
                    32'hc00399a4: $display("[%0d] FUNC: wake_up_process(task=0x%08x) lr=0x%08x state@task=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9],
                                           main_memory[(cpu.rf[3] - 32'hC0000000) >> 2]);
                    // kthread_create_on_node: jal wake_up_process (confirm this code executes)
                    32'hc002f7f8: begin
                        $display("[%0d] FUNC: kthread_create_on_node->wake_kthreadd r17=0x%08x kthreadd_task=0x%08x",
                                           cycle_count, cpu.rf[17],
                                           main_memory[(cpu.rf[17] + 32'h6984 - 32'hC0000000) >> 2]);
                        // Enable PC dump for next 100 cycles to trace the branch
                        pc_dump_start <= cycle_count;
                        pc_dump_enable <= 1;
                    end
                    // kthread_create_on_node entry
                    32'hc002f75c: $display("[%0d] FUNC: kthread_create_on_node(fn=0x%08x, data=0x%08x, node=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[9]);
                    // kthreadd processing loop: create_kthread called from kthreadd
                    32'hc002f154: $display("[%0d] FUNC: kthreadd_create_kthread(create=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);

                    // Functions between early and main initcall loops in kernel_init_freeable
                    32'hc02ac32c: $display("[%0d] FUNC: post_early_call_1 (0xc02ac32c) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b0314: $display("[%0d] FUNC: post_early_call_2 (0xc02b0314) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b7a68: $display("[%0d] FUNC: post_early_call_3 (0xc02b7a68) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc005bd58: $display("[%0d] FUNC: post_early_call_4 (0xc005bd58) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc0234ed4: $display("[%0d] FUNC: post_early_call_5 (0xc0234ed4) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);

                    // Subfunctions called by post_early_call_3 (0xc02b7a68 = likely do_basic_setup)
                    32'hc00a28f0: $display("[%0d] FUNC: sub3_1 (0xc00a28f0) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b7d7c: $display("[%0d] FUNC: sub3_2_driver_init (0xc02b7d7c) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b7490: $display("[%0d] FUNC: sub3_3 (0xc02b7490) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b755c: $display("[%0d] FUNC: sub3_4 (0xc02b755c) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b76bc: $display("[%0d] FUNC: sub3_5 (0xc02b76bc) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b7a20: $display("[%0d] FUNC: sub3_6_do_initcalls (0xc02b7a20) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b7ee8: $display("[%0d] FUNC: sub3_7 (0xc02b7ee8) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b7928: $display("[%0d] FUNC: sub3_8 (0xc02b7928) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b79b4: $display("[%0d] FUNC: sub3_9 (0xc02b79b4) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    32'hc02b7b24: $display("[%0d] FUNC: sub3_10 (0xc02b7b24) lr=0x%08x",
                                           cycle_count, cpu.rf[9]);

                    // Start of main initcall loop (0xc02a74dc)
                    32'hc02a74dc: $display("[%0d] FUNC: main_initcall_loop_start lr=0x%08x r26(level)=%0d",
                                           cycle_count, cpu.rf[9], cpu.rf[26]);

                    // __mod_timer - timer enqueue function
                    32'hc0062c68: $display("[%0d] FUNC: __mod_timer(timer=0x%08x, expires=0x%08x, mode=%0d) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[9]);
                    // schedule_timeout entry
                    32'hc02561f8: $display("[%0d] FUNC: schedule_timeout(timeout=0x%08x) lr=0x%08x",
                                           cycle_count, cpu.rf[3], cpu.rf[9]);

                    // clockevents_program_event - may reveal clockevent setup
                    32'hc0005c60: $display("[%0d] FUNC: openrisc_clockevent_init() lr=0x%08x",
                                           cycle_count, cpu.rf[9]);
                    // clockevents_register_device
                    32'hc0063c90: $display("[%0d] FUNC: clockevents_register_device() lr=0x%08x r3=0x%08x",
                                           cycle_count, cpu.rf[9], cpu.rf[3]);
                    // clockevents_config_and_register
                    32'hc0063dac: $display("[%0d] FUNC: clockevents_config_and_register() lr=0x%08x r3=0x%08x",
                                           cycle_count, cpu.rf[9], cpu.rf[3]);

                    default: ;
                endcase
            end

            // Panic spin loop detection (backup): panic_smp_self_stop loop at 0xc000cfbc
            if (cpu.pc_rd == 32'hc000cfbc && prev_pc != 32'hc000cfbc && !panic_detected) begin
                panic_detected <= 1;
                $display("=== PANIC SPIN LOOP at cycle %0d ===", cycle_count);
                $display("  PC=0x%08x r1(sp)=0x%08x r9(lr)=0x%08x", cpu.pc_rd, cpu.rf[1], cpu.rf[9]);
                $finish;
            end
            // Stop after panic detected + some cycles for printk to finish
            if (panic_detected && cycle_count > 250000) begin
                $display("=== Stopping after panic at cycle %0d ===", cycle_count);
                $finish;
            end

            // Stuck PC detection: PC unchanged for 100 cycles
            if (cpu.pc_rd == prev_pc)
                stuck_count = stuck_count + 1;
            else
                stuck_count = 0;

            if (stuck_count == 100 && !bad_pc_triggered) begin
                bad_pc_triggered <= 1;
                $display("=== STUCK PC DETECTED at cycle %0d (100 cycles same PC) ===", cycle_count);
                $display("  PC=0x%08x SR=0x%08x instr=0x%08x",
                         cpu.pc_rd, cpu.sr_rd, cpu.instr);
                $display("  EPCR0=0x%08x ESR0=0x%08x EEAR0=0x%08x",
                         cpu.epcr0_rd, cpu.esr0_rd, cpu.eear0_rd);
                $display("  r1(sp)=0x%08x r3=0x%08x r9(lr)=0x%08x r11=0x%08x",
                         cpu.rf[1], cpu.rf[3], cpu.rf[9], cpu.rf[11]);
                for (i = 0; i < 32; i = i + 1)
                    $display("  r%0d=0x%08x", i, cpu.rf[i]);
                $display("Trace buffer (last %0d PC changes):", trace_count < TRACE_DEPTH ? trace_count : TRACE_DEPTH);
                for (i = 0; i < TRACE_DEPTH; i = i + 1) begin
                    j = (trace_idx + i) % TRACE_DEPTH;
                    if (trace_cycle[j] != 0)
                        $display("  [%0d] PC=0x%08x instr=0x%08x SR=0x%08x",
                                 trace_cycle[j], trace_pc[j], trace_instr[j], trace_sr[j]);
                end
                $display("=== END STUCK PC TRACE ===");
                $finish;
            end

            // Track R1 (stack pointer) for stack overflow detection
            // Init stack: 0xc0280000 to 0xc0282000 (8KB)
            if (cpu.rf[1] != prev_r1 && cycle_count > 30) begin
                // Detect when R1 leaves init stack range
                if (!r1_overflow_reported && cpu.rf[1] < 32'hc0280000 && cpu.rf[1] >= 32'hc0000000) begin
                    r1_overflow_reported <= 1;
                    $display("=== R1 STACK OVERFLOW at cycle %0d ===", cycle_count);
                    $display("  R1: 0x%08x -> 0x%08x (below init_thread_union 0xc0280000)",
                             prev_r1, cpu.rf[1]);
                    $display("  PC=0x%08x instr=0x%08x SR=0x%08x", cpu.pc_rd, cpu.instr, cpu.sr_rd);
                    $display("  r9(lr)=0x%08x r10=0x%08x", cpu.rf[9], cpu.rf[10]);
                    $display("=== END R1 OVERFLOW ===");
                end
            end
            prev_r1 <= cpu.rf[1];

            prev_pc <= cpu.pc_rd;
            prev_sr <= cpu.sr_rd;

            // Timeout
            if (cycle_count >= max_cycles) begin
                $display("==============================================");
                $display("TIMEOUT after %0d cycles", cycle_count);
                $display("  PC=0x%08x SR=0x%08x", cpu.pc_rd, cpu.sr_rd);
                $display("  EPCR0=0x%08x ESR0=0x%08x EEAR0=0x%08x",
                         cpu.epcr0_rd, cpu.esr0_rd, cpu.eear0_rd);
                $display("  r1(sp)=0x%08x r9(lr)=0x%08x r3=0x%08x r11=0x%08x",
                         cpu.rf[1], cpu.rf[9], cpu.rf[3], cpu.rf[11]);
                $display("  TTMR=0x%08x TTCR=0x%08x PICMR=0x%08x PICSR=0x%08x",
                         cpu.ttmr_rd, cpu.ttcr_rd, pic_inst.picmr, pic_inst.picsr);
                // Dump trace buffer
                $display("Trace buffer (last %0d PC changes):", trace_count < TRACE_DEPTH ? trace_count : TRACE_DEPTH);
                for (i = 0; i < TRACE_DEPTH; i = i + 1) begin
                    j = (trace_idx + i) % TRACE_DEPTH;
                    if (trace_cycle[j] != 0)
                        $display("  [%0d] PC=0x%08x instr=0x%08x SR=0x%08x",
                                 trace_cycle[j], trace_pc[j], trace_instr[j], trace_sr[j]);
                end
                $display("==============================================");
                $finish;
            end
        end
    end

    // =========================================================================
    // DTLB Debug Tracing (disabled - too noisy for long runs)
    // =========================================================================
    always @(posedge clk) begin
        if (!reset) begin
            // TTMR/TTCR write traces disabled for long runs
        end
    end

    // =========================================================================
    // VCD Waveform Dump
    // =========================================================================
    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("linux_boot_tb.vcd");
            $dumpvars(0, linux_boot_tb);
        end
    end

    // =========================================================================
    // Cleanup
    // =========================================================================
    final begin
        if (uart_log_handle != 0)
            $fclose(uart_log_handle);
        $display("Simulation ended at cycle %0d, final PC=0x%08x", cycle_count, cpu.pc_rd);
    end

endmodule

`default_nettype wire
