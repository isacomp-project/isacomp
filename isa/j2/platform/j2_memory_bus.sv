// J2 Memory Bus Arbiter and Address Decoder
// Routes memory requests between main memory and peripherals based on address
//
// Memory Map (matching j2_isacomp.dts):
//   0x00000000 - 0x03EFFFFF: Main RAM (63MB)
//   0x03F00000 - 0x03FFFFFF: SOC Peripherals (1MB)
//     0x03F00100: UARTLite
//     0x03F00200: AIC + PIT
//
// This module consolidates the many individual memory ports from the J2 core
// into a unified bus interface with address-based routing.

module j2_memory_bus #(
    parameter MEMORY_BASE = 32'h00000000,
    parameter MEMORY_SIZE = 32'h03F00000,  // 63MB
    parameter PERIPH_BASE = 32'h03F00000,
    parameter PERIPH_SIZE = 32'h00100000   // 1MB
) (
    input  logic        clk,
    input  logic        reset,

    // =========================================================================
    // Memory Read Interface (from J2 core - multiple ports consolidated)
    // =========================================================================
    // Instruction fetch port (highest priority)
    input  logic [31:0] ifetch_addr,
    input  logic        ifetch_valid,
    output logic [31:0] ifetch_data,

    // Data read port (from load instructions)
    input  logic [31:0] dread_addr,
    input  logic        dread_valid,
    output logic [31:0] dread_data,

    // =========================================================================
    // Memory Write Interface (from J2 core)
    // =========================================================================
    input  logic [31:0] write_addr,
    input  logic [31:0] write_data,
    input  logic [3:0]  write_be,      // Byte enables
    input  logic        write_valid,

    // =========================================================================
    // Main Memory Interface (to external memory controller)
    // =========================================================================
    output logic [31:0] mem_read_addr,
    output logic        mem_read_valid,
    input  logic [31:0] mem_read_data,

    output logic [31:0] mem_write_addr,
    output logic [31:0] mem_write_data,
    output logic [3:0]  mem_write_be,
    output logic        mem_write_valid,

    // =========================================================================
    // Peripheral Bus Interface (directly connected to peripherals)
    // =========================================================================
    output logic [31:0] periph_addr,
    output logic [31:0] periph_wdata,
    output logic        periph_we,
    output logic        periph_re,
    input  logic [31:0] periph_rdata,
    input  logic        periph_ack
);

    // Address decode functions
    function automatic logic is_peripheral_addr(input logic [31:0] addr);
        return (addr >= PERIPH_BASE) && (addr < PERIPH_BASE + PERIPH_SIZE);
    endfunction

    function automatic logic is_memory_addr(input logic [31:0] addr);
        return (addr >= MEMORY_BASE) && (addr < MEMORY_BASE + MEMORY_SIZE);
    endfunction

    // =========================================================================
    // Read Path - Route to memory or peripherals
    // =========================================================================
    // Instruction fetch always goes to memory (no peripheral execute)
    // Data reads are routed based on address

    // Instruction fetch is direct to memory
    assign mem_read_addr = ifetch_valid ? ifetch_addr : dread_addr;
    assign mem_read_valid = ifetch_valid || (dread_valid && is_memory_addr(dread_addr));

    // Instruction fetch data directly from memory
    assign ifetch_data = mem_read_data;

    // Data read: mux between memory and peripheral
    logic dread_is_periph;
    assign dread_is_periph = is_peripheral_addr(dread_addr);

    // Register peripheral read data for one cycle (matching memory latency)
    logic [31:0] periph_rdata_reg;
    always_ff @(posedge clk) begin
        if (reset) begin
            periph_rdata_reg <= 32'd0;
        end else if (periph_ack) begin
            periph_rdata_reg <= periph_rdata;
        end
    end

    assign dread_data = dread_is_periph ? periph_rdata_reg : mem_read_data;

    // =========================================================================
    // Write Path - Route to memory or peripherals
    // =========================================================================
    logic write_is_periph;
    assign write_is_periph = is_peripheral_addr(write_addr);

    // Memory write (when address is in memory range)
    assign mem_write_addr = write_addr;
    assign mem_write_data = write_data;
    assign mem_write_be = write_be;
    assign mem_write_valid = write_valid && is_memory_addr(write_addr);

    // Peripheral write (when address is in peripheral range)
    assign periph_addr = dread_valid && dread_is_periph ? dread_addr : write_addr;
    assign periph_wdata = write_data;
    assign periph_we = write_valid && write_is_periph;
    assign periph_re = dread_valid && dread_is_periph;

endmodule


// ============================================================================
// J2 Memory Port Consolidator
// ============================================================================
// Consolidates the many individual memory ports from the externalized J2 core
// into a simpler instruction fetch + data access interface.
//
// The J2 core generates separate ports for each unique memory access pattern
// (e.g., umem_pc, umem_load_addr, umem_Rm, etc.). This module:
// 1. Combines all data read ports into a single data read interface
// 2. Keeps instruction fetch (umem_pc) as a separate high-priority port
// 3. Fans out the response data to all requesting ports

module j2_port_consolidator (
    // =========================================================================
    // Instruction Fetch Port (from J2 core)
    // =========================================================================
    input  logic [31:0] umem_pc_read_req_addr,
    input  logic        umem_pc_read_req_valid,
    output logic [31:0] umem_pc_read_resp_data,

    // =========================================================================
    // Data Read Ports (from J2 core - common ones)
    // =========================================================================
    input  logic [31:0] umem_load_addr_read_req_addr,
    input  logic        umem_load_addr_read_req_valid,
    output logic [31:0] umem_load_addr_read_resp_data,

    input  logic [31:0] umem_Rm_read_req_addr,
    input  logic        umem_Rm_read_req_valid,
    output logic [31:0] umem_Rm_read_resp_data,

    input  logic [31:0] umem_addr_m_read_req_addr,
    input  logic        umem_addr_m_read_req_valid,
    output logic [31:0] umem_addr_m_read_resp_data,

    input  logic [31:0] umem_addr_n_read_req_addr,
    input  logic        umem_addr_n_read_req_valid,
    output logic [31:0] umem_addr_n_read_resp_data,

    // Post-increment/pre-decrement loads
    input  logic [31:0] umem_movl_postinc_addr_read_req_addr,
    input  logic        umem_movl_postinc_addr_read_req_valid,
    output logic [31:0] umem_movl_postinc_addr_read_resp_data,

    input  logic [31:0] umem_movw_postinc_addr_read_req_addr,
    input  logic        umem_movw_postinc_addr_read_req_valid,
    output logic [31:0] umem_movw_postinc_addr_read_resp_data,

    // PC-relative loads
    input  logic [31:0] umem_movl_pcrel_addr_read_req_addr,
    input  logic        umem_movl_pcrel_addr_read_req_valid,
    output logic [31:0] umem_movl_pcrel_addr_read_resp_data,

    input  logic [31:0] umem_movw_pcrel_addr_read_req_addr,
    input  logic        umem_movw_pcrel_addr_read_req_valid,
    output logic [31:0] umem_movw_pcrel_addr_read_resp_data,

    // Displacement loads
    input  logic [31:0] umem_movl_disp_load_addr_read_req_addr,
    input  logic        umem_movl_disp_load_addr_read_req_valid,
    output logic [31:0] umem_movl_disp_load_addr_read_resp_data,

    input  logic [31:0] umem_movw_disp_load_addr_read_req_addr,
    input  logic        umem_movw_disp_load_addr_read_req_valid,
    output logic [31:0] umem_movw_disp_load_addr_read_resp_data,

    input  logic [31:0] umem_movb_disp_load_addr_read_req_addr,
    input  logic        umem_movb_disp_load_addr_read_req_valid,
    output logic [31:0] umem_movb_disp_load_addr_read_resp_data,

    // GBR-relative loads
    input  logic [31:0] umem_movl_gbr_load_addr_read_req_addr,
    input  logic        umem_movl_gbr_load_addr_read_req_valid,
    output logic [31:0] umem_movl_gbr_load_addr_read_resp_data,

    input  logic [31:0] umem_movw_gbr_load_addr_read_req_addr,
    input  logic        umem_movw_gbr_load_addr_read_req_valid,
    output logic [31:0] umem_movw_gbr_load_addr_read_resp_data,

    input  logic [31:0] umem_movb_gbr_load_addr_read_req_addr,
    input  logic        umem_movb_gbr_load_addr_read_req_valid,
    output logic [31:0] umem_movb_gbr_load_addr_read_resp_data,

    // Indexed loads
    input  logic [31:0] umem_movb_indexed_load_addr_read_req_addr,
    input  logic        umem_movb_indexed_load_addr_read_req_valid,
    output logic [31:0] umem_movb_indexed_load_addr_read_resp_data,

    // Stack operations (RTE)
    input  logic [31:0] umem_rte_stack_ptr_read_req_addr,
    input  logic        umem_rte_stack_ptr_read_req_valid,
    output logic [31:0] umem_rte_stack_ptr_read_resp_data,

    input  logic [31:0] umem_rte_stack_ptr_add_4_read_req_addr,
    input  logic        umem_rte_stack_ptr_add_4_read_req_valid,
    output logic [31:0] umem_rte_stack_ptr_add_4_read_resp_data,

    // Exception vector fetch
    input  logic [31:0] umem_vbr_add_22_b0_exc_vector_2_b0_read_req_addr,
    input  logic        umem_vbr_add_22_b0_exc_vector_2_b0_read_req_valid,
    output logic [31:0] umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_data,

    // System register loads
    input  logic [31:0] umem_ldsl_pr_addr_read_req_addr,
    input  logic        umem_ldsl_pr_addr_read_req_valid,
    output logic [31:0] umem_ldsl_pr_addr_read_resp_data,

    input  logic [31:0] umem_ldsl_macl_addr_read_req_addr,
    input  logic        umem_ldsl_macl_addr_read_req_valid,
    output logic [31:0] umem_ldsl_macl_addr_read_resp_data,

    input  logic [31:0] umem_ldsl_mach_addr_read_req_addr,
    input  logic        umem_ldsl_mach_addr_read_req_valid,
    output logic [31:0] umem_ldsl_mach_addr_read_resp_data,

    input  logic [31:0] umem_ldcl_gbr_addr_read_req_addr,
    input  logic        umem_ldcl_gbr_addr_read_req_valid,
    output logic [31:0] umem_ldcl_gbr_addr_read_resp_data,

    input  logic [31:0] umem_ldcl_sr_addr_read_req_addr,
    input  logic        umem_ldcl_sr_addr_read_req_valid,
    output logic [31:0] umem_ldcl_sr_addr_read_resp_data,

    // Atomic operations
    input  logic [31:0] umem_casl_addr_read_req_addr,
    input  logic        umem_casl_addr_read_req_valid,
    output logic [31:0] umem_casl_addr_read_resp_data,

    input  logic [31:0] umem_tasb_addr_read_req_addr,
    input  logic        umem_tasb_addr_read_req_valid,
    output logic [31:0] umem_tasb_addr_read_resp_data,

    // GBR byte operations
    input  logic [31:0] umem_andb_gbr_addr_read_req_addr,
    input  logic        umem_andb_gbr_addr_read_req_valid,
    output logic [31:0] umem_andb_gbr_addr_read_resp_data,

    input  logic [31:0] umem_orb_gbr_addr_read_req_addr,
    input  logic        umem_orb_gbr_addr_read_req_valid,
    output logic [31:0] umem_orb_gbr_addr_read_resp_data,

    input  logic [31:0] umem_xorb_gbr_addr_read_req_addr,
    input  logic        umem_xorb_gbr_addr_read_req_valid,
    output logic [31:0] umem_xorb_gbr_addr_read_resp_data,

    input  logic [31:0] umem_tstb_gbr_addr_read_req_addr,
    input  logic        umem_tstb_gbr_addr_read_req_valid,
    output logic [31:0] umem_tstb_gbr_addr_read_resp_data,

    // =========================================================================
    // Write Port (from J2 core)
    // =========================================================================
    input  logic [31:0] umem_write_req_addr,
    input  logic [31:0] umem_write_req_data,
    input  logic [3:0]  umem_write_req_we,
    input  logic        umem_write_req_valid,

    // =========================================================================
    // Consolidated Bus Interface (to memory bus)
    // =========================================================================
    output logic [31:0] ifetch_addr,
    output logic        ifetch_valid,
    input  logic [31:0] ifetch_data,

    output logic [31:0] dread_addr,
    output logic        dread_valid,
    input  logic [31:0] dread_data,

    output logic [31:0] write_addr,
    output logic [31:0] write_data,
    output logic [3:0]  write_be,
    output logic        write_valid
);

    // =========================================================================
    // Instruction Fetch Path (direct passthrough)
    // =========================================================================
    assign ifetch_addr = umem_pc_read_req_addr;
    assign ifetch_valid = umem_pc_read_req_valid;
    assign umem_pc_read_resp_data = ifetch_data;

    // =========================================================================
    // Data Read Path - Priority mux of all data read ports
    // =========================================================================
    // OR together all data read valid signals
    wire any_data_read = umem_load_addr_read_req_valid |
                         umem_Rm_read_req_valid |
                         umem_addr_m_read_req_valid |
                         umem_addr_n_read_req_valid |
                         umem_movl_postinc_addr_read_req_valid |
                         umem_movw_postinc_addr_read_req_valid |
                         umem_movl_pcrel_addr_read_req_valid |
                         umem_movw_pcrel_addr_read_req_valid |
                         umem_movl_disp_load_addr_read_req_valid |
                         umem_movw_disp_load_addr_read_req_valid |
                         umem_movb_disp_load_addr_read_req_valid |
                         umem_movl_gbr_load_addr_read_req_valid |
                         umem_movw_gbr_load_addr_read_req_valid |
                         umem_movb_gbr_load_addr_read_req_valid |
                         umem_movb_indexed_load_addr_read_req_valid |
                         umem_rte_stack_ptr_read_req_valid |
                         umem_rte_stack_ptr_add_4_read_req_valid |
                         umem_vbr_add_22_b0_exc_vector_2_b0_read_req_valid |
                         umem_ldsl_pr_addr_read_req_valid |
                         umem_ldsl_macl_addr_read_req_valid |
                         umem_ldsl_mach_addr_read_req_valid |
                         umem_ldcl_gbr_addr_read_req_valid |
                         umem_ldcl_sr_addr_read_req_valid |
                         umem_casl_addr_read_req_valid |
                         umem_tasb_addr_read_req_valid |
                         umem_andb_gbr_addr_read_req_valid |
                         umem_orb_gbr_addr_read_req_valid |
                         umem_xorb_gbr_addr_read_req_valid |
                         umem_tstb_gbr_addr_read_req_valid;

    assign dread_valid = any_data_read;

    // Priority mux for data read address (in practice, only one will be active)
    always_comb begin
        dread_addr = 32'd0;
        if (umem_load_addr_read_req_valid)
            dread_addr = umem_load_addr_read_req_addr;
        else if (umem_Rm_read_req_valid)
            dread_addr = umem_Rm_read_req_addr;
        else if (umem_addr_m_read_req_valid)
            dread_addr = umem_addr_m_read_req_addr;
        else if (umem_addr_n_read_req_valid)
            dread_addr = umem_addr_n_read_req_addr;
        else if (umem_movl_postinc_addr_read_req_valid)
            dread_addr = umem_movl_postinc_addr_read_req_addr;
        else if (umem_movw_postinc_addr_read_req_valid)
            dread_addr = umem_movw_postinc_addr_read_req_addr;
        else if (umem_movl_pcrel_addr_read_req_valid)
            dread_addr = umem_movl_pcrel_addr_read_req_addr;
        else if (umem_movw_pcrel_addr_read_req_valid)
            dread_addr = umem_movw_pcrel_addr_read_req_addr;
        else if (umem_movl_disp_load_addr_read_req_valid)
            dread_addr = umem_movl_disp_load_addr_read_req_addr;
        else if (umem_movw_disp_load_addr_read_req_valid)
            dread_addr = umem_movw_disp_load_addr_read_req_addr;
        else if (umem_movb_disp_load_addr_read_req_valid)
            dread_addr = umem_movb_disp_load_addr_read_req_addr;
        else if (umem_movl_gbr_load_addr_read_req_valid)
            dread_addr = umem_movl_gbr_load_addr_read_req_addr;
        else if (umem_movw_gbr_load_addr_read_req_valid)
            dread_addr = umem_movw_gbr_load_addr_read_req_addr;
        else if (umem_movb_gbr_load_addr_read_req_valid)
            dread_addr = umem_movb_gbr_load_addr_read_req_addr;
        else if (umem_movb_indexed_load_addr_read_req_valid)
            dread_addr = umem_movb_indexed_load_addr_read_req_addr;
        else if (umem_rte_stack_ptr_read_req_valid)
            dread_addr = umem_rte_stack_ptr_read_req_addr;
        else if (umem_rte_stack_ptr_add_4_read_req_valid)
            dread_addr = umem_rte_stack_ptr_add_4_read_req_addr;
        else if (umem_vbr_add_22_b0_exc_vector_2_b0_read_req_valid)
            dread_addr = umem_vbr_add_22_b0_exc_vector_2_b0_read_req_addr;
        else if (umem_ldsl_pr_addr_read_req_valid)
            dread_addr = umem_ldsl_pr_addr_read_req_addr;
        else if (umem_ldsl_macl_addr_read_req_valid)
            dread_addr = umem_ldsl_macl_addr_read_req_addr;
        else if (umem_ldsl_mach_addr_read_req_valid)
            dread_addr = umem_ldsl_mach_addr_read_req_addr;
        else if (umem_ldcl_gbr_addr_read_req_valid)
            dread_addr = umem_ldcl_gbr_addr_read_req_addr;
        else if (umem_ldcl_sr_addr_read_req_valid)
            dread_addr = umem_ldcl_sr_addr_read_req_addr;
        else if (umem_casl_addr_read_req_valid)
            dread_addr = umem_casl_addr_read_req_addr;
        else if (umem_tasb_addr_read_req_valid)
            dread_addr = umem_tasb_addr_read_req_addr;
        else if (umem_andb_gbr_addr_read_req_valid)
            dread_addr = umem_andb_gbr_addr_read_req_addr;
        else if (umem_orb_gbr_addr_read_req_valid)
            dread_addr = umem_orb_gbr_addr_read_req_addr;
        else if (umem_xorb_gbr_addr_read_req_valid)
            dread_addr = umem_xorb_gbr_addr_read_req_addr;
        else if (umem_tstb_gbr_addr_read_req_valid)
            dread_addr = umem_tstb_gbr_addr_read_req_addr;
    end

    // Fan out read data to all ports
    assign umem_load_addr_read_resp_data = dread_data;
    assign umem_Rm_read_resp_data = dread_data;
    assign umem_addr_m_read_resp_data = dread_data;
    assign umem_addr_n_read_resp_data = dread_data;
    assign umem_movl_postinc_addr_read_resp_data = dread_data;
    assign umem_movw_postinc_addr_read_resp_data = dread_data;
    assign umem_movl_pcrel_addr_read_resp_data = dread_data;
    assign umem_movw_pcrel_addr_read_resp_data = dread_data;
    assign umem_movl_disp_load_addr_read_resp_data = dread_data;
    assign umem_movw_disp_load_addr_read_resp_data = dread_data;
    assign umem_movb_disp_load_addr_read_resp_data = dread_data;
    assign umem_movl_gbr_load_addr_read_resp_data = dread_data;
    assign umem_movw_gbr_load_addr_read_resp_data = dread_data;
    assign umem_movb_gbr_load_addr_read_resp_data = dread_data;
    assign umem_movb_indexed_load_addr_read_resp_data = dread_data;
    assign umem_rte_stack_ptr_read_resp_data = dread_data;
    assign umem_rte_stack_ptr_add_4_read_resp_data = dread_data;
    assign umem_vbr_add_22_b0_exc_vector_2_b0_read_resp_data = dread_data;
    assign umem_ldsl_pr_addr_read_resp_data = dread_data;
    assign umem_ldsl_macl_addr_read_resp_data = dread_data;
    assign umem_ldsl_mach_addr_read_resp_data = dread_data;
    assign umem_ldcl_gbr_addr_read_resp_data = dread_data;
    assign umem_ldcl_sr_addr_read_resp_data = dread_data;
    assign umem_casl_addr_read_resp_data = dread_data;
    assign umem_tasb_addr_read_resp_data = dread_data;
    assign umem_andb_gbr_addr_read_resp_data = dread_data;
    assign umem_orb_gbr_addr_read_resp_data = dread_data;
    assign umem_xorb_gbr_addr_read_resp_data = dread_data;
    assign umem_tstb_gbr_addr_read_resp_data = dread_data;

    // =========================================================================
    // Write Path (direct passthrough)
    // =========================================================================
    assign write_addr = umem_write_req_addr;
    assign write_data = umem_write_req_data;
    assign write_be = umem_write_req_we;
    assign write_valid = umem_write_req_valid;

endmodule
