// Alpha64 Interval Timer
// ======================
// Memory-mapped interval timer for Alpha64 Linux boot.
// Registers at BASE_ADDR with 8-byte spacing (little-endian).
//
// Register Map:
//   0x00: TIMER_CTL    (R/W) - bit 0: enable
//   0x08: TIMER_PERIOD (R/W) - countdown reload value
//   0x10: TIMER_COUNT  (R)   - current countdown value
//   0x18: TIMER_STATUS (R/W) - bit 0: IRQ pending (write-1-to-clear)
//
// Also provides a free-running 64-bit cycle counter for the Alpha PCC register.

module alpha_timer #(
    parameter BASE_ADDR      = 64'h0000000080010000,
    parameter DEFAULT_PERIOD = 64'd48828  // 50MHz / 1024Hz
) (
    input  logic        clk,
    input  logic        rst_n,

    // Bus interface
    input  logic [63:0] bus_addr,
    input  logic [63:0] bus_wdata,
    input  logic        bus_we,
    input  logic        bus_re,
    input  logic        bus_valid,
    output logic [63:0] bus_rdata,
    output logic        bus_ack,

    // Timer interrupt output
    output logic        timer_irq,

    // Free-running cycle counter for PCC register
    output logic [63:0] cycle_count
);

    // Registers
    logic        timer_enable;
    logic [63:0] timer_period;
    logic [63:0] timer_count;
    logic        timer_irq_pending;

    // Address decode - 4 registers at 8-byte spacing = 0x20 bytes
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 64'h20);
    wire [4:0] reg_offset = bus_addr[4:0];

    // IRQ output is level-triggered from the pending status bit
    assign timer_irq = timer_irq_pending;

    // Free-running cycle counter (always increments, independent of timer enable)
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cycle_count <= 64'd0;
        else
            cycle_count <= cycle_count + 64'd1;
    end

    // Timer countdown logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            timer_enable      <= 1'b0;
            timer_period      <= DEFAULT_PERIOD;
            timer_count       <= DEFAULT_PERIOD;
            timer_irq_pending <= 1'b0;
        end else begin
            if (timer_enable) begin
                if (timer_count == 64'd0) begin
                    // Countdown expired: set IRQ pending, reload from period
                    timer_irq_pending <= 1'b1;
                    timer_count       <= timer_period;
                end else begin
                    timer_count <= timer_count - 64'd1;
                end
            end

            // Bus write handling (applied after countdown so writes take priority)
            if (bus_valid && addr_match && bus_we) begin
                case (reg_offset)
                    5'h00: timer_enable <= bus_wdata[0];      // TIMER_CTL
                    5'h08: timer_period <= bus_wdata;          // TIMER_PERIOD
                    // 0x10: TIMER_COUNT is read-only
                    5'h18: begin                               // TIMER_STATUS (write-1-to-clear)
                        if (bus_wdata[0])
                            timer_irq_pending <= 1'b0;
                    end
                    default: ;
                endcase
            end
        end
    end

    // Bus read logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bus_rdata <= 64'd0;
            bus_ack   <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (bus_valid && addr_match) begin
                bus_ack <= 1'b1;

                case (reg_offset)
                    5'h00: bus_rdata <= {63'd0, timer_enable};      // TIMER_CTL
                    5'h08: bus_rdata <= timer_period;                // TIMER_PERIOD
                    5'h10: bus_rdata <= timer_count;                 // TIMER_COUNT
                    5'h18: bus_rdata <= {63'd0, timer_irq_pending}; // TIMER_STATUS
                    default: bus_rdata <= 64'd0;
                endcase
            end
        end
    end

endmodule
