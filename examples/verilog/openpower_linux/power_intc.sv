// Simple Interrupt Controller for OpenPOWER SoC
// Provides basic interrupt aggregation for Linux boot

module power_intc #(
    parameter BASE_ADDR = 64'hC0004000
) (
    input  logic        clk,
    input  logic        reset,

    // Bus interface
    input  logic [63:0] bus_addr,
    input  logic [63:0] bus_wdata,
    input  logic [7:0]  bus_we,
    input  logic        bus_valid,
    output logic [63:0] bus_rdata,
    output logic        bus_ack,

    // Interrupt sources (active high)
    input  logic [31:0] irq_sources,

    // Output to CPU
    output logic        irq_out,
    output logic [5:0]  irq_vector
);

    // Registers
    // 0x00: IRQ Status (read-only) - pending interrupts
    // 0x04: IRQ Enable - which interrupts are enabled
    // 0x08: IRQ Vector - current interrupt vector (read clears)

    logic [31:0] irq_enable;
    logic [31:0] irq_pending;
    logic [31:0] irq_status;  // sources & enable

    // Address decode
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 64'h20);
    wire [4:0] reg_offset = bus_addr[4:0];

    // Interrupt logic
    assign irq_pending = irq_sources;
    assign irq_status = irq_pending & irq_enable;
    assign irq_out = |irq_status;

    // Priority encoder for vector
    always_comb begin
        irq_vector = 6'd0;
        for (int i = 31; i >= 0; i = i - 1) begin
            if (irq_status[i])
                irq_vector = i[5:0];
        end
    end

    // Bus read/write
    always_ff @(posedge clk) begin
        if (reset) begin
            irq_enable <= 32'hFFFFFFFF;  // All enabled by default
            bus_rdata <= 64'd0;
            bus_ack <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (bus_valid && addr_match) begin
                bus_ack <= 1'b1;

                case (reg_offset)
                    5'h00: begin  // IRQ Status (read-only)
                        bus_rdata <= {32'd0, irq_status};
                    end
                    5'h04: begin  // IRQ Enable
                        bus_rdata <= {32'd0, irq_enable};
                        if (|bus_we)
                            irq_enable <= bus_wdata[31:0];
                    end
                    5'h08: begin  // IRQ Pending (read-only)
                        bus_rdata <= {32'd0, irq_pending};
                    end
                    5'h0C: begin  // IRQ Vector
                        bus_rdata <= {58'd0, irq_vector};
                    end
                    default: begin
                        bus_rdata <= 64'd0;
                    end
                endcase
            end
        end
    end

endmodule
