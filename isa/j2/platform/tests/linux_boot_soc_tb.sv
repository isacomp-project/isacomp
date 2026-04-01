// J2 SoC Linux Boot Testbench with Externalized Memory
// ======================================================
// This testbench uses the proper SoC memory bus model instead of memory mirroring.
// It instantiates the J2 core with externalized memory and provides:
// 1. Memory controller simulation for main RAM
// 2. Peripheral bus with address decoding
// 3. Direct peripheral integration (no mirroring)
//
// Memory Map:
//   0x00000000 - 0x03EFFFFF: Main RAM (63MB)
//   0x03F00100 - 0x03F0010F: UART
//   0x03F00200 - 0x03F0022F: AIC + PIT (shared base, different register offsets)

`timescale 1ns/1ps
`default_nettype none

module linux_boot_soc_tb;

    // =========================================================================
    // Parameters
    // =========================================================================
    parameter CLK_PERIOD = 20;  // 50 MHz
    parameter MEMORY_SIZE = 32'h04000000;  // 64MB
    parameter PERIPH_BASE = 32'h03F00000;
    parameter PERIPH_SIZE = 32'h00100000;

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
        return (addr >= PERIPH_BASE) && (addr < PERIPH_BASE + PERIPH_SIZE);
    endfunction

    function automatic logic is_memory(input logic [31:0] addr);
        return (addr < PERIPH_BASE);
    endfunction

    // =========================================================================
    // J2 Core Reset Values
    // =========================================================================
    wire [31:0] reset_pc = 32'h00000000;  // Boot stub (sets VBR, R4=FDT, jumps to kernel)
    wire [31:0] reset_vbr = 32'h00000000; // Boot stub will set VBR
    wire [31:0] reset_sr = 32'h40000000;  // MD=1 privileged mode
    wire [31:0] zero32 = 32'd0;

    // =========================================================================
    // Peripheral Bus
    // =========================================================================
    logic [31:0] periph_addr;
    logic [31:0] periph_wdata;
    logic        periph_we;
    logic        periph_re;
    logic [31:0] periph_rdata;

    // AIC
    wire [31:0] aic_rdata;
    wire aic_ack;
    wire aic_irq_out;
    wire [7:0] aic_irq_vector;

    // PIT
    wire [31:0] pit_rdata;
    wire pit_ack;
    wire pit_timer_irq;

    // UART
    wire [31:0] uart_rdata;
    wire uart_ack;
    wire uart_irq;

    // IRQ sources to AIC
    wire [111:0] irq_sources;
    assign irq_sources = {53'd0, uart_irq, 1'd0, pit_timer_irq, 56'd0};

    // IRQ to CPU
    wire irq_i = aic_irq_out;
    wire [7:0] irq_vector = aic_irq_vector;
    wire [3:0] irq_priority = pit.piten[23:20];  // Priority from PIT PITEN register

    // =========================================================================
    // AIC - Advanced Interrupt Controller
    // =========================================================================
    jcore_aic #(
        .BASE_ADDR(PERIPH_BASE + 32'h200)
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
    // NOTE: PIT and AIC share the same base address (0x200) but use different
    // register offsets. This matches real J2 hardware.
    // =========================================================================
    jcore_pit #(
        .BASE_ADDR(PERIPH_BASE + 32'h200),
        .BUS_PERIOD_NS(20)
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
    // UART - UARTLite Compatible
    // =========================================================================
    uartlite #(
        .BASE_ADDR(PERIPH_BASE + 32'h100)
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

    // Peripheral read mux
    assign periph_rdata = aic_ack ? aic_rdata :
                          pit_ack ? pit_rdata :
                          uart_ack ? uart_rdata : 32'd0;

    // Peripheral response ready - wait for ack from peripheral
    wire periph_ack = aic_ack | pit_ack | uart_ack;

    // =========================================================================
    // Memory Read Response Helper
    // =========================================================================
    function automatic logic [31:0] get_read_data(input logic [31:0] addr);
        if (is_peripheral(addr))
            return periph_rdata;
        else
            return main_memory[addr[25:2]];
    endfunction

    // =========================================================================
    // Memory Ports - Instruction Fetch (PC)
    // =========================================================================
    wire [31:0] umem_pc_read_req_addr;
    wire umem_pc_read_req_valid;
    wire [31:0] umem_pc_read_resp_data = main_memory[umem_pc_read_req_addr[25:2]];
    wire umem_pc_read_resp_ready = umem_pc_read_req_valid;

    // =========================================================================
    // Memory Ports - Write (first port: SR push, regular stores)
    // =========================================================================
    wire [31:0] umem_write_req_addr;
    wire [31:0] umem_write_req_data;
    wire [3:0]  umem_write_req_we;
    wire umem_write_req_valid;
    wire umem_write_resp_ready = umem_write_req_valid;

    // Second write port for exception PC push
    wire [31:0] umem_1_write_req_addr;
    wire [31:0] umem_1_write_req_data;
    wire [3:0]  umem_1_write_req_we;
    wire umem_1_write_req_valid;
    wire umem_1_write_resp_ready = umem_1_write_req_valid;

    // Third write port (if needed for additional simultaneous writes)
    wire [31:0] umem_2_write_req_addr;
    wire [31:0] umem_2_write_req_data;
    wire [3:0]  umem_2_write_req_we;
    wire umem_2_write_req_valid;
    wire umem_2_write_resp_ready = umem_2_write_req_valid;

    // Track write requests to prevent duplicates (for peripherals)
    logic write_req_prev;
    wire write_req_rising = umem_write_req_valid && !write_req_prev;
    always_ff @(posedge clk) begin
        if (reset)
            write_req_prev <= 1'b0;
        else
            write_req_prev <= umem_write_req_valid;
    end

    // =========================================================================
    // Memory Ports - Data Reads
    // =========================================================================
    // Define all data read port signals
    wire [31:0] umem_load_addr_read_req_addr;
    wire umem_load_addr_read_req_valid;
    wire [31:0] umem_load_addr_read_resp_data;
    wire umem_load_addr_read_resp_ready;

    wire [31:0] umem_Rm_read_req_addr;
    wire umem_Rm_read_req_valid;
    wire [31:0] umem_Rm_read_resp_data;
    wire umem_Rm_read_resp_ready;

    wire [31:0] umem_addr_m_read_req_addr;
    wire umem_addr_m_read_req_valid;
    wire [31:0] umem_addr_m_read_resp_data;
    wire umem_addr_m_read_resp_ready;

    wire [31:0] umem_addr_n_read_req_addr;
    wire umem_addr_n_read_req_valid;
    wire [31:0] umem_addr_n_read_resp_data;
    wire umem_addr_n_read_resp_ready;

    wire [31:0] umem_movl_postinc_addr_read_req_addr;
    wire umem_movl_postinc_addr_read_req_valid;
    wire [31:0] umem_movl_postinc_addr_read_resp_data;
    wire umem_movl_postinc_addr_read_resp_ready;

    wire [31:0] umem_movw_postinc_addr_read_req_addr;
    wire umem_movw_postinc_addr_read_req_valid;
    wire [31:0] umem_movw_postinc_addr_read_resp_data;
    wire umem_movw_postinc_addr_read_resp_ready;

    wire [31:0] umem_movl_pcrel_addr_read_req_addr;
    wire umem_movl_pcrel_addr_read_req_valid;
    wire [31:0] umem_movl_pcrel_addr_read_resp_data;
    wire umem_movl_pcrel_addr_read_resp_ready;

    wire [31:0] umem_movw_pcrel_addr_read_req_addr;
    wire umem_movw_pcrel_addr_read_req_valid;
    wire [31:0] umem_movw_pcrel_addr_read_resp_data;
    wire umem_movw_pcrel_addr_read_resp_ready;

    wire [31:0] umem_movl_disp_load_addr_read_req_addr;
    wire umem_movl_disp_load_addr_read_req_valid;
    wire [31:0] umem_movl_disp_load_addr_read_resp_data;
    wire umem_movl_disp_load_addr_read_resp_ready;

    wire [31:0] umem_movw_disp_load_addr_read_req_addr;
    wire umem_movw_disp_load_addr_read_req_valid;
    wire [31:0] umem_movw_disp_load_addr_read_resp_data;
    wire umem_movw_disp_load_addr_read_resp_ready;

    wire [31:0] umem_movb_disp_load_addr_read_req_addr;
    wire umem_movb_disp_load_addr_read_req_valid;
    wire [31:0] umem_movb_disp_load_addr_read_resp_data;
    wire umem_movb_disp_load_addr_read_resp_ready;

    wire [31:0] umem_movl_gbr_load_addr_read_req_addr;
    wire umem_movl_gbr_load_addr_read_req_valid;
    wire [31:0] umem_movl_gbr_load_addr_read_resp_data;
    wire umem_movl_gbr_load_addr_read_resp_ready;

    wire [31:0] umem_movw_gbr_load_addr_read_req_addr;
    wire umem_movw_gbr_load_addr_read_req_valid;
    wire [31:0] umem_movw_gbr_load_addr_read_resp_data;
    wire umem_movw_gbr_load_addr_read_resp_ready;

    wire [31:0] umem_movb_gbr_load_addr_read_req_addr;
    wire umem_movb_gbr_load_addr_read_req_valid;
    wire [31:0] umem_movb_gbr_load_addr_read_resp_data;
    wire umem_movb_gbr_load_addr_read_resp_ready;

    wire [31:0] umem_movb_indexed_load_addr_read_req_addr;
    wire umem_movb_indexed_load_addr_read_req_valid;
    wire [31:0] umem_movb_indexed_load_addr_read_resp_data;
    wire umem_movb_indexed_load_addr_read_resp_ready;

    wire [31:0] umem_rte_stack_ptr_read_req_addr;
    wire umem_rte_stack_ptr_read_req_valid;
    wire [31:0] umem_rte_stack_ptr_read_resp_data;
    wire umem_rte_stack_ptr_read_resp_ready;

    wire [31:0] umem_rte_stack_ptr_add_4_read_req_addr;
    wire umem_rte_stack_ptr_add_4_read_req_valid;
    wire [31:0] umem_rte_stack_ptr_add_4_read_resp_data;
    wire umem_rte_stack_ptr_add_4_read_resp_ready;

    wire [31:0] umem_vbr_add_22_b0_exc_vector_2_b0_read_req_addr;
    wire umem_vbr_add_22_b0_exc_vector_2_b0_read_req_valid;
    wire [31:0] umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_data;
    wire umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_ready;

    wire [31:0] umem_ldsl_pr_addr_read_req_addr;
    wire umem_ldsl_pr_addr_read_req_valid;
    wire [31:0] umem_ldsl_pr_addr_read_resp_data;
    wire umem_ldsl_pr_addr_read_resp_ready;

    wire [31:0] umem_ldsl_macl_addr_read_req_addr;
    wire umem_ldsl_macl_addr_read_req_valid;
    wire [31:0] umem_ldsl_macl_addr_read_resp_data;
    wire umem_ldsl_macl_addr_read_resp_ready;

    wire [31:0] umem_ldsl_mach_addr_read_req_addr;
    wire umem_ldsl_mach_addr_read_req_valid;
    wire [31:0] umem_ldsl_mach_addr_read_resp_data;
    wire umem_ldsl_mach_addr_read_resp_ready;

    wire [31:0] umem_ldcl_gbr_addr_read_req_addr;
    wire umem_ldcl_gbr_addr_read_req_valid;
    wire [31:0] umem_ldcl_gbr_addr_read_resp_data;
    wire umem_ldcl_gbr_addr_read_resp_ready;

    wire [31:0] umem_ldcl_sr_addr_read_req_addr;
    wire umem_ldcl_sr_addr_read_req_valid;
    wire [31:0] umem_ldcl_sr_addr_read_resp_data;
    wire umem_ldcl_sr_addr_read_resp_ready;

    wire [31:0] umem_casl_addr_read_req_addr;
    wire umem_casl_addr_read_req_valid;
    wire [31:0] umem_casl_addr_read_resp_data;
    wire umem_casl_addr_read_resp_ready;

    wire [31:0] umem_tasb_addr_read_req_addr;
    wire umem_tasb_addr_read_req_valid;
    wire [31:0] umem_tasb_addr_read_resp_data;
    wire umem_tasb_addr_read_resp_ready;

    wire [31:0] umem_andb_gbr_addr_read_req_addr;
    wire umem_andb_gbr_addr_read_req_valid;
    wire [31:0] umem_andb_gbr_addr_read_resp_data;
    wire umem_andb_gbr_addr_read_resp_ready;

    wire [31:0] umem_orb_gbr_addr_read_req_addr;
    wire umem_orb_gbr_addr_read_req_valid;
    wire [31:0] umem_orb_gbr_addr_read_resp_data;
    wire umem_orb_gbr_addr_read_resp_ready;

    wire [31:0] umem_xorb_gbr_addr_read_req_addr;
    wire umem_xorb_gbr_addr_read_req_valid;
    wire [31:0] umem_xorb_gbr_addr_read_resp_data;
    wire umem_xorb_gbr_addr_read_resp_ready;

    wire [31:0] umem_tstb_gbr_addr_read_req_addr;
    wire umem_tstb_gbr_addr_read_req_valid;
    wire [31:0] umem_tstb_gbr_addr_read_resp_data;
    wire umem_tstb_gbr_addr_read_resp_ready;

    // =========================================================================
    // Peripheral Bus Routing - Track active data read for peripheral access
    // =========================================================================
    always_comb begin
        periph_addr = 32'd0;
        periph_we = 1'b0;
        periph_re = 1'b0;
        periph_wdata = umem_write_req_data;

        // Write to peripheral (use rising edge to prevent duplicates)
        // Writes have priority over reads - don't let reads overwrite the address
        if (write_req_rising && is_peripheral(umem_write_req_addr)) begin
            periph_addr = umem_write_req_addr;
            periph_we = 1'b1;
        end else if (is_peripheral(umem_movl_disp_load_addr_read_req_addr)) begin
            // Read from peripheral - trigger on address match
            // Note: We check address without valid because peripheral data must be
            // available combinationally for the CPU's memory read response
            periph_addr = umem_movl_disp_load_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_movw_disp_load_addr_read_req_addr)) begin
            periph_addr = umem_movw_disp_load_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_movb_disp_load_addr_read_req_addr)) begin
            periph_addr = umem_movb_disp_load_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_movl_gbr_load_addr_read_req_addr)) begin
            periph_addr = umem_movl_gbr_load_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_movw_gbr_load_addr_read_req_addr)) begin
            periph_addr = umem_movw_gbr_load_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_movb_gbr_load_addr_read_req_addr)) begin
            periph_addr = umem_movb_gbr_load_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_movl_postinc_addr_read_req_addr)) begin
            periph_addr = umem_movl_postinc_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_movw_postinc_addr_read_req_addr)) begin
            periph_addr = umem_movw_postinc_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_movb_indexed_load_addr_read_req_addr)) begin
            periph_addr = umem_movb_indexed_load_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_load_addr_read_req_addr)) begin
            periph_addr = umem_load_addr_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_Rm_read_req_addr)) begin
            periph_addr = umem_Rm_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_addr_m_read_req_addr)) begin
            periph_addr = umem_addr_m_read_req_addr;
            periph_re = 1'b1;
        end else if (is_peripheral(umem_addr_n_read_req_addr)) begin
            periph_addr = umem_addr_n_read_req_addr;
            periph_re = 1'b1;
        end
    end

    // Debug: show peripheral writes and reads (only with +debug)
    always @(posedge clk) begin
        if (debug_enable && periph_we)
            $display("[%0t] PERIPH WRITE: addr=0x%08x data=0x%08x we=%b", $time, periph_addr, periph_wdata, umem_write_req_we);
        if (debug_enable && periph_re)
            $display("[%0t] PERIPH READ: addr=0x%08x data=0x%08x", $time, periph_addr, periph_rdata);
    end

    // Debug: trace ANY read request with valid to peripheral addresses (>=0x03f00000)
    // Check ALL 29 read ports (only with +debug)
    always @(posedge clk) begin
        if (debug_enable) begin
            if (umem_Rm_read_req_valid && umem_Rm_read_req_addr >= 32'h03f00000) $display("[%0t] RD Rm: 0x%08x", $time, umem_Rm_read_req_addr);
            if (umem_addr_m_read_req_valid && umem_addr_m_read_req_addr >= 32'h03f00000) $display("[%0t] RD addr_m: 0x%08x", $time, umem_addr_m_read_req_addr);
            if (umem_addr_n_read_req_valid && umem_addr_n_read_req_addr >= 32'h03f00000) $display("[%0t] RD addr_n: 0x%08x", $time, umem_addr_n_read_req_addr);
            if (umem_load_addr_read_req_valid && umem_load_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD load_addr: 0x%08x", $time, umem_load_addr_read_req_addr);
            if (umem_movl_postinc_addr_read_req_valid && umem_movl_postinc_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movl_postinc: 0x%08x", $time, umem_movl_postinc_addr_read_req_addr);
            if (umem_movl_disp_load_addr_read_req_valid && umem_movl_disp_load_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movl_disp: 0x%08x", $time, umem_movl_disp_load_addr_read_req_addr);
            if (umem_movl_gbr_load_addr_read_req_valid && umem_movl_gbr_load_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movl_gbr: 0x%08x", $time, umem_movl_gbr_load_addr_read_req_addr);
            if (umem_movl_pcrel_addr_read_req_valid && umem_movl_pcrel_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movl_pcrel: 0x%08x", $time, umem_movl_pcrel_addr_read_req_addr);
            if (umem_movw_postinc_addr_read_req_valid && umem_movw_postinc_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movw_postinc: 0x%08x", $time, umem_movw_postinc_addr_read_req_addr);
            if (umem_movw_disp_load_addr_read_req_valid && umem_movw_disp_load_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movw_disp: 0x%08x", $time, umem_movw_disp_load_addr_read_req_addr);
            if (umem_movw_gbr_load_addr_read_req_valid && umem_movw_gbr_load_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movw_gbr: 0x%08x", $time, umem_movw_gbr_load_addr_read_req_addr);
            if (umem_movw_pcrel_addr_read_req_valid && umem_movw_pcrel_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movw_pcrel: 0x%08x", $time, umem_movw_pcrel_addr_read_req_addr);
            if (umem_movb_disp_load_addr_read_req_valid && umem_movb_disp_load_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movb_disp: 0x%08x", $time, umem_movb_disp_load_addr_read_req_addr);
            if (umem_movb_gbr_load_addr_read_req_valid && umem_movb_gbr_load_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movb_gbr: 0x%08x", $time, umem_movb_gbr_load_addr_read_req_addr);
            if (umem_movb_indexed_load_addr_read_req_valid && umem_movb_indexed_load_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD movb_idx: 0x%08x", $time, umem_movb_indexed_load_addr_read_req_addr);
            if (umem_andb_gbr_addr_read_req_valid && umem_andb_gbr_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD andb_gbr: 0x%08x", $time, umem_andb_gbr_addr_read_req_addr);
            if (umem_orb_gbr_addr_read_req_valid && umem_orb_gbr_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD orb_gbr: 0x%08x", $time, umem_orb_gbr_addr_read_req_addr);
            if (umem_xorb_gbr_addr_read_req_valid && umem_xorb_gbr_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD xorb_gbr: 0x%08x", $time, umem_xorb_gbr_addr_read_req_addr);
            if (umem_tstb_gbr_addr_read_req_valid && umem_tstb_gbr_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD tstb_gbr: 0x%08x", $time, umem_tstb_gbr_addr_read_req_addr);
            if (umem_ldsl_pr_addr_read_req_valid && umem_ldsl_pr_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD ldsl_pr: 0x%08x", $time, umem_ldsl_pr_addr_read_req_addr);
            if (umem_ldsl_macl_addr_read_req_valid && umem_ldsl_macl_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD ldsl_macl: 0x%08x", $time, umem_ldsl_macl_addr_read_req_addr);
            if (umem_ldsl_mach_addr_read_req_valid && umem_ldsl_mach_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD ldsl_mach: 0x%08x", $time, umem_ldsl_mach_addr_read_req_addr);
            if (umem_ldcl_gbr_addr_read_req_valid && umem_ldcl_gbr_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD ldcl_gbr: 0x%08x", $time, umem_ldcl_gbr_addr_read_req_addr);
            if (umem_ldcl_sr_addr_read_req_valid && umem_ldcl_sr_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD ldcl_sr: 0x%08x", $time, umem_ldcl_sr_addr_read_req_addr);
            if (umem_casl_addr_read_req_valid && umem_casl_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD casl: 0x%08x", $time, umem_casl_addr_read_req_addr);
            if (umem_tasb_addr_read_req_valid && umem_tasb_addr_read_req_addr >= 32'h03f00000) $display("[%0t] RD tasb: 0x%08x", $time, umem_tasb_addr_read_req_addr);
        end
    end

    // Debug: show PC, instruction data, and internal signals (only with +debug)
    integer debug_cycle = 0;
    always @(posedge clk) begin
        if (!reset) begin
            debug_cycle <= debug_cycle + 1;
            if (debug_enable && (debug_cycle < 20 || debug_cycle % 100000 == 0))
                $display("[%0d] PC=0x%08x instr=0x%08x instr_reg=0x%04x stall=%b sel_pc_add_2=%b pc_wr=0x%08x",
                    debug_cycle,
                    umem_pc_read_req_addr, umem_pc_read_resp_data,
                    cpu.instr, cpu.mem_ext_stall,
                    cpu.select_pc_add_2_pc_merged, cpu.pc_wr);
        end
    end

    // Debug: trace IRQ signals (only with +debug)
    logic prev_pit_timer_irq = 0;
    logic prev_irq_i = 0;
    logic [3:0] prev_imask = 0;
    always @(posedge clk) begin
        if (!reset) begin
            if (debug_enable) begin
                if (pit_timer_irq && !prev_pit_timer_irq)
                    $display("[IRQ] PIT timer_irq ASSERTED at cycle %0d", debug_cycle);
                if (!pit_timer_irq && prev_pit_timer_irq)
                    $display("[IRQ] PIT timer_irq CLEARED at cycle %0d", debug_cycle);
                if (irq_i && !prev_irq_i)
                    $display("[IRQ] CPU irq_i ASSERTED vec=%0d prio=%0d at cycle %0d",
                        irq_vector, irq_priority, debug_cycle);
                if (!irq_i && prev_irq_i)
                    $display("[IRQ] CPU irq_i CLEARED at cycle %0d", debug_cycle);
            end
            prev_imask <= cpu.sr_rd[7:4];
            prev_pit_timer_irq <= pit_timer_irq;
            prev_irq_i <= irq_i;
        end
    end

    // =========================================================================
    // Memory Read Response - Route to memory or peripheral
    // =========================================================================
    assign umem_load_addr_read_resp_data = is_peripheral(umem_load_addr_read_req_addr) ? periph_rdata : main_memory[umem_load_addr_read_req_addr[25:2]];
    assign umem_load_addr_read_resp_ready = is_peripheral(umem_load_addr_read_req_addr) ? periph_ack : umem_load_addr_read_req_valid;

    assign umem_Rm_read_resp_data = is_peripheral(umem_Rm_read_req_addr) ? periph_rdata : main_memory[umem_Rm_read_req_addr[25:2]];
    assign umem_Rm_read_resp_ready = is_peripheral(umem_Rm_read_req_addr) ? periph_ack : umem_Rm_read_req_valid;

    assign umem_addr_m_read_resp_data = is_peripheral(umem_addr_m_read_req_addr) ? periph_rdata : main_memory[umem_addr_m_read_req_addr[25:2]];
    assign umem_addr_m_read_resp_ready = is_peripheral(umem_addr_m_read_req_addr) ? periph_ack : umem_addr_m_read_req_valid;

    assign umem_addr_n_read_resp_data = is_peripheral(umem_addr_n_read_req_addr) ? periph_rdata : main_memory[umem_addr_n_read_req_addr[25:2]];
    assign umem_addr_n_read_resp_ready = is_peripheral(umem_addr_n_read_req_addr) ? periph_ack : umem_addr_n_read_req_valid;

    assign umem_movl_postinc_addr_read_resp_data = is_peripheral(umem_movl_postinc_addr_read_req_addr) ? periph_rdata : main_memory[umem_movl_postinc_addr_read_req_addr[25:2]];
    assign umem_movl_postinc_addr_read_resp_ready = is_peripheral(umem_movl_postinc_addr_read_req_addr) ? periph_ack : umem_movl_postinc_addr_read_req_valid;

    assign umem_movw_postinc_addr_read_resp_data = is_peripheral(umem_movw_postinc_addr_read_req_addr) ? periph_rdata : main_memory[umem_movw_postinc_addr_read_req_addr[25:2]];
    assign umem_movw_postinc_addr_read_resp_ready = is_peripheral(umem_movw_postinc_addr_read_req_addr) ? periph_ack : umem_movw_postinc_addr_read_req_valid;

    assign umem_movl_pcrel_addr_read_resp_data = main_memory[umem_movl_pcrel_addr_read_req_addr[25:2]];
    assign umem_movl_pcrel_addr_read_resp_ready = umem_movl_pcrel_addr_read_req_valid;

    assign umem_movw_pcrel_addr_read_resp_data = main_memory[umem_movw_pcrel_addr_read_req_addr[25:2]];
    assign umem_movw_pcrel_addr_read_resp_ready = umem_movw_pcrel_addr_read_req_valid;

    assign umem_movl_disp_load_addr_read_resp_data = is_peripheral(umem_movl_disp_load_addr_read_req_addr) ? periph_rdata : main_memory[umem_movl_disp_load_addr_read_req_addr[25:2]];
    assign umem_movl_disp_load_addr_read_resp_ready = is_peripheral(umem_movl_disp_load_addr_read_req_addr) ? periph_ack : umem_movl_disp_load_addr_read_req_valid;

    assign umem_movw_disp_load_addr_read_resp_data = is_peripheral(umem_movw_disp_load_addr_read_req_addr) ? periph_rdata : main_memory[umem_movw_disp_load_addr_read_req_addr[25:2]];
    assign umem_movw_disp_load_addr_read_resp_ready = is_peripheral(umem_movw_disp_load_addr_read_req_addr) ? periph_ack : umem_movw_disp_load_addr_read_req_valid;

    assign umem_movb_disp_load_addr_read_resp_data = is_peripheral(umem_movb_disp_load_addr_read_req_addr) ? periph_rdata : main_memory[umem_movb_disp_load_addr_read_req_addr[25:2]];
    assign umem_movb_disp_load_addr_read_resp_ready = is_peripheral(umem_movb_disp_load_addr_read_req_addr) ? periph_ack : umem_movb_disp_load_addr_read_req_valid;

    assign umem_movl_gbr_load_addr_read_resp_data = is_peripheral(umem_movl_gbr_load_addr_read_req_addr) ? periph_rdata : main_memory[umem_movl_gbr_load_addr_read_req_addr[25:2]];
    assign umem_movl_gbr_load_addr_read_resp_ready = is_peripheral(umem_movl_gbr_load_addr_read_req_addr) ? periph_ack : umem_movl_gbr_load_addr_read_req_valid;

    assign umem_movw_gbr_load_addr_read_resp_data = is_peripheral(umem_movw_gbr_load_addr_read_req_addr) ? periph_rdata : main_memory[umem_movw_gbr_load_addr_read_req_addr[25:2]];
    assign umem_movw_gbr_load_addr_read_resp_ready = is_peripheral(umem_movw_gbr_load_addr_read_req_addr) ? periph_ack : umem_movw_gbr_load_addr_read_req_valid;

    assign umem_movb_gbr_load_addr_read_resp_data = is_peripheral(umem_movb_gbr_load_addr_read_req_addr) ? periph_rdata : main_memory[umem_movb_gbr_load_addr_read_req_addr[25:2]];
    assign umem_movb_gbr_load_addr_read_resp_ready = is_peripheral(umem_movb_gbr_load_addr_read_req_addr) ? periph_ack : umem_movb_gbr_load_addr_read_req_valid;

    assign umem_movb_indexed_load_addr_read_resp_data = is_peripheral(umem_movb_indexed_load_addr_read_req_addr) ? periph_rdata : main_memory[umem_movb_indexed_load_addr_read_req_addr[25:2]];
    assign umem_movb_indexed_load_addr_read_resp_ready = is_peripheral(umem_movb_indexed_load_addr_read_req_addr) ? periph_ack : umem_movb_indexed_load_addr_read_req_valid;

    assign umem_rte_stack_ptr_read_resp_data = main_memory[umem_rte_stack_ptr_read_req_addr[25:2]];
    assign umem_rte_stack_ptr_read_resp_ready = umem_rte_stack_ptr_read_req_valid;

    assign umem_rte_stack_ptr_add_4_read_resp_data = main_memory[umem_rte_stack_ptr_add_4_read_req_addr[25:2]];
    // NOTE: These two signals are unconditionally included in mem_ext_stall (bug in generator)
    // so they must always be high to avoid permanent stall
    assign umem_rte_stack_ptr_add_4_read_resp_ready = 1'b1;

    assign umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_data = main_memory[umem_vbr_add_22_b0_exc_vector_2_b0_read_req_addr[25:2]];
    assign umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_ready = 1'b1;

    assign umem_ldsl_pr_addr_read_resp_data = main_memory[umem_ldsl_pr_addr_read_req_addr[25:2]];
    assign umem_ldsl_pr_addr_read_resp_ready = umem_ldsl_pr_addr_read_req_valid;

    assign umem_ldsl_macl_addr_read_resp_data = main_memory[umem_ldsl_macl_addr_read_req_addr[25:2]];
    assign umem_ldsl_macl_addr_read_resp_ready = umem_ldsl_macl_addr_read_req_valid;

    assign umem_ldsl_mach_addr_read_resp_data = main_memory[umem_ldsl_mach_addr_read_req_addr[25:2]];
    assign umem_ldsl_mach_addr_read_resp_ready = umem_ldsl_mach_addr_read_req_valid;

    assign umem_ldcl_gbr_addr_read_resp_data = main_memory[umem_ldcl_gbr_addr_read_req_addr[25:2]];
    assign umem_ldcl_gbr_addr_read_resp_ready = umem_ldcl_gbr_addr_read_req_valid;

    assign umem_ldcl_sr_addr_read_resp_data = main_memory[umem_ldcl_sr_addr_read_req_addr[25:2]];
    assign umem_ldcl_sr_addr_read_resp_ready = umem_ldcl_sr_addr_read_req_valid;

    assign umem_casl_addr_read_resp_data = main_memory[umem_casl_addr_read_req_addr[25:2]];
    assign umem_casl_addr_read_resp_ready = umem_casl_addr_read_req_valid;

    assign umem_tasb_addr_read_resp_data = main_memory[umem_tasb_addr_read_req_addr[25:2]];
    assign umem_tasb_addr_read_resp_ready = umem_tasb_addr_read_req_valid;

    assign umem_andb_gbr_addr_read_resp_data = is_peripheral(umem_andb_gbr_addr_read_req_addr) ? periph_rdata : main_memory[umem_andb_gbr_addr_read_req_addr[25:2]];
    assign umem_andb_gbr_addr_read_resp_ready = is_peripheral(umem_andb_gbr_addr_read_req_addr) ? periph_ack : umem_andb_gbr_addr_read_req_valid;

    assign umem_orb_gbr_addr_read_resp_data = is_peripheral(umem_orb_gbr_addr_read_req_addr) ? periph_rdata : main_memory[umem_orb_gbr_addr_read_req_addr[25:2]];
    assign umem_orb_gbr_addr_read_resp_ready = is_peripheral(umem_orb_gbr_addr_read_req_addr) ? periph_ack : umem_orb_gbr_addr_read_req_valid;

    assign umem_xorb_gbr_addr_read_resp_data = is_peripheral(umem_xorb_gbr_addr_read_req_addr) ? periph_rdata : main_memory[umem_xorb_gbr_addr_read_req_addr[25:2]];
    assign umem_xorb_gbr_addr_read_resp_ready = is_peripheral(umem_xorb_gbr_addr_read_req_addr) ? periph_ack : umem_xorb_gbr_addr_read_req_valid;

    assign umem_tstb_gbr_addr_read_resp_data = is_peripheral(umem_tstb_gbr_addr_read_req_addr) ? periph_rdata : main_memory[umem_tstb_gbr_addr_read_req_addr[25:2]];
    assign umem_tstb_gbr_addr_read_resp_ready = is_peripheral(umem_tstb_gbr_addr_read_req_addr) ? periph_ack : umem_tstb_gbr_addr_read_req_valid;

    // =========================================================================
    // Memory Write Handler (First write port - SR push, regular stores)
    // =========================================================================
    always_ff @(posedge clk) begin
        if (!reset && umem_write_req_valid && is_memory(umem_write_req_addr)) begin
            if (umem_write_req_we[0])
                main_memory[umem_write_req_addr[25:2]][7:0] <= umem_write_req_data[7:0];
            if (umem_write_req_we[1])
                main_memory[umem_write_req_addr[25:2]][15:8] <= umem_write_req_data[15:8];
            if (umem_write_req_we[2])
                main_memory[umem_write_req_addr[25:2]][23:16] <= umem_write_req_data[23:16];
            if (umem_write_req_we[3])
                main_memory[umem_write_req_addr[25:2]][31:24] <= umem_write_req_data[31:24];
        end
    end

    // =========================================================================
    // Memory Write Handler (Second write port - exception PC push)
    // =========================================================================
    always_ff @(posedge clk) begin
        if (!reset && umem_1_write_req_valid && is_memory(umem_1_write_req_addr)) begin
            // Exception PC pushes are always 32-bit
            main_memory[umem_1_write_req_addr[25:2]] <= umem_1_write_req_data;
        end
    end

    // =========================================================================
    // Memory Write Handler (Third write port)
    // =========================================================================
    always_ff @(posedge clk) begin
        if (!reset && umem_2_write_req_valid && is_memory(umem_2_write_req_addr)) begin
            main_memory[umem_2_write_req_addr[25:2]] <= umem_2_write_req_data;
        end
    end

    // =========================================================================
    // J2 Core Instance
    // =========================================================================
    j2_complete_extmem cpu (
        .clk(clk),
        .reset(reset),

        // Reset values
        .reset_pc(reset_pc),
        .reset_pr(zero32),
        .reset_t_rd(1'b0),
        .reset_delay_slot(1'b0),
        .reset_branch_target_rd(zero32),
        .reset_macl(zero32),
        .reset_mach(zero32),
        .reset_gbr(zero32),
        .reset_sr(reset_sr),
        .reset_vbr(reset_vbr),

        // IRQ interface
        .irq_i_rd(irq_i),
        .irq_i_wr(irq_i),
        .irq_priority_rd(irq_priority),
        .irq_priority_wr(irq_priority),
        .irq_vector_rd(irq_vector),
        .irq_vector_wr(irq_vector),

        // Instruction fetch
        .umem_pc_read_req_addr(umem_pc_read_req_addr),
        .umem_pc_read_req_valid(umem_pc_read_req_valid),
        .umem_pc_read_resp_data(umem_pc_read_resp_data),
        .umem_pc_read_resp_ready(umem_pc_read_resp_ready),

        // Write port (first - SR push, regular stores)
        .umem_write_req_addr(umem_write_req_addr),
        .umem_write_req_data(umem_write_req_data),
        .umem_write_req_we(umem_write_req_we),
        .umem_write_req_valid(umem_write_req_valid),
        .umem_write_resp_ready(umem_write_resp_ready),

        // Second write port (exception PC push)
        .umem_1_write_req_addr(umem_1_write_req_addr),
        .umem_1_write_req_data(umem_1_write_req_data),
        .umem_1_write_req_we(umem_1_write_req_we),
        .umem_1_write_req_valid(umem_1_write_req_valid),
        .umem_1_write_resp_ready(umem_1_write_resp_ready),

        // Third write port
        .umem_2_write_req_addr(umem_2_write_req_addr),
        .umem_2_write_req_data(umem_2_write_req_data),
        .umem_2_write_req_we(umem_2_write_req_we),
        .umem_2_write_req_valid(umem_2_write_req_valid),
        .umem_2_write_resp_ready(umem_2_write_resp_ready),

        // Data read ports
        .umem_load_addr_read_req_addr(umem_load_addr_read_req_addr),
        .umem_load_addr_read_req_valid(umem_load_addr_read_req_valid),
        .umem_load_addr_read_resp_data(umem_load_addr_read_resp_data),
        .umem_load_addr_read_resp_ready(umem_load_addr_read_resp_ready),

        .umem_Rm_read_req_addr(umem_Rm_read_req_addr),
        .umem_Rm_read_req_valid(umem_Rm_read_req_valid),
        .umem_Rm_read_resp_data(umem_Rm_read_resp_data),
        .umem_Rm_read_resp_ready(umem_Rm_read_resp_ready),

        .umem_addr_m_read_req_addr(umem_addr_m_read_req_addr),
        .umem_addr_m_read_req_valid(umem_addr_m_read_req_valid),
        .umem_addr_m_read_resp_data(umem_addr_m_read_resp_data),
        .umem_addr_m_read_resp_ready(umem_addr_m_read_resp_ready),

        .umem_addr_n_read_req_addr(umem_addr_n_read_req_addr),
        .umem_addr_n_read_req_valid(umem_addr_n_read_req_valid),
        .umem_addr_n_read_resp_data(umem_addr_n_read_resp_data),
        .umem_addr_n_read_resp_ready(umem_addr_n_read_resp_ready),

        .umem_movl_postinc_addr_read_req_addr(umem_movl_postinc_addr_read_req_addr),
        .umem_movl_postinc_addr_read_req_valid(umem_movl_postinc_addr_read_req_valid),
        .umem_movl_postinc_addr_read_resp_data(umem_movl_postinc_addr_read_resp_data),
        .umem_movl_postinc_addr_read_resp_ready(umem_movl_postinc_addr_read_resp_ready),

        .umem_movw_postinc_addr_read_req_addr(umem_movw_postinc_addr_read_req_addr),
        .umem_movw_postinc_addr_read_req_valid(umem_movw_postinc_addr_read_req_valid),
        .umem_movw_postinc_addr_read_resp_data(umem_movw_postinc_addr_read_resp_data),
        .umem_movw_postinc_addr_read_resp_ready(umem_movw_postinc_addr_read_resp_ready),

        .umem_movl_pcrel_addr_read_req_addr(umem_movl_pcrel_addr_read_req_addr),
        .umem_movl_pcrel_addr_read_req_valid(umem_movl_pcrel_addr_read_req_valid),
        .umem_movl_pcrel_addr_read_resp_data(umem_movl_pcrel_addr_read_resp_data),
        .umem_movl_pcrel_addr_read_resp_ready(umem_movl_pcrel_addr_read_resp_ready),

        .umem_movw_pcrel_addr_read_req_addr(umem_movw_pcrel_addr_read_req_addr),
        .umem_movw_pcrel_addr_read_req_valid(umem_movw_pcrel_addr_read_req_valid),
        .umem_movw_pcrel_addr_read_resp_data(umem_movw_pcrel_addr_read_resp_data),
        .umem_movw_pcrel_addr_read_resp_ready(umem_movw_pcrel_addr_read_resp_ready),

        .umem_movl_disp_load_addr_read_req_addr(umem_movl_disp_load_addr_read_req_addr),
        .umem_movl_disp_load_addr_read_req_valid(umem_movl_disp_load_addr_read_req_valid),
        .umem_movl_disp_load_addr_read_resp_data(umem_movl_disp_load_addr_read_resp_data),
        .umem_movl_disp_load_addr_read_resp_ready(umem_movl_disp_load_addr_read_resp_ready),

        .umem_movw_disp_load_addr_read_req_addr(umem_movw_disp_load_addr_read_req_addr),
        .umem_movw_disp_load_addr_read_req_valid(umem_movw_disp_load_addr_read_req_valid),
        .umem_movw_disp_load_addr_read_resp_data(umem_movw_disp_load_addr_read_resp_data),
        .umem_movw_disp_load_addr_read_resp_ready(umem_movw_disp_load_addr_read_resp_ready),

        .umem_movb_disp_load_addr_read_req_addr(umem_movb_disp_load_addr_read_req_addr),
        .umem_movb_disp_load_addr_read_req_valid(umem_movb_disp_load_addr_read_req_valid),
        .umem_movb_disp_load_addr_read_resp_data(umem_movb_disp_load_addr_read_resp_data),
        .umem_movb_disp_load_addr_read_resp_ready(umem_movb_disp_load_addr_read_resp_ready),

        .umem_movl_gbr_load_addr_read_req_addr(umem_movl_gbr_load_addr_read_req_addr),
        .umem_movl_gbr_load_addr_read_req_valid(umem_movl_gbr_load_addr_read_req_valid),
        .umem_movl_gbr_load_addr_read_resp_data(umem_movl_gbr_load_addr_read_resp_data),
        .umem_movl_gbr_load_addr_read_resp_ready(umem_movl_gbr_load_addr_read_resp_ready),

        .umem_movw_gbr_load_addr_read_req_addr(umem_movw_gbr_load_addr_read_req_addr),
        .umem_movw_gbr_load_addr_read_req_valid(umem_movw_gbr_load_addr_read_req_valid),
        .umem_movw_gbr_load_addr_read_resp_data(umem_movw_gbr_load_addr_read_resp_data),
        .umem_movw_gbr_load_addr_read_resp_ready(umem_movw_gbr_load_addr_read_resp_ready),

        .umem_movb_gbr_load_addr_read_req_addr(umem_movb_gbr_load_addr_read_req_addr),
        .umem_movb_gbr_load_addr_read_req_valid(umem_movb_gbr_load_addr_read_req_valid),
        .umem_movb_gbr_load_addr_read_resp_data(umem_movb_gbr_load_addr_read_resp_data),
        .umem_movb_gbr_load_addr_read_resp_ready(umem_movb_gbr_load_addr_read_resp_ready),

        .umem_movb_indexed_load_addr_read_req_addr(umem_movb_indexed_load_addr_read_req_addr),
        .umem_movb_indexed_load_addr_read_req_valid(umem_movb_indexed_load_addr_read_req_valid),
        .umem_movb_indexed_load_addr_read_resp_data(umem_movb_indexed_load_addr_read_resp_data),
        .umem_movb_indexed_load_addr_read_resp_ready(umem_movb_indexed_load_addr_read_resp_ready),

        .umem_rte_stack_ptr_read_req_addr(umem_rte_stack_ptr_read_req_addr),
        .umem_rte_stack_ptr_read_req_valid(umem_rte_stack_ptr_read_req_valid),
        .umem_rte_stack_ptr_read_resp_data(umem_rte_stack_ptr_read_resp_data),
        .umem_rte_stack_ptr_read_resp_ready(umem_rte_stack_ptr_read_resp_ready),

        .umem_rte_stack_ptr_add_4_read_req_addr(umem_rte_stack_ptr_add_4_read_req_addr),
        .umem_rte_stack_ptr_add_4_read_req_valid(umem_rte_stack_ptr_add_4_read_req_valid),
        .umem_rte_stack_ptr_add_4_read_resp_data(umem_rte_stack_ptr_add_4_read_resp_data),
        .umem_rte_stack_ptr_add_4_read_resp_ready(umem_rte_stack_ptr_add_4_read_resp_ready),

        .umem_vbr_add_22_b0_exc_vector_2_b0_read_req_addr(umem_vbr_add_22_b0_exc_vector_2_b0_read_req_addr),
        .umem_vbr_add_22_b0_exc_vector_2_b0_read_req_valid(umem_vbr_add_22_b0_exc_vector_2_b0_read_req_valid),
        .umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_data(umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_data),
        .umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_ready(umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_ready),

        .umem_ldsl_pr_addr_read_req_addr(umem_ldsl_pr_addr_read_req_addr),
        .umem_ldsl_pr_addr_read_req_valid(umem_ldsl_pr_addr_read_req_valid),
        .umem_ldsl_pr_addr_read_resp_data(umem_ldsl_pr_addr_read_resp_data),
        .umem_ldsl_pr_addr_read_resp_ready(umem_ldsl_pr_addr_read_resp_ready),

        .umem_ldsl_macl_addr_read_req_addr(umem_ldsl_macl_addr_read_req_addr),
        .umem_ldsl_macl_addr_read_req_valid(umem_ldsl_macl_addr_read_req_valid),
        .umem_ldsl_macl_addr_read_resp_data(umem_ldsl_macl_addr_read_resp_data),
        .umem_ldsl_macl_addr_read_resp_ready(umem_ldsl_macl_addr_read_resp_ready),

        .umem_ldsl_mach_addr_read_req_addr(umem_ldsl_mach_addr_read_req_addr),
        .umem_ldsl_mach_addr_read_req_valid(umem_ldsl_mach_addr_read_req_valid),
        .umem_ldsl_mach_addr_read_resp_data(umem_ldsl_mach_addr_read_resp_data),
        .umem_ldsl_mach_addr_read_resp_ready(umem_ldsl_mach_addr_read_resp_ready),

        .umem_ldcl_gbr_addr_read_req_addr(umem_ldcl_gbr_addr_read_req_addr),
        .umem_ldcl_gbr_addr_read_req_valid(umem_ldcl_gbr_addr_read_req_valid),
        .umem_ldcl_gbr_addr_read_resp_data(umem_ldcl_gbr_addr_read_resp_data),
        .umem_ldcl_gbr_addr_read_resp_ready(umem_ldcl_gbr_addr_read_resp_ready),

        .umem_ldcl_sr_addr_read_req_addr(umem_ldcl_sr_addr_read_req_addr),
        .umem_ldcl_sr_addr_read_req_valid(umem_ldcl_sr_addr_read_req_valid),
        .umem_ldcl_sr_addr_read_resp_data(umem_ldcl_sr_addr_read_resp_data),
        .umem_ldcl_sr_addr_read_resp_ready(umem_ldcl_sr_addr_read_resp_ready),

        .umem_casl_addr_read_req_addr(umem_casl_addr_read_req_addr),
        .umem_casl_addr_read_req_valid(umem_casl_addr_read_req_valid),
        .umem_casl_addr_read_resp_data(umem_casl_addr_read_resp_data),
        .umem_casl_addr_read_resp_ready(umem_casl_addr_read_resp_ready),

        .umem_tasb_addr_read_req_addr(umem_tasb_addr_read_req_addr),
        .umem_tasb_addr_read_req_valid(umem_tasb_addr_read_req_valid),
        .umem_tasb_addr_read_resp_data(umem_tasb_addr_read_resp_data),
        .umem_tasb_addr_read_resp_ready(umem_tasb_addr_read_resp_ready),

        .umem_andb_gbr_addr_read_req_addr(umem_andb_gbr_addr_read_req_addr),
        .umem_andb_gbr_addr_read_req_valid(umem_andb_gbr_addr_read_req_valid),
        .umem_andb_gbr_addr_read_resp_data(umem_andb_gbr_addr_read_resp_data),
        .umem_andb_gbr_addr_read_resp_ready(umem_andb_gbr_addr_read_resp_ready),

        .umem_orb_gbr_addr_read_req_addr(umem_orb_gbr_addr_read_req_addr),
        .umem_orb_gbr_addr_read_req_valid(umem_orb_gbr_addr_read_req_valid),
        .umem_orb_gbr_addr_read_resp_data(umem_orb_gbr_addr_read_resp_data),
        .umem_orb_gbr_addr_read_resp_ready(umem_orb_gbr_addr_read_resp_ready),

        .umem_xorb_gbr_addr_read_req_addr(umem_xorb_gbr_addr_read_req_addr),
        .umem_xorb_gbr_addr_read_req_valid(umem_xorb_gbr_addr_read_req_valid),
        .umem_xorb_gbr_addr_read_resp_data(umem_xorb_gbr_addr_read_resp_data),
        .umem_xorb_gbr_addr_read_resp_ready(umem_xorb_gbr_addr_read_resp_ready),

        .umem_tstb_gbr_addr_read_req_addr(umem_tstb_gbr_addr_read_req_addr),
        .umem_tstb_gbr_addr_read_req_valid(umem_tstb_gbr_addr_read_req_valid),
        .umem_tstb_gbr_addr_read_resp_data(umem_tstb_gbr_addr_read_resp_data),
        .umem_tstb_gbr_addr_read_resp_ready(umem_tstb_gbr_addr_read_resp_ready)
    );

    // =========================================================================
    // Debug Control
    // =========================================================================
    logic debug_enable = 0;
    initial begin
        if ($test$plusargs("debug")) debug_enable = 1;
    end

    // =========================================================================
    // Boot Image Loading
    // =========================================================================
    string boot_image;
    integer boot_file;
    integer word_count;
    reg [7:0] byte_data;
    integer j;
    integer bytes_read;

    initial begin
        // Initialize memory with NOP pattern
        for (integer i = 0; i < MEM_WORDS; i = i + 1) begin
            main_memory[i] = 32'h00090009;  // NOP
        end

        // Load boot image
        if (!$value$plusargs("boot_image=%s", boot_image)) begin
            boot_image = "vmlinux.bin";
        end

        boot_file = $fopen(boot_image, "rb");
        if (boot_file == 0) begin
            $display("ERROR: Could not open boot image: %s", boot_image);
            $finish;
        end

        $display("J2 SoC Linux Boot Testbench");
        $display("===========================");
        $display("Loading boot image: %s", boot_image);

        // Load at address 0
        word_count = 0;
        while (!$feof(boot_file)) begin
            for (j = 3; j >= 0; j = j - 1) begin
                bytes_read = $fread(byte_data, boot_file);
                if (bytes_read == 1)
                    main_memory[word_count][j*8 +: 8] = byte_data;
            end
            word_count = word_count + 1;
        end
        $fclose(boot_file);
        $display("Loaded %0d words (%0d bytes)", word_count, word_count * 4);

        // Load initramfs at 0x03800000 (56MB)
        begin
            string initramfs_path;
            integer initramfs_file;
            integer initramfs_words;
            integer initramfs_base;

            if (!$value$plusargs("initramfs=%s", initramfs_path)) begin
                initramfs_path = "../initramfs/initramfs.cpio";
            end

            initramfs_file = $fopen(initramfs_path, "rb");
            if (initramfs_file != 0) begin
                initramfs_base = 32'h03800000 >> 2;  // Word address
                initramfs_words = 0;
                while (!$feof(initramfs_file)) begin
                    for (j = 3; j >= 0; j = j - 1) begin
                        bytes_read = $fread(byte_data, initramfs_file);
                        if (bytes_read == 1)
                            main_memory[initramfs_base + initramfs_words][j*8 +: 8] = byte_data;
                    end
                    initramfs_words = initramfs_words + 1;
                end
                $fclose(initramfs_file);

                // Patch boot params: INITRD_START at 0x1010, INITRD_SIZE at 0x1014
                main_memory[32'h1010 >> 2] = 32'h03800000;  // INITRD_START
                main_memory[32'h1014 >> 2] = initramfs_words * 4;  // INITRD_SIZE

                $display("Loaded initramfs: %s (%0d bytes) at 0x03800000",
                         initramfs_path, initramfs_words * 4);
            end else begin
                $display("No initramfs loaded (file not found: %s)", initramfs_path);
            end
        end

        // Start
        reset = 1;
        repeat (20) @(posedge clk);
        reset = 0;

        $display("Starting execution at PC=0x%08x", reset_pc);
        $display("Memory: 0x00000000 - 0x%08x", PERIPH_BASE - 1);
        $display("Peripherals: 0x%08x - 0x%08x", PERIPH_BASE, PERIPH_BASE + PERIPH_SIZE - 1);
    end

    // =========================================================================
    // Simulation Control
    // =========================================================================
    integer cycle_count = 0;
    integer max_cycles;

    initial begin
        if (!$value$plusargs("max_cycles=%d", max_cycles))
            max_cycles = 500000000;  // 500M cycles default
    end

    always @(posedge clk) begin
        if (!reset) begin
            cycle_count <= cycle_count + 1;
            if (cycle_count >= max_cycles) begin
                $display("TIMEOUT after %0d cycles", cycle_count);
                $finish;
            end
        end
    end

endmodule

`default_nettype wire
