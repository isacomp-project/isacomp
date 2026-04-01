`timescale 1ns/1ps
module j2_complete_tb;

    // Clock and reset
    reg clk;
    reg reset;

    // Processor interface
    // Reset value signals
    wire [15:0] reset_pc_rd = 16'h0;

    // Memory for ELF loading

    // Device Under Test
    j2_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(reset_pc_rd)
        // Add other ports as needed
    );

    // Clock generation
    initial clk = 0;
    always #(10/2) clk = ~clk;

    // ELF loading and test execution
    integer i;
    integer elf_size;
    reg [31:0] elf_data;
    integer mem_file;
    string elf_file;

    initial begin
        // Get ELF file from plusargs
        if (!$value$plusargs("elf_load=%s", elf_file)) begin
            $display("ERROR: No ELF file specified. Use +elf_load=<file.elf>");
            $finish;
        end

        // Load ELF file using VPI
        $display("Loading ELF file: %s", elf_file);
        $elf_load_file(elf_file);
        elf_size = $elf_get_size();
        $display("ELF size: %0d bytes", elf_size);

        // Write ELF data directly to processor's instruction memory
        $display("Loading %0d bytes into instruction memory...", elf_size);
        for (i = 0; i < elf_size; i = i + 4) begin
            elf_data = $elf_read_32(i);
            // Load into imem (word-addressed)
            dut.imem[i/4] = elf_data;
        end
        $display("Loaded program into instruction memory");

        // Create empty register file if needed
        mem_file = $fopen("rf.mem", "w");
        if (mem_file != 0) begin
            $fclose(mem_file);
        end

        // Create empty dmem.mem if needed
        mem_file = $fopen("dmem.mem", "w");
        if (mem_file != 0) begin
            $fclose(mem_file);
        end

        // Reset sequence - start before memories load
        reset = 1;

        // Wait for memories to be loaded by $readmemh
        #10;

        // Release reset and start execution
        repeat(5) @(posedge clk);
        reset = 0;
        $display("Reset released, starting execution...");
        $display("Initial PC: 0x%08x", dut.pc_rd);
    end

    // Completion detection
    integer cycle_count;
    reg [31:0] pass_pc;
    reg [31:0] fail_pc;
    reg pass_pc_valid;
    reg fail_pc_valid;

    initial begin
        cycle_count = 0;
        pass_pc_valid = 0;
        fail_pc_valid = 0;

        // Extract pass/fail addresses from ELF symbols
        if ($value$plusargs("pass_addr=%h", pass_pc)) begin
            pass_pc_valid = 1;
            $display("Pass address: 0x%08x", pass_pc);
        end

        if ($value$plusargs("fail_addr=%h", fail_pc)) begin
            fail_pc_valid = 1;
            $display("Fail address: 0x%08x", fail_pc);
        end

        @(negedge reset);  // Wait for reset to deassert

        // Monitor execution
        forever begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Debug: Print PC every 100 cycles
            if (cycle_count % 100 == 0) begin
                $display("Cycle %0d: PC = 0x%08x", cycle_count, dut.pc_rd);
            end

            if (cycle_count >= 10000) begin
                $display("ERROR: Timeout after %0d cycles", cycle_count);
                $display("Final PC: 0x%08x", dut.pc_rd);
                $display("FAILED");
                $finish(1);
            end

            // Check for pass condition
            if (pass_pc_valid && dut.pc_rd == pass_pc) begin
                $display("*** TEST PASSED *** at cycle %0d (PC=0x%08x)", cycle_count, pass_pc);
                $finish(0);
            end

            // Check for fail condition
            if (fail_pc_valid && dut.pc_rd == fail_pc) begin
                $display("*** TEST FAILED *** at cycle %0d (PC=0x%08x)", cycle_count, fail_pc);
                $finish(1);
            end

        end
    end

    // Waveform dumping
    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("j2_complete_tb.vcd");
            $dumpvars(0, j2_complete_tb);
        end
    end

endmodule
