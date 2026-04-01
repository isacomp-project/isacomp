// CLINT (Core Local Interruptor) for RISC-V
// Provides machine timer (mtime/mtimecmp) and software interrupts
//
// Memory Map (relative to BASE_ADDR):
//   0x0000 - 0x0003: MSIP (Machine Software Interrupt Pending)
//   0x4000 - 0x4007: MTIMECMP (64-bit timer compare)
//   0xBFF8 - 0xBFFF: MTIME (64-bit timer counter)

`timescale 1ns/1ps

module clint #(
    parameter BASE_ADDR = 32'h02000000,
    parameter CLOCK_FREQ_HZ = 50_000_000,
    parameter TIMER_FREQ_HZ = 10_000_000
) (
    input  logic        clk,
    input  logic        reset,

    // Bus interface
    input  logic [31:0] bus_addr,
    input  logic [31:0] bus_wdata,
    input  logic        bus_we,
    input  logic        bus_re,
    output logic [31:0] bus_rdata,
    output logic        bus_ack,

    // Timer outputs (directly accessible by CPU)
    output logic [31:0] mtime_lo,
    output logic [31:0] mtime_hi,

    // Interrupt outputs
    output logic        timer_irq_pending,
    output logic        sw_irq_pending
);

    // Timer prescaler for accurate timing
    localparam PRESCALER_MAX = (CLOCK_FREQ_HZ / TIMER_FREQ_HZ) - 1;
    logic [$clog2(PRESCALER_MAX+1)-1:0] prescaler;

    // 64-bit timer
    logic [63:0] mtime;
    logic [63:0] mtimecmp;

    // Software interrupt
    logic msip;

    // Address decode
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < (BASE_ADDR + 32'h10000));
    wire [15:0] offset = bus_addr[15:0];

    // Timer compare
    assign timer_irq_pending = (mtime >= mtimecmp);
    assign sw_irq_pending = msip;

    // Timer output
    assign mtime_lo = mtime[31:0];
    assign mtime_hi = mtime[63:32];

    always_ff @(posedge clk) begin
        if (reset) begin
            mtime <= 64'h0;
            mtimecmp <= 64'hFFFF_FFFF_FFFF_FFFF;  // Start with max to prevent immediate interrupt
            msip <= 1'b0;
            prescaler <= 0;
            bus_ack <= 1'b0;
            bus_rdata <= 32'h0;
        end else begin
            bus_ack <= 1'b0;

            // Timer increment with prescaler
            if (prescaler >= PRESCALER_MAX) begin
                prescaler <= 0;
                mtime <= mtime + 1;
            end else begin
                prescaler <= prescaler + 1;
            end

            // Bus access
            if (addr_match) begin
                if (bus_we) begin
                    bus_ack <= 1'b1;
                    case (offset)
                        16'h0000: msip <= bus_wdata[0];  // MSIP
                        16'h4000: mtimecmp[31:0] <= bus_wdata;   // MTIMECMP low
                        16'h4004: mtimecmp[63:32] <= bus_wdata;  // MTIMECMP high
                        16'hBFF8: mtime[31:0] <= bus_wdata;      // MTIME low
                        16'hBFFC: mtime[63:32] <= bus_wdata;     // MTIME high
                        default: ;
                    endcase
                end else if (bus_re) begin
                    bus_ack <= 1'b1;
                    case (offset)
                        16'h0000: bus_rdata <= {31'h0, msip};
                        16'h4000: bus_rdata <= mtimecmp[31:0];
                        16'h4004: bus_rdata <= mtimecmp[63:32];
                        16'hBFF8: bus_rdata <= mtime[31:0];
                        16'hBFFC: bus_rdata <= mtime[63:32];
                        default: bus_rdata <= 32'h0;
                    endcase
                end
            end
        end
    end

endmodule
