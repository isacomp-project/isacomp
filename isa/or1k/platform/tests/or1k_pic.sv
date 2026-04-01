// OR1K Programmable Interrupt Controller (PIC)
// Level-sensitive interrupt controller for aggregating external IRQ sources
//
// The OR1K architecture defines the PIC via SPR group 9, but in a typical SoC
// the PIC is memory-mapped. This module provides a memory-mapped PIC that
// aggregates multiple interrupt sources into a single irq_pending signal
// for the CPU.
//
// Register Map (relative to BASE_ADDR):
//   0x00: PICMR - PIC Mask Register (which IRQs are enabled)
//     Each bit corresponds to one IRQ line. 1 = enabled, 0 = masked.
//   0x04: PICSR - PIC Status Register (which IRQs are pending)
//     Each bit reflects the current state of the corresponding IRQ source.
//     Level-sensitive: bits are updated from irq_sources every cycle.
//     Software can write 1 to a bit to clear it (write-1-to-clear).
//
// The PIC outputs irq_pending = |(PICSR & PICMR), which is connected
// to the CPU's irq_pending_rd input. The CPU takes the external interrupt
// exception (vector 0x800) when SR.IEE is set and irq_pending is asserted.
//
// OR1K Linux expects a "pic-level" compatible interrupt controller.

`timescale 1ns/1ps

module or1k_pic #(
    parameter [31:0] BASE_ADDR = 32'h90000000,
    parameter NUM_IRQS = 32
) (
    input  logic        clk,
    input  logic        reset,

    // Bus interface
    input  logic [31:0] bus_addr,
    input  logic [31:0] bus_wdata,
    input  logic        bus_we,
    output logic [31:0] bus_rdata,

    // Interrupt inputs (active-high, active when source is asserting)
    input  logic [NUM_IRQS-1:0] irq_sources,

    // Aggregated interrupt output to CPU
    output logic        irq_pending
);

    // =========================================================================
    // PIC Registers
    // =========================================================================
    reg [31:0] picmr;  // Mask register: enables individual IRQ lines
    reg [31:0] picsr;  // Status register: reflects pending IRQ state

    // =========================================================================
    // Address Decode
    // =========================================================================
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 256);

    // =========================================================================
    // Outputs
    // =========================================================================
    // Interrupt is pending if any enabled source is active
    assign irq_pending = |(picsr & picmr);

    // Read data mux: offset 0 = PICMR, offset 4 = PICSR
    assign bus_rdata = bus_addr[2] ? picsr : picmr;

    // =========================================================================
    // PIC Logic
    // =========================================================================
    always_ff @(posedge clk) begin
        if (reset) begin
            picmr <= 32'h0;
            picsr <= 32'h0;
        end else begin
            // Level-sensitive: update status register from hardware sources
            // Zero-extend if NUM_IRQS < 32
            picsr <= {{(32-NUM_IRQS){1'b0}}, irq_sources};

            // Bus writes
            if (bus_we && addr_match) begin
                if (!bus_addr[2])
                    picmr <= bus_wdata;           // Write mask register
                else
                    picsr <= picsr & ~bus_wdata;  // Write-1-to-clear status
            end
        end
    end

endmodule
