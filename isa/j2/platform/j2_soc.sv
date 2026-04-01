// J2 System-on-Chip for NOMMU Linux Boot
// Integrates the J2 processor with memory-mapped peripherals:
//   - JCORE AIC (Interrupt Controller) at 0xABCD0200
//   - JCORE PIT (Timer) at 0xABCD0200 (overlapping, different offsets)
//   - UARTLite at 0xABCD0100
//   - Main memory at 0x10000000 (64MB)
//
// Memory map (matching j2_mimas_v2.dts):
//   0x00000000 - 0x0FFFFFFF: Reset/Boot (alias to 0x10000000)
//   0x10000000 - 0x13FFFFFF: Main RAM (64MB)
//   0xABCD0000 - 0xABCDFFFF: SOC peripherals
//     0xABCD0040: SPI (not implemented)
//     0xABCD00C0: Cache controller (not implemented)
//     0xABCD0100: UARTLite
//     0xABCD0200: AIC + PIT

module j2_soc #(
    parameter MEMORY_SIZE = 32'h04000000,  // 64MB
    parameter MEMORY_BASE = 32'h10000000,
    parameter SOC_BASE    = 32'hABCD0000,
    parameter UART_OFFSET = 32'h100,
    parameter AIC_OFFSET  = 32'h200,
    parameter PIT_OFFSET  = 32'h200
) (
    input  logic        clk,
    input  logic        reset,

    // Boot configuration
    input  logic [31:0] reset_pc,
    input  logic [31:0] reset_vbr,

    // Debug outputs
    output logic [31:0] debug_pc,
    output logic [31:0] debug_sr,
    output logic        debug_halted,

    // Simulation control
    output logic        sim_uart_tx_valid,
    output logic [7:0]  sim_uart_tx_data,
    input  logic [7:0]  sim_uart_rx_data,
    input  logic        sim_uart_rx_valid
);

    // =========================================================================
    // Main Memory (64MB, word-addressed)
    // =========================================================================
    localparam MEM_WORDS = MEMORY_SIZE / 4;
    localparam MEM_ADDR_BITS = $clog2(MEM_WORDS);

    logic [31:0] main_memory [0:MEM_WORDS-1];

    // Memory access signals from processor (directly patched in)
    logic [31:0] mem_read_addr;
    logic [31:0] mem_write_addr;
    logic [31:0] mem_write_data;
    logic [3:0]  mem_write_be;  // Byte enables
    logic        mem_write_en;

    // =========================================================================
    // Peripheral Bus
    // =========================================================================
    logic [31:0] periph_addr;
    logic [31:0] periph_wdata;
    logic        periph_we;
    logic        periph_re;
    logic [31:0] periph_rdata;

    // AIC signals
    logic [31:0] aic_rdata;
    logic        aic_ack;
    logic        aic_irq_out;
    logic [7:0]  aic_irq_vector;

    // PIT signals
    logic [31:0] pit_rdata;
    logic        pit_ack;
    logic        pit_timer_irq;

    // UART signals
    logic [31:0] uart_rdata;
    logic        uart_ack;
    logic        uart_irq;

    // =========================================================================
    // Interrupt Sources
    // =========================================================================
    // Map peripheral interrupts to AIC inputs
    // Timer at vector 0x48 (72) = input 72-16 = 56
    // UART at vector 0x12 (18) = input 18-16 = 2
    logic [111:0] irq_sources;

    always_comb begin
        irq_sources = 112'd0;
        irq_sources[56] = pit_timer_irq;  // Timer at IRQ 72
        irq_sources[2] = uart_irq;         // UART at IRQ 18
    end

    // =========================================================================
    // J2 Processor Core
    // =========================================================================
    // The processor instantiation - connects to internal memory
    // We override the memory behavior in the testbench for Linux boot

    wire cpu_irq = aic_irq_out;

    j2_complete cpu (
        .clk(clk),
        .reset(reset),
        .reset_pc(reset_pc),
        .reset_pr(32'd0),
        .reset_t_rd(1'b0),
        .reset_delay_slot(1'b0),
        .reset_branch_target_rd(32'd0),
        .reset_macl(32'd0),
        .reset_mach(32'd0),
        .reset_gbr(32'd0),
        .reset_sr(32'h40000000),  // MD=1 (privileged mode)
        .reset_vbr(reset_vbr),
        .irq_i_rd(cpu_irq),
        .irq_i_wr(cpu_irq)
    );

    // Debug outputs
    assign debug_pc = cpu.pc;
    assign debug_sr = cpu.sr;
    assign debug_halted = 1'b0;  // No halt detection yet

    // =========================================================================
    // Address Decode and Peripheral Instantiation
    // =========================================================================

    // AIC - Advanced Interrupt Controller
    jcore_aic #(
        .BASE_ADDR(SOC_BASE + AIC_OFFSET)
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

    // PIT - Programmable Interval Timer
    jcore_pit #(
        .BASE_ADDR(SOC_BASE + PIT_OFFSET),
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

    // UARTLite
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

    // Simulation UART output (directly from TX FIFO drain)
    assign sim_uart_tx_valid = 1'b0;  // Handled by $write in UART module
    assign sim_uart_tx_data = 8'd0;

    // =========================================================================
    // Memory Initialization (for simulation)
    // =========================================================================
    initial begin
        // Initialize memory to zero
        for (int i = 0; i < MEM_WORDS; i++) begin
            main_memory[i] = 32'd0;
        end
    end

endmodule
