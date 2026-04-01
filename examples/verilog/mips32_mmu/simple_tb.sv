`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;

    // Reset value wires - all tied to zero except where needed
    wire [31:0] zero32 = 32'd0;
    wire zero1 = 1'b0;

    // CP0 Status register reset value:
    // - BEV=0 (bit 22): Normal exception vectors (0x8000xxxx)
    // - ERL=0, EXL=0: Normal execution
    // For testing, we start in kernel mode with IE=0 (interrupts disabled)
    wire [31:0] reset_status = 32'h00000000;  // Kernel mode, no exceptions

    // CP0 Config register: MIPS32, little-endian
    wire [31:0] reset_config = 32'h80000000;  // M bit set, Config1 exists

    // PRId: Processor ID (custom implementation)
    wire [31:0] reset_prid = 32'h00000001;  // Simple ID

    // Random register starts at TLB size-1 (31 for 32-entry TLB)
    wire [31:0] reset_random = 32'd31;

    // Configurable reset PC (default kseg0)
    reg [31:0] reset_pc_val = 32'h80000000;

    mips32_mmu dut (
        .clk(clk),
        .reset(reset),
        .reset_pc(reset_pc_val),             // Configurable start address
        .reset_cp0_badvaddr_rd(zero32),
        .reset_cp0_cause_rd(zero32),
        .reset_cp0_compare_rd(zero32),
        .reset_cp0_config_rd(reset_config),
        .reset_cp0_context_rd(zero32),
        .reset_cp0_count_rd(zero32),
        .reset_cp0_entryhi(zero32),
        .reset_cp0_entrylo0(zero32),
        .reset_cp0_entrylo1(zero32),
        .reset_cp0_epc_rd(zero32),
        .reset_cp0_errorepc_rd(zero32),
        .reset_cp0_index_rd(zero32),
        .reset_cp0_prid_rd(reset_prid),
        .reset_cp0_random_rd(reset_random),
        .reset_cp0_status_rd(reset_status),
        .reset_cp0_wired_rd(zero32),
        .reset_hi(zero32),
        .reset_lladdr_rd(zero32),
        .reset_llbit_rd(zero1),
        .reset_lo(zero32)
    );

    reg [31:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    // UART monitoring - physical address 0x000FF000 = word address 0x3FC00
    reg [31:0] last_uart_val = 32'h0;
    localparam UART_WORD_ADDR = 18'h3FC00;  // 0xFF000 / 4

    always @(posedge clk) begin
        if (!reset && dut.umem[UART_WORD_ADDR] != last_uart_val) begin
            // UART write detected - print character
            $write("%c", dut.umem[UART_WORD_ADDR][7:0]);
            last_uart_val <= dut.umem[UART_WORD_ADDR];
        end
    end

    initial begin
        clk = 0; reset = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;
        if (!$value$plusargs("reset_pc=%h", reset_pc_val)) reset_pc_val = 32'h80000000;
        $readmemh("umem.hex", dut.umem);
        $readmemh("rf.hex", dut.rf);
        // Load TLB arrays for MMU tests
        $readmemh("tlb_vpn2.hex", dut.tlb_vpn2);
        $readmemh("tlb_asid.hex", dut.tlb_asid);
        $readmemh("tlb_hi.hex", dut.tlb_hi);
        $readmemh("tlb_lo0.hex", dut.tlb_lo0);
        $readmemh("tlb_lo1.hex", dut.tlb_lo1);
        $readmemh("tlb_pfn0.hex", dut.tlb_pfn0);
        $readmemh("tlb_pfn1.hex", dut.tlb_pfn1);
        $readmemh("tlb_v0.hex", dut.tlb_v0);
        $readmemh("tlb_v1.hex", dut.tlb_v1);
        $readmemh("tlb_d0.hex", dut.tlb_d0);
        $readmemh("tlb_d1.hex", dut.tlb_d1);
        $readmemh("tlb_g.hex", dut.tlb_g);
        repeat(3) @(posedge clk);
        reset = 0;
        for (i = 0; i < 5000; i = i + 1) begin
            @(posedge clk);
            // Debug: print first 50 cycles
            if (i < 50) begin
                $display("Cycle %0d: PC=0x%08x instr=0x%08x $8=%d $9=%d $10=%d", i, dut.pc, dut.instr, dut.rf[8], dut.rf[9], dut.rf[10]);
            end
            // Check PC for pass/fail
            // Handle both kseg0 and kuseg addresses (they map to same physical address)
            // kseg0: 0x80000000-0x9FFFFFFF -> physical 0x00000000-0x1FFFFFFF
            // kuseg: 0x00000000-0x7FFFFFFF -> uses TLB, identity-mapped in our tests
            if (dut.pc == pass_addr || dut.pc == (pass_addr & 32'h1FFFFFFF)) begin $display("TEST PASSED"); $finish; end
            if (dut.pc == fail_addr || dut.pc == (fail_addr & 32'h1FFFFFFF)) begin $display("TEST FAILED at pc=%h testnum=%d", dut.pc, dut.rf[2]); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
