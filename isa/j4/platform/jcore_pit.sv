// JCORE PIT (Programmable Interval Timer)
// Compatible with Linux jcore,pit driver
//
// Register Map:
//   0x00 - PITEN: Enable register
//          bit 26: enable
//          bits 20-23: priority
//          bits 12-19: IRQ number
//   0x10 - THROT: Throttle period (countdown value)
//   0x14 - COUNT: Current count value (R)
//   0x18 - BUSPD: Bus period in nanoseconds (R)
//   0x20 - SECHI: Seconds high (R)
//   0x24 - SECLO: Seconds low (R)
//   0x28 - NSEC: Nanoseconds (R)

module jcore_pit #(
    parameter BASE_ADDR = 32'hABCD0200,
    parameter BUS_PERIOD_NS = 20,      // 50 MHz bus = 20ns period
    parameter DEFAULT_IRQ = 8'h48      // Default timer interrupt vector (72)
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

    // Timer interrupt output
    output logic        timer_irq
);

    // Registers
    logic [31:0] piten;    // Enable + IRQ + priority
    logic [31:0] throt;    // Throttle period
    logic [31:0] count;    // Current count

    // Real-time clock (free-running)
    logic [31:0] sec_lo;
    logic [31:0] sec_hi;
    logic [31:0] nsec;

    // Derived signals
    wire pit_enable = piten[26];
    wire [7:0] pit_irq = piten[19:12];

    // Address decode
    // NOTE: PIT and AIC share the same base address but use different register offsets.
    // PIT handles: 0x00 (PITEN), 0x10 (THROT), 0x14 (COUNT), 0x18 (BUSPD), 0x20-0x28 (time)
    // AIC handles: 0x04 (INTEN), 0x08 (INTPRI), 0x0C (reserved)
    wire [5:0] reg_offset = bus_addr[5:0];
    wire is_aic_register = (reg_offset == 6'h04) || (reg_offset == 6'h08) || (reg_offset == 6'h0C);
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 48) && !is_aic_register;

    // Timer IRQ state
    logic timer_irq_pending;
    logic piten_write;  // Pulse when PITEN is written

    // Timer countdown - periodic mode with auto-reload
    // Timer auto-reloads on expiry, IRQ stays high until count reloads
    // This allows the CPU time to take the interrupt before it clears
    always_ff @(posedge clk) begin
        if (reset) begin
            count <= 32'd0;
            timer_irq_pending <= 1'b0;
        end else if (piten_write) begin
            // Writing to PITEN clears pending IRQ and reloads count
            timer_irq_pending <= 1'b0;
            count <= throt;
        end else if (pit_enable) begin
            if (count == 32'd0) begin
                // Expired - set IRQ and auto-reload
                timer_irq_pending <= 1'b1;
                count <= throt;  // Auto-reload for next period
            end else begin
                count <= count - 1;
                // Clear IRQ after ~100 cycles to give CPU time to sample it
                // count starts at throt after reload, so clear when count < throt - 100
                if (timer_irq_pending && count <= throt - 100) begin
                    timer_irq_pending <= 1'b0;
                end
            end
        end else begin
            timer_irq_pending <= 1'b0;
        end
    end

    assign timer_irq = timer_irq_pending && pit_enable;

    // Debug counter (no output by default)

    // Real-time clock
    always_ff @(posedge clk) begin
        if (reset) begin
            nsec <= 32'd0;
            sec_lo <= 32'd0;
            sec_hi <= 32'd0;
        end else begin
            if (nsec >= 32'd999_999_999) begin
                nsec <= 32'd0;
                if (sec_lo == 32'hFFFFFFFF) begin
                    sec_lo <= 32'd0;
                    sec_hi <= sec_hi + 1;
                end else begin
                    sec_lo <= sec_lo + 1;
                end
            end else begin
                nsec <= nsec + BUS_PERIOD_NS;
            end
        end
    end

    // Generate piten_write pulse
    assign piten_write = addr_match && bus_we && (reg_offset == 6'h00);

    // Register read/write
    always_ff @(posedge clk) begin
        if (reset) begin
            piten <= 32'd0;
            throt <= 32'd0;
            bus_rdata <= 32'd0;
            bus_ack <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (addr_match && (bus_we || bus_re)) begin
                bus_ack <= 1'b1;

                if (bus_we) begin
                    case (reg_offset)
                        6'h00: piten <= bus_wdata;    // PITEN
                        6'h10: throt <= bus_wdata;    // THROT
                        default: ;
                    endcase
                end

                if (bus_re) begin
                    case (reg_offset)
                        6'h00: bus_rdata <= piten;              // PITEN
                        6'h10: bus_rdata <= throt;              // THROT
                        6'h14: bus_rdata <= count;              // COUNT
                        6'h18: bus_rdata <= BUS_PERIOD_NS;      // BUSPD
                        6'h20: bus_rdata <= sec_hi;             // SECHI
                        6'h24: bus_rdata <= sec_lo;             // SECLO
                        6'h28: bus_rdata <= nsec;               // NSEC
                        default: bus_rdata <= 32'd0;
                    endcase
                end
            end
        end
    end

endmodule
