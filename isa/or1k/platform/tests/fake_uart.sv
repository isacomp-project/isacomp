// Fake UART for OR1K Linux console output
// NS16550A compatible - captures TX writes and displays them
//
// Adapted for OR1K platform with 32-bit address bus.
// Default base address matches OR1K SoC memory map: 0x90000100.
//
// Register map (byte offsets from BASE_ADDR):
//   0x0: RBR/THR - Receive/Transmit holding register (DLAB=0)
//   0x0: DLL     - Divisor Latch Low (DLAB=1)
//   0x1: IER     - Interrupt enable register (DLAB=0)
//   0x1: DLM     - Divisor Latch High (DLAB=1)
//   0x2: IIR/FCR - Interrupt ID / FIFO control
//   0x3: LCR     - Line control register
//   0x4: MCR     - Modem control register
//   0x5: LSR     - Line status register
//   0x6: MSR     - Modem status register
//   0x7: SCR     - Scratch register

`timescale 1ns/1ps

module fake_uart #(
    parameter [31:0] BASE_ADDR = 32'h90000100
) (
    input  logic        clk,
    input  logic        reset,

    // Bus interface (32-bit addresses, 32-bit data for MMIO)
    input  logic [31:0] bus_addr,
    input  logic [31:0] bus_wdata,
    input  logic        bus_we,
    input  logic        bus_re,
    output logic [31:0] bus_rdata,
    output logic        bus_ack,

    // TX output for monitoring
    output logic        tx_valid,
    output logic [7:0]  tx_data,

    // LSR output for mirroring to umem
    output logic [7:0]  lsr,

    // Interrupt output (active-high)
    output logic        irq
);

    // =========================================================================
    // Internal Registers
    // =========================================================================
    logic [7:0] thr;        // Transmit holding register
    logic [7:0] ier;        // Interrupt enable
    logic [7:0] fcr;        // FIFO control
    logic [7:0] lcr;        // Line control
    logic [7:0] mcr;        // Modem control
    logic [7:0] scr;        // Scratch register
    logic       thr_int_pending;  // THR empty interrupt pending flag

    // =========================================================================
    // Status Registers (read-only)
    // =========================================================================

    // LSR bits:
    //   bit 0: Data Ready (RX data available)
    //   bit 1: Overrun Error
    //   bit 2: Parity Error
    //   bit 3: Framing Error
    //   bit 4: Break Interrupt
    //   bit 5: THR Empty (TX ready to accept data)
    //   bit 6: Transmitter Empty (shift register empty)
    //   bit 7: Error in FIFO
    // Always ready to transmit in simulation
    assign lsr = 8'b0110_0000;

    // IIR: Interrupt Identification Register
    //   bit 0: 0 = interrupt pending, 1 = no interrupt pending
    //   bits 3:1: interrupt ID (010 = THR empty, 001 = modem status)
    wire [7:0] iir = (ier[1] && thr_int_pending) ? 8'h02 : 8'h01;

    // Interrupt output: asserted when THR-empty interrupt is enabled and pending
    assign irq = (ier[1] && thr_int_pending);

    // MSR: Modem Status Register (unused in simulation)
    wire [7:0] msr = 8'h00;

    // =========================================================================
    // Address Decode
    // =========================================================================
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < (BASE_ADDR + 32'h100));
    // Use bits [4:2] for register select to match reg-shift=2 (word-aligned regs)
    wire [2:0] reg_addr = bus_addr[4:2];

    // DLAB (Divisor Latch Access Bit) - LCR bit 7
    wire dlab = lcr[7];

    // Big-endian OR1K: byte stores via RMW place data in the MSByte [31:24]
    wire [7:0] wr_byte = bus_wdata[31:24];

    // =========================================================================
    // Register Access Logic
    // =========================================================================
    always_ff @(posedge clk) begin
        if (reset) begin
            thr <= 8'h00;
            ier <= 8'h00;
            fcr <= 8'h00;
            lcr <= 8'h00;
            mcr <= 8'h00;
            scr <= 8'h00;
            thr_int_pending <= 1'b0;
            tx_valid <= 1'b0;
            tx_data <= 8'h00;
            bus_ack <= 1'b0;
            bus_rdata <= 32'h0;
        end else begin
            tx_valid <= 1'b0;
            bus_ack <= 1'b0;

            if (addr_match) begin
                // ---------------------------------------------------------
                // Write path
                // ---------------------------------------------------------
                if (bus_we) begin
                    bus_ack <= 1'b1;
                    case (reg_addr)
                        3'h0: begin
                            if (!dlab) begin
                                // THR write - transmit character (consumed instantly)
                                thr <= wr_byte;
                                thr_int_pending <= 1'b1;
                                tx_valid <= 1'b1;
                                tx_data <= wr_byte;
                                // Display printable ASCII to simulation console
                                if (wr_byte >= 8'h20 && wr_byte < 8'h7F) begin
                                    $write("%c", wr_byte);
                                end else if (wr_byte == 8'h0A) begin
                                    $write("\n");
                                end else if (wr_byte == 8'h0D) begin
                                    // Carriage return - ignore (handled with newline)
                                end else begin
                                    $write("[%02x]", wr_byte);
                                end
                                $fflush();
                            end
                            // else: DLL (Divisor Latch Low) - ignored in simulation
                        end
                        3'h1: begin
                            if (!dlab) begin
                                ier <= wr_byte;
                            end
                            // else: DLM (Divisor Latch High) - ignored in simulation
                        end
                        3'h2: fcr <= wr_byte;
                        3'h3: lcr <= wr_byte;
                        3'h4: mcr <= wr_byte;
                        3'h7: scr <= wr_byte;
                        default: ;
                    endcase
                end

                // ---------------------------------------------------------
                // Read path
                // ---------------------------------------------------------
                else if (bus_re) begin
                    bus_ack <= 1'b1;
                    // Replicate byte data across all 4 byte lanes so both
                    // big-endian byte loads (l.lbz) and word loads work correctly
                    case (reg_addr)
                        3'h0: bus_rdata <= dlab ? 32'h00 : 32'h00;  // RBR (no RX data) or DLL
                        3'h1: bus_rdata <= dlab ? 32'h00 : {4{ier}};  // IER or DLM
                        3'h2: begin
                            bus_rdata <= {4{iir}};
                            thr_int_pending <= 1'b0;  // Reading IIR clears THR interrupt
                        end
                        3'h3: bus_rdata <= {4{lcr}};
                        3'h4: bus_rdata <= {4{mcr}};
                        3'h5: bus_rdata <= {4{lsr}};
                        3'h6: bus_rdata <= {4{msr}};
                        3'h7: bus_rdata <= {4{scr}};
                        default: bus_rdata <= 32'h00;
                    endcase
                end
            end
        end
    end

endmodule
