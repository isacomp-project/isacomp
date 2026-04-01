// Alpha64 Interrupt Controller
// =============================
// Simple interrupt aggregation for Alpha64 Linux boot.
// Memory-mapped registers at BASE_ADDR with 8-byte spacing (little-endian).
//
// Register Map:
//   0x00: IRQ_STATUS  (R)   - raw pending device interrupts
//   0x08: IRQ_ENABLE  (R/W) - per-device interrupt mask
//   0x10: IRQ_PENDING (R)   - IRQ_STATUS & IRQ_ENABLE (masked pending)
//
// The ext_isr_bits output maps device interrupts into Alpha ISR bit positions:
//   irq_sources[0] -> ISR bit 4  (device interrupt 0, typically timer)
//   irq_sources[1] -> ISR bit 5  (device interrupt 1, typically UART)
//   irq_sources[N] -> ISR bit 4+N

module alpha_intc #(
    parameter BASE_ADDR = 64'h0000000080000000
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

    // Interrupt sources (active high)
    input  logic [15:0] irq_sources,

    // Output: ISR bits for CPU injection
    // Maps device IRQs to Alpha ISR bit positions:
    //   irq_sources[0] -> ISR bit 4 (device interrupt 0 / timer)
    //   irq_sources[1] -> ISR bit 5 (device interrupt 1 / UART)
    //   etc.
    output logic [63:0] ext_isr_bits
);

    // Registers
    logic [15:0] irq_enable;
    logic [15:0] irq_pending;
    logic [15:0] irq_status;

    // Address decode - 3 registers at 8-byte spacing = 0x18 bytes
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 64'h18);
    wire [4:0] reg_offset = bus_addr[4:0];

    // Interrupt logic
    assign irq_status  = irq_sources;
    assign irq_pending = irq_status & irq_enable;

    // Map masked pending interrupts into Alpha ISR bit positions.
    // Device interrupts start at ISR bit 4 (bits 0-3 are software/reserved).
    always_comb begin
        ext_isr_bits = 64'd0;
        for (int i = 0; i < 16; i++) begin
            ext_isr_bits[i + 4] = irq_pending[i];
        end
    end

    // Bus read/write
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            irq_enable <= 16'hFFFF;  // All enabled by default
            bus_rdata  <= 64'd0;
            bus_ack    <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (bus_valid && addr_match) begin
                bus_ack <= 1'b1;

                case (reg_offset)
                    5'h00: begin  // IRQ_STATUS (read-only)
                        bus_rdata <= {48'd0, irq_status};
                    end
                    5'h08: begin  // IRQ_ENABLE (read/write)
                        bus_rdata <= {48'd0, irq_enable};
                        if (bus_we)
                            irq_enable <= bus_wdata[15:0];
                    end
                    5'h10: begin  // IRQ_PENDING (read-only)
                        bus_rdata <= {48'd0, irq_pending};
                    end
                    default: begin
                        bus_rdata <= 64'd0;
                    end
                endcase
            end
        end
    end

endmodule
