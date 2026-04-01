// M68K System-on-Chip for Linux Boot
// Integrates the M68K processor with memory-mapped peripherals:
//   - M68K Interrupt Controller at 0x10000200
//   - M68K Timer at 0x10000300
//   - UARTLite at 0x10000100
//   - Main memory at 0x00000000 (64MB)
//
// Memory map:
//   0x00000000 - 0x03FFFFFF: Main RAM (64MB)
//     0x00000000 - 0x000003FF: Exception vectors (1KB)
//     0x00001000 - 0x03FFFFFF: Kernel and application space
//   0x10000000 - 0x10FFFFFF: SOC peripherals (16MB I/O space)
//     0x10000100 - 0x1000010F: UARTLite
//     0x10000200 - 0x1000021F: Interrupt Controller
//     0x10000300 - 0x1000031F: Timer

module m68k_soc #(
    parameter MEMORY_SIZE = 32'h04000000,  // 64MB
    parameter MEMORY_BASE = 32'h00000000,
    parameter SOC_BASE    = 32'h10000000,
    parameter UART_OFFSET = 32'h100,
    parameter INTC_OFFSET = 32'h200,
    parameter TIMER_OFFSET = 32'h300
) (
    input  logic        clk,
    input  logic        reset,

    // Boot configuration
    input  logic [31:0] reset_pc,
    input  logic [31:0] reset_ssp,
    input  logic [31:0] reset_vbr,

    // Debug outputs
    output logic [31:0] debug_pc,
    output logic [15:0] debug_sr,
    output logic        debug_halted,

    // Simulation control
    output logic        sim_uart_tx_valid,
    output logic [7:0]  sim_uart_tx_data,
    input  logic [7:0]  sim_uart_rx_data,
    input  logic        sim_uart_rx_valid
);

    // =========================================================================
    // Peripheral Bus Signals
    // =========================================================================
    logic [31:0] periph_addr;
    logic [31:0] periph_wdata;
    logic        periph_we;
    logic        periph_re;
    logic [31:0] periph_rdata;

    // Interrupt Controller signals
    logic [31:0] intc_rdata;
    logic        intc_ack;
    logic [2:0]  intc_ipl;
    logic [7:0]  intc_vector;
    logic        intc_pending;

    // Timer signals
    logic [31:0] timer_rdata;
    logic        timer_ack;
    logic        timer_irq;

    // UART signals
    logic [31:0] uart_rdata;
    logic        uart_ack;
    logic        uart_irq;

    // =========================================================================
    // Interrupt Sources
    // =========================================================================
    // Map peripheral interrupts to interrupt controller inputs
    // Source 0: Timer
    // Source 1: UART
    logic [7:0] irq_sources;

    always_comb begin
        irq_sources = 8'd0;
        irq_sources[0] = timer_irq;
        irq_sources[1] = uart_irq;
    end

    // =========================================================================
    // M68K Processor Core
    // =========================================================================
    cpu_m68k_linux cpu (
        .clk(clk),
        .reset(reset),

        // Reset state - supervisor mode, interrupts disabled
        .reset_pc(reset_pc),
        .reset_ssp(reset_ssp),
        .reset_usp(32'd0),
        .reset_sr(16'h2700),        // Supervisor mode, IPL=7 (all masked)
        .reset_vbr_rd(reset_vbr),

        // MMU disabled initially
        .reset_tc_rd(32'd0),
        .reset_tt0_rd(32'd0),
        .reset_tt1_rd(32'd0),
        .reset_crp_rd(64'd0),
        .reset_srp_rd(64'd0),
        .reset_mmusr_rd(16'd0),

        // Control registers
        .reset_cacr_rd(32'd0),
        .reset_caar_rd(32'd0),
        .reset_sfc_rd(3'd0),
        .reset_dfc_rd(3'd0),
        .reset_msp_rd(32'd0),

        // Flags
        .reset_flag_C(1'b0),
        .reset_flag_N(1'b0),
        .reset_flag_V(1'b0),
        .reset_flag_X(1'b0),
        .reset_flag_Z(1'b0),

        // Status
        .reset_halted_rd(1'b0),
        .reset_reset_out_rd(1'b0),

        // External interrupt priority level from interrupt controller
        .ipl_rd(intc_ipl),
        .ipl_wr(intc_ipl)
    );

    // Debug outputs
    assign debug_pc = cpu.pc;
    assign debug_sr = cpu.sr;
    assign debug_halted = cpu.halted_rd;

    // =========================================================================
    // Peripheral Instantiation
    // =========================================================================

    // Interrupt Controller
    m68k_intc #(
        .BASE_ADDR(SOC_BASE + INTC_OFFSET),
        .NUM_SOURCES(8),
        .DEFAULT_VECTOR(8'd64)
    ) intc (
        .clk(clk),
        .reset(reset),
        .bus_addr(periph_addr),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_re(periph_re),
        .bus_rdata(intc_rdata),
        .bus_ack(intc_ack),
        .irq_sources(irq_sources),
        .ipl(intc_ipl),
        .irq_vector(intc_vector),
        .irq_pending(intc_pending)
    );

    // Timer
    m68k_timer #(
        .BASE_ADDR(SOC_BASE + TIMER_OFFSET),
        .BUS_PERIOD_NS(20)  // 50 MHz
    ) timer (
        .clk(clk),
        .reset(reset),
        .bus_addr(periph_addr),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_re(periph_re),
        .bus_rdata(timer_rdata),
        .bus_ack(timer_ack),
        .timer_irq(timer_irq)
    );

    // UARTLite (reused from J2 platform)
    uartlite #(
        .BASE_ADDR(SOC_BASE + UART_OFFSET)
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
        .sim_rx_data(sim_uart_rx_data),
        .sim_rx_valid(sim_uart_rx_valid),
        .sim_rx_ready()
    );

    // Simulation UART output
    assign sim_uart_tx_valid = 1'b0;  // Handled by $write in UART module
    assign sim_uart_tx_data = 8'd0;

endmodule
