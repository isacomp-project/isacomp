// 16550 UART (OpenPOWER/Microwatt Compatible)
// Compatible with Linux 8250/16550 driver
//
// Register Map (byte offsets):
//   0x00 - RBR (R) / THR (W) - Receive/Transmit buffer
//          DLL (W) when DLAB=1 - Divisor Latch Low
//   0x01 - IER (R/W) - Interrupt Enable Register
//          DLH (W) when DLAB=1 - Divisor Latch High
//   0x02 - IIR (R) - Interrupt ID Register
//          FCR (W) - FIFO Control Register
//   0x03 - LCR (R/W) - Line Control Register
//   0x04 - MCR (R/W) - Modem Control Register
//   0x05 - LSR (R) - Line Status Register
//   0x06 - MSR (R) - Modem Status Register
//   0x07 - SCR (R/W) - Scratch Register
//
// For simulation, TX drains immediately and provides UART output via $write

module uart16550 #(
    parameter BASE_ADDR = 64'hC0002000,
    parameter ADDR_WIDTH = 64,
    parameter FIFO_DEPTH = 16
) (
    input  logic                   clk,
    input  logic                   reset,

    // Bus interface (64-bit address for OpenPOWER)
    input  logic [ADDR_WIDTH-1:0]  bus_addr,
    input  logic [63:0]            bus_wdata,
    input  logic [7:0]             bus_we,      // Byte enables
    input  logic                   bus_valid,
    output logic [63:0]            bus_rdata,
    output logic                   bus_ack,

    // UART interrupt
    output logic                   uart_irq,

    // Simulation interface for RX injection
    input  logic [7:0]             sim_rx_data,
    input  logic                   sim_rx_valid,
    output logic                   sim_rx_ready
);

    // TX FIFO
    logic [7:0] tx_fifo [FIFO_DEPTH-1:0];
    logic [4:0] tx_wr_ptr, tx_rd_ptr;
    logic [4:0] tx_count;
    wire tx_empty = (tx_count == 0);
    wire tx_full = (tx_count == FIFO_DEPTH);

    // RX FIFO
    logic [7:0] rx_fifo [FIFO_DEPTH-1:0];
    logic [4:0] rx_wr_ptr, rx_rd_ptr;
    logic [4:0] rx_count;
    wire rx_valid = (rx_count != 0);
    wire rx_full = (rx_count == FIFO_DEPTH);

    // Registers
    logic [7:0] ier;     // Interrupt Enable Register
    logic [7:0] lcr;     // Line Control Register
    logic [7:0] mcr;     // Modem Control Register
    logic [7:0] scr;     // Scratch Register
    logic [15:0] divisor; // Baud rate divisor
    logic fifo_enable;

    // Derived signals
    wire dlab = lcr[7];  // Divisor Latch Access Bit

    // Address decode - Microwatt-compatible with reg-shift=2 (4-byte register spacing)
    // Registers at BASE+0x00, BASE+0x04, BASE+0x08, ..., BASE+0x1C
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 32);
    wire [2:0] reg_offset = bus_addr[4:2];  // reg-shift=2: bits [4:2] select register

    // Big-endian byte lane extraction based on actual byte address within doubleword
    wire [2:0] byte_lane = bus_addr[2:0];
    reg [7:0] wr_byte;
    always @* begin
        case (byte_lane)
            3'd0: wr_byte = bus_wdata[63:56];
            3'd1: wr_byte = bus_wdata[55:48];
            3'd2: wr_byte = bus_wdata[47:40];
            3'd3: wr_byte = bus_wdata[39:32];
            3'd4: wr_byte = bus_wdata[31:24];
            3'd5: wr_byte = bus_wdata[23:16];
            3'd6: wr_byte = bus_wdata[15:8];
            3'd7: wr_byte = bus_wdata[7:0];
        endcase
    end

    // Line Status Register (LSR) - always read-only
    // Bit 0: Data Ready (DR) - RX FIFO has data
    // Bit 1: Overrun Error (OE)
    // Bit 2: Parity Error (PE)
    // Bit 3: Framing Error (FE)
    // Bit 4: Break Interrupt (BI)
    // Bit 5: THR Empty (THRE) - TX FIFO empty
    // Bit 6: Transmitter Empty (TEMT) - TX shift register empty
    // Bit 7: Error in RCVR FIFO
    logic overrun_err;
    wire [7:0] lsr = {1'b0, tx_empty, tx_empty, 4'b0000, rx_valid};

    // Interrupt Identification Register (IIR) - read-only
    // Bit 0: Interrupt Pending (0 = pending)
    // Bits 3:1: Interrupt ID
    //   000 = Modem Status
    //   001 = THR Empty
    //   010 = Received Data Available
    //   011 = Receiver Line Status
    //   110 = Character Timeout
    // Bits 5:4: Reserved
    // Bits 7:6: FIFO enabled
    wire irq_rx = ier[0] && rx_valid;
    wire irq_tx = ier[1] && tx_empty;
    wire irq_pending = irq_rx || irq_tx;
    wire [2:0] irq_id = irq_rx ? 3'b010 : (irq_tx ? 3'b001 : 3'b000);
    wire [7:0] iir = {fifo_enable ? 2'b11 : 2'b00, 2'b00, irq_id, !irq_pending};

    // RX ready for simulation injection
    assign sim_rx_ready = !rx_full;

    // Interrupt output
    assign uart_irq = irq_pending;

    // File handle for UART output
    integer uart_fd;
    integer uart_char_count = 0;
    initial begin
        uart_fd = $fopen("uart_output.txt", "w");
    end
    final begin
        if (uart_fd) $fclose(uart_fd);
    end

    // TX FIFO - drain immediately in simulation
    always_ff @(posedge clk) begin
        if (reset) begin
            tx_wr_ptr <= 0;
            tx_rd_ptr <= 0;
            tx_count <= 0;
        end else begin
            // Drain TX FIFO immediately (simulation behaves as if baud rate is infinite)
            if (!tx_empty) begin
                tx_rd_ptr <= tx_rd_ptr + 1;
                tx_count <= tx_count - 1;
            end
        end
    end

    // RX FIFO - accept simulation injection
    always_ff @(posedge clk) begin
        if (reset) begin
            rx_wr_ptr <= 0;
            rx_rd_ptr <= 0;
            rx_count <= 0;
            overrun_err <= 0;
        end else begin
            // Accept RX data from simulation
            if (sim_rx_valid && sim_rx_ready) begin
                rx_fifo[rx_wr_ptr[3:0]] <= sim_rx_data;
                rx_wr_ptr <= rx_wr_ptr + 1;
                rx_count <= rx_count + 1;
            end else if (sim_rx_valid && !sim_rx_ready) begin
                overrun_err <= 1'b1;
            end
        end
    end

    // Transaction tracking to prevent double-processing
    // (CPU may hold valid for multiple cycles)
    logic bus_valid_prev;
    always_ff @(posedge clk) begin
        if (reset) bus_valid_prev <= 1'b0;
        else bus_valid_prev <= addr_match && bus_valid;
    end
    wire new_transaction = addr_match && bus_valid && !bus_valid_prev;

    // Register read/write
    always_ff @(posedge clk) begin
        if (reset) begin
            ier <= 8'd0;
            lcr <= 8'h03;  // 8N1
            mcr <= 8'd0;
            scr <= 8'd0;
            divisor <= 16'd1;
            fifo_enable <= 1'b0;
            bus_rdata <= 64'd0;
            bus_ack <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (new_transaction) begin
                bus_ack <= 1'b1;

                // Write operations (check byte enables)
                // wr_byte extracts the correct big-endian byte lane
                if (|bus_we) begin
                    case (reg_offset)
                        3'h0: begin  // THR/DLL
                            if (dlab) begin
                                divisor[7:0] <= wr_byte;
                            end else begin
                                // TX write
                                if (!tx_full) begin
                                    tx_fifo[tx_wr_ptr[3:0]] <= wr_byte;
                                    tx_wr_ptr <= tx_wr_ptr + 1;
                                    tx_count <= tx_count + 1;
                                    $fwrite(uart_fd, "%c", wr_byte);
                                    $fflush(uart_fd);
                                    if (uart_char_count < 200)
                                        $display("[UART_THR] char#%0d: 0x%02x ('%c') byte_lane=%0d bus_data=0x%016x bus_we=0x%02x",
                                            uart_char_count, wr_byte, wr_byte,
                                            byte_lane, bus_wdata, bus_we);
                                    uart_char_count <= uart_char_count + 1;
                                end
                            end
                        end
                        3'h1: begin  // IER/DLH
                            if (dlab)
                                divisor[15:8] <= wr_byte;
                            else
                                ier <= wr_byte;
                        end
                        3'h2: begin  // FCR
                            fifo_enable <= wr_byte[0];
                            if (wr_byte[1]) begin  // Reset RX FIFO
                                rx_wr_ptr <= 0;
                                rx_rd_ptr <= 0;
                                rx_count <= 0;
                            end
                            if (wr_byte[2]) begin  // Reset TX FIFO
                                tx_wr_ptr <= 0;
                                tx_rd_ptr <= 0;
                                tx_count <= 0;
                            end
                        end
                        3'h3: lcr <= wr_byte;
                        3'h4: mcr <= wr_byte;
                        3'h7: scr <= wr_byte;
                        default: ;
                    endcase
                end

                // Read operations - select register data
                // Then place in correct big-endian byte lane based on actual address
                begin
                    reg [7:0] rd_byte;
                    case (reg_offset)
                        3'h0: begin  // RBR/DLL
                            if (dlab)
                                rd_byte = divisor[7:0];
                            else begin
                                rd_byte = rx_fifo[rx_rd_ptr[3:0]];
                                if (rx_valid && !(|bus_we)) begin
                                    rx_rd_ptr <= rx_rd_ptr + 1;
                                    rx_count <= rx_count - 1;
                                end
                            end
                        end
                        3'h1: rd_byte = dlab ? divisor[15:8] : ier;
                        3'h2: rd_byte = iir;
                        3'h3: rd_byte = lcr;
                        3'h4: rd_byte = mcr;
                        3'h5: rd_byte = lsr;
                        3'h6: rd_byte = 8'hB0;  // MSR: CTS, DSR, DCD set
                        3'h7: rd_byte = scr;
                    endcase
                    // Place byte in correct big-endian lane
                    bus_rdata <= 64'd0;
                    case (byte_lane)
                        3'd0: bus_rdata[63:56] <= rd_byte;
                        3'd1: bus_rdata[55:48] <= rd_byte;
                        3'd2: bus_rdata[47:40] <= rd_byte;
                        3'd3: bus_rdata[39:32] <= rd_byte;
                        3'd4: bus_rdata[31:24] <= rd_byte;
                        3'd5: bus_rdata[23:16] <= rd_byte;
                        3'd6: bus_rdata[15:8]  <= rd_byte;
                        3'd7: bus_rdata[7:0]   <= rd_byte;
                    endcase
                end
            end
        end
    end

endmodule
