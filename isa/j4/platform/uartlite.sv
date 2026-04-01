// Xilinx UARTLite Compatible UART
// Compatible with Linux xlnx,xps-uartlite-1.00.a driver
//
// Register Map:
//   0x00 - RX FIFO (R) - Read data from receive FIFO
//          Also accepts TX writes for earlycon compatibility
//   0x04 - TX FIFO (W) - Write data to transmit FIFO
//   0x08 - STAT (R) - Status register
//          bit 0: RX_FIFO_VALID - RX FIFO has data
//          bit 1: RX_FIFO_FULL  - RX FIFO is full
//          bit 2: TX_FIFO_EMPTY - TX FIFO is empty
//          bit 3: TX_FIFO_FULL  - TX FIFO is full
//          bit 4: INTR_ENABLED
//          bit 5: OVERRUN_ERR
//          bit 6: FRAME_ERR
//          bit 7: PARITY_ERR
//   0x0C - CTRL (W) - Control register
//          bit 0: RST_TX_FIFO - Reset TX FIFO
//          bit 1: RST_RX_FIFO - Reset RX FIFO
//          bit 4: ENABLE_INTR - Enable interrupts
//
// For simulation, we use direct $write for TX output and provide
// a simple interface for character injection to RX.

module uartlite #(
    parameter BASE_ADDR = 32'hABCD0100,
    parameter FIFO_DEPTH = 16
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

    // UART interrupt
    output logic        uart_irq,

    // Simulation interface for RX injection
    input  logic [7:0]  sim_rx_data,
    input  logic        sim_rx_valid,
    output logic        sim_rx_ready
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

    // Control
    logic intr_enable;
    logic overrun_err;

    // File handle for UART output
    integer uart_fd;
    initial begin
        uart_fd = $fopen("uart_output.txt", "w");
    end
    final begin
        if (uart_fd) $fclose(uart_fd);
    end

    // Address decode
    wire addr_match = (bus_addr >= BASE_ADDR) && (bus_addr < BASE_ADDR + 16);
    wire [3:0] reg_offset = bus_addr[3:0];

    // Status register
    wire [31:0] status = {24'd0,
                          1'b0,        // bit 7: parity err
                          1'b0,        // bit 6: frame err
                          overrun_err, // bit 5: overrun err
                          intr_enable, // bit 4: intr enabled
                          tx_full,     // bit 3: TX FIFO full
                          tx_empty,    // bit 2: TX FIFO empty
                          rx_full,     // bit 1: RX FIFO full
                          rx_valid};   // bit 0: RX FIFO valid

    // RX ready for simulation injection
    assign sim_rx_ready = !rx_full;

    // Interrupt: trigger when RX has data or TX is empty (and interrupts enabled)
    assign uart_irq = intr_enable && (rx_valid || tx_empty);

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

    // Register read/write
    always_ff @(posedge clk) begin
        if (reset) begin
            intr_enable <= 1'b0;
            bus_rdata <= 32'd0;
            bus_ack <= 1'b0;
        end else begin
            bus_ack <= 1'b0;

            if (addr_match && (bus_we || bus_re)) begin
                bus_ack <= 1'b1;

                if (bus_we) begin
                    case (reg_offset)
                        4'h0, 4'h4: begin  // TX FIFO write (0x00 for earlycon, 0x04 standard)
                            if (!tx_full) begin
                                tx_fifo[tx_wr_ptr[3:0]] <= bus_wdata[7:0];
                                tx_wr_ptr <= tx_wr_ptr + 1;
                                tx_count <= tx_count + 1;
                                $fwrite(uart_fd, "%c", bus_wdata[7:0]);
                                $fflush(uart_fd);
                            end
                        end
                        4'hC: begin  // CTRL
                            if (bus_wdata[0]) begin  // RST_TX_FIFO
                                tx_wr_ptr <= 0;
                                tx_rd_ptr <= 0;
                                tx_count <= 0;
                            end
                            if (bus_wdata[1]) begin  // RST_RX_FIFO
                                rx_wr_ptr <= 0;
                                rx_rd_ptr <= 0;
                                rx_count <= 0;
                                overrun_err <= 0;
                            end
                            intr_enable <= bus_wdata[4];
                        end
                        default: ;
                    endcase
                end

                if (bus_re) begin
                    case (reg_offset)
                        4'h0: begin  // RX FIFO read
                            bus_rdata <= {24'd0, rx_fifo[rx_rd_ptr[3:0]]};
                            if (rx_valid) begin
                                rx_rd_ptr <= rx_rd_ptr + 1;
                                rx_count <= rx_count - 1;
                            end
                        end
                        4'h8: bus_rdata <= status;  // STAT
                        default: bus_rdata <= 32'd0;
                    endcase
                end
            end
        end
    end

endmodule
