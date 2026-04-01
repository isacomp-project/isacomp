// M68K Programmable Timer
// Similar to ColdFire/MCF PIT for Linux compatibility
//
// Register Map:
//   0x00 - CTRL: Control Register
//          bit 0: Enable
//          bit 1: Interrupt Enable
//          bit 2: Auto-reload mode (periodic)
//          bit 3: Clear pending (write 1 to clear)
//   0x04 - LOAD: Load/Reload value (countdown start)
//   0x08 - COUNT: Current count value (R)
//   0x0C - STATUS: Status register (R)
//          bit 0: Interrupt pending
//          bit 1: Timer running
//   0x10 - PRESCALE: Prescaler value (R/W)
//   0x14 - SEC_LO: Seconds counter low (R)
//   0x18 - SEC_HI: Seconds counter high (R)
//   0x1C - NSEC: Nanoseconds within second (R)

module m68k_timer #(
    parameter BASE_ADDR = 32'h10000300,
    parameter BUS_PERIOD_NS = 20       // 50 MHz = 20ns period
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
    logic [31:0] ctrl;
    logic [31:0] load;
    logic [31:0] count;
    logic [31:0] prescale;
    logic [31:0] prescale_count;

    // Real-time clock (free-running)
    logic [31:0] sec_lo;
    logic [31:0] sec_hi;
    logic [31:0] nsec;

    // Status
    logic irq_pending;

    // Control bits
    wire timer_enable = ctrl[0];
    wire irq_enable = ctrl[1];
    wire auto_reload = ctrl[2];

    // Address decode
    wire [4:0] reg_offset = bus_addr[4:0];
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 32);

    // Prescaler tick
    logic prescale_tick;
    always_ff @(posedge clk) begin
        if (reset || !timer_enable) begin
            prescale_count <= 32'd0;
            prescale_tick <= 1'b0;
        end else begin
            if (prescale_count >= prescale) begin
                prescale_count <= 32'd0;
                prescale_tick <= 1'b1;
            end else begin
                prescale_count <= prescale_count + 1;
                prescale_tick <= 1'b0;
            end
        end
    end

    // Timer countdown
    always_ff @(posedge clk) begin
        if (reset) begin
            count <= 32'd0;
            irq_pending <= 1'b0;
        end else if (!timer_enable) begin
            // Timer disabled - hold count
        end else if (bus_we && addr_match && reg_offset == 5'h00 && bus_wdata[3]) begin
            // Writing to CTRL with bit 3 set clears pending
            irq_pending <= 1'b0;
        end else if (prescale_tick) begin
            if (count == 32'd0) begin
                // Timer expired
                irq_pending <= 1'b1;
                if (auto_reload) begin
                    count <= load;
                end
            end else begin
                count <= count - 1;
            end
        end
    end

    // Timer IRQ output
    assign timer_irq = irq_pending && irq_enable;

    // Real-time clock (free-running, independent of timer)
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

    // Register read/write
    always_ff @(posedge clk) begin
        if (reset) begin
            ctrl <= 32'd0;
            load <= 32'd0;
            prescale <= 32'd0;
            bus_rdata <= 32'd0;
            bus_ack <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (addr_match && (bus_we || bus_re)) begin
                bus_ack <= 1'b1;

                if (bus_we) begin
                    case (reg_offset)
                        5'h00: begin
                            ctrl <= bus_wdata;
                            // If enabling timer and count is 0, load initial value
                            if (bus_wdata[0] && !ctrl[0] && count == 0) begin
                                count <= load;
                            end
                        end
                        5'h04: load <= bus_wdata;
                        5'h10: prescale <= bus_wdata;
                        default: ;
                    endcase
                end

                if (bus_re) begin
                    case (reg_offset)
                        5'h00: bus_rdata <= ctrl;
                        5'h04: bus_rdata <= load;
                        5'h08: bus_rdata <= count;
                        5'h0C: bus_rdata <= {30'd0, timer_enable, irq_pending};
                        5'h10: bus_rdata <= prescale;
                        5'h14: bus_rdata <= sec_lo;
                        5'h18: bus_rdata <= sec_hi;
                        5'h1C: bus_rdata <= nsec;
                        default: bus_rdata <= 32'd0;
                    endcase
                end
            end
        end
    end

endmodule
