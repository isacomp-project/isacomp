// Auto-generated memory wrapper for umem
// Implements valid-ready handshake protocol for AXI-Lite compatibility
// Use this at SoC level to connect to the CPU's externalized memory ports

module umem_memory #(
    parameter DATA_WIDTH = 64,
    parameter ADDR_WIDTH = 15,
    parameter DEPTH = 32768,
    parameter LATENCY = 1  // Memory read latency in cycles
)(
    input wire clk,
    input wire reset,
    // Read port (valid-ready handshake)
    input wire [ADDR_WIDTH-1:0] read_req_addr,
    input wire read_req_valid,
    output reg [DATA_WIDTH-1:0] read_resp_data,
    output reg read_resp_ready,
    // Write port (valid-ready handshake)
    input wire [ADDR_WIDTH-1:0] write_req_addr,
    input wire [DATA_WIDTH-1:0] write_req_data,
    input wire [7:0] write_req_we,
    input wire write_req_valid,
    output reg write_resp_ready
);

    // Memory array
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // Read pipeline for latency modeling
    reg [LATENCY-1:0] read_pending;
    reg [DATA_WIDTH-1:0] read_data_pipeline [0:LATENCY-1];

    // Memory initialization
    initial begin
        integer i;
        for (i = 0; i < DEPTH; i = i + 1) begin
            mem[i] = 0;
        end
        $readmemh("umem.hex", mem);
    end

    // Read logic with configurable latency
    always @(posedge clk) begin
        if (reset) begin
            read_pending <= 0;
            read_resp_ready <= 0;
        end else begin
            // Shift read pipeline
            read_pending <= {read_pending[LATENCY-2:0], read_req_valid};

            // Combinational read from memory (latency added by pipeline)
            if (read_req_valid) begin
                read_data_pipeline[0] <= mem[read_req_addr >> 2];  // Word-aligned
            end

            // Pipeline the data
            for (integer i = 1; i < LATENCY; i = i + 1) begin
                read_data_pipeline[i] <= read_data_pipeline[i-1];
            end

            // Output when pipeline completes
            read_resp_ready <= read_pending[LATENCY-1];
            read_resp_data <= read_data_pipeline[LATENCY-1];
        end
    end

    // Write logic (single cycle)
    always @(posedge clk) begin
        if (reset) begin
            write_resp_ready <= 0;
        end else begin
            write_resp_ready <= write_req_valid;  // Acknowledge writes immediately
            if (write_req_valid) begin
                // Byte-enable write
                for (integer b = 0; b < DATA_WIDTH/8; b = b + 1) begin
                    if (write_req_we[b]) begin
                        mem[write_req_addr >> 2][b*8 +: 8] <= write_req_data[b*8 +: 8];
                    end
                end
            end
        end
    end

endmodule
