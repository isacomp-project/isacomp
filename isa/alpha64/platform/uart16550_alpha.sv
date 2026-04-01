// 16550 UART for Alpha64 (Little-Endian)
// =======================================
// Compatible with Linux 8250/16550 driver using reg-shift=3 (8-byte register spacing).
// Adapted from the OpenPOWER uart16550.sv for the Alpha memory model:
//   - Little-endian: data byte in bus_wdata[7:0] / bus_rdata[7:0]
//   - 8-byte register spacing: register select from bus_addr[5:3]
//
// Register Map (8-byte offsets from BASE_ADDR):
//   0x00 - RBR (R) / THR (W) - Receive/Transmit buffer
//           DLL (W) when DLAB=1 - Divisor Latch Low
//   0x08 - IER (R/W) - Interrupt Enable Register
//           DLH (W) when DLAB=1 - Divisor Latch High
//   0x10 - IIR (R) - Interrupt ID Register
//           FCR (W) - FIFO Control Register
//   0x18 - LCR (R/W) - Line Control Register
//   0x20 - MCR (R/W) - Modem Control Register
//   0x28 - LSR (R) - Line Status Register
//   0x30 - MSR (R) - Modem Status Register
//   0x38 - SCR (R/W) - Scratch Register
//
// For simulation, TX drains immediately and output goes to $write and uart_output.txt.

module uart16550_alpha #(
    parameter BASE_ADDR  = 64'h0000000080020000,
    parameter FIFO_DEPTH = 16
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

    // UART interrupt
    output logic        uart_irq,

    // Simulation RX injection
    input  logic [7:0]  sim_rx_data,
    input  logic        sim_rx_valid,
    output logic        sim_rx_ready
);

    // -------------------------------------------------------
    // TX FIFO
    // -------------------------------------------------------
    logic [7:0] tx_fifo [FIFO_DEPTH-1:0];
    logic [4:0] tx_wr_ptr, tx_rd_ptr;
    logic [4:0] tx_count;
    // For simulation: THRE always set so serial polling loops don't stall.
    // Output capture happens directly on THR write ($write/$fwrite), so FIFO
    // tracking is not needed for correctness.
    wire  tx_empty = 1'b1;
    wire  tx_full  = 1'b0;

    // -------------------------------------------------------
    // RX FIFO
    // -------------------------------------------------------
    logic [7:0] rx_fifo [FIFO_DEPTH-1:0];
    logic [4:0] rx_wr_ptr, rx_rd_ptr;
    logic [4:0] rx_count;
    wire  rx_data_ready = (rx_count != 0);
    wire  rx_full       = (rx_count == FIFO_DEPTH[4:0]);

    // -------------------------------------------------------
    // Registers
    // -------------------------------------------------------
    logic [7:0]  ier;       // Interrupt Enable Register
    logic [7:0]  lcr;       // Line Control Register
    logic [7:0]  mcr;       // Modem Control Register
    logic [7:0]  scr;       // Scratch Register
    logic [15:0] divisor;   // Baud rate divisor (DLL/DLH)
    logic        fifo_enable;
    logic        overrun_err;

    // Derived signals
    wire dlab = lcr[7];  // Divisor Latch Access Bit

    // -------------------------------------------------------
    // Address decode
    // -------------------------------------------------------
    // 8 registers at 8-byte spacing = 0x40 bytes address range
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 64'h40);
    // reg-shift=3: bits [5:3] select which 16550 register
    wire [2:0] reg_sel = bus_addr[5:3];

    // Little-endian: write data byte is bus_wdata[7:0]
    wire [7:0] wr_byte = bus_wdata[7:0];

    // -------------------------------------------------------
    // Line Status Register (LSR) - read-only
    // -------------------------------------------------------
    // Bit 0: Data Ready (DR)       - RX FIFO has data
    // Bit 1: Overrun Error (OE)
    // Bit 2: Parity Error (PE)     - not implemented
    // Bit 3: Framing Error (FE)    - not implemented
    // Bit 4: Break Interrupt (BI)  - not implemented
    // Bit 5: THR Empty (THRE)      - TX FIFO empty
    // Bit 6: Transmitter Empty     - TX shift register + FIFO empty
    // Bit 7: Error in RCVR FIFO   - not implemented
    wire [7:0] lsr = {1'b0, tx_empty, tx_empty, 3'b000, overrun_err, rx_data_ready};

    // -------------------------------------------------------
    // Interrupt Identification Register (IIR) - read-only
    // -------------------------------------------------------
    // Bit 0: Interrupt NOT Pending (0 = interrupt pending)
    // Bits 3:1: Interrupt ID
    //   001 = THR Empty
    //   010 = Received Data Available
    // Bits 7:6: FIFO status (11 when FIFOs enabled)
    wire irq_rx      = ier[0] && rx_data_ready;
    wire irq_tx      = ier[1] && tx_empty;
    wire irq_active  = irq_rx || irq_tx;
    wire [2:0] irq_id = irq_rx ? 3'b010 : (irq_tx ? 3'b001 : 3'b000);
    wire [7:0] iir    = {fifo_enable ? 2'b11 : 2'b00, 2'b00, irq_id, !irq_active};

    // -------------------------------------------------------
    // Outputs
    // -------------------------------------------------------
    assign uart_irq    = irq_active;
    assign sim_rx_ready = !rx_full;

    // -------------------------------------------------------
    // File handle for UART output
    // -------------------------------------------------------
    integer uart_fd;
    integer uart_char_count = 0;
    initial begin
        uart_fd = $fopen("uart_output.txt", "w");
    end
    final begin
        if (uart_fd) $fclose(uart_fd);
    end

    // -------------------------------------------------------
    // TX FIFO drain - immediate in simulation
    // -------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx_wr_ptr <= 5'd0;
            tx_rd_ptr <= 5'd0;
            tx_count  <= 5'd0;
        end else begin
            // Drain one entry per cycle (infinite baud in simulation)
            if (!tx_empty) begin
                tx_rd_ptr <= tx_rd_ptr + 5'd1;
                tx_count  <= tx_count - 5'd1;
            end
        end
    end

    // -------------------------------------------------------
    // RX FIFO - accept simulation injection
    // -------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_wr_ptr   <= 5'd0;
            rx_rd_ptr   <= 5'd0;
            rx_count    <= 5'd0;
            overrun_err <= 1'b0;
        end else begin
            if (sim_rx_valid && sim_rx_ready) begin
                rx_fifo[rx_wr_ptr[$clog2(FIFO_DEPTH)-1:0]] <= sim_rx_data;
                rx_wr_ptr <= rx_wr_ptr + 5'd1;
                rx_count  <= rx_count + 5'd1;
            end else if (sim_rx_valid && !sim_rx_ready) begin
                overrun_err <= 1'b1;
            end
        end
    end

    // -------------------------------------------------------
    // Transaction edge detection to prevent double-processing
    // -------------------------------------------------------
    logic bus_valid_prev;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            bus_valid_prev <= 1'b0;
        else
            bus_valid_prev <= addr_match && bus_valid;
    end
    wire new_transaction = addr_match && bus_valid && !bus_valid_prev;

    // -------------------------------------------------------
    // Register read/write
    // -------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ier         <= 8'd0;
            lcr         <= 8'h03;  // 8N1 default
            mcr         <= 8'd0;
            scr         <= 8'd0;
            divisor     <= 16'd1;
            fifo_enable <= 1'b0;
            bus_rdata   <= 64'd0;
            bus_ack     <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (new_transaction) begin
                bus_ack <= 1'b1;

                // -------------------------------------------
                // Write operations
                // -------------------------------------------
                if (bus_we) begin
                    case (reg_sel)
                        3'h0: begin  // THR / DLL
                            if (dlab) begin
                                divisor[7:0] <= wr_byte;
                            end else if (!tx_full) begin
                                tx_fifo[tx_wr_ptr[$clog2(FIFO_DEPTH)-1:0]] <= wr_byte;
                                tx_wr_ptr <= tx_wr_ptr + 5'd1;
                                tx_count  <= tx_count + 5'd1;
                                // Simulation output
                                $write("%c", wr_byte);
                                $fwrite(uart_fd, "%c", wr_byte);
                                $fflush(uart_fd);
                                // Suppress per-char debug after first 10 chars
                                if (uart_char_count < 10)
                                    $display("[UART] char#%0d: 0x%02x ('%c')",
                                             uart_char_count, wr_byte, wr_byte);
                                uart_char_count <= uart_char_count + 1;
                            end
                        end
                        3'h1: begin  // IER / DLH
                            if (dlab)
                                divisor[15:8] <= wr_byte;
                            else
                                ier <= wr_byte;
                        end
                        3'h2: begin  // FCR (write-only)
                            fifo_enable <= wr_byte[0];
                            if (wr_byte[1]) begin  // Reset RX FIFO
                                rx_wr_ptr <= 5'd0;
                                rx_rd_ptr <= 5'd0;
                                rx_count  <= 5'd0;
                            end
                            if (wr_byte[2]) begin  // Reset TX FIFO
                                tx_wr_ptr <= 5'd0;
                                tx_rd_ptr <= 5'd0;
                                tx_count  <= 5'd0;
                            end
                        end
                        3'h3: lcr <= wr_byte;
                        3'h4: mcr <= wr_byte;
                        // 3'h5: LSR is read-only
                        // 3'h6: MSR is read-only
                        3'h7: scr <= wr_byte;
                        default: ;
                    endcase
                end

                // -------------------------------------------
                // Read operations
                // Little-endian: place byte in bus_rdata[7:0]
                // -------------------------------------------
                begin
                    reg [7:0] rd_byte;
                    case (reg_sel)
                        3'h0: begin  // RBR / DLL
                            if (dlab) begin
                                rd_byte = divisor[7:0];
                            end else begin
                                rd_byte = rx_fifo[rx_rd_ptr[$clog2(FIFO_DEPTH)-1:0]];
                                // Pop RX FIFO on read (only if not a write)
                                if (rx_data_ready && !bus_we) begin
                                    rx_rd_ptr <= rx_rd_ptr + 5'd1;
                                    rx_count  <= rx_count - 5'd1;
                                end
                            end
                        end
                        3'h1: rd_byte = dlab ? divisor[15:8] : ier;
                        3'h2: rd_byte = iir;
                        3'h3: rd_byte = lcr;
                        3'h4: rd_byte = mcr;
                        3'h5: begin
                            rd_byte = lsr;
                            // Clear overrun error on LSR read
                            if (!bus_we)
                                overrun_err <= 1'b0;
                        end
                        3'h6: rd_byte = 8'hB0;  // MSR: CTS, DSR, DCD asserted
                        3'h7: rd_byte = scr;
                    endcase
                    // Little-endian: data byte in lowest lane
                    bus_rdata <= {56'd0, rd_byte};
                end
            end
        end
    end

endmodule
