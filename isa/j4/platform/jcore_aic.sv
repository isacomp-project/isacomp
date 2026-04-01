// JCORE AIC (Advanced Interrupt Controller)
// Compatible with Linux jcore,aic1 driver
//
// Register Map (at base + cpu_id * 0x10):
//   0x00 - INTST: Interrupt Status (R)
//   0x04 - INTEN: Interrupt Enable (R/W)
//   0x08 - INTPRI: Interrupt Priority (R/W) - must be 0xffffffff for interrupts to work
//   0x0C - Reserved
//
// This implements the AIC1 variant which:
// - Uses hardware IRQ numbers 16-127
// - Has a single priority register that must be set to enable interrupts
// - Clears pending status when CPU accepts the interrupt

module jcore_aic #(
    parameter BASE_ADDR = 32'hABCD0200,
    parameter NUM_IRQS = 112  // IRQs 16-127
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

    // Interrupt sources (directly from peripherals)
    input  logic [NUM_IRQS-1:0] irq_sources,

    // To CPU
    output logic        irq_out,
    output logic [7:0]  irq_vector  // Vector number for CPU (16-127)
);

    // Registers
    logic [31:0] intpri;   // Priority register - must be 0xffffffff
    logic [NUM_IRQS-1:0] irq_pending;
    logic [NUM_IRQS-1:0] irq_edge_detect;

    // Address decode
    // NOTE: AIC and PIT share the same base address but use different register offsets.
    // AIC handles: 0x04 (INTEN), 0x08 (INTPRI), 0x0C (reserved)
    // PIT handles: 0x00 (PITEN), 0x10-0x28 (timer registers)
    wire [3:0] reg_offset = bus_addr[3:0];
    wire is_aic_register = (reg_offset == 4'h4) || (reg_offset == 4'h8) || (reg_offset == 4'hC);
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 16) && is_aic_register;

    // Edge detection for interrupt sources
    always_ff @(posedge clk) begin
        if (reset) begin
            irq_edge_detect <= '0;
        end else begin
            irq_edge_detect <= irq_sources;
        end
    end

    // Level-triggered interrupts - follow irq_sources directly
    // The peripheral (e.g., PIT) is responsible for holding the IRQ high
    // until acknowledged by the kernel writing to its control register
    always_ff @(posedge clk) begin
        if (reset) begin
            irq_pending <= '0;
        end else begin
            irq_pending <= irq_sources;
        end
    end

    // Find highest priority pending interrupt
    // Lower IRQ numbers have higher priority
    logic [7:0] highest_irq;
    logic any_pending;

    always_comb begin
        highest_irq = 8'd0;
        any_pending = 1'b0;
        for (int i = 0; i < NUM_IRQS; i++) begin
            if (irq_pending[i] && !any_pending) begin
                highest_irq = i[7:0] + 8'd16;  // IRQs start at 16
                any_pending = 1'b1;
            end
        end
    end

    // Output IRQ to CPU
    // Only assert if priority register is set (Linux requirement)
    assign irq_out = any_pending && (intpri != 32'd0);
    assign irq_vector = highest_irq;

    // Register read/write
    always_ff @(posedge clk) begin
        if (reset) begin
            intpri <= 32'd0;
            bus_rdata <= 32'd0;
            bus_ack <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (addr_match && (bus_we || bus_re)) begin
                bus_ack <= 1'b1;

                if (bus_we) begin
                    case (reg_offset)
                        4'h8: intpri <= bus_wdata;  // INTPRI
                        default: ;
                    endcase
                end

                if (bus_re) begin
                    case (reg_offset)
                        4'h0: bus_rdata <= {24'd0, irq_vector};  // INTST - current vector
                        4'h4: bus_rdata <= 32'hFFFFFFFF;         // INTEN - always enabled
                        4'h8: bus_rdata <= intpri;               // INTPRI
                        default: bus_rdata <= 32'd0;
                    endcase
                end
            end
        end
    end

endmodule
