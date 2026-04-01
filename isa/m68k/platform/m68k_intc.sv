// M68K Interrupt Controller
// Manages interrupt requests and provides vector numbers
//
// M68K Interrupt Model:
// - 3-bit IPL (Interrupt Priority Level) input to CPU
// - IPL 0 = no interrupt, IPL 7 = non-maskable
// - CPU compares IPL to SR[10:8] (interrupt mask)
// - Vector provided during interrupt acknowledge cycle
//
// Register Map:
//   0x00 - ISR: Interrupt Status Register (R) - pending interrupts
//   0x04 - IER: Interrupt Enable Register (R/W)
//   0x08 - IPR: Interrupt Priority Register (R/W) - 3 bits per source
//   0x0C - IMR: Interrupt Mask Register (R/W)
//   0x10 - IVR: Interrupt Vector Base (R/W) - base vector number
//   0x14 - IAR: Interrupt Acknowledge (R) - returns current vector

module m68k_intc #(
    parameter BASE_ADDR = 32'h10000200,
    parameter NUM_SOURCES = 8,        // Number of interrupt sources
    parameter DEFAULT_VECTOR = 8'd64  // Base vector number (user interrupts start at 64)
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

    // Interrupt sources from peripherals
    input  logic [NUM_SOURCES-1:0] irq_sources,

    // To CPU
    output logic [2:0]  ipl,          // Interrupt Priority Level
    output logic [7:0]  irq_vector,   // Vector number for IACK
    output logic        irq_pending   // Any interrupt pending
);

    // Registers
    logic [NUM_SOURCES-1:0] ier;      // Interrupt Enable
    logic [NUM_SOURCES-1:0] imr;      // Interrupt Mask
    logic [31:0] ipr;                 // Priority (3 bits per source, up to 8 sources)
    logic [7:0] ivr;                  // Vector base

    // Derived signals
    logic [NUM_SOURCES-1:0] pending;
    logic [2:0] highest_priority;
    logic [7:0] highest_vector;
    integer highest_source;

    // Pending = source active AND enabled AND not masked
    assign pending = irq_sources & ier & ~imr;

    // Address decode
    wire [4:0] reg_offset = bus_addr[4:0];
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 32);

    // Find highest priority pending interrupt
    always_comb begin
        highest_priority = 3'd0;
        highest_vector = 8'd0;
        highest_source = -1;

        for (int i = 0; i < NUM_SOURCES; i++) begin
            if (pending[i]) begin
                logic [2:0] src_priority;
                src_priority = ipr[(i*4) +: 3];  // 3 bits per source

                if (src_priority > highest_priority) begin
                    highest_priority = src_priority;
                    highest_vector = ivr + i[7:0];
                    highest_source = i;
                end
            end
        end
    end

    // Output to CPU
    assign ipl = highest_priority;
    assign irq_vector = highest_vector;
    assign irq_pending = (highest_priority != 3'd0);

    // Register read/write
    always_ff @(posedge clk) begin
        if (reset) begin
            ier <= '0;
            imr <= '0;
            ipr <= 32'h77777777;  // All sources at priority 7 by default
            ivr <= DEFAULT_VECTOR;
            bus_rdata <= 32'd0;
            bus_ack <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (addr_match && (bus_we || bus_re)) begin
                bus_ack <= 1'b1;

                if (bus_we) begin
                    case (reg_offset)
                        5'h04: ier <= bus_wdata[NUM_SOURCES-1:0];  // IER
                        5'h08: ipr <= bus_wdata;                    // IPR
                        5'h0C: imr <= bus_wdata[NUM_SOURCES-1:0];  // IMR
                        5'h10: ivr <= bus_wdata[7:0];              // IVR
                        default: ;
                    endcase
                end

                if (bus_re) begin
                    case (reg_offset)
                        5'h00: bus_rdata <= {{(32-NUM_SOURCES){1'b0}}, pending};  // ISR
                        5'h04: bus_rdata <= {{(32-NUM_SOURCES){1'b0}}, ier};      // IER
                        5'h08: bus_rdata <= ipr;                                   // IPR
                        5'h0C: bus_rdata <= {{(32-NUM_SOURCES){1'b0}}, imr};      // IMR
                        5'h10: bus_rdata <= {24'd0, ivr};                         // IVR
                        5'h14: bus_rdata <= {24'd0, highest_vector};              // IAR
                        default: bus_rdata <= 32'd0;
                    endcase
                end
            end
        end
    end

endmodule
