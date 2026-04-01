// OpenPOWER SoC Linux Boot Testbench
// ====================================
// This testbench boots Linux on the OpenPOWER LCS core with:
// 1. 64MB main memory
// 2. 16550 UART for console
// 3. Decrementer timer for Linux tick
// 4. Basic interrupt controller
//
// Memory Map (Microwatt-compatible):
//   0x00000000 - 0x03FFFFFF: Main RAM (64MB)
//   0xC0002000: UART 16550
//   0xC0004000: Interrupt Controller
//   0xC0006000: SoC Info/Syscon
//
// Boot Process:
// 1. Load kernel image at address 0 (or specified address)
// 2. Optionally load DTB
// 3. Start CPU at reset vector
//
// Usage:
//   ./obj_dir/Vlinux_boot_tb +kernel=vmlinux.bin [+dtb=device.dtb] [+debug]

`timescale 1ns/1ps
`default_nettype none

module linux_boot_tb;

    // =========================================================================
    // Parameters
    // =========================================================================
    parameter CLK_PERIOD = 10;  // 100 MHz
    parameter MEMORY_SIZE = 32'h10000000;  // 256MB
    parameter PERIPH_BASE = 64'hC0000000;
    parameter PERIPH_SIZE = 32'h00100000;

    // =========================================================================
    // Clock and Reset
    // =========================================================================
    logic clk = 0;
    logic reset = 1;

    always #(CLK_PERIOD/2) clk = ~clk;

    // =========================================================================
    // Main Memory (256MB, doubleword-addressed for 64-bit PowerPC)
    // =========================================================================
    localparam MEM_WORDS = MEMORY_SIZE / 8;  // 64-bit words
    logic [63:0] main_memory [0:MEM_WORDS-1];

    // =========================================================================
    // Address Decode
    // =========================================================================
    function automatic logic is_peripheral(input logic [63:0] addr);
        return (addr >= PERIPH_BASE) && (addr < PERIPH_BASE + PERIPH_SIZE);
    endfunction

    function automatic logic is_memory(input logic [63:0] addr);
        return (addr < MEMORY_SIZE);
    endfunction

    // =========================================================================
    // Reset Values for OpenPOWER
    // =========================================================================
    // MSR: SF=1 (64-bit mode), HV=0, PR=0 (supervisor), EE=0 (no ext irq)
    wire [63:0] reset_msr = 64'h8000000000000000;  // SF=1
    logic [63:0] reset_pc = 64'h0000000000000000;   // Start at 0 (overridden by load_addr)
    wire [63:0] zero64 = 64'd0;
    // CTR force removed - use hierarchical access (cpu.ctr_rd) instead

    // =========================================================================
    // Peripheral Bus
    // =========================================================================
    logic [63:0] periph_addr;
    logic [63:0] periph_wdata;
    logic [7:0]  periph_we;
    logic        periph_valid;
    logic [63:0] periph_rdata;
    logic        periph_ack;

    // UART
    wire [63:0] uart_rdata;
    wire uart_ack;
    wire uart_irq;

    // Interrupt Controller
    wire [63:0] intc_rdata;
    wire intc_ack;
    wire [31:0] irq_sources;
    wire external_irq;
    wire [5:0] irq_vector;

    // Syscon
    logic [63:0] syscon_rdata;
    logic syscon_ack;

    // Timer/Decrementer
    logic [63:0] timebase;
    logic [63:0] dec_value;
    logic [63:0] dec_write_data;
    logic        dec_write_enable;
    logic        dec_irq;

    assign irq_sources = {30'd0, dec_irq, uart_irq};

    // =========================================================================
    // Address Decode for Peripherals
    // =========================================================================
    function automatic logic is_uart_addr(input logic [63:0] addr);
        return (addr >= 64'hC0002000) && (addr < 64'hC0002020);
    endfunction

    function automatic logic is_intc_addr(input logic [63:0] addr);
        return (addr >= 64'hC0004000) && (addr < 64'hC0004020);
    endfunction

    function automatic logic is_syscon_addr(input logic [63:0] addr);
        return (addr >= 64'hC0006000) && (addr < 64'hC0006010);
    endfunction

    // =========================================================================
    // UART - 16550 Compatible
    // =========================================================================
    uart16550 #(
        .BASE_ADDR(64'hC0002000)
    ) uart (
        .clk(clk),
        .reset(reset),
        .bus_addr(periph_addr),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_valid(periph_valid),
        .bus_rdata(uart_rdata),
        .bus_ack(uart_ack),
        .uart_irq(uart_irq),
        .sim_rx_data(8'd0),
        .sim_rx_valid(1'b0),
        .sim_rx_ready()
    );

    // =========================================================================
    // Interrupt Controller
    // =========================================================================
    power_intc #(
        .BASE_ADDR(64'hC0004000)
    ) intc (
        .clk(clk),
        .reset(reset),
        .bus_addr(periph_addr),
        .bus_wdata(periph_wdata),
        .bus_we(periph_we),
        .bus_valid(periph_valid),
        .bus_rdata(intc_rdata),
        .bus_ack(intc_ack),
        .irq_sources(irq_sources),
        .irq_out(external_irq),
        .irq_vector(irq_vector)
    );

    // =========================================================================
    // Timer - Time Base and Decrementer
    // =========================================================================
    // Detect mtspr DEC from CPU (hierarchical reference to internal signal)
    assign dec_write_enable = cpu.mtspr_dec_enable && !cpu.mem_ext_stall;
    assign dec_write_data = cpu.dec_wr;

    power_timer timer (
        .clk(clk),
        .reset(reset),
        .timebase(timebase),
        .dec_write_data(dec_write_data),
        .dec_write_enable(dec_write_enable),
        .dec_value(dec_value),
        .dec_irq(dec_irq),
        .irq_enable(1'b1)
    );

    // Inject TB and DEC into CPU via hierarchical write
    // The CPU has tb and dec as internal registers; we override them each cycle
    // so that mftb/mfspr_dec read the externally-managed values.
    always @(posedge clk) begin
        if (!reset) begin
            cpu.tb <= timebase;
            cpu.dec <= dec_value;
        end
    end

    // =========================================================================
    // Syscon - SoC Info
    // =========================================================================
    always_ff @(posedge clk) begin
        if (reset) begin
            syscon_rdata <= 64'd0;
            syscon_ack <= 1'b0;
        end else begin
            syscon_ack <= 1'b0;
            if (is_syscon_addr(periph_addr) && periph_valid) begin
                syscon_ack <= 1'b1;
                case (periph_addr[3:0])
                    4'h0: syscon_rdata <= 64'h4F50454E504F5752;  // "OPENPOWR"
                    4'h8: syscon_rdata <= 64'h0000000100000001;  // UART + INTC present
                    default: syscon_rdata <= 64'd0;
                endcase
            end
        end
    end

    // Default peripheral ACK for unmapped addresses in the peripheral range.
    // Without MMU, kernel virtual addresses can truncate to land in peripheral
    // space (0xC0000000-0xC00FFFFF) without matching any real peripheral.
    // Without a default ACK, such accesses stall the CPU forever.
    logic default_periph_ack;
    always_ff @(posedge clk) begin
        if (reset)
            default_periph_ack <= 1'b0;
        else
            default_periph_ack <= periph_valid &&
                                  !is_uart_addr(periph_addr) &&
                                  !is_intc_addr(periph_addr) &&
                                  !is_syscon_addr(periph_addr);
    end

    // Peripheral read mux
    assign periph_rdata = uart_ack ? uart_rdata :
                          intc_ack ? intc_rdata :
                          syscon_ack ? syscon_rdata : 64'd0;
    assign periph_ack = uart_ack | intc_ack | syscon_ack | default_periph_ack;

    // =========================================================================
    // Memory Ports - Instruction Fetch (PC, translated by ISA-level MMU)
    // =========================================================================
    wire [31:0] umem_pc_pa_read_req_addr;
    wire umem_pc_pa_read_req_valid;
    wire [63:0] umem_pc_pa_read_resp_data;
    wire umem_pc_pa_read_resp_ready;

    assign umem_pc_pa_read_resp_data = main_memory[umem_pc_pa_read_req_addr[27:3]];
    assign umem_pc_pa_read_resp_ready = umem_pc_pa_read_req_valid;

    // =========================================================================
    // Memory Ports - Instruction Fetch Next Word (for unaligned instruction spanning)
    // =========================================================================
    wire [31:0] umem_pc_pa_rd_next_read_req_addr;
    wire umem_pc_pa_rd_next_read_req_valid;
    wire [63:0] umem_pc_pa_rd_next_read_resp_data;
    wire umem_pc_pa_rd_next_read_resp_ready;

    assign umem_pc_pa_rd_next_read_resp_data = main_memory[umem_pc_pa_rd_next_read_req_addr[27:3]];
    assign umem_pc_pa_rd_next_read_resp_ready = umem_pc_pa_rd_next_read_req_valid;

    // =========================================================================
    // Memory Ports - Data Read (EA, translated by ISA-level MMU)
    // =========================================================================
    wire [31:0] umem_ea_pa_read_req_addr;
    wire umem_ea_pa_read_req_valid;
    wire [63:0] umem_ea_pa_read_resp_data;
    wire umem_ea_pa_read_resp_ready;

    // =========================================================================
    // Memory Ports - Data Read Next Word (for unaligned data load spanning)
    // =========================================================================
    wire [31:0] umem_ea_pa_rd_next_read_req_addr;
    wire umem_ea_pa_rd_next_read_req_valid;
    wire [63:0] umem_ea_pa_rd_next_read_resp_data;
    wire umem_ea_pa_rd_next_read_resp_ready;

    assign umem_ea_pa_rd_next_read_resp_data = main_memory[umem_ea_pa_rd_next_read_req_addr[27:3]];
    assign umem_ea_pa_rd_next_read_resp_ready = umem_ea_pa_rd_next_read_req_valid;

    // =========================================================================
    // Memory Ports - MMU Page Table Walk (Instruction Fetch)
    // These 6 ports serve the radix page table walk for instruction fetch
    // =========================================================================
    wire [31:0] umem_pate1_addr_read_req_addr;
    wire umem_pate1_addr_read_req_valid;
    wire [31:0] umem_prte0_addr_read_req_addr;
    wire umem_prte0_addr_read_req_valid;
    wire [31:0] umem_pgd_addr_read_req_addr;
    wire umem_pgd_addr_read_req_valid;
    wire [31:0] umem_pud_addr_read_req_addr;
    wire umem_pud_addr_read_req_valid;
    wire [31:0] umem_pmd_addr_read_req_addr;
    wire umem_pmd_addr_read_req_valid;
    wire [31:0] umem_pte_addr_read_req_addr;
    wire umem_pte_addr_read_req_valid;

    // Direct memory read for instruction MMU page table walk ports
    wire umem_pate1_addr_read_resp_ready;
    wire umem_prte0_addr_read_resp_ready;
    wire umem_pgd_addr_read_resp_ready;
    wire umem_pud_addr_read_resp_ready;
    wire umem_pmd_addr_read_resp_ready;
    wire umem_pte_addr_read_resp_ready;
    assign umem_pate1_addr_read_resp_ready = umem_pate1_addr_read_req_valid;
    assign umem_prte0_addr_read_resp_ready = umem_prte0_addr_read_req_valid;
    assign umem_pgd_addr_read_resp_ready = umem_pgd_addr_read_req_valid;
    assign umem_pud_addr_read_resp_ready = umem_pud_addr_read_req_valid;
    assign umem_pmd_addr_read_resp_ready = umem_pmd_addr_read_req_valid;
    assign umem_pte_addr_read_resp_ready = umem_pte_addr_read_req_valid;

    wire [63:0] umem_pate1_addr_read_resp_data = main_memory[umem_pate1_addr_read_req_addr[27:3]];
    wire [63:0] umem_prte0_addr_read_resp_data = main_memory[umem_prte0_addr_read_req_addr[27:3]];
    wire [63:0] umem_pgd_addr_read_resp_data = main_memory[umem_pgd_addr_read_req_addr[27:3]];
    wire [63:0] umem_pud_addr_read_resp_data = main_memory[umem_pud_addr_read_req_addr[27:3]];
    wire [63:0] umem_pmd_addr_read_resp_data = main_memory[umem_pmd_addr_read_req_addr[27:3]];
    wire [63:0] umem_pte_addr_read_resp_data = main_memory[umem_pte_addr_read_req_addr[27:3]];

    // =========================================================================
    // Memory Ports - MMU Page Table Walk (Data Load)
    // =========================================================================
    wire [31:0] umem_ld_pate1_addr_read_req_addr;
    wire umem_ld_pate1_addr_read_req_valid;
    wire [31:0] umem_ld_prte0_addr_read_req_addr;
    wire umem_ld_prte0_addr_read_req_valid;
    wire [31:0] umem_ld_pgd_addr_read_req_addr;
    wire umem_ld_pgd_addr_read_req_valid;
    wire [31:0] umem_ld_pud_addr_read_req_addr;
    wire umem_ld_pud_addr_read_req_valid;
    wire [31:0] umem_ld_pmd_addr_read_req_addr;
    wire umem_ld_pmd_addr_read_req_valid;
    wire [31:0] umem_ld_pte_addr_read_req_addr;
    wire umem_ld_pte_addr_read_req_valid;

    wire umem_ld_pate1_addr_read_resp_ready;
    wire umem_ld_prte0_addr_read_resp_ready;
    wire umem_ld_pgd_addr_read_resp_ready;
    wire umem_ld_pud_addr_read_resp_ready;
    wire umem_ld_pmd_addr_read_resp_ready;
    wire umem_ld_pte_addr_read_resp_ready;
    assign umem_ld_pate1_addr_read_resp_ready = umem_ld_pate1_addr_read_req_valid;
    assign umem_ld_prte0_addr_read_resp_ready = umem_ld_prte0_addr_read_req_valid;
    assign umem_ld_pgd_addr_read_resp_ready = umem_ld_pgd_addr_read_req_valid;
    assign umem_ld_pud_addr_read_resp_ready = umem_ld_pud_addr_read_req_valid;
    assign umem_ld_pmd_addr_read_resp_ready = umem_ld_pmd_addr_read_req_valid;
    assign umem_ld_pte_addr_read_resp_ready = umem_ld_pte_addr_read_req_valid;

    wire [63:0] umem_ld_pate1_addr_read_resp_data = main_memory[umem_ld_pate1_addr_read_req_addr[27:3]];
    wire [63:0] umem_ld_prte0_addr_read_resp_data = main_memory[umem_ld_prte0_addr_read_req_addr[27:3]];
    wire [63:0] umem_ld_pgd_addr_read_resp_data = main_memory[umem_ld_pgd_addr_read_req_addr[27:3]];
    wire [63:0] umem_ld_pud_addr_read_resp_data = main_memory[umem_ld_pud_addr_read_req_addr[27:3]];
    wire [63:0] umem_ld_pmd_addr_read_resp_data = main_memory[umem_ld_pmd_addr_read_req_addr[27:3]];
    wire [63:0] umem_ld_pte_addr_read_resp_data = main_memory[umem_ld_pte_addr_read_req_addr[27:3]];

    // =========================================================================
    // Memory Ports - MMU Page Table Walk (Data Store)
    // =========================================================================
    wire [31:0] umem_st_pate1_addr_read_req_addr;
    wire umem_st_pate1_addr_read_req_valid;
    wire [31:0] umem_st_prte0_addr_read_req_addr;
    wire umem_st_prte0_addr_read_req_valid;
    wire [31:0] umem_st_pgd_addr_read_req_addr;
    wire umem_st_pgd_addr_read_req_valid;
    wire [31:0] umem_st_pud_addr_read_req_addr;
    wire umem_st_pud_addr_read_req_valid;
    wire [31:0] umem_st_pmd_addr_read_req_addr;
    wire umem_st_pmd_addr_read_req_valid;
    wire [31:0] umem_st_pte_addr_read_req_addr;
    wire umem_st_pte_addr_read_req_valid;

    wire umem_st_pate1_addr_read_resp_ready;
    wire umem_st_prte0_addr_read_resp_ready;
    wire umem_st_pgd_addr_read_resp_ready;
    wire umem_st_pud_addr_read_resp_ready;
    wire umem_st_pmd_addr_read_resp_ready;
    wire umem_st_pte_addr_read_resp_ready;
    assign umem_st_pate1_addr_read_resp_ready = umem_st_pate1_addr_read_req_valid;
    assign umem_st_prte0_addr_read_resp_ready = umem_st_prte0_addr_read_req_valid;
    assign umem_st_pgd_addr_read_resp_ready = umem_st_pgd_addr_read_req_valid;
    assign umem_st_pud_addr_read_resp_ready = umem_st_pud_addr_read_req_valid;
    assign umem_st_pmd_addr_read_resp_ready = umem_st_pmd_addr_read_req_valid;
    assign umem_st_pte_addr_read_resp_ready = umem_st_pte_addr_read_req_valid;

    wire [63:0] umem_st_pate1_addr_read_resp_data = main_memory[umem_st_pate1_addr_read_req_addr[27:3]];
    wire [63:0] umem_st_prte0_addr_read_resp_data = main_memory[umem_st_prte0_addr_read_req_addr[27:3]];
    wire [63:0] umem_st_pgd_addr_read_resp_data = main_memory[umem_st_pgd_addr_read_req_addr[27:3]];
    wire [63:0] umem_st_pud_addr_read_resp_data = main_memory[umem_st_pud_addr_read_req_addr[27:3]];
    wire [63:0] umem_st_pmd_addr_read_resp_data = main_memory[umem_st_pmd_addr_read_req_addr[27:3]];
    wire [63:0] umem_st_pte_addr_read_resp_data = main_memory[umem_st_pte_addr_read_req_addr[27:3]];

    // Data read - route to memory or peripheral
    // The CPU now handles unaligned reads internally via the next-word read ports
    // (umem_pc_pa_rd_next and umem_ea_pa_rd_next). The testbench just returns the
    // aligned doubleword for each port - the CPU merges data from two reads when needed.
    wire ea_is_periph = is_peripheral({32'd0, umem_ea_pa_read_req_addr});
    wire ea_is_memory = is_memory({32'd0, umem_ea_pa_read_req_addr});

    assign umem_ea_pa_read_resp_data = ea_is_periph ? periph_rdata :
                                       main_memory[umem_ea_pa_read_req_addr[27:3]];
    assign umem_ea_pa_read_resp_ready = ea_is_periph ? periph_ack : umem_ea_pa_read_req_valid;

    // Route data reads to peripheral bus
    wire write_is_periph = is_peripheral({32'd0, umem_write_req_addr});
    always_comb begin
        periph_addr = 64'd0;
        periph_valid = 1'b0;
        periph_we = 8'd0;
        periph_wdata = 64'd0;

        // Data reads to peripheral
        if (umem_ea_pa_read_req_valid && ea_is_periph) begin
            periph_addr = {32'd0, umem_ea_pa_read_req_addr};
            periph_valid = 1'b1;
        end

        // Data writes to peripheral
        if (umem_write_req_valid && write_is_periph) begin
            periph_addr = {32'd0, umem_write_req_addr};
            periph_valid = 1'b1;
            periph_we = umem_write_req_we;
            periph_wdata = umem_write_req_data;
        end
    end

    // =========================================================================
    // Memory Ports - Data Write
    // =========================================================================
    wire [31:0] umem_write_req_addr;
    wire [63:0] umem_write_req_data;
    wire [7:0]  umem_write_req_we;
    wire umem_write_req_valid;
    wire umem_write_resp_ready;

    wire write_is_memory = is_memory({32'd0, umem_write_req_addr});
    assign umem_write_resp_ready = write_is_periph ? periph_ack : umem_write_req_valid;

    // Text protection: safety net for early boot before page tables are set up.
    // With ISA-level MMU, the CPU outputs physical addresses, so this check
    // applies directly to the physical address output.
    reg text_protection_enabled = 0;
    always_ff @(posedge clk) begin
        // Enable text protection once the kernel's early_setup is entered (0x01004160)
        // or after fast_memcpy completes the kernel copy. This prevents writes to
        // .text and .init.text during the main kernel execution.
        if (!text_protection_enabled && (
            umem_pc_pa_read_req_addr == 32'h01006630 ||   // early_setup
            (fast_memcpy_done && umem_pc_pa_read_req_addr == 32'h01012720)))
            text_protection_enabled <= 1;
    end
    // CPU writes go through unprotected - the kernel legitimately writes to its
    // own text during init (exception vectors, ftrace, alternatives patching).
    // Text protection only applies in the memset accelerator which bypasses the CPU.
    always_ff @(posedge clk) begin
        // Debug traces removed (CA bit bug fixed)
        // Trace writes to process table (0x0E000000-0x0E0000FF)
        if (!reset && umem_write_req_valid && write_is_memory &&
            umem_write_req_addr >= 32'h0E000000 && umem_write_req_addr < 32'h0E000100)
            $display("[%0d] PROCTBL_WRITE: addr=0x%08x data=0x%016x we=0x%02x PC=0x%08x word_idx=0x%06x",
                cycle_count, umem_write_req_addr, umem_write_req_data, umem_write_req_we,
                umem_pc_pa_read_req_addr, umem_write_req_addr[27:3]);
        if (!reset && umem_write_req_valid && write_is_memory) begin
            // dcbz: zero entire 64-byte cache line (8 doublewords)
            // The CPU outputs the cache-line-aligned physical address.
            if (cpu.dcbz_enable) begin
                main_memory[umem_write_req_addr[27:3] + 0] <= 64'h0;
                main_memory[umem_write_req_addr[27:3] + 1] <= 64'h0;
                main_memory[umem_write_req_addr[27:3] + 2] <= 64'h0;
                main_memory[umem_write_req_addr[27:3] + 3] <= 64'h0;
                main_memory[umem_write_req_addr[27:3] + 4] <= 64'h0;
                main_memory[umem_write_req_addr[27:3] + 5] <= 64'h0;
                main_memory[umem_write_req_addr[27:3] + 6] <= 64'h0;
                main_memory[umem_write_req_addr[27:3] + 7] <= 64'h0;
            end else
            // Unaligned doubleword store support:
            // std/stdx require word alignment (addr[1:0]=0) but NOT doubleword
            // alignment, so addr[2:0] can be 4. When we=0xFF and addr[2]=1,
            // the 8-byte store crosses a doubleword boundary: upper 4 data bytes
            // go to the lower 4 bytes of the first doubleword, lower 4 data bytes
            // go to the upper 4 bytes of the next doubleword.
            if (umem_write_req_we == 8'hFF && umem_write_req_addr[2:0] == 3'd4) begin
                // Unaligned std at offset 4: split 8-byte store across two DWs
                // First doubleword: lower 4 bytes get data[63:32]
                main_memory[umem_write_req_addr[27:3]][31:24] <= umem_write_req_data[63:56];
                main_memory[umem_write_req_addr[27:3]][23:16] <= umem_write_req_data[55:48];
                main_memory[umem_write_req_addr[27:3]][15:8]  <= umem_write_req_data[47:40];
                main_memory[umem_write_req_addr[27:3]][7:0]   <= umem_write_req_data[39:32];
                // Second doubleword: upper 4 bytes get data[31:0]
                main_memory[umem_write_req_addr[27:3] + 1][63:56] <= umem_write_req_data[31:24];
                main_memory[umem_write_req_addr[27:3] + 1][55:48] <= umem_write_req_data[23:16];
                main_memory[umem_write_req_addr[27:3] + 1][47:40] <= umem_write_req_data[15:8];
                main_memory[umem_write_req_addr[27:3] + 1][39:32] <= umem_write_req_data[7:0];
            end else if ((cpu.stw_enable | cpu.stwx_enable | cpu.stwu_enable |
                        cpu.stwux_enable | cpu.stwbrx_enable | cpu.stwcx_enable |
                        cpu.stmw_enable) &&
                       umem_write_req_addr[2:0] >= 3'd5) begin
                // Spanning stw at offset 5/6/7: word crosses DW boundary.
                // CPU's byte-enable underflows for these offsets, so handle both
                // the current DW trailing bytes and next DW spilling bytes here.
                // Big-endian: word[31:24]=byte0, word[23:16]=byte1, word[15:8]=byte2, word[7:0]=byte3
                case (umem_write_req_addr[2:0])
                    3'd5: begin
                        // 3 bytes in current DW (5,6,7), 1 byte in next DW (0)
                        main_memory[umem_write_req_addr[27:3]][23:16] <= cpu.stw_word_data[31:24];
                        main_memory[umem_write_req_addr[27:3]][15:8]  <= cpu.stw_word_data[23:16];
                        main_memory[umem_write_req_addr[27:3]][7:0]   <= cpu.stw_word_data[15:8];
                        main_memory[umem_write_req_addr[27:3] + 1][63:56] <= cpu.stw_word_data[7:0];
                    end
                    3'd6: begin
                        // 2 bytes in current DW (6,7), 2 bytes in next DW (0,1)
                        main_memory[umem_write_req_addr[27:3]][15:8]  <= cpu.stw_word_data[31:24];
                        main_memory[umem_write_req_addr[27:3]][7:0]   <= cpu.stw_word_data[23:16];
                        main_memory[umem_write_req_addr[27:3] + 1][63:56] <= cpu.stw_word_data[15:8];
                        main_memory[umem_write_req_addr[27:3] + 1][55:48] <= cpu.stw_word_data[7:0];
                    end
                    3'd7: begin
                        // 1 byte in current DW (7), 3 bytes in next DW (0,1,2)
                        main_memory[umem_write_req_addr[27:3]][7:0]   <= cpu.stw_word_data[31:24];
                        main_memory[umem_write_req_addr[27:3] + 1][63:56] <= cpu.stw_word_data[23:16];
                        main_memory[umem_write_req_addr[27:3] + 1][55:48] <= cpu.stw_word_data[15:8];
                        main_memory[umem_write_req_addr[27:3] + 1][47:40] <= cpu.stw_word_data[7:0];
                    end
                    default: ;
                endcase
            end else if ((cpu.sth_enable | cpu.sthx_enable | cpu.sthu_enable |
                          cpu.sthux_enable | cpu.sthbrx_enable | cpu.sthcx_enable) &&
                         umem_write_req_addr[2:0] == 3'd7) begin
                // Spanning sth at offset 7: halfword crosses DW boundary.
                // 1 byte in current DW (7), 1 byte in next DW (0)
                main_memory[umem_write_req_addr[27:3]][7:0]   <= cpu.sth_half_data[15:8];
                main_memory[umem_write_req_addr[27:3] + 1][63:56] <= cpu.sth_half_data[7:0];
            end else begin
                // Normal byte-enabled write within single doubleword
                // CPU generates correct byte enables and positioned data for
                // all non-spanning offsets (stb 0-7, sth 0-6, stw 0-4, std 0)
                if (umem_write_req_we[0])
                    main_memory[umem_write_req_addr[27:3]][7:0] <= umem_write_req_data[7:0];
                if (umem_write_req_we[1])
                    main_memory[umem_write_req_addr[27:3]][15:8] <= umem_write_req_data[15:8];
                if (umem_write_req_we[2])
                    main_memory[umem_write_req_addr[27:3]][23:16] <= umem_write_req_data[23:16];
                if (umem_write_req_we[3])
                    main_memory[umem_write_req_addr[27:3]][31:24] <= umem_write_req_data[31:24];
                if (umem_write_req_we[4])
                    main_memory[umem_write_req_addr[27:3]][39:32] <= umem_write_req_data[39:32];
                if (umem_write_req_we[5])
                    main_memory[umem_write_req_addr[27:3]][47:40] <= umem_write_req_data[47:40];
                if (umem_write_req_we[6])
                    main_memory[umem_write_req_addr[27:3]][55:48] <= umem_write_req_data[55:48];
                if (umem_write_req_we[7])
                    main_memory[umem_write_req_addr[27:3]][63:56] <= umem_write_req_data[63:56];
            end
        end
    end

    // =========================================================================
    // UART TX Character Display + File Output
    // =========================================================================
    integer uart_log_fd;
    integer uart_write_count = 0;
    initial begin
        uart_log_fd = $fopen("uart_output.log", "w");
        if (uart_log_fd == 0) begin
            $display("WARNING: Could not open uart_output.log for writing");
        end
    end
    always @(posedge clk) begin
        // Detailed trace for ALL writes to UART address range (first 500)
        if (!reset && umem_write_req_valid && umem_write_req_addr >= 32'hC0002000 &&
            umem_write_req_addr < 32'hC0002020) begin
            if (uart_write_count < 500) begin
                $display("[%0d] UART_BUS_WR #%0d: addr=0x%08x reg=%0d data=0x%016x we=0x%02x byte0=0x%02x stall=%b PC=0x%08x",
                    cycle_count, uart_write_count,
                    umem_write_req_addr, umem_write_req_addr[4:2],
                    umem_write_req_data, umem_write_req_we,
                    umem_write_req_data[63:56], cpu.mem_ext_stall,
                    umem_pc_pa_read_req_addr);
            end
            if (!cpu.mem_ext_stall)
                uart_write_count <= uart_write_count + 1;
        end
        // Character capture - use stall-gated capture for correct dedup
        if (!reset && umem_write_req_valid && !cpu.mem_ext_stall &&
            umem_write_req_addr == 32'hC0002000) begin
            $write("%c", umem_write_req_data[63:56]);
            if (uart_log_fd != 0) begin
                $fwrite(uart_log_fd, "%c", umem_write_req_data[63:56]);
                $fflush(uart_log_fd);
            end
        end
    end

    // =========================================================================
    // Cross-DW store diagnostic: detect when stw/sth crosses DW boundary
    // (CPU truncates spilling bytes - data is lost)
    // =========================================================================
    integer crossdw_store_count = 0;
    // (crossdw_fix_trace_count removed - spanning stores now handled directly)
    always @(posedge clk) begin
        if (!reset && umem_write_req_valid && !cpu.mem_ext_stall && write_is_memory) begin
            // stw/stwx/stwu/stwux at byte offset >= 5 crosses DW boundary
            if ((cpu.stw_enable | cpu.stwx_enable | cpu.stwu_enable | cpu.stwux_enable |
                 cpu.stwbrx_enable | cpu.stwcx_enable) && umem_write_req_addr[2:0] >= 3'd5) begin
                if (crossdw_store_count < 100)
                    $display("[%0d] CROSS_DW_STW: addr=0x%08x off=%0d data=0x%016x we=0x%02x PC=0x%08x (bytes lost!)",
                        cycle_count, umem_write_req_addr, umem_write_req_addr[2:0],
                        umem_write_req_data, umem_write_req_we, umem_pc_pa_read_req_addr);
                crossdw_store_count <= crossdw_store_count + 1;
            end
            // sth/sthx/sthu/sthux at byte offset 7 crosses DW boundary
            if ((cpu.sth_enable | cpu.sthx_enable | cpu.sthu_enable | cpu.sthux_enable |
                 cpu.sthbrx_enable | cpu.sthcx_enable) && umem_write_req_addr[2:0] == 3'd7) begin
                if (crossdw_store_count < 100)
                    $display("[%0d] CROSS_DW_STH: addr=0x%08x data=0x%016x we=0x%02x PC=0x%08x (bytes lost!)",
                        cycle_count, umem_write_req_addr,
                        umem_write_req_data, umem_write_req_we, umem_pc_pa_read_req_addr);
                crossdw_store_count <= crossdw_store_count + 1;
            end
        end
    end

    // =========================================================================
    // setup_userns_sysctls crash trace
    // setup_userns_sysctls at 0x6fd40:
    //   0x6fd80: bl kmemdup - r3=src, r4=size(704), r5=gfp(3264)
    //   0x6fd88: mr. r31,r3 - check kmemdup result
    //   0x6fdc4: bl __register_sysctl_table - returns ctl_table_header
    //   0x6fdcc: std r3,408(r30) - store result
    //   0x6fdd0: ld r9,408(r30) - check result
    //   0x6fdfc: return path
    // =========================================================================
    always @(posedge clk) begin
        if (!reset && !cpu.mem_ext_stall) begin
            // kmemdup call - check what it returns
            if (umem_pc_pa_read_req_addr == 32'h0006fd80)
                $display("[%0d] USERNS_KMEMDUP_CALL: r3(src)=0x%016x r4(size)=%0d r5(gfp)=%0d",
                    cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5]);
            // After kmemdup - check result
            if (umem_pc_pa_read_req_addr == 32'h0006fd88)
                $display("[%0d] USERNS_KMEMDUP_RET: r3(result)=0x%016x (NULL=%s)",
                    cycle_count, cpu.rf[3], (cpu.rf[3] == 64'd0) ? "YES" : "no");
            // __register_sysctl_table call
            if (umem_pc_pa_read_req_addr == 32'h0006fdc4)
                $display("[%0d] USERNS_REGSYSCTL_CALL: r3=0x%016x r4=0x%016x r5(table)=0x%016x r6(nentries)=%0d",
                    cycle_count, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[6]);
            // After __register_sysctl_table - check result
            if (umem_pc_pa_read_req_addr == 32'h0006fdcc)
                $display("[%0d] USERNS_REGSYSCTL_RET: r3(header)=0x%016x (NULL=%s)",
                    cycle_count, cpu.rf[3], (cpu.rf[3] == 64'd0) ? "YES" : "no");
            // Check the loaded value at the decision point
            if (umem_pc_pa_read_req_addr == 32'h0006fdd8)
                $display("[%0d] USERNS_CHECK: r9(ns_sysctls)=0x%016x r3=%0d",
                    cycle_count, cpu.rf[9], cpu.rf[3]);
            // Return from setup_userns_sysctls
            if (umem_pc_pa_read_req_addr == 32'h0006fe00)
                $display("[%0d] USERNS_RETURN: r3=%0d (1=success, 0=fail)",
                    cycle_count, cpu.rf[3]);
            // === insert_header: key decision traces ===
            // -EEXIST detected (0x1597e0: li r30,-17)
            if (umem_pc_pa_read_req_addr == 32'h001597e0)
                $display("[%0d] IH_EEXIST: new_procname=0x%016x exist_procname=0x%016x",
                    cycle_count, cpu.rf[23], cpu.rf[19]);
            // __register_sysctl_table: insert_header result (0x15a14c)
            if (umem_pc_pa_read_req_addr == 32'h0015a14c)
                $display("[%0d] REGSYSCTL_INSERT_RET: err=%0d (0=success)",
                    cycle_count, cpu.rf[3]);
            // __register_sysctl_table: failure path (0x159ef0)
            if (umem_pc_pa_read_req_addr == 32'h00159ef0)
                $display("[%0d] REGSYSCTL_FAIL_NULL: will return NULL",
                    cycle_count);
        end
    end

    // =========================================================================
    // MSR Change Trace (detect loss of 64-bit mode)
    // =========================================================================
    reg [63:0] prev_msr = 0;
    always @(posedge clk) begin
        if (!reset && cpu.msr_rd != prev_msr) begin
                $display("[%0d] MSR_CHANGE: 0x%016x -> 0x%016x (SF=%b IR=%b DR=%b EE=%b) PC=0x%016x",
                    cycle_count, prev_msr, cpu.msr_rd,
                    cpu.msr_rd[63], cpu.msr_rd[5], cpu.msr_rd[4],
                    cpu.msr_rd[15], cpu.pc_rd);
            prev_msr <= cpu.msr_rd;
        end
    end

    // =========================================================================
    // OpenPOWER Core Instance
    // =========================================================================
    openpower_lcs_extmem cpu (
        .clk(clk),
        .reset(reset),

        // Reset values
        .reset_pc(reset_pc),
        .reset_msr(reset_msr),
        .reset_lr(zero64),
        .reset_ctr_rd(zero64),
        // ctr_force ports removed - not generated by current processor
        .reset_cr_rd(32'd0),
        .reset_xer(zero64),
        .reset_srr0(zero64),
        .reset_srr1(zero64),
        .reset_dar(zero64),
        .reset_dsisr_rd(32'd0),
        // .reset_fpscr_rd removed - no FP scoreboard in this build
        .reset_pvr_rd(32'h004e0202),  // PVR for Microwatt-like CPU
        .reset_resv_addr_rd(zero64),
        .reset_resv_valid_rd(1'b0),
        .reset_sprg0(zero64),
        .reset_sprg1(zero64),
        .reset_sprg2(zero64),
        .reset_sprg3(zero64),
        .reset_dec(zero64),
        .reset_tb(zero64),
        .reset_prtbl(zero64),
        .reset_pidr(zero64),

        // Instruction fetch (translated by ISA-level MMU)
        .umem_pc_pa_read_req_addr(umem_pc_pa_read_req_addr),
        .umem_pc_pa_read_req_valid(umem_pc_pa_read_req_valid),
        .umem_pc_pa_read_resp_data(umem_pc_pa_read_resp_data),
        .umem_pc_pa_read_resp_ready(umem_pc_pa_read_resp_ready),

        // Data read (translated by ISA-level MMU)
        .umem_ea_pa_read_req_addr(umem_ea_pa_read_req_addr),
        .umem_ea_pa_read_req_valid(umem_ea_pa_read_req_valid),
        .umem_ea_pa_read_resp_data(umem_ea_pa_read_resp_data),
        .umem_ea_pa_read_resp_ready(umem_ea_pa_read_resp_ready),

        // Next-word read ports (for unaligned access spanning DW boundaries)
        .umem_pc_pa_rd_next_read_req_addr(umem_pc_pa_rd_next_read_req_addr),
        .umem_pc_pa_rd_next_read_req_valid(umem_pc_pa_rd_next_read_req_valid),
        .umem_pc_pa_rd_next_read_resp_data(umem_pc_pa_rd_next_read_resp_data),
        .umem_pc_pa_rd_next_read_resp_ready(umem_pc_pa_rd_next_read_resp_ready),
        .umem_ea_pa_rd_next_read_req_addr(umem_ea_pa_rd_next_read_req_addr),
        .umem_ea_pa_rd_next_read_req_valid(umem_ea_pa_rd_next_read_req_valid),
        .umem_ea_pa_rd_next_read_resp_data(umem_ea_pa_rd_next_read_resp_data),
        .umem_ea_pa_rd_next_read_resp_ready(umem_ea_pa_rd_next_read_resp_ready),

        // Instruction MMU page table walk read ports
        .umem_pate1_addr_read_req_addr(umem_pate1_addr_read_req_addr),
        .umem_pate1_addr_read_req_valid(umem_pate1_addr_read_req_valid),
        .umem_pate1_addr_read_resp_data(umem_pate1_addr_read_resp_data),
        .umem_pate1_addr_read_resp_ready(umem_pate1_addr_read_resp_ready),
        .umem_prte0_addr_read_req_addr(umem_prte0_addr_read_req_addr),
        .umem_prte0_addr_read_req_valid(umem_prte0_addr_read_req_valid),
        .umem_prte0_addr_read_resp_data(umem_prte0_addr_read_resp_data),
        .umem_prte0_addr_read_resp_ready(umem_prte0_addr_read_resp_ready),
        .umem_pgd_addr_read_req_addr(umem_pgd_addr_read_req_addr),
        .umem_pgd_addr_read_req_valid(umem_pgd_addr_read_req_valid),
        .umem_pgd_addr_read_resp_data(umem_pgd_addr_read_resp_data),
        .umem_pgd_addr_read_resp_ready(umem_pgd_addr_read_resp_ready),
        .umem_pud_addr_read_req_addr(umem_pud_addr_read_req_addr),
        .umem_pud_addr_read_req_valid(umem_pud_addr_read_req_valid),
        .umem_pud_addr_read_resp_data(umem_pud_addr_read_resp_data),
        .umem_pud_addr_read_resp_ready(umem_pud_addr_read_resp_ready),
        .umem_pmd_addr_read_req_addr(umem_pmd_addr_read_req_addr),
        .umem_pmd_addr_read_req_valid(umem_pmd_addr_read_req_valid),
        .umem_pmd_addr_read_resp_data(umem_pmd_addr_read_resp_data),
        .umem_pmd_addr_read_resp_ready(umem_pmd_addr_read_resp_ready),
        .umem_pte_addr_read_req_addr(umem_pte_addr_read_req_addr),
        .umem_pte_addr_read_req_valid(umem_pte_addr_read_req_valid),
        .umem_pte_addr_read_resp_data(umem_pte_addr_read_resp_data),
        .umem_pte_addr_read_resp_ready(umem_pte_addr_read_resp_ready),

        // Load MMU page table walk read ports
        .umem_ld_pate1_addr_read_req_addr(umem_ld_pate1_addr_read_req_addr),
        .umem_ld_pate1_addr_read_req_valid(umem_ld_pate1_addr_read_req_valid),
        .umem_ld_pate1_addr_read_resp_data(umem_ld_pate1_addr_read_resp_data),
        .umem_ld_pate1_addr_read_resp_ready(umem_ld_pate1_addr_read_resp_ready),
        .umem_ld_prte0_addr_read_req_addr(umem_ld_prte0_addr_read_req_addr),
        .umem_ld_prte0_addr_read_req_valid(umem_ld_prte0_addr_read_req_valid),
        .umem_ld_prte0_addr_read_resp_data(umem_ld_prte0_addr_read_resp_data),
        .umem_ld_prte0_addr_read_resp_ready(umem_ld_prte0_addr_read_resp_ready),
        .umem_ld_pgd_addr_read_req_addr(umem_ld_pgd_addr_read_req_addr),
        .umem_ld_pgd_addr_read_req_valid(umem_ld_pgd_addr_read_req_valid),
        .umem_ld_pgd_addr_read_resp_data(umem_ld_pgd_addr_read_resp_data),
        .umem_ld_pgd_addr_read_resp_ready(umem_ld_pgd_addr_read_resp_ready),
        .umem_ld_pud_addr_read_req_addr(umem_ld_pud_addr_read_req_addr),
        .umem_ld_pud_addr_read_req_valid(umem_ld_pud_addr_read_req_valid),
        .umem_ld_pud_addr_read_resp_data(umem_ld_pud_addr_read_resp_data),
        .umem_ld_pud_addr_read_resp_ready(umem_ld_pud_addr_read_resp_ready),
        .umem_ld_pmd_addr_read_req_addr(umem_ld_pmd_addr_read_req_addr),
        .umem_ld_pmd_addr_read_req_valid(umem_ld_pmd_addr_read_req_valid),
        .umem_ld_pmd_addr_read_resp_data(umem_ld_pmd_addr_read_resp_data),
        .umem_ld_pmd_addr_read_resp_ready(umem_ld_pmd_addr_read_resp_ready),
        .umem_ld_pte_addr_read_req_addr(umem_ld_pte_addr_read_req_addr),
        .umem_ld_pte_addr_read_req_valid(umem_ld_pte_addr_read_req_valid),
        .umem_ld_pte_addr_read_resp_data(umem_ld_pte_addr_read_resp_data),
        .umem_ld_pte_addr_read_resp_ready(umem_ld_pte_addr_read_resp_ready),

        // Store MMU page table walk read ports
        .umem_st_pate1_addr_read_req_addr(umem_st_pate1_addr_read_req_addr),
        .umem_st_pate1_addr_read_req_valid(umem_st_pate1_addr_read_req_valid),
        .umem_st_pate1_addr_read_resp_data(umem_st_pate1_addr_read_resp_data),
        .umem_st_pate1_addr_read_resp_ready(umem_st_pate1_addr_read_resp_ready),
        .umem_st_prte0_addr_read_req_addr(umem_st_prte0_addr_read_req_addr),
        .umem_st_prte0_addr_read_req_valid(umem_st_prte0_addr_read_req_valid),
        .umem_st_prte0_addr_read_resp_data(umem_st_prte0_addr_read_resp_data),
        .umem_st_prte0_addr_read_resp_ready(umem_st_prte0_addr_read_resp_ready),
        .umem_st_pgd_addr_read_req_addr(umem_st_pgd_addr_read_req_addr),
        .umem_st_pgd_addr_read_req_valid(umem_st_pgd_addr_read_req_valid),
        .umem_st_pgd_addr_read_resp_data(umem_st_pgd_addr_read_resp_data),
        .umem_st_pgd_addr_read_resp_ready(umem_st_pgd_addr_read_resp_ready),
        .umem_st_pud_addr_read_req_addr(umem_st_pud_addr_read_req_addr),
        .umem_st_pud_addr_read_req_valid(umem_st_pud_addr_read_req_valid),
        .umem_st_pud_addr_read_resp_data(umem_st_pud_addr_read_resp_data),
        .umem_st_pud_addr_read_resp_ready(umem_st_pud_addr_read_resp_ready),
        .umem_st_pmd_addr_read_req_addr(umem_st_pmd_addr_read_req_addr),
        .umem_st_pmd_addr_read_req_valid(umem_st_pmd_addr_read_req_valid),
        .umem_st_pmd_addr_read_resp_data(umem_st_pmd_addr_read_resp_data),
        .umem_st_pmd_addr_read_resp_ready(umem_st_pmd_addr_read_resp_ready),
        .umem_st_pte_addr_read_req_addr(umem_st_pte_addr_read_req_addr),
        .umem_st_pte_addr_read_req_valid(umem_st_pte_addr_read_req_valid),
        .umem_st_pte_addr_read_resp_data(umem_st_pte_addr_read_resp_data),
        .umem_st_pte_addr_read_resp_ready(umem_st_pte_addr_read_resp_ready),

        // Data write
        .umem_write_req_addr(umem_write_req_addr),
        .umem_write_req_data(umem_write_req_data),
        .umem_write_req_we(umem_write_req_we),
        .umem_write_req_valid(umem_write_req_valid),
        .umem_write_resp_ready(umem_write_resp_ready)
    );

    // =========================================================================
    // Debug Control
    // =========================================================================
    logic debug_enable = 0;
    initial begin
        if ($test$plusargs("debug")) debug_enable = 1;
    end

    // Debug: PC and instruction trace
    // Select correct 32-bit instruction based on PC[2] (big-endian: PC[2]=0 uses upper half)
    wire [31:0] debug_instr = umem_pc_pa_read_req_addr[2] ?
                              umem_pc_pa_read_resp_data[31:0] :
                              umem_pc_pa_read_resp_data[63:32];
    integer debug_cycle = 0;
    logic [31:0] prev_pc = 32'hFFFFFFFF;
    logic [31:0] max_pc = 0;
    always @(posedge clk) begin
        if (!reset) begin
            debug_cycle <= debug_cycle + 1;
            // Track highest PC reached (forward progress indicator)
            if (umem_pc_pa_read_req_addr > max_pc && umem_pc_pa_read_req_addr < 32'h01000000)
                max_pc <= umem_pc_pa_read_req_addr;
            // Log PC transitions (when PC actually changes)
            if (debug_enable && umem_pc_pa_read_req_addr != prev_pc) begin
                if (debug_cycle < 200 ||
                    debug_cycle % 10000000 == 0)
                    $display("[%0d] PC=0x%08x instr=0x%08x stall=%b wr=%b wr_addr=0x%08x",
                        debug_cycle,
                        umem_pc_pa_read_req_addr,
                        debug_instr,
                        cpu.mem_ext_stall,
                        umem_write_req_valid,
                        umem_write_req_addr);
            end
            // Trace key function entries for debugging
            if (umem_pc_pa_read_req_addr != prev_pc) begin
                // === Exception vector detection ===
                // Any PC jump to 0x100-0x1800 range indicates an exception
                if (umem_pc_pa_read_req_addr >= 32'h00000100 &&
                    umem_pc_pa_read_req_addr <= 32'h00001800 &&
                    prev_pc > 32'h00002000) begin
                    $display("[%0d] EXCEPTION_VECTOR: PC=0x%08x (from 0x%08x) LR=0x%016x SRR0=0x%016x SRR1=0x%016x r3=0x%016x",
                        debug_cycle, umem_pc_pa_read_req_addr, prev_pc, cpu.lr,
                        cpu.srr0, cpu.srr1, cpu.rf[3]);
                end
                // === Jump to zero-filled region detection ===
                if (debug_instr == 32'h00000000 && umem_pc_pa_read_req_addr > 32'h00001000)
                    $display("[%0d] ZERO_INSTR: PC=0x%08x (from 0x%08x) LR=0x%016x CTR=0x%016x",
                        debug_cycle, umem_pc_pa_read_req_addr, prev_pc, cpu.lr, cpu.ctr_rd);
                // === Non-trivial function call detection ===
                // Trace first entry into boot wrapper library (0x01100000-0x01110000)
                if (umem_pc_pa_read_req_addr >= 32'h01100000 &&
                    umem_pc_pa_read_req_addr < 32'h01110000 &&
                    prev_pc < 32'h01100000 &&
                    debug_cycle < 200000)
                    $display("[%0d] ENTER_WRAPPER_LIB: PC=0x%08x (from 0x%08x) LR=0x%016x",
                        debug_cycle, umem_pc_pa_read_req_addr, prev_pc, cpu.lr);
                // Trace returns from wrapper lib back to wrapper code
                if (umem_pc_pa_read_req_addr < 32'h01100000 &&
                    prev_pc >= 32'h01100000 &&
                    prev_pc < 32'h01110000 &&
                    debug_cycle < 200000)
                    $display("[%0d] EXIT_WRAPPER_LIB: PC=0x%08x (from 0x%08x) LR=0x%016x",
                        debug_cycle, umem_pc_pa_read_req_addr, prev_pc, cpu.lr);
                // === Boot wrapper loop debug ===
                // cmplw r9,r8 in cache flush loop
                if (umem_pc_pa_read_req_addr == 32'h00000150 && debug_cycle < 200) begin
                    $display("[%0d] CMPLW: r9=0x%016x r8=0x%016x r10=0x%016x CR=0x%08x",
                        debug_cycle, cpu.rf[9], cpu.rf[8], cpu.rf[10], cpu.cr_rd);
                end
                // blt in cache flush loop - show first 10 exits
                if (umem_pc_pa_read_req_addr == 32'h00000158)
                    $display("[%0d] CACHE_FLUSH_DONE: r9=0x%016x r8=0x%016x",
                        debug_cycle, cpu.rf[9], cpu.rf[8]);
                // BSS clear loop comparison
                if (umem_pc_pa_read_req_addr == 32'h00000174 && (debug_cycle < 200 || debug_cycle > 15000)) begin
                    $display("[%0d] BSS_CMPLW: r9=0x%016x r8=0x%016x",
                        debug_cycle, cpu.rf[9], cpu.rf[8]);
                end
                // Track boot wrapper flow
                if (umem_pc_pa_read_req_addr == 32'h0000017c)
                    $display("[%0d] POST_BSS: at 0x17c r8=0x%016x r10=0x%016x r1=0x%016x",
                        debug_cycle, cpu.rf[8], cpu.rf[10], cpu.rf[1]);
                if (umem_pc_pa_read_req_addr == 32'h00000188)
                    $display("[%0d] STACK_LOAD: lwz r1,0(r8) r8=0x%016x", debug_cycle, cpu.rf[8]);
                if (umem_pc_pa_read_req_addr == 32'h00000194)
                    $display("[%0d] BL_0x10: r1=0x%016x r3=0x%016x", debug_cycle, cpu.rf[1], cpu.rf[3]);
                if (umem_pc_pa_read_req_addr == 32'h00000010)
                    $display("[%0d] CALL_0x10: entered r1=0x%016x r3=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[1], cpu.rf[3], cpu.lr);
                if (umem_pc_pa_read_req_addr == 32'h0000006c)
                    $display("[%0d] RETURN_0x10: r1=0x%016x LR=0x%016x r0=0x%016x",
                        debug_cycle, cpu.rf[1], cpu.lr, cpu.rf[0]);
                if (umem_pc_pa_read_req_addr == 32'h00000198)
                    $display("[%0d] B_0xBF0: jumping to 0xbf0", debug_cycle);
                if (umem_pc_pa_read_req_addr == 32'h00000bf0)
                    $display("[%0d] AT_0xBF0: r3=0x%016x r1=0x%016x", debug_cycle, cpu.rf[3], cpu.rf[1]);
                if (umem_pc_pa_read_req_addr == 32'h00000070)
                    $display("[%0d] RESET_LOOP: hit reset loop at 0x70!", debug_cycle);
                // memblock_add local entry: r3=base, r4=size
                if (umem_pc_pa_read_req_addr == 32'h000ef9ac)
                    $display("[%0d] MEMBLOCK_ADD: base=0x%016x size=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.lr);
                // early_init_dt_add_memory_arch local entry: r3=base, r4=size
                if (umem_pc_pa_read_req_addr == 32'h010058cc)
                    $display("[%0d] DT_ADD_MEMORY: base=0x%016x size=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.lr);
                // early_init_devtree local entry
                if (umem_pc_pa_read_req_addr == 32'h01005978)
                    $display("[%0d] EARLY_INIT_DEVTREE: r3=0x%016x (fdt pointer)",
                        debug_cycle, cpu.rf[3]);
                // memblock_end_of_DRAM local entry
                if (umem_pc_pa_read_req_addr == 32'h000efd14)
                    $display("[%0d] MEMBLOCK_END_OF_DRAM: called, LR=0x%016x",
                        debug_cycle, cpu.lr);
                // Boot wrapper function call at 0x4c
                if (umem_pc_pa_read_req_addr == 32'h0000004c)
                    $display("[%0d] BL_1940: calling 0x1940, r3=0x%016x r4=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4]);
                // === Kernel early boot key functions ===
                // early_setup (phys 0x1004160)
                if (umem_pc_pa_read_req_addr == 32'h01004160)
                    $display("[%0d] EARLY_SETUP: entered, r3(dt_ptr)=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // start_kernel (phys 0x1000a98)
                if (umem_pc_pa_read_req_addr == 32'h01000a98)
                    $display("[%0d] START_KERNEL: entered!",
                        debug_cycle);
                // setup_arch (phys 0x1005f14)
                if (umem_pc_pa_read_req_addr == 32'h01005f14)
                    $display("[%0d] SETUP_ARCH: entered",
                        debug_cycle);
                // early_init_devtree (phys 0x1003638)
                if (umem_pc_pa_read_req_addr == 32'h01003638)
                    $display("[%0d] EARLY_INIT_DEVTREE: entered, r3(dt_ptr)=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // mmu_early_init_devtree (phys 0x1009348)
                if (umem_pc_pa_read_req_addr == 32'h01009348)
                    $display("[%0d] MMU_EARLY_INIT_DEVTREE: entered",
                        debug_cycle);
                // radix__early_init_mmu (phys 0x100b1b4)
                if (umem_pc_pa_read_req_addr == 32'h0100b1b4)
                    $display("[%0d] RADIX_EARLY_INIT_MMU: entered",
                        debug_cycle);
                // hash__early_init_mmu (phys 0x100a018)
                if (umem_pc_pa_read_req_addr == 32'h0100a018)
                    $display("[%0d] HASH_EARLY_INIT_MMU: entered",
                        debug_cycle);
                // panic (phys 0x4199c)
                if (umem_pc_pa_read_req_addr == 32'h0004199c)
                    $display("[%0d] PANIC: entered! r3(fmt)=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.lr);
                // vpanic (phys 0x41690)
                if (umem_pc_pa_read_req_addr == 32'h00041690)
                    $display("[%0d] VPANIC: entered! r3(fmt)=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.lr);
                // die (phys 0x155dc)
                if (umem_pc_pa_read_req_addr == 32'h000155dc)
                    $display("[%0d] DIE: entered! r3(str)=0x%016x r4(regs)=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.lr);
                // _printk (phys 0x82090) - show format string
                if (umem_pc_pa_read_req_addr == 32'h0007c4a0) begin : printk_trace
                    automatic logic [31:0] fmt_addr;
                    automatic logic [63:0] w0, w1, w2, w3;
                    fmt_addr = cpu.rf[3][31:0];
                    w0 = main_memory[fmt_addr[27:3]];
                    w1 = main_memory[fmt_addr[27:3] + 1];
                    w2 = main_memory[fmt_addr[27:3] + 2];
                    w3 = main_memory[fmt_addr[27:3] + 3];
                    $display("[%0d] PRINTK: fmt=0x%08x LR=0x%016x data: %016x %016x %016x %016x",
                        debug_cycle, fmt_addr, cpu.lr, w0, w1, w2, w3);
                end
                // __warn_printk (phys 0x4dc30)
                if (umem_pc_pa_read_req_addr == 32'h0004dc30)
                    $display("[%0d] WARN_PRINTK: fmt=0x%08x LR=0x%016x",
                        debug_cycle, cpu.rf[3][31:0], cpu.lr);
                // udbg_puts (phys 0x1775c)
                if (umem_pc_pa_read_req_addr == 32'h0001775c)
                    $display("[%0d] UDBG_PUTS: str=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.lr);
                // udbg_early_init (phys 0x1006334)
                if (umem_pc_pa_read_req_addr == 32'h01006334)
                    $display("[%0d] UDBG_EARLY_INIT: entered",
                        debug_cycle);
                // udbg_uart_init_mmio (phys 0x100a1b4)
                if (umem_pc_pa_read_req_addr == 32'h0100a1b4)
                    $display("[%0d] UDBG_UART_INIT_MMIO: addr=r3=0x%016x stride=r4=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4]);
                // register_early_udbg_console (phys 0x1006368)
                if (umem_pc_pa_read_req_addr == 32'h01006368)
                    $display("[%0d] REGISTER_EARLY_UDBG_CONSOLE: entered",
                        debug_cycle);
                // machine_hang+0x8 entry (phys 0x17190)
                if (umem_pc_pa_read_req_addr == 32'h00017190)
                    $display("[%0d] MACHINE_HANG: entered LR=0x%016x r3=0x%016x",
                        debug_cycle, cpu.lr, cpu.rf[3]);
                // machine_power_off (phys 0x17668)
                if (umem_pc_pa_read_req_addr == 32'h00017668)
                    $display("[%0d] MACHINE_POWER_OFF: entered LR=0x%016x",
                        debug_cycle, cpu.lr);
                // machine_halt (phys 0x176e8)
                if (umem_pc_pa_read_req_addr == 32'h000176e8)
                    $display("[%0d] MACHINE_HALT: entered LR=0x%016x",
                        debug_cycle, cpu.lr);
                // panic (phys 0x4dda8)
                if (umem_pc_pa_read_req_addr == 32'h0004dda8)
                    $display("[%0d] PANIC: entered LR=0x%016x r3=0x%016x",
                        debug_cycle, cpu.lr, cpu.rf[3]);
                // Halt loop - dump registers, stack, and log buffer
                if (umem_pc_pa_read_req_addr == 32'h000171b4) begin : halt_dump
                    automatic integer hi;
                    automatic logic [31:0] sp_phys;
                    $display("[%0d] HALT_LOOP: b . reached. LR=0x%016x MSR=0x%016x CR=0x%08x",
                        debug_cycle, cpu.lr, cpu.msr_rd, cpu.cr_rd);
                    $display("  r0=0x%016x  r1(sp)=0x%016x  r2(toc)=0x%016x  r3=0x%016x",
                        cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3]);
                    $display("  SRR0=0x%016x  SRR1=0x%016x  CTR=0x%016x  XER=0x%016x",
                        cpu.srr0, cpu.srr1, cpu.ctr_rd, cpu.xer);
                    // Stack backtrace: PowerPC64 stack frames are chained
                    // Each frame: [backchain_ptr(8)] [saved_cr(4)] [saved_lr(8@+16)]
                    sp_phys = cpu.rf[1][31:0];  // truncate to physical
                    $display("=== STACK BACKTRACE (sp=0x%08x) ===", sp_phys);
                    for (hi = 0; hi < 16; hi = hi + 1) begin
                        if (sp_phys != 0 && sp_phys < 32'h0FFFFFFF) begin
                            $display("  frame[%0d]: sp=0x%08x backchain=0x%016x LR=0x%016x",
                                hi, sp_phys,
                                main_memory[sp_phys[27:3]],
                                main_memory[(sp_phys + 16) >> 3]);
                            sp_phys = main_memory[sp_phys[27:3]][31:0];
                        end
                    end
                    // Dump __log_buf at physical 0x10e9b68 (4096 bytes = 512 words)
                    $display("=== KERNEL LOG BUFFER DUMP (__log_buf @ 0x10e9b68) ===");
                    for (hi = 0; hi < 512; hi = hi + 1) begin
                        $display("  [+0x%03x] %016x %016x",
                            hi * 16,
                            main_memory[(32'h10e9b68 >> 3) + hi*2],
                            main_memory[(32'h10e9b68 >> 3) + hi*2 + 1]);
                    end
                    $display("=== END LOG BUFFER DUMP ===");
                end
                // Trace UART writes - fixed bit range check
                if (umem_write_req_valid &&
                    umem_write_req_addr >= 32'hC0002000 &&
                    umem_write_req_addr < 32'hC0002100)
                    $display("[%0d] UART_WRITE: addr=0x%08x data=0x%016x we=0x%02x",
                        debug_cycle, umem_write_req_addr, umem_write_req_data, umem_write_req_we);
                // microwatt_setup_arch (phys 0x1012720)
                if (umem_pc_pa_read_req_addr == 32'h01012720)
                    $display("[%0d] MICROWATT_SETUP_ARCH: entered",
                        debug_cycle);
                // microwatt_init_IRQ (phys 0x10126f4)
                if (umem_pc_pa_read_req_addr == 32'h010126f4)
                    $display("[%0d] MICROWATT_INIT_IRQ: entered",
                        debug_cycle);
                // console_init (phys 0x1015f58)
                if (umem_pc_pa_read_req_addr == 32'h01015f58)
                    $display("[%0d] CONSOLE_INIT: entered",
                        debug_cycle);
                // setup_earlycon (phys 0x10230ac)
                if (umem_pc_pa_read_req_addr == 32'h010230ac)
                    $display("[%0d] SETUP_EARLYCON: entered, r3=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // register_console (phys 0x7f000)
                if (umem_pc_pa_read_req_addr == 32'h0007f000)
                    $display("[%0d] REGISTER_CONSOLE: entered, r3(console)=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // __kmem_cache_create+0x8 (phys 0xf4290)
                if (umem_pc_pa_read_req_addr == 32'h000f4290)
                    $display("[%0d] KMEM_CACHE_CREATE: s=r3=0x%016x flags=r4=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4]);
                // __kmem_cache_create error return (phys 0xf45f4)
                if (umem_pc_pa_read_req_addr == 32'h000f45f4)
                    $display("[%0d] KMEM_CACHE_CREATE_ERR: r30=0x%016x r31(s)=0x%016x r29(size)=0x%016x",
                        debug_cycle, cpu.rf[30], cpu.rf[31], cpu.rf[29]);
                // __kmem_cache_create order check at 0xf45ec (cmplwi r9,12)
                if (umem_pc_pa_read_req_addr == 32'h000f45ec)
                    $display("[%0d] KMEM_CACHE_ORDER_CHECK: r9(order)=0x%016x r30(size)=0x%016x",
                        debug_cycle, cpu.rf[9], cpu.rf[30]);
                // __kmem_cache_create after reciprocal_value (phys 0xf4314)
                if (umem_pc_pa_read_req_addr == 32'h000f4314)
                    $display("[%0d] KMEM_CACHE_POST_RECIP: r3(recip)=0x%016x r30(size)=0x%016x r29(size_aligned)=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[30], cpu.rf[29]);
                // Trace all PCs in __kmem_cache_create (0xf4288 - 0xf4648) during the call
                if (debug_cycle > 24700000 && umem_pc_pa_read_req_addr >= 32'h000f4288 &&
                    umem_pc_pa_read_req_addr < 32'h000f4648)
                    $display("[%0d] KMEM_PC: 0x%08x r0=0x%016x r3=0x%016x r9=0x%016x r10=0x%016x r29=0x%016x r30=0x%016x",
                        debug_cycle, umem_pc_pa_read_req_addr, cpu.rf[0], cpu.rf[3], cpu.rf[9], cpu.rf[10], cpu.rf[29], cpu.rf[30]);
                // Debug cntlzd internal signals when at the cntlzd instruction PC
                if (umem_pc_pa_read_req_addr == 32'h000f45e4)
                    $display("[%0d] CNTLZD_DBG: enable=%b count_mux=0x%02x count=0x%02x result=0x%016x ternary_125=0x%02x ternary_10=0x%02x w_8_d64=0x%02x rf_wr_en=%b rf_wr_addr=%0d rf_wr_data=0x%016x",
                        debug_cycle, cpu.cntlzd_enable, cpu.cntlzd_count_mux, cpu.cntlzd_count, cpu.cntlzd_result,
                        cpu.ternary_125, cpu.ternary_10, cpu.w_8_d64,
                        cpu.rf_write_enable, cpu.rf_write_addr_mux, cpu.rf_write_data_mux);
                // create_boot_cache+0x8 (phys 0x1019ef4)
                if (umem_pc_pa_read_req_addr == 32'h01019ef4)
                    $display("[%0d] CREATE_BOOT_CACHE: s=r3=0x%016x name=r4=0x%016x size=r5=0x%016x flags=r6=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[6]);
                // __alloc_percpu+0x8 (phys 0xcb354)
                if (umem_pc_pa_read_req_addr == 32'h000cb354)
                    $display("[%0d] ALLOC_PERCPU: size=r3=0x%016x align=r4=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.lr);
                // pcpu_alloc+0x8 (phys 0xcae08)
                if (umem_pc_pa_read_req_addr == 32'h000cae08)
                    $display("[%0d] PCPU_ALLOC: size=r3=0x%016x align=r4=0x%016x reserved=r5=0x%016x gfp=r6=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[6]);
                // setup_per_cpu_areas+0x8 (phys 0x1019e00)
                if (umem_pc_pa_read_req_addr == 32'h01019e00)
                    $display("[%0d] SETUP_PER_CPU_AREAS: entered LR=0x%016x",
                        debug_cycle, cpu.lr);
                // pcpu_setup_first_chunk+0x8 (phys 0x10195ac)
                if (umem_pc_pa_read_req_addr == 32'h010195ac)
                    $display("[%0d] PCPU_SETUP_FIRST_CHUNK: entered LR=0x%016x",
                        debug_cycle, cpu.lr);
                // alloc_slab_page (phys 0xf1888)
                if (umem_pc_pa_read_req_addr == 32'h000f1888)
                    $display("[%0d] ALLOC_SLAB_PAGE: s=r3=0x%016x alloc_gfp=r4=0x%016x node=r5=0x%016x order=r6(oo)=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[6]);
                // __alloc_pages (phys 0xee064)
                if (umem_pc_pa_read_req_addr == 32'h000ee064)
                    $display("[%0d] ALLOC_PAGES: gfp=r3=0x%016x order=r4=0x%016x preferred_nid=r5=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5]);
                // Trace kernel PC progress every 100K cycles (more granular)
                if (debug_cycle > 5000000 && debug_cycle % 100000 < 2 &&
                    umem_pc_pa_read_req_addr < 32'h02000000)
                    $display("[%0d] KERNEL_PC: 0x%08x LR=0x%016x r1(sp)=0x%016x MSR=0x%016x",
                        debug_cycle, umem_pc_pa_read_req_addr, cpu.lr, cpu.rf[1], cpu.msr_rd);
                // desc_read: ld r8,0(r3) at 0x00088534 - trace ring buffer load
                if (umem_pc_pa_read_req_addr == 32'h00088534) begin
                    automatic logic [31:0] desc_addr;
                    desc_addr = cpu.rf[3][31:0];
                    if (debug_cycle < 7200000 || debug_cycle % 50000000 == 0)
                        $display("[%0d] DESC_READ: desc_ptr=r3=0x%016x r30(req_id)=0x%016x mem[r3]=0x%016x",
                            debug_cycle, cpu.rf[3], cpu.rf[30], main_memory[desc_addr[27:3]]);
                end
                // prb_first_seq: cmplwi after desc_read at 0x00088ac8
                if (umem_pc_pa_read_req_addr == 32'h00088ac8) begin
                    if (debug_cycle < 7200000 || debug_cycle % 50000000 == 0)
                        $display("[%0d] PRB_FIRST_SEQ: desc_read returned r3=0x%016x",
                            debug_cycle, cpu.rf[3]);
                end
                // backwards_memcpy entry (0x01102F4C)
                if (umem_pc_pa_read_req_addr == 32'h01102F4C)
                    $display("[%0d] BACKWARDS_MEMCPY: dest=r3=0x%016x src=r4=0x%016x count=r5=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5]);
                // memcpy entry (0x01102E94)
                if (umem_pc_pa_read_req_addr == 32'h01102E94)
                    $display("[%0d] MEMCPY: dest=r3=0x%016x src=r4=0x%016x count=r5=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5]);
                // memmove entry (0x01102E8C)
                if (umem_pc_pa_read_req_addr == 32'h01102E8C)
                    $display("[%0d] MEMMOVE: dest=r3=0x%016x src=r4=0x%016x count=r5=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.lr);
                // mtctr at backwards_memcpy byte loop (0x01102FA4)
                if (umem_pc_pa_read_req_addr == 32'h01102FA4)
                    $display("[%0d] BACKWARDS_MEMCPY_BYTE_LOOP: CTR_to_load=r5=0x%016x",
                        debug_cycle, cpu.rf[5]);
                // mtctr at memcpy byte loop (0x01102EEC)
                if (umem_pc_pa_read_req_addr == 32'h01102EEC)
                    $display("[%0d] MEMCPY_BYTE_LOOP: CTR_to_load=r5=0x%016x",
                        debug_cycle, cpu.rf[5]);
                // fdt_init entry (0x01100850)
                if (umem_pc_pa_read_req_addr == 32'h01100850)
                    $display("[%0d] FDT_INIT: fdt_ptr=r3=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // fdt_open_into entry (0x0110AFC0)
                if (umem_pc_pa_read_req_addr == 32'h0110AFC0)
                    $display("[%0d] FDT_OPEN_INTO: fdt=r3=0x%016x buf=r4=0x%016x bufsize=r5=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5]);
                // fdt_num_mem_rsv entry (0x011080C0)
                if (umem_pc_pa_read_req_addr == 32'h011080C0)
                    $display("[%0d] FDT_NUM_MEM_RSV: fdt=r3=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // fdt_mem_rsv entry (0x01107D70)
                if (umem_pc_pa_read_req_addr == 32'h01107D70)
                    $display("[%0d] FDT_MEM_RSV: fdt=r3=0x%016x n=r4=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4]);
                // fdt_mem_rsv - after lwz r9,16(r3) at 0x01107D74
                if (umem_pc_pa_read_req_addr == 32'h01107D74)
                    $display("[%0d] FDT_MEM_RSV+4: r9(off_mem_rsvmap)=0x%016x r4=0x%016x",
                        debug_cycle, cpu.rf[9], cpu.rf[4]);
                // fdt_mem_rsv - after lwz r9,4(r3) at 0x01107D88
                if (umem_pc_pa_read_req_addr == 32'h01107D88)
                    $display("[%0d] FDT_MEM_RSV+18: r9(totalsize)=0x%016x r4(offset)=0x%016x r3=0x%016x",
                        debug_cycle, cpu.rf[9], cpu.rf[4], cpu.rf[3]);
                // fdt_mem_rsv - at isellt (0x01107D94)
                if (umem_pc_pa_read_req_addr == 32'h01107D94)
                    $display("[%0d] FDT_MEM_RSV+24: r9(totalsize-16)=0x%016x r4(offset)=0x%016x r3(ptr)=0x%016x CR=0x%08x",
                        debug_cycle, cpu.rf[9], cpu.rf[4], cpu.rf[3], cpu.cr_rd);
                // fdt_mem_rsv - after isellt, before blr (0x01107D98)
                if (umem_pc_pa_read_req_addr == 32'h01107D98)
                    $display("[%0d] FDT_MEM_RSV_RET: result=r3=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // fdt_mem_rsv - NULL return path (0x01107DA0)
                if (umem_pc_pa_read_req_addr == 32'h01107DA0)
                    $display("[%0d] FDT_MEM_RSV_NULL: returning NULL (overflow check failed)",
                        debug_cycle);
                // fdt_ro_probe_ entry (0x0110BA60)
                if (umem_pc_pa_read_req_addr == 32'h0110BA60)
                    $display("[%0d] FDT_RO_PROBE: fdt=r3=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // fdt_check_header entry (0x0110BB70)
                if (umem_pc_pa_read_req_addr == 32'h0110BB70)
                    $display("[%0d] FDT_CHECK_HEADER: fdt=r3=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // platform_init entry (0x01100010)
                if (umem_pc_pa_read_req_addr == 32'h01100010)
                    $display("[%0d] PLATFORM_INIT: r3=0x%016x",
                        debug_cycle, cpu.rf[3]);
                // fdt_num_mem_rsv: beq after or. (0x011080EC)
                if (umem_pc_pa_read_req_addr == 32'h011080EC)
                    $display("[%0d] FDT_NUM_MEM_RSV_BEQ: r9=0x%016x r10=0x%016x CR=0x%08x r3(ptr)=0x%016x i=r31=0x%016x",
                        debug_cycle, cpu.rf[9], cpu.rf[10], cpu.cr_rd, cpu.rf[3], cpu.rf[31]);
                // fdt_num_mem_rsv: addi r31,r31,1 (0x011080F0) - loop didn't exit
                if (umem_pc_pa_read_req_addr == 32'h011080F0)
                    $display("[%0d] FDT_NUM_MEM_RSV_LOOP_CONT: i incremented r31=0x%016x",
                        debug_cycle, cpu.rf[31]);
                // prep_kernel: just before bl partial_decompress (0x01100A18)
                if (umem_pc_pa_read_req_addr == 32'h01100A18)
                    $display("[%0d] PREP_KERNEL->partial_decompress: compressed=r3=0x%016x size=r4=0x%016x outbuf=r5=0x%016x bufsize=r6=0x%016x skip=r7=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
                // prep_kernel: after partial_decompress returns (0x01100A1C)
                if (umem_pc_pa_read_req_addr == 32'h01100A1C) begin
                    automatic logic [31:0] buf_addr;
                    buf_addr = cpu.rf[31][31:0]; // r31 = output buffer
                    $display("[%0d] PARTIAL_DECOMPRESS returned: r3=0x%016x outbuf=r31=0x%08x",
                        debug_cycle, cpu.rf[3], buf_addr);
                    $display("  Decompressed bytes at 0x%08x:", buf_addr);
                    $display("    [+0x00] = 0x%016x", main_memory[buf_addr[27:3]]);
                    $display("    [+0x08] = 0x%016x", main_memory[buf_addr[27:3] + 1]);
                    $display("    [+0x10] = 0x%016x", main_memory[buf_addr[27:3] + 2]);
                    $display("    [+0x18] = 0x%016x", main_memory[buf_addr[27:3] + 3]);
                end
                // parse_elf64 entry (0x01107B70)
                if (umem_pc_pa_read_req_addr == 32'h01107B70) begin
                    automatic logic [31:0] elf_addr;
                    automatic integer elf_w;
                    elf_addr = cpu.rf[3][31:0];
                    elf_w = elf_addr[27:3];
                    $display("[%0d] PARSE_ELF64: buf=r3=0x%08x first_word=0x%08x (expect 0x7F454C46)",
                        debug_cycle, elf_addr, main_memory[elf_w][63:32]);
                    // Dump first 128 bytes (16 words) of buffer
                    for (integer di = 0; di < 16; di++)
                        $display("  buf[+0x%02x] = 0x%016x", di*8, main_memory[elf_w + di]);
                end
                // parse_elf64: after bnelr at 0x01107B9C - check EI_CLASS/DATA
                if (umem_pc_pa_read_req_addr == 32'h01107BA0)
                    $display("[%0d] PARSE_ELF64: passed class/data check, loading e_type from offset 16",
                        debug_cycle);
                // parse_elf64: after cmplwi at 0x01107BAC - check e_type
                if (umem_pc_pa_read_req_addr == 32'h01107BB0)
                    $display("[%0d] PARSE_ELF64: e_type check: r10=0x%016x CR=0x%08x",
                        debug_cycle, cpu.rf[10], cpu.cr_rd);
                // parse_elf64: after cmpwi r10,21 at 0x01107BB8 - check e_machine
                if (umem_pc_pa_read_req_addr == 32'h01107BBC)
                    $display("[%0d] PARSE_ELF64: e_machine check: r10=0x%016x (expect 21) CR=0x%08x",
                        debug_cycle, cpu.rf[10], cpu.cr_rd);
                // parse_elf64: after loading e_phnum and e_phoff (0x01107BC8)
                if (umem_pc_pa_read_req_addr == 32'h01107BC8)
                    $display("[%0d] PARSE_ELF64: e_phnum=r7=0x%016x e_phoff_low=r10=0x%016x",
                        debug_cycle, cpu.rf[7], cpu.rf[10]);
                // parse_elf64: in phdr loop, checking p_type (0x01107C10)
                if (umem_pc_pa_read_req_addr == 32'h01107C10)
                    $display("[%0d] PARSE_ELF64_LOOP: p_type=r8=0x%016x (expect 1=PT_LOAD) r9=0x%016x",
                        debug_cycle, cpu.rf[8], cpu.rf[9]);
                // parse_elf64: second phdr check (0x01107BF8)
                if (umem_pc_pa_read_req_addr == 32'h01107BF8)
                    $display("[%0d] PARSE_ELF64_LOOP2: p_type=r8=0x%016x (expect 1=PT_LOAD) r9=0x%016x",
                        debug_cycle, cpu.rf[8], cpu.rf[9]);
                // parse_elf64: failure return (0x01107C5C)
                if (umem_pc_pa_read_req_addr == 32'h01107C5C)
                    $display("[%0d] PARSE_ELF64: FAILED - returning 0. r7=0x%016x r8=0x%016x r9=0x%016x r10=0x%016x",
                        debug_cycle, cpu.rf[7], cpu.rf[8], cpu.rf[9], cpu.rf[10]);
                // parse_elf64: success (0x01107C18)
                if (umem_pc_pa_read_req_addr == 32'h01107C18)
                    $display("[%0d] PARSE_ELF64: found PT_LOAD! r7=0x%016x r10=0x%016x r9=0x%016x",
                        debug_cycle, cpu.rf[7], cpu.rf[10], cpu.rf[9]);
                // parse_elf32 entry (0x01107C70)
                if (umem_pc_pa_read_req_addr == 32'h01107C70) begin
                    automatic logic [31:0] elf_addr;
                    elf_addr = cpu.rf[3][31:0];
                    $display("[%0d] PARSE_ELF32: buf=r3=0x%08x first_word=0x%08x (expect 0x7F454C46)",
                        debug_cycle, elf_addr, main_memory[elf_addr[27:3]][63:32]);
                end
                // Error path: printf before exit (0x01100B68)
                if (umem_pc_pa_read_req_addr == 32'h01100B68)
                    $display("[%0d] PREP_KERNEL ERROR: Not a valid ELF - about to print error and exit", debug_cycle);
                // Second partial_decompress call (0x01100AB0)
                if (umem_pc_pa_read_req_addr == 32'h01100AB0)
                    $display("[%0d] PREP_KERNEL->partial_decompress(2nd): compressed=r3=0x%016x size=r4=0x%016x outbuf=r5=0x%016x loadsize=r6=0x%016x skip=r7=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
                // partial_decompress: check gzip magic (0x01106234)
                if (umem_pc_pa_read_req_addr == 32'h01106234)
                    $display("[%0d] PARTIAL_DECOMPRESS: checking gzip magic at r28=0x%016x, first_byte=r9 loaded next...",
                        debug_cycle, cpu.rf[28]);
                // partial_decompress: gzip magic byte check at 0x01106238
                if (umem_pc_pa_read_req_addr == 32'h01106238)
                    $display("[%0d] GZIP_MAGIC_1: byte[0]=r9=0x%016x (expect 0x1f)",
                        debug_cycle, cpu.rf[9]);
                // partial_decompress: second gzip magic byte check at 0x01106244
                if (umem_pc_pa_read_req_addr == 32'h01106244)
                    $display("[%0d] GZIP_MAGIC_2: byte[1]=r9=0x%016x (expect 0x8b)",
                        debug_cycle, cpu.rf[9]);
            end
            // === Trace parse_elf64 function ===
                // parse_elf64 at 0x01107B50 in new build
                if (umem_pc_pa_read_req_addr >= 32'h01107B50 &&
                    umem_pc_pa_read_req_addr <= 32'h01107D00) begin
                    $display("[%0d] ELF: PC=0x%08x instr=0x%08x r3=0x%016x r8=0x%016x r9=0x%016x r10=0x%016x CR=0x%08x ea=0x%08x ea_d=0x%016x",
                        debug_cycle, umem_pc_pa_read_req_addr, debug_instr,
                        cpu.rf[3], cpu.rf[8], cpu.rf[9], cpu.rf[10], cpu.cr_rd,
                        umem_ea_pa_read_req_addr, umem_ea_pa_read_resp_data);
                end
                // Also trace prep_kernel around the call to parse_elf64
                if (umem_pc_pa_read_req_addr >= 32'h01100A00 &&
                    umem_pc_pa_read_req_addr <= 32'h01100A30) begin
                    $display("[%0d] PREP: PC=0x%08x instr=0x%08x r3=0x%016x r31=0x%016x LR=0x%016x",
                        debug_cycle, umem_pc_pa_read_req_addr, debug_instr,
                        cpu.rf[3], cpu.rf[31], cpu.lr);
                end

                // === Kernel memcpy entry trace (0x36380) ===
                // memcpy(dest=r3, src=r4, count=r5), LR=caller
                if (umem_pc_pa_read_req_addr == 32'h00036380)
                    $display("[%0d] KERN_MEMCPY: dest=r3=0x%016x src=r4=0x%016x count=r5=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.lr);

                // === vsnprintf entry trace (0x4512e0) ===
                // vsnprintf(buf=r3, size=r4, fmt=r5, args=r6), LR=caller
                if (umem_pc_pa_read_req_addr == 32'h004512e0)
                    $display("[%0d] VSNPRINTF: buf=r3=0x%016x size=r4=0x%016x fmt=r5=0x%016x args=r6=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.lr);

                // === _printk entry trace (0x7c4a0) ===
                if (umem_pc_pa_read_req_addr == 32'h0007c4a0)
                    $display("[%0d] PRINTK: fmt=r3=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.lr);

                // === memcpy return trace (blr at 0x36558) ===
                if (umem_pc_pa_read_req_addr == 32'h00036558)
                    $display("[%0d] KERN_MEMCPY_RET: r3(dest)=0x%016x LR=0x%016x",
                        debug_cycle, cpu.rf[3], cpu.lr);

            prev_pc <= umem_pc_pa_read_req_addr;
        end
    end

    // =========================================================================
    // Boot Image Loading
    // =========================================================================
    string kernel_image;
    string dtb_image;
    integer kernel_file;
    integer dtb_file;
    integer word_count;
    reg [7:0] byte_data;
    integer j;
    integer bytes_read;
    integer load_addr_int;
    integer load_word_base;

    initial begin
        // Initialize memory to zero
        for (integer i = 0; i < MEM_WORDS; i = i + 1) begin
            main_memory[i] = 64'h0000000000000000;
        end

        // Determine load address (default: 0 for test programs, use +load_addr for ELF binaries)
        load_addr_int = 0;
        if ($value$plusargs("load_addr=%h", load_addr_int)) begin
            $display("Load address override: 0x%08x", load_addr_int);
        end
        load_word_base = load_addr_int / 8;
        reset_pc = {32'd0, load_addr_int};

        // Optional separate entry point (overrides reset_pc without changing load address)
        // Use +entry=ADDR when load address differs from execution start address
        // e.g., preloaded binary loaded at 0 but boot wrapper entry at 0x01100000
        begin
            integer entry_addr_int;
            if ($value$plusargs("entry=%h", entry_addr_int)) begin
                reset_pc = {32'd0, entry_addr_int};
                $display("Entry point override: 0x%08x", entry_addr_int);
            end
        end

        // Load kernel image
        if (!$value$plusargs("kernel=%s", kernel_image)) begin
            kernel_image = "vmlinux.bin";
        end

        kernel_file = $fopen(kernel_image, "rb");
        if (kernel_file == 0) begin
            $display("ERROR: Could not open kernel image: %s", kernel_image);
            $finish;
        end

        $display("OpenPOWER SoC Linux Boot Testbench");
        $display("===================================");
        $display("Loading kernel image: %s at 0x%08x", kernel_image, load_addr_int);

        // Load kernel as big-endian binary (PowerPC native byte order)
        word_count = 0;
        while (!$feof(kernel_file)) begin
            logic [7:0] file_bytes [0:7];
            // Read 8 bytes (one doubleword)
            for (j = 0; j < 8; j = j + 1) begin
                bytes_read = $fread(byte_data, kernel_file);
                file_bytes[j] = (bytes_read == 1) ? byte_data : 8'd0;
            end

            // Big-endian: first byte goes to MSB
            main_memory[load_word_base + word_count][63:56] = file_bytes[0];
            main_memory[load_word_base + word_count][55:48] = file_bytes[1];
            main_memory[load_word_base + word_count][47:40] = file_bytes[2];
            main_memory[load_word_base + word_count][39:32] = file_bytes[3];
            main_memory[load_word_base + word_count][31:24] = file_bytes[4];
            main_memory[load_word_base + word_count][23:16] = file_bytes[5];
            main_memory[load_word_base + word_count][15:8]  = file_bytes[6];
            main_memory[load_word_base + word_count][7:0]   = file_bytes[7];
            word_count = word_count + 1;
        end
        $fclose(kernel_file);
        $display("Loaded %0d doublewords (%0d bytes)", word_count, word_count * 8);

        // Optionally load DTB
        if ($value$plusargs("dtb=%s", dtb_image)) begin
            dtb_file = $fopen(dtb_image, "rb");
            if (dtb_file != 0) begin
                // Load DTB at a known location (e.g., 0x01F00000 = 31MB)
                integer dtb_base = 32'h01F00000 >> 3;  // Word address
                integer dtb_words = 0;
                while (!$feof(dtb_file)) begin
                    for (j = 7; j >= 0; j = j - 1) begin
                        bytes_read = $fread(byte_data, dtb_file);
                        if (bytes_read == 1)
                            main_memory[dtb_base + dtb_words][j*8 +: 8] = byte_data;
                    end
                    dtb_words = dtb_words + 1;
                end
                $fclose(dtb_file);
                $display("Loaded DTB: %s (%0d bytes) at 0x%08x",
                         dtb_image, dtb_words * 8, dtb_base * 8);
            end
        end

        // NOTE: All address-specific patches from previous kernel build are disabled.
        // The current kernel (6.8.0 BE) has different symbol addresses.
        // Re-enable and update addresses only if specific issues are hit.
        $display("Memory patches disabled (stale addresses from previous kernel build)");

        // Verify FDT header at expected location (0x01111B68)
        if (load_addr_int != 0) begin
            integer dtb_word_idx;
            dtb_word_idx = 32'h01111B68 >> 3;
            $display("FDT verification at memory address 0x01111B68 (word index 0x%06x):", dtb_word_idx);
            $display("  Word[0] (magic+totalsize): 0x%016x", main_memory[dtb_word_idx]);
            $display("  Word[1] (off_dt_struct+off_dt_strings): 0x%016x", main_memory[dtb_word_idx+1]);
            $display("  Word[2] (off_mem_rsvmap+version): 0x%016x", main_memory[dtb_word_idx+2]);
            $display("  Word[3] (last_comp_ver+boot_cpuid): 0x%016x", main_memory[dtb_word_idx+3]);
            $display("  Word[4] (size_dt_strings+size_dt_struct): 0x%016x", main_memory[dtb_word_idx+4]);
            // Check magic
            if (main_memory[dtb_word_idx][63:32] == 32'hD00DFEED)
                $display("  FDT magic OK: 0xD00DFEED");
            else
                $display("  FDT magic WRONG: 0x%08x (expected 0xD00DFEED)", main_memory[dtb_word_idx][63:32]);
        end

        // Start
        reset = 1;
        repeat (20) @(posedge clk);
        reset = 0;

        // FDT address: set r3 for the kernel boot.
        // Priority: 1) +fdt_addr=  2) +dtb= loaded file  3) auto-detect in image
        begin
            integer fdt_addr_int;
            integer fdt_found;
            fdt_found = 0;
            if ($value$plusargs("fdt_addr=%h", fdt_addr_int)) begin
                cpu.rf[3] = {32'd0, fdt_addr_int};
                $display("FDT address set in r3: 0x%08x (from +fdt_addr)", fdt_addr_int);
                fdt_found = 1;
            end
            // If external DTB was loaded via +dtb=, use its address (0x01F00000)
            if (!fdt_found && main_memory[32'h01F00000 >> 3][63:32] == 32'hD00DFEED) begin
                fdt_addr_int = 32'h01F00000;
                cpu.rf[3] = {32'd0, fdt_addr_int};
                $display("FDT address set in r3: 0x%08x (from +dtb= loaded file, size=%0d)",
                    fdt_addr_int, main_memory[32'h01F00000 >> 3][31:0]);
                fdt_found = 1;
            end
            // Auto-detect: scan for FDT magic in loaded image
            if (!fdt_found) begin
                integer scan_idx;
                for (scan_idx = 32'h100000 >> 3; scan_idx < 32'h02000000 >> 3; scan_idx = scan_idx + 1) begin
                    if (!fdt_found && main_memory[scan_idx][63:32] == 32'hD00DFEED) begin
                        if (main_memory[scan_idx][31:0] >= 32'h00000400 &&
                            main_memory[scan_idx][31:0] < 32'h00010000 &&
                            main_memory[scan_idx+1][31:0] >= 32'h00000011) begin
                            fdt_addr_int = scan_idx << 3;
                            cpu.rf[3] = {32'd0, fdt_addr_int};
                            $display("FDT auto-detected at 0x%08x (magic=0xD00DFEED, size=%0d), set in r3",
                                fdt_addr_int, main_memory[scan_idx][31:0]);
                            fdt_found = 1;
                        end
                    end
                end
                if (!fdt_found)
                    $display("WARNING: No FDT found in loaded image, r3=0 (kernel may hang)");
            end
        end

        $display("Starting execution at PC=0x%08x", reset_pc);
        $display("Memory: 0x00000000 - 0x%08x", MEMORY_SIZE - 1);
        $display("Peripherals: 0x%08x - 0x%08x", PERIPH_BASE, PERIPH_BASE + PERIPH_SIZE - 1);
    end

    // =========================================================================
    // Missing Instruction Fix: mftbu (mfspr rt, SPR 269 = TBU)
    // =========================================================================
    // The CPU doesn't implement SPR 269 (Time Base Upper). Detect the mfspr
    // instruction pattern and inject the correct TBU value into the dest reg.
    // Encoding: opcode=31, XO=339, SPR field: instr[20:16]=13, instr[15:11]=8
    logic [63:0] udelay_target_tb;
    always @(posedge clk) begin
        if (!reset && umem_pc_pa_read_req_addr != prev_pc) begin
            // General mftbu fix: detect mfspr rt, 269 instruction pattern
            begin
                automatic logic [31:0] mftbu_instr;
                mftbu_instr = umem_pc_pa_read_req_addr[2] ?
                              umem_pc_pa_read_resp_data[31:0] :
                              umem_pc_pa_read_resp_data[63:32];
                if (mftbu_instr[31:26] == 6'd31 &&
                    mftbu_instr[10:1]  == 10'd339 &&
                    mftbu_instr[20:16] == 5'd13 &&
                    mftbu_instr[15:11] == 5'd8) begin
                    // Inject upper 32 bits of timebase into dest register
                    cpu.rf[mftbu_instr[25:21]] <= {32'd0, timebase[63:32]};
                end
            end
            // Simulation udelay fast-skip: when we enter the wait loop at
            // 0x011030B8 (label 2 of udelay), fast-forward the timebase past
            // the target {r8, r9} so the loop exits in 1-2 iterations.
            if (umem_pc_pa_read_req_addr == 32'h011030B8) begin
                udelay_target_tb = {cpu.rf[8][31:0], cpu.rf[9][31:0]};
                if (timebase < udelay_target_tb) begin
                    timer.timebase <= udelay_target_tb + 1;
                end
            end
            // Kernel __delay spin-wait fast-skip at 0x00014728:
            // Function: 14724: mftb r10 (start time)
            //           14728: mftb r9 (loop: current time)
            //           1472c: subf r9,r10,r9  (elapsed = current - start)
            //           14730: cmpld r9,r3 (elapsed >= target?)
            //           14734: bge 1471c (done → exit)
            //           1473c: b 14728 (loop back)
            // Intercept at the loop body (14728) not the entry (14724),
            // so r10 already has the start time from the first mftb.
            if (umem_pc_pa_read_req_addr == 32'h00014728) begin
                if (cpu.rf[3] > 0 && cpu.rf[3] < 64'h0000_0100_0000_0000) begin
                    timer.timebase <= timebase + cpu.rf[3][63:0] + 1;
                    if (debug_cycle < 20000000 || debug_cycle % 50000000 == 0)
                        $display("[%0d] DELAY_SKIP: target_ticks=r3=0x%016x, fast-forwarding timebase",
                            debug_cycle, cpu.rf[3]);
                end
            end
        end
    end

    // =========================================================================
    // Boot Wrapper Copy-Flush Accelerator
    // =========================================================================
    // The boot wrapper's relocate() uses a copy-flush function at offset 0xBD24.
    // It copies 64 bytes per outer iteration (8 dwords inner loop + dcbst + icbi).
    // With 17MB of kernel this takes ~14M cycles. Intercept at function entry
    // and do the bulk copy instantly in testbench memory.
    //
    // Function signature at 0xBD24:
    //   r3 = dest base, r4 = src base, r5 = total bytes, r6 = start offset
    // Function body:
    //   bd24: addi r5,r5,-8
    //   bd28: addi r6,r6,-8
    //   bd2c: li r0,8 / mtctr r0       (outer loop: 8 dwords per block)
    //   bd34-bd40: addi r6,8 / ldx / stdx / bdnz (inner copy loop)
    //   bd44-bd4c: dcbst / hwsync / icbi
    //   bd50: cmpld r6,r5 / blt bd2c   (outer loop back)
    //   bd58-bd68: hwsync / restore / isync / blr
    //
    // Called from 0x0110BCF0 (boot wrapper area) and 0xBD1C (relocated copy).
    // We intercept at both 0x0110BD24 and 0x0000BD24.
    always @(posedge clk) begin
        if (!reset && umem_pc_pa_read_req_addr != prev_pc) begin
            if ((umem_pc_pa_read_req_addr == 32'h0110BD24 ||
                 umem_pc_pa_read_req_addr == 32'h0000BD24) &&
                cpu.rf[5][31:0] > 32'h100)  // r5 = byte count, skip if trivial
            begin : fast_copy_flush
                integer fci;
                logic [31:0] cf_dest, cf_src, cf_size, cf_off, cf_ndw;
                cf_dest = cpu.rf[3][31:0];  // low 32 bits (0xC000... → phys 0)
                cf_src  = cpu.rf[4][31:0];
                cf_size = cpu.rf[5][31:0];
                cf_off  = cpu.rf[6][31:0];
                cf_ndw  = (cf_size - cf_off) >> 3;
                $display("[%0d] FAST_COPY_FLUSH: dest=0x%08x src=0x%08x size=0x%08x off=0x%08x (%0d dwords)",
                    debug_cycle, cf_dest, cf_src, cf_size, cf_off, cf_ndw);

                // Bulk copy all doublewords
                for (fci = 0; fci < cf_ndw; fci = fci + 1) begin
                    main_memory[(cf_dest + cf_off + fci*8) >> 3] =
                        main_memory[(cf_src + cf_off + fci*8) >> 3];
                end

                // Set r6 = r5 - 56 so that after the function's addi adjustments
                // and one final inner loop iteration (64 bytes), r6 >= r5 and the
                // outer loop exits naturally via the cmpld/blt.
                // bd24: r5 = r5 - 8  →  cf_size - 8
                // bd28: r6 = r6 - 8  →  (cf_size - 56) - 8 = cf_size - 64
                // inner loop adds 64: r6 = cf_size - 64 + 64 = cf_size
                // cmpld: cf_size >= cf_size - 8  → not-less-than → loop exits
                cpu.rf[6] <= {32'd0, cf_size - 32'd56};

                $display("[%0d] FAST_COPY_FLUSH: done, copied %0d bytes", debug_cycle, cf_ndw * 8);

                // Apply post-copy patches when kernel is copied to address 0
                if (cf_dest == 32'h00000000 && cf_size > 32'h10000) begin
                    // SCC polling loops - NOP the beq instructions
                    main_memory[32'h7B6D][31:0] = 32'h60000000;  // udbg_real_scc_putc
                    main_memory[32'h7B56][31:0] = 32'h60000000;  // udbg_scc_putc
                    main_memory[32'h7B7A][31:0] = 32'h60000000;  // udbg_scc_getc
                    // msgsync NOP
                    main_memory[32'h5B6F][31:0] = 32'h60000000;
                    $display("[%0d] Applied post-copy patches: SCC polling NOPs, msgsync NOP", debug_cycle);
                end
            end
        end
    end

    // =========================================================================
    // Fast Memcpy Accelerator (kernel memcpy.S)
    // =========================================================================
    // Intercept at the kernel's memcpy doubleword loop when CTR is large.
    // Forward loop at 0x01102EB8 (boot wrapper) or equivalent after relocation.
    logic fast_memcpy_done = 0;
    always @(posedge clk) begin
        if (!reset && umem_pc_pa_read_req_addr != prev_pc) begin
            if (umem_pc_pa_read_req_addr == 32'h01102EB8 && cpu.ctr_rd > 100000 && !fast_memcpy_done)
            begin : fast_mcpy
                integer mi;
                logic [31:0] mcpy_src, mcpy_dest;
                logic [31:0] dw_count;
                mcpy_src = cpu.rf[4][31:0] + 4;
                mcpy_dest = cpu.rf[6][31:0] + 4;
                dw_count = cpu.ctr_rd[31:0];
                $display("[%0d] FAST_MEMCPY: dest=0x%08x src=0x%08x dwords=%0d (CTR) - accelerating",
                    debug_cycle, mcpy_dest, mcpy_src, dw_count);
                for (mi = 0; mi < dw_count; mi = mi + 1) begin
                    main_memory[(mcpy_dest + mi*8) >> 3] = main_memory[(mcpy_src + mi*8) >> 3];
                end
                cpu.ctr_rd <= 64'd1;
                cpu.rf[4] <= {32'd0, cpu.rf[4][31:0] + (dw_count - 1) * 8};
                cpu.rf[6] <= {32'd0, cpu.rf[6][31:0] + (dw_count - 1) * 8};
                fast_memcpy_done <= 1;
                $display("[%0d] FAST_MEMCPY: done - %0d bytes", debug_cycle, dw_count * 8);
            end
        end
        if (reset) fast_memcpy_done <= 0;
    end

    // =========================================================================
    // Fast Memset Accelerator (kernel memset 64-byte unrolled loop)
    // =========================================================================
    // The kernel's memset at 0x36130 stores 64 bytes per iteration:
    //   36130-3614c: 8 x std r4,N(r6) (N=0,8,16,24,32,40,48,56)
    //   36150: addi r6,r6,64
    //   36154: bdnz 36130
    // r4 = fill value (usually 0), r6 = dest pointer, CTR = iterations
    always @(posedge clk) begin
        if (!reset && umem_pc_pa_read_req_addr != prev_pc) begin
            // Trace memset entry: r3=dest, r4=value, r5=size, LR=caller
            if (umem_pc_pa_read_req_addr == 32'h000360c8 && debug_cycle < 2000000)
                $display("[%0d] MEMSET_ENTRY: dest=0x%016x val=0x%02x size=0x%016x LR=0x%016x",
                    debug_cycle, cpu.rf[3], cpu.rf[4][7:0], cpu.rf[5], cpu.lr);

            if (umem_pc_pa_read_req_addr == 32'h00036130 && cpu.ctr_rd > 1000)
            begin : fast_memset
                integer msi;
                logic [31:0] ms_dest;
                logic [31:0] ms_orig_count;
                logic [31:0] ms_count;
                logic [63:0] ms_val;
                logic [31:0] ms_addr;
                logic [63:0] ms_vaddr;
                logic ms_is_linear;
                ms_vaddr = cpu.rf[6];
                ms_dest = cpu.rf[6][31:0];
                ms_orig_count = cpu.ctr_rd[31:0];
                ms_count = ms_orig_count;
                ms_val = cpu.rf[4];
                // Only accelerate memset in the linear mapping (PAGE_OFFSET = 0xc000000000000000)
                // For vmemmap or other non-linear mappings, the physical address != low 32 bits
                // so bypassing the MMU would write to wrong locations
                ms_is_linear = (ms_vaddr[63:32] == 32'hc0000000);
                if (!ms_is_linear) begin
                    // Not in linear map - don't accelerate, let the CPU handle it
                    // Don't modify r6 or CTR - the CPU will execute the loop normally
                    if (debug_cycle < 5000000)
                        $display("[%0d] FAST_MEMSET_SKIP: vaddr=0x%016x (not linear map), count=%0d - CPU will handle",
                            debug_cycle, ms_vaddr, ms_orig_count);
                end else begin
                    // Linear map: physical address = low 32 bits of virtual address
                    // Clamp to memory bounds to prevent out-of-bounds writes
                    if (ms_dest >= MEMORY_SIZE)
                        ms_count = 0;
                    else if (ms_dest + ms_count * 64 > MEMORY_SIZE || ms_dest + ms_count * 64 < ms_dest)
                        ms_count = (MEMORY_SIZE - ms_dest) / 64;
                    if (debug_cycle < 5000000 || ms_count > 0)
                        $display("[%0d] FAST_MEMSET: dest=0x%016x (phys 0x%08x) val=0x%016x count=%0d/%0d (%0d bytes)",
                            debug_cycle, ms_vaddr, ms_dest, ms_val, ms_count, ms_orig_count, ms_count * 64);
                    for (msi = 0; msi < ms_count; msi = msi + 1) begin
                        ms_addr = ms_dest + msi * 64;
                        // Skip writes to protected text regions
                        if (text_protection_enabled && (
                            (ms_addr < 32'h00287000) ||
                            (ms_addr >= 32'h01000000 && ms_addr < 32'h01028000))) begin
                            $display("[%0d] FAST_MEMSET: BLOCKED write to text at 0x%08x", debug_cycle, ms_addr);
                        end else begin
                            main_memory[ms_addr[27:3]]     = ms_val;
                            main_memory[(ms_addr+8) >> 3]  = ms_val;
                            main_memory[(ms_addr+16) >> 3] = ms_val;
                            main_memory[(ms_addr+24) >> 3] = ms_val;
                            main_memory[(ms_addr+32) >> 3] = ms_val;
                            main_memory[(ms_addr+40) >> 3] = ms_val;
                            main_memory[(ms_addr+48) >> 3] = ms_val;
                            main_memory[(ms_addr+56) >> 3] = ms_val;
                        end
                    end
                    // Advance past the loop - preserve high 32 bits
                    cpu.rf[6] <= {ms_vaddr[63:32], ms_dest + (ms_orig_count - 1) * 64};
                    cpu.ctr_rd <= 64'd1;
                    if (debug_cycle < 5000000 || ms_count > 0)
                        $display("[%0d] FAST_MEMSET: done", debug_cycle);
                end
            end
        end
    end

    // =========================================================================
    // Data Read Trace for FDT region
    // =========================================================================
    always @(posedge clk) begin
        if (!reset && umem_ea_pa_read_req_valid && !cpu.mem_ext_stall) begin
            // Trace reads from full FDT region (header + struct + strings)
            // FDT base=0x01111B68, size=0x1625, end=0x0111318D
            if (umem_ea_pa_read_req_addr >= 32'h01111B60 && umem_ea_pa_read_req_addr < 32'h01113200 &&
                debug_cycle < 400000)
                $display("[%0d] FDT_READ: addr=0x%08x data=0x%016x PC=0x%08x",
                    debug_cycle, umem_ea_pa_read_req_addr, umem_ea_pa_read_resp_data,
                    umem_pc_pa_read_req_addr);
            // Late FDT reads (header only) for loop detection
            if (umem_ea_pa_read_req_addr >= 32'h01111B60 && umem_ea_pa_read_req_addr < 32'h01111BA0 &&
                debug_cycle >= 400000)
                $display("[%0d] FDT_READ: addr=0x%08x data=0x%016x PC=0x%08x",
                    debug_cycle, umem_ea_pa_read_req_addr, umem_ea_pa_read_resp_data,
                    umem_pc_pa_read_req_addr);
        end
    end

    // =========================================================================
    // Simulation Control
    // =========================================================================
    integer cycle_count = 0;
    integer max_cycles;
    reg [63:0] prev_pc_diag = 0;
    integer stuck_count = 0;
    reg stuck_reported = 0;
    integer isi_count = 0;
    reg [63:0] prev_pidr = 0;

    initial begin
        if (!$value$plusargs("max_cycles=%d", max_cycles))
            max_cycles = 500000000;  // 500M cycles default
    end

    always @(posedge clk) begin
        if (!reset) begin
            cycle_count <= cycle_count + 1;
            // Track PIDR changes
            if (cpu.pidr !== prev_pidr) begin
                $display("[PIDR c=%0d] PIDR changed: 0x%016x -> 0x%016x PC=0x%016x instr=0x%08x LR=0x%016x r3=0x%016x r4=0x%016x r9=0x%016x",
                    cycle_count, prev_pidr, cpu.pidr, cpu.pc_rd, cpu.instr,
                    cpu.lr, cpu.rf[3], cpu.rf[4], cpu.rf[9]);
                prev_pidr <= cpu.pidr;
            end
            // Early debug: trace first 200 cycles
            if (cycle_count < 200) begin
                $display("[DBG c=%0d] PC=0x%04x pc_wr=0x%04x stall=%b instr=0x%08x CTR=0x%016x",
                    cycle_count, cpu.pc[15:0], cpu.pc_wr[15:0], cpu.mem_ext_stall, cpu.instr, cpu.ctr_rd);
            end
            // BC-specific debug (disabled - too much output)
            // if (cpu.bc_enable) begin ... end
            // RFID debug: trace rfid execution and post-rfid MMU state
            if (cpu.rfid_enable) begin
                $display("[RFID c=%0d] PC=0x%016x SRR0=0x%016x SRR1=0x%016x MSR=0x%016x",
                    cycle_count, cpu.pc_rd, cpu.srr0_rd, cpu.srr1_rd, cpu.msr);
                $display("  pc_wr=0x%016x msr_ir=%b prtbl=0x%016x pidr=0x%016x",
                    cpu.pc_wr, cpu.msr_ir, cpu.prtbl, cpu.pidr);
            end
            // ISI debug: trace when instr_trap_taken fires
            if (cpu.instr_trap_taken) begin
                isi_count <= isi_count + 1;
                $display("[ISI #%0d c=%0d] PC=0x%016x pc_wr=0x%016x MSR=0x%016x msr_ir=%b",
                    isi_count, cycle_count, cpu.pc_rd, cpu.pc_wr, cpu.msr, cpu.msr_ir);
                $display("  pc_pa=0x%016x prtbl=0x%016x pidr=0x%016x",
                    cpu.pc_pa, cpu.prtbl, cpu.pidr);
                // Detailed page table walk dump for first 3 ISIs
                if (isi_count < 3) begin : isi_diag
                    automatic logic [63:0] diag_pate0, diag_pate1, diag_prte0, diag_prte1;
                    automatic logic [31:0] diag_part_base, diag_proc_base, diag_rpd_base_addr;
                    automatic logic [31:0] diag_pgd_a, diag_pud_a, diag_pmd_a, diag_pte_a;
                    automatic logic [63:0] diag_pgd_e, diag_pud_e, diag_pmd_e, diag_pte_e;
                    automatic logic [12:0] diag_pgd_idx;
                    automatic logic [8:0]  diag_pud_idx, diag_pmd_idx, diag_pte_idx;
                    // CPU's internal MMU walk signals
                    $display("  === CPU MMU Walk Signals ===");
                    $display("  part_tbl_base=0x%016x pate1=0x%016x", cpu.part_tbl_base, cpu.pate1);
                    $display("  proc_tbl_base=0x%016x prte0=0x%016x", cpu.proc_tbl_base, cpu.prte0);
                    $display("  rpd_base=0x%016x", cpu.rpd_base);
                    $display("  pgd_entry=0x%016x (V=%b L=%b)", cpu.pgd_entry, cpu.pgd_entry[63], cpu.pgd_entry[62]);
                    $display("  pud_entry=0x%016x (V=%b L=%b)", cpu.pud_entry, cpu.pud_entry[63], cpu.pud_entry[62]);
                    $display("  pmd_entry=0x%016x (V=%b L=%b)", cpu.pmd_entry, cpu.pmd_entry[63], cpu.pmd_entry[62]);
                    $display("  pte_entry=0x%016x (V=%b L=%b)", cpu.pte_entry, cpu.pte_entry[63], cpu.pte_entry[62]);
                    $display("  translation_valid=%b translation_fault=%b",
                        cpu.translation_valid, cpu.translation_fault);
                    // Walk port addresses
                    $display("  === Walk Port Addresses ===");
                    $display("  pate1_addr_port=0x%08x data=0x%016x",
                        umem_pate1_addr_read_req_addr, umem_pate1_addr_read_resp_data);
                    $display("  prte0_addr_port=0x%08x data=0x%016x",
                        umem_prte0_addr_read_req_addr, umem_prte0_addr_read_resp_data);
                    $display("  pgd_addr_port=0x%08x data=0x%016x",
                        umem_pgd_addr_read_req_addr, umem_pgd_addr_read_resp_data);
                    $display("  pud_addr_port=0x%08x data=0x%016x",
                        umem_pud_addr_read_req_addr, umem_pud_addr_read_resp_data);
                    $display("  pmd_addr_port=0x%08x data=0x%016x",
                        umem_pmd_addr_read_req_addr, umem_pmd_addr_read_resp_data);
                    $display("  pte_addr_port=0x%08x data=0x%016x",
                        umem_pte_addr_read_req_addr, umem_pte_addr_read_resp_data);
                    // Independent walk from testbench main_memory
                    diag_part_base = {cpu.prtbl[31:12], 12'd0};
                    diag_pate0 = main_memory[diag_part_base[27:3]];
                    diag_pate1 = main_memory[(diag_part_base[27:3]) + 1];
                    $display("  === Testbench Memory Walk ===");
                    $display("  PartTbl @0x%08x: PATE0=0x%016x PATE1=0x%016x",
                        diag_part_base, diag_pate0, diag_pate1);
                    diag_proc_base = {diag_pate1[31:12], 12'd0};
                    diag_prte0 = main_memory[(diag_proc_base >> 3) + (cpu.pidr[15:0] * 2)];
                    diag_prte1 = main_memory[(diag_proc_base >> 3) + (cpu.pidr[15:0] * 2) + 1];
                    $display("  ProcTbl @0x%08x+PID(%0d)*16: PRTE0=0x%016x PRTE1=0x%016x",
                        diag_proc_base, cpu.pidr[15:0], diag_prte0, diag_prte1);
                    // Also dump PID=0 entry for comparison
                    $display("  ProcTbl PID=0: PRTE0=0x%016x PRTE1=0x%016x",
                        main_memory[diag_proc_base >> 3],
                        main_memory[(diag_proc_base >> 3) + 1]);
                    diag_rpd_base_addr = {diag_prte0[31:12], 12'd0};
                    diag_pgd_idx = cpu.pc_rd[51:39];
                    diag_pud_idx = cpu.pc_rd[38:30];
                    diag_pmd_idx = cpu.pc_rd[29:21];
                    diag_pte_idx = cpu.pc_rd[20:12];
                    $display("  EA=0x%016x: PGD_idx=%0d PUD_idx=%0d PMD_idx=%0d PTE_idx=%0d page_off=0x%03x",
                        cpu.pc_rd, diag_pgd_idx, diag_pud_idx, diag_pmd_idx, diag_pte_idx, cpu.pc_rd[11:0]);
                    diag_pgd_a = diag_rpd_base_addr + (diag_pgd_idx << 3);
                    diag_pgd_e = main_memory[diag_pgd_a[27:3]];
                    $display("  PGD @0x%08x [rpd=0x%08x + idx*8]: entry=0x%016x V=%b L=%b",
                        diag_pgd_a, diag_rpd_base_addr, diag_pgd_e, diag_pgd_e[63], diag_pgd_e[62]);
                    if (diag_pgd_e[63] && !diag_pgd_e[62]) begin
                        diag_pud_a = {diag_pgd_e[31:12], 12'd0} + (diag_pud_idx << 3);
                        diag_pud_e = main_memory[diag_pud_a[27:3]];
                        $display("  PUD @0x%08x: entry=0x%016x V=%b L=%b",
                            diag_pud_a, diag_pud_e, diag_pud_e[63], diag_pud_e[62]);
                        if (diag_pud_e[63] && !diag_pud_e[62]) begin
                            diag_pmd_a = {diag_pud_e[31:12], 12'd0} + (diag_pmd_idx << 3);
                            diag_pmd_e = main_memory[diag_pmd_a[27:3]];
                            $display("  PMD @0x%08x: entry=0x%016x V=%b L=%b",
                                diag_pmd_a, diag_pmd_e, diag_pmd_e[63], diag_pmd_e[62]);
                            if (diag_pmd_e[63] && !diag_pmd_e[62]) begin
                                diag_pte_a = {diag_pmd_e[31:12], 12'd0} + (diag_pte_idx << 3);
                                diag_pte_e = main_memory[diag_pte_a[27:3]];
                                $display("  PTE @0x%08x: entry=0x%016x V=%b L=%b RPN=0x%09x",
                                    diag_pte_a, diag_pte_e, diag_pte_e[63], diag_pte_e[62],
                                    diag_pte_e[56:12]);
                            end
                        end
                    end
                    $display("  === End ISI Diagnostic ===");
                end
            end
            // MMU page table walk debug: trace when msr_ir is set
            if (cpu.msr_ir && cycle_count < 10000) begin
                $display("[MMU c=%0d] PC=0x%016x pc_pa=0x%016x msr_ir=%b instr_trap=%b stall=%b",
                    cycle_count, cpu.pc_rd, cpu.pc_pa, cpu.msr_ir, cpu.instr_trap_taken, cpu.mem_ext_stall);
            end
            // Progress report every 1M cycles
            if (cycle_count % 1000000 == 0 && cycle_count > 0) begin
                $display("[cycle %0d] PC=0x%08x CTR=0x%016x stall=%b pc_rdy=%b ea_req=%b ea_addr=0x%08x ea_rdy=%b wr_req=%b",
                    cycle_count, cpu.pc_rd, cpu.ctr_rd, cpu.mem_ext_stall,
                    umem_pc_pa_read_resp_ready,
                    umem_ea_pa_read_req_valid, umem_ea_pa_read_req_addr,
                    umem_ea_pa_read_resp_ready,
                    umem_write_req_valid);
            end
            if (0 && cycle_count % 1000000 == 0 && cycle_count > 0) begin
                $display("[cycle %0d] PC=0x%08x CTR=0x%016x stall=%b ea_req=%b wr_req=%b",
                    cycle_count, cpu.pc_rd, cpu.ctr_rd, cpu.mem_ext_stall,
                    umem_ea_pa_read_req_valid,
                    umem_write_req_valid);
            end
            // Detect stuck PC (no change for 100 cycles)
            if (cpu.pc_rd == prev_pc_diag)
                stuck_count <= stuck_count + 1;
            else begin
                stuck_count <= 0;
                prev_pc_diag <= cpu.pc_rd;
            end
            if (stuck_count == 100 && !stuck_reported) begin : stuck_diag
                automatic logic [63:0] pt_base, part_entry, proc_entry, pgd_entry;
                automatic logic [31:0] part_addr, proc_addr, pgd_addr, pud_addr, pmd_addr, pte_addr;
                automatic logic [31:0] stuck_phys;
                stuck_phys = cpu.pc_rd[31:0];  // Physical for linear map
                $display("[STUCK] cycle=%0d PC=0x%016x instr=0x%08x mfspr_en=%b pc_add4=%016x pc_wr=%016x sel_add4=%b",
                    cycle_count, cpu.pc_rd, cpu.instr, cpu.mfspr_enable, cpu.pc_add_4, cpu.pc_wr, cpu.select_pc_add_4_pc_merged);
                $display("[STUCK]   prtbl=0x%016x pidr=0x%016x msr=0x%016x msr_ir=%b",
                    cpu.prtbl, cpu.pidr, cpu.msr_rd, cpu.msr_ir);
                $display("[STUCK]   pc_pa=0x%016x pc_pa_req_addr=0x%08x pc_pa_resp_ready=%b",
                    cpu.pc_pa, umem_pc_pa_read_req_addr, umem_pc_pa_read_resp_ready);
                // Dump page table entries for the stuck address
                // Partition table: at prtbl + 0 (PATE0) and prtbl + 8 (PATE1)
                pt_base = {cpu.prtbl[63:12], 12'd0};
                part_addr = pt_base[31:0];
                $display("[STUCK]   PTCR base=0x%08x PATE0=0x%016x PATE1=0x%016x",
                    part_addr, main_memory[part_addr[27:3]], main_memory[(part_addr+8) >> 3]);
                // Process table base from PATE1 bits [55:12], shifted left 12
                part_entry = main_memory[(part_addr+8) >> 3];  // PATE1
                proc_addr = {part_entry[51:12], 12'd0};
                $display("[STUCK]   ProcTbl base=0x%08x PRTE0=0x%016x PRTE1=0x%016x",
                    proc_addr[31:0], main_memory[proc_addr[27:3]], main_memory[(proc_addr+8) >> 3]);
                // RPD base from PRTE0 bits [55:12], shifted left 12
                proc_entry = main_memory[proc_addr[27:3]];  // PRTE0
                pgd_addr = {proc_entry[55:12], 12'd0};
                $display("[STUCK]   PGD base=0x%08x entry[0]=0x%016x entry[1]=0x%016x",
                    pgd_addr[31:0], main_memory[pgd_addr[27:3]], main_memory[(pgd_addr+8) >> 3]);
                // Memory at the stuck physical address
                $display("[STUCK]   mem[0x%08x]=0x%016x", stuck_phys, main_memory[stuck_phys[27:3]]);
                // Register dump
                $display("[STUCK]   r0=0x%016x  r1(sp)=0x%016x  r2(toc)=0x%016x  r3=0x%016x",
                    cpu.rf[0], cpu.rf[1], cpu.rf[2], cpu.rf[3]);
                $display("[STUCK]   r4=0x%016x  r5=0x%016x  r6=0x%016x  r7=0x%016x",
                    cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7]);
                $display("[STUCK]   r13=0x%016x  LR=0x%016x  CR=0x%08x  XER=0x%016x",
                    cpu.rf[13], cpu.lr, cpu.cr_rd, cpu.xer);
                $display("[STUCK]   SRR0=0x%016x  SRR1=0x%016x  CTR=0x%016x",
                    cpu.srr0, cpu.srr1, cpu.ctr_rd);
                // Stack backtrace
                begin : stuck_stack
                    automatic integer si;
                    automatic logic [31:0] sp_phys;
                    sp_phys = cpu.rf[1][31:0];
                    $display("=== STACK BACKTRACE (sp=0x%08x) ===", sp_phys);
                    for (si = 0; si < 20; si = si + 1) begin
                        if (sp_phys != 0 && sp_phys < 32'h0FFFFFFF) begin
                            $display("  frame[%0d]: sp=0x%08x backchain=0x%016x LR=0x%016x",
                                si, sp_phys,
                                main_memory[sp_phys[27:3]],
                                main_memory[(sp_phys + 16) >> 3]);
                            sp_phys = main_memory[sp_phys[27:3]][31:0];
                        end
                    end
                end
                // Dump kernel log buffer (__log_buf @ 0x10e9b68, 8192 bytes)
                begin : stuck_logbuf
                    automatic integer li;
                    automatic logic [31:0] log_base;
                    log_base = 32'h10e9b68;
                    $display("=== KERNEL LOG BUFFER (__log_buf @ 0x%08x) ===", log_base);
                    for (li = 0; li < 1024; li = li + 1) begin
                        if (main_memory[(log_base >> 3) + li] != 64'h0)
                            $display("  [+0x%04x] %016x",
                                li * 8,
                                main_memory[(log_base >> 3) + li]);
                    end
                    $display("=== END LOG BUFFER ===");
                end
                stuck_reported <= 1;
                // Don't finish - let simulation continue past stuck loops
                // Reset stuck detection to allow continued monitoring
                stuck_count <= 0;
                prev_pc_diag <= 64'h0;
            end
            if (cycle_count >= max_cycles) begin
                $display("TIMEOUT after %0d cycles at PC=0x%016x", cycle_count, cpu.pc_rd);
                if (uart_log_fd != 0) $fclose(uart_log_fd);
                $finish;
            end
        end
    end

endmodule

`default_nettype wire
