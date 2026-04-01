// OR1K Tick Timer Peripheral
// Provides tick timer functionality via memory-mapped registers
//
// The CPU's SPR-based tick timer (TTMR/TTCR) is NOT present in the generated
// CPU module. This external module is the sole source of tick timer
// functionality and generates the tick_irq_pending signal consumed by the
// CPU's exception handling logic.
//
// Register Map (relative to BASE_ADDR):
//   0x00: TTMR - Tick Timer Mode Register
//     [31:30] Mode: 00=disabled, 01=restart, 10=one-shot, 11=continuous
//     [29]    IP: Interrupt Pending
//     [28]    IE: Interrupt Enable (OR1K architecture)
//     [27:0]  TP: Timer Period (match value)
//   0x04: TTCR - Tick Timer Count Register
//     [27:0]  Count value
//
// Timer Modes:
//   00 (Disabled):   Counter does not increment. No interrupts generated.
//   01 (Restart):    Counter resets to 0 on match, IP set on match.
//   10 (One-shot):   Counter stops on match, IP set on match.
//   11 (Continuous): Counter keeps incrementing past match, IP set on match.
//
// The tick_irq_pending output directly drives the CPU's tick timer exception
// input. The CPU takes the exception when SR.TEE (bit 1) is set and
// tick_irq_pending is asserted.

`timescale 1ns/1ps

module or1k_tick_timer #(
    parameter [31:0] BASE_ADDR = 32'h90000200
) (
    input  logic        clk,
    input  logic        reset,

    // Bus interface
    input  logic [31:0] bus_addr,
    input  logic [31:0] bus_wdata,
    input  logic        bus_we,
    output logic [31:0] bus_rdata,

    // Interrupt output to CPU
    output logic        tick_irq_pending
);

    // =========================================================================
    // Timer Registers
    // =========================================================================
    reg [31:0] ttmr;  // Mode register
    reg [31:0] ttcr;  // Count register

    // =========================================================================
    // Decode TTMR fields
    // =========================================================================
    wire [1:0]  timer_mode   = ttmr[31:30];
    wire [27:0] timer_period = ttmr[27:0];
    wire [27:0] timer_count  = ttcr[27:0];
    wire        timer_enabled = (timer_mode != 2'b00);
    wire        timer_match   = timer_enabled && (timer_count == timer_period);

    // =========================================================================
    // Address Decode
    // =========================================================================
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 256);

    // =========================================================================
    // Outputs
    // =========================================================================
    // Interrupt pending: driven by the IP bit in TTMR
    assign tick_irq_pending = ttmr[29];

    // Read data mux: offset 0 = TTMR, offset 4 = TTCR
    assign bus_rdata = bus_addr[2] ? ttcr : ttmr;

    // =========================================================================
    // Timer Logic
    // =========================================================================
    always_ff @(posedge clk) begin
        if (reset) begin
            ttmr <= 32'h0;
            ttcr <= 32'h0;
        end else begin
            // Counter update (runs every cycle when enabled)
            if (timer_enabled) begin
                if (timer_match) begin
                    case (timer_mode)
                        2'b01: ttcr[27:0] <= 28'b0;              // Restart: reset count
                        2'b10: ;                                   // One-shot: stop counting
                        2'b11: ttcr[27:0] <= timer_count + 1;    // Continuous: keep going
                        default: ;
                    endcase
                    ttmr[29] <= 1'b1;  // Set IP (Interrupt Pending) on match
                end else begin
                    ttcr[27:0] <= timer_count + 1;
                end
            end

            // Bus writes (take priority over counter updates for written fields)
            if (bus_we && addr_match) begin
                if (!bus_addr[2])
                    ttmr <= bus_wdata;  // Write TTMR (including IP clear)
                else
                    ttcr <= bus_wdata;  // Write TTCR
            end
        end
    end

endmodule
