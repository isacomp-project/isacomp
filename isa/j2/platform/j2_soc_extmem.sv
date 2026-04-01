// J2 SoC with Externalized Memory Bus
// ====================================
// This module wraps the J2 core with externalized memory and provides:
// 1. Memory bus consolidation (many read ports -> single bus)
// 2. Address decoding (memory vs peripheral routing)
// 3. Peripheral integration (AIC, PIT, UART via standard bus interface)
//
// Memory Map (matching j2_isacomp.dts):
//   0x00000000 - 0x03EFFFFF: Main RAM (63MB)
//   0x03F00000 - 0x03FFFFFF: SOC Peripherals (1MB)
//     0x03F00100: UARTLite (16 bytes)
//     0x03F00200: AIC + PIT (48 bytes)
//
// This replaces the memory mirroring approach in the original testbench
// with a proper SoC bus architecture using the valid-ready protocol.

module j2_soc_extmem #(
    parameter MEMORY_SIZE   = 32'h03F00000,  // 63MB
    parameter MEMORY_BASE   = 32'h00000000,
    parameter PERIPH_BASE   = 32'h03F00000,
    parameter PERIPH_SIZE   = 32'h00100000,  // 1MB
    parameter UART_OFFSET   = 32'h00000100,
    parameter AIC_OFFSET    = 32'h00000200
) (
    input  logic        clk,
    input  logic        reset,

    // =========================================================================
    // External Memory Interface (to memory controller/testbench)
    // Consolidated single-port interface for main memory
    // =========================================================================
    // Instruction fetch (always to memory)
    output logic [31:0] mem_ifetch_addr,
    output logic        mem_ifetch_valid,
    input  logic [31:0] mem_ifetch_data,
    input  logic        mem_ifetch_ready,

    // Data access (routed to memory or peripheral)
    output logic [31:0] mem_data_addr,
    output logic        mem_data_read_valid,
    input  logic [31:0] mem_data_read_data,
    input  logic        mem_data_read_ready,

    output logic [31:0] mem_data_write_addr,
    output logic [31:0] mem_data_write_data,
    output logic [3:0]  mem_data_write_be,
    output logic        mem_data_write_valid,
    input  logic        mem_data_write_ready,

    // =========================================================================
    // Interrupt Interface
    // =========================================================================
    output logic        irq_out,           // IRQ to external handler (optional)
    input  logic [3:0]  ext_irq_priority,  // External IRQ priority (0 = no IRQ)

    // =========================================================================
    // UART Interface (directly exposed for external connection)
    // =========================================================================
    output logic [7:0]  uart_tx_data,
    output logic        uart_tx_valid,
    input  logic        uart_tx_ready,
    input  logic [7:0]  uart_rx_data,
    input  logic        uart_rx_valid,
    output logic        uart_rx_ready,

    // =========================================================================
    // Timer Tick Output (optional, for external timing)
    // =========================================================================
    output logic        timer_tick
);

    // =========================================================================
    // Address Decode Functions
    // =========================================================================
    function automatic logic is_peripheral_addr(input logic [31:0] addr);
        return (addr >= PERIPH_BASE) && (addr < PERIPH_BASE + PERIPH_SIZE);
    endfunction

    function automatic logic is_memory_addr(input logic [31:0] addr);
        return (addr >= MEMORY_BASE) && (addr < MEMORY_BASE + MEMORY_SIZE);
    endfunction

    function automatic logic is_uart_addr(input logic [31:0] addr);
        logic [31:0] offset;
        offset = addr - PERIPH_BASE;
        return (offset >= UART_OFFSET) && (offset < UART_OFFSET + 32'h10);
    endfunction

    function automatic logic is_aic_pit_addr(input logic [31:0] addr);
        logic [31:0] offset;
        offset = addr - PERIPH_BASE;
        return (offset >= AIC_OFFSET) && (offset < AIC_OFFSET + 32'h30);
    endfunction

    // =========================================================================
    // J2 Core Signals
    // =========================================================================
    // Reset values
    logic [31:0] reset_pc = 32'h00002000;  // Kernel entry point
    logic [31:0] reset_vbr = 32'h00000000;
    logic [31:0] reset_sr = 32'h40000000;  // MD=1, privileged mode
    logic [31:0] zero32 = 32'd0;

    // IRQ interface
    logic        irq_i;
    logic [3:0]  irq_priority;
    logic [7:0]  irq_vector;

    // Peripheral bus
    logic [31:0] periph_addr;
    logic [31:0] periph_wdata;
    logic        periph_we;
    logic        periph_re;
    logic [31:0] periph_rdata;
    logic        periph_ack;

    // Consolidated read ports (from J2 core)
    // Instruction fetch is separate (highest priority, always to memory)
    logic [31:0] ifetch_addr;
    logic        ifetch_valid;
    logic [31:0] ifetch_data;
    logic        ifetch_ready;

    // Data access (consolidated from all load ports)
    logic [31:0] dread_addr;
    logic        dread_valid;
    logic [31:0] dread_data;
    logic        dread_ready;

    // Write access
    logic [31:0] write_addr;
    logic [31:0] write_data;
    logic [3:0]  write_be;
    logic        write_valid;
    logic        write_ready;

    // =========================================================================
    // Peripheral Instances
    // =========================================================================

    // AIC - Advanced Interrupt Controller
    logic [111:0] irq_sources;
    logic         aic_irq_out;
    logic [7:0]   aic_irq_vector;
    logic [3:0]   aic_irq_priority;

    logic [31:0]  aic_rdata;
    logic         aic_ack;

    jcore_aic aic (
        .clk(clk),
        .reset(reset),
        .addr(periph_addr[7:0]),
        .wdata(periph_wdata),
        .we(periph_we && is_aic_pit_addr(periph_addr)),
        .rdata(aic_rdata),
        .irq_sources(irq_sources),
        .irq_out(aic_irq_out),
        .irq_vector(aic_irq_vector)
    );

    // PIT - Programmable Interval Timer
    logic         pit_timer_irq;
    logic [31:0]  pit_rdata;
    logic         pit_ack;

    jcore_pit pit (
        .clk(clk),
        .reset(reset),
        .addr(periph_addr[7:0]),
        .wdata(periph_wdata),
        .we(periph_we && is_aic_pit_addr(periph_addr)),
        .rdata(pit_rdata),
        .timer_irq(pit_timer_irq),
        .timer_tick(timer_tick)
    );

    // UART - UARTLite compatible
    logic [31:0]  uart_rdata;
    logic         uart_ack;
    logic         uart_irq;

    uartlite uart (
        .clk(clk),
        .reset(reset),
        .addr(periph_addr[3:0]),
        .wdata(periph_wdata),
        .we(periph_we && is_uart_addr(periph_addr)),
        .re(periph_re && is_uart_addr(periph_addr)),
        .rdata(uart_rdata),
        .tx_data(uart_tx_data),
        .tx_valid(uart_tx_valid),
        .tx_ready(uart_tx_ready),
        .rx_data(uart_rx_data),
        .rx_valid(uart_rx_valid),
        .rx_ready(uart_rx_ready),
        .irq(uart_irq)
    );

    // Connect IRQ sources
    always_comb begin
        irq_sources = 112'd0;
        irq_sources[56] = pit_timer_irq;  // Timer at IRQ 72 (56+16)
        irq_sources[2]  = uart_irq;        // UART at IRQ 18 (2+16)
    end

    // IRQ to CPU
    assign irq_i = aic_irq_out;
    assign irq_vector = aic_irq_vector;
    assign irq_priority = 4'd7;  // Fixed priority for now
    assign irq_out = aic_irq_out;

    // =========================================================================
    // Peripheral Bus Multiplexer
    // =========================================================================
    always_comb begin
        periph_rdata = 32'd0;
        periph_ack = 1'b0;

        if (is_uart_addr(periph_addr)) begin
            periph_rdata = uart_rdata;
            periph_ack = 1'b1;  // UART is single-cycle
        end else if (is_aic_pit_addr(periph_addr)) begin
            // AIC and PIT share the same address space
            // PIT is at offsets 0x00-0x18, AIC at 0x20-0x2F
            if (periph_addr[7:0] >= 8'h20) begin
                periph_rdata = aic_rdata;
            end else begin
                periph_rdata = pit_rdata;
            end
            periph_ack = 1'b1;
        end
    end

    // =========================================================================
    // Data Read Path - Route to memory or peripheral
    // =========================================================================
    logic dread_is_periph;
    logic dread_is_memory;

    assign dread_is_periph = is_peripheral_addr(dread_addr);
    assign dread_is_memory = is_memory_addr(dread_addr);

    // Peripheral read interface
    assign periph_addr = dread_valid && dread_is_periph ? dread_addr :
                         write_valid && is_peripheral_addr(write_addr) ? write_addr : 32'd0;
    assign periph_re = dread_valid && dread_is_periph;

    // Memory read interface (only if not peripheral)
    assign mem_data_addr = dread_addr;
    assign mem_data_read_valid = dread_valid && dread_is_memory;

    // Read data mux
    assign dread_data = dread_is_periph ? periph_rdata : mem_data_read_data;
    assign dread_ready = dread_is_periph ? periph_ack : mem_data_read_ready;

    // =========================================================================
    // Instruction Fetch - Direct to memory
    // =========================================================================
    assign mem_ifetch_addr = ifetch_addr;
    assign mem_ifetch_valid = ifetch_valid;
    assign ifetch_data = mem_ifetch_data;
    assign ifetch_ready = mem_ifetch_ready;

    // =========================================================================
    // Data Write Path - Route to memory or peripheral
    // =========================================================================
    logic write_is_periph;
    logic write_is_memory;

    assign write_is_periph = is_peripheral_addr(write_addr);
    assign write_is_memory = is_memory_addr(write_addr);

    // Peripheral write
    assign periph_wdata = write_data;
    assign periph_we = write_valid && write_is_periph;

    // Memory write
    assign mem_data_write_addr = write_addr;
    assign mem_data_write_data = write_data;
    assign mem_data_write_be = write_be;
    assign mem_data_write_valid = write_valid && write_is_memory;

    // Write ready mux
    assign write_ready = write_is_periph ? 1'b1 : mem_data_write_ready;

    // =========================================================================
    // J2 Core Instance with Port Consolidation
    // =========================================================================
    // The J2 core has many individual memory ports. This instantiation
    // consolidates them into ifetch, dread, and write interfaces.

    // All read ports share the same data response (only one active at a time)
    wire [31:0] shared_read_data = dread_data;
    wire shared_read_ready = dread_ready;

    // Generate the J2 core instantiation with consolidated ports
    // Note: This is a simplified wrapper - full implementation would
    // dynamically generate based on port list from generator

    // For the SoC testbench, we use the simple_tb.sv generated by the
    // generator, but replace the memory model with proper bus routing.
    // The actual J2 core instantiation happens in linux_boot_soc_tb.sv

endmodule


// ============================================================================
// J2 Port Consolidator
// ============================================================================
// This module consolidates the many individual read ports from the J2 core
// into a unified bus interface. Only one read port can be active at a time
// in the single-cycle J2 implementation.

module j2_port_consolidator (
    input  logic clk,
    input  logic reset,

    // =========================================================================
    // Consolidated Bus Interface (to SoC)
    // =========================================================================
    output logic [31:0] ifetch_addr,
    output logic        ifetch_valid,
    input  logic [31:0] ifetch_data,
    input  logic        ifetch_ready,

    output logic [31:0] dread_addr,
    output logic        dread_valid,
    input  logic [31:0] dread_data,
    input  logic        dread_ready,

    output logic [31:0] write_addr,
    output logic [31:0] write_data,
    output logic [3:0]  write_be,
    output logic        write_valid,
    input  logic        write_ready,

    // =========================================================================
    // Individual Memory Ports (from J2 core)
    // These are directly wired from the generated j2_complete_extmem module
    // =========================================================================

    // Instruction fetch (PC)
    input  logic [31:0] umem_pc_read_req_addr,
    input  logic        umem_pc_read_req_valid,
    output logic [31:0] umem_pc_read_resp_data,
    output logic        umem_pc_read_resp_ready,

    // Generic write port
    input  logic [31:0] umem_write_req_addr,
    input  logic [31:0] umem_write_req_data,
    input  logic [3:0]  umem_write_req_we,
    input  logic        umem_write_req_valid,
    output logic        umem_write_resp_ready,

    // Data read ports (active signals, addresses, and responses)
    // Note: In the actual implementation, this would be parameterized
    // or generated. For now, we show the pattern for a subset of ports.

    input  logic [31:0] umem_load_addr_read_req_addr,
    input  logic        umem_load_addr_read_req_valid,
    output logic [31:0] umem_load_addr_read_resp_data,
    output logic        umem_load_addr_read_resp_ready,

    input  logic [31:0] umem_Rm_read_req_addr,
    input  logic        umem_Rm_read_req_valid,
    output logic [31:0] umem_Rm_read_resp_data,
    output logic        umem_Rm_read_resp_ready

    // ... additional ports would follow the same pattern
);

    // =========================================================================
    // Instruction Fetch (Direct Passthrough)
    // =========================================================================
    assign ifetch_addr = umem_pc_read_req_addr;
    assign ifetch_valid = umem_pc_read_req_valid;
    assign umem_pc_read_resp_data = ifetch_data;
    assign umem_pc_read_resp_ready = ifetch_ready;

    // =========================================================================
    // Write Path (Direct Passthrough)
    // =========================================================================
    assign write_addr = umem_write_req_addr;
    assign write_data = umem_write_req_data;
    assign write_be = umem_write_req_we;
    assign write_valid = umem_write_req_valid;
    assign umem_write_resp_ready = write_ready;

    // =========================================================================
    // Data Read Path - Priority Mux
    // =========================================================================
    // Only one data read port is active at a time in single-cycle J2
    wire any_dread = umem_load_addr_read_req_valid |
                     umem_Rm_read_req_valid;

    assign dread_valid = any_dread;

    // Priority mux for address
    always_comb begin
        dread_addr = 32'd0;
        if (umem_load_addr_read_req_valid)
            dread_addr = umem_load_addr_read_req_addr;
        else if (umem_Rm_read_req_valid)
            dread_addr = umem_Rm_read_req_addr;
    end

    // Fan out response to all ports
    assign umem_load_addr_read_resp_data = dread_data;
    assign umem_load_addr_read_resp_ready = dread_ready;

    assign umem_Rm_read_resp_data = dread_data;
    assign umem_Rm_read_resp_ready = dread_ready;

endmodule
