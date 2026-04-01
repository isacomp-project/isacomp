// Fake UART for OpenSBI console output
// NS16550A compatible - captures TX writes and displays them
//
// Register map (byte offsets):
//   0x0: RBR/THR - Receive/Transmit holding register
//   0x1: IER - Interrupt enable register
//   0x2: IIR/FCR - Interrupt ID / FIFO control
//   0x3: LCR - Line control register
//   0x4: MCR - Modem control register
//   0x5: LSR - Line status register
//   0x6: MSR - Modem status register
//   0x7: SCR - Scratch register

`timescale 1ns/1ps

module fake_uart #(
    parameter BASE_ADDR = 32'h10000000
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

    // TX output for monitoring
    output logic        tx_valid,
    output logic [7:0]  tx_data
);

    // Registers
    logic [7:0] thr;        // Transmit holding register
    logic [7:0] ier;        // Interrupt enable
    logic [7:0] fcr;        // FIFO control
    logic [7:0] lcr;        // Line control
    logic [7:0] mcr;        // Modem control
    logic [7:0] scr;        // Scratch register
    logic       thr_int_pending;  // THR empty interrupt pending flag

    // LSR bits:
    // bit 0: Data ready (RX)
    // bit 5: THR empty (TX ready)
    // bit 6: Transmitter empty
    wire [7:0] lsr = 8'b0110_0000;  // Always ready to transmit

    // IIR: Interrupt identification register
    // bit 0: 0 = interrupt pending, 1 = no interrupt
    // bits 3:1: interrupt ID (010 = THR empty)
    // THR empty interrupt: set on THR write (byte consumed instantly),
    // cleared when IIR is read (per 16550 spec)
    wire [7:0] iir = (ier[1] && thr_int_pending) ? 8'h02 : 8'h01;

    // MSR: Modem status (not used)
    wire [7:0] msr = 8'b0000_0000;

    // Address decode
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < (BASE_ADDR + 32'h100));
    wire [3:0] reg_addr = bus_addr[3:0];

    // DLAB (Divisor Latch Access Bit) - LCR bit 7
    wire dlab = lcr[7];

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
                if (bus_we) begin
                    bus_ack <= 1'b1;
                    case (reg_addr)
                        4'h0: begin
                            if (!dlab) begin
                                // THR write - transmit character (consumed instantly)
                                thr <= bus_wdata[7:0];
                                thr_int_pending <= 1'b1;  // THR empty after instant consume
                                tx_valid <= 1'b1;
                                tx_data <= bus_wdata[7:0];
                                // Display character
                                if (bus_wdata[7:0] >= 8'h20 && bus_wdata[7:0] < 8'h7F) begin
                                    $write("%c", bus_wdata[7:0]);
                                end else if (bus_wdata[7:0] == 8'h0A) begin
                                    $write("\n");
                                end else if (bus_wdata[7:0] == 8'h0D) begin
                                    // Carriage return - ignore
                                end else begin
                                    $write("[%02x]", bus_wdata[7:0]);
                                end
                                $fflush();
                            end
                            // else: DLL (divisor latch low) - ignored
                        end
                        4'h1: begin
                            if (!dlab) begin
                                ier <= bus_wdata[7:0];
                            end
                            // else: DLM (divisor latch high) - ignored
                        end
                        4'h2: fcr <= bus_wdata[7:0];
                        4'h3: lcr <= bus_wdata[7:0];
                        4'h4: mcr <= bus_wdata[7:0];
                        4'h7: scr <= bus_wdata[7:0];
                        default: ;
                    endcase
                end else if (bus_re) begin
                    bus_ack <= 1'b1;
                    case (reg_addr)
                        4'h0: bus_rdata <= dlab ? 32'h00 : 32'h00;  // RBR (no RX data) or DLL
                        4'h1: bus_rdata <= dlab ? 32'h00 : {24'h0, ier};  // IER or DLM
                        4'h2: begin
                            bus_rdata <= {24'h0, iir};
                            thr_int_pending <= 1'b0;  // Reading IIR clears THR interrupt
                        end
                        4'h3: bus_rdata <= {24'h0, lcr};
                        4'h4: bus_rdata <= {24'h0, mcr};
                        4'h5: bus_rdata <= {24'h0, lsr};
                        4'h6: bus_rdata <= {24'h0, msr};
                        4'h7: bus_rdata <= {24'h0, scr};
                        default: bus_rdata <= 32'h00;
                    endcase
                end
            end
        end
    end

endmodule
