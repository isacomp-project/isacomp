`timescale 1ns/1ps
// Simple testbench for 6502 that doesn't require DPI co-simulation
// Just runs the Dormann test and checks for pass/fail addresses

module cpu_6502_test_tb;

    // Clock and reset
    reg clk;
    reg reset;

    // Reset values
    reg [15:0] reset_pc;
    reg [7:0] reset_A_val;
    reg [7:0] reset_X_val;
    reg [7:0] reset_Y_val;
    reg [7:0] reset_S_val;
    reg reset_flag_C_val;
    reg reset_flag_V_val;
    reg reset_flag_N_val;
    reg reset_flag_Z_val;
    reg reset_flag_D_val;
    reg reset_flag_I_val;

    // Device Under Test
    cpu_6502_test dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(reset_pc),
        .reset_A(reset_A_val),
        .reset_flag_C(reset_flag_C_val),
        .reset_flag_V_rd(reset_flag_V_val),
        .reset_flag_N_rd(reset_flag_N_val),
        .reset_flag_Z_rd(reset_flag_Z_val),
        .reset_flag_D_rd(reset_flag_D_val),
        .reset_Y(reset_Y_val),
        .reset_flag_I_rd(reset_flag_I_val),
        .reset_X(reset_X_val),
        .reset_S(reset_S_val)
    );

    // Clock generation
    initial clk = 0;
    always #5 clk = ~clk;  // 10ns period = 100MHz

    // Test execution
    integer cycle_count;
    reg [15:0] prev_pc;
    integer pc_stall_count;
    reg [15:0] pass_pc;
    reg [15:0] fail_pc;

    initial begin
        pass_pc = 16'h3469;  // Dormann test pass address
        fail_pc = 16'h3463;  // Dormann test fail address

        $display("6502 Simple Testbench");
        $display("Pass address: 0x%04x", pass_pc);
        $display("Fail address: 0x%04x", fail_pc);

        // Default reset values
        reset_pc = 16'h0400;
        reset_A_val = 8'h00;
        reset_X_val = 8'h00;
        reset_Y_val = 8'h00;
        reset_S_val = 8'hFF;
        reset_flag_N_val = 1'b0;
        reset_flag_V_val = 1'b0;
        reset_flag_D_val = 1'b0;
        reset_flag_I_val = 1'b1;
        reset_flag_Z_val = 1'b0;
        reset_flag_C_val = 1'b0;

        // Load memory from imem.hex
        $display("Loading memory from imem.hex");
        $readmemh("imem.hex", dut.mainmem);

        // Reset sequence
        cycle_count = 0;
        pc_stall_count = 0;
        prev_pc = 16'h0;
        reset = 1;

        repeat(5) @(posedge clk);
        reset = 0;

        $display("Reset released, starting execution at PC=0x%04x", dut.pc_rd);

        // Monitor execution
        forever begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Progress report every 100K cycles
            if (cycle_count % 100000 == 0) begin
                $display("Cycle %0d: PC = 0x%04x A=0x%02x X=0x%02x Y=0x%02x D=%b",
                         cycle_count, dut.pc_rd, dut.A, dut.X, dut.Y, dut.flag_D_rd);
            end

            // Timeout after 100M cycles
            if (cycle_count >= 100000000) begin
                $display("ERROR: Timeout after %0d cycles", cycle_count);
                $display("Final PC: 0x%04x", dut.pc_rd);
                $display("FAILED");
                $finish(1);
            end

            // Check for pass condition
            if (dut.pc_rd == pass_pc) begin
                $display("*** TEST PASSED *** at cycle %0d (PC=0x%04x)", cycle_count, pass_pc);
                $finish(0);
            end

            // Check for fail condition
            if (dut.pc_rd == fail_pc) begin
                $display("*** TEST FAILED *** at cycle %0d (PC=0x%04x)", cycle_count, fail_pc);
                $finish(1);
            end

            // Check for PC stall (e.g., JMP * infinite loop)
            if (dut.pc_rd == prev_pc) begin
                pc_stall_count = pc_stall_count + 1;
                if (pc_stall_count >= 10) begin
                    $display("*** PC STALLED *** at cycle %0d (PC=0x%04x for %0d cycles)",
                             cycle_count, dut.pc_rd, pc_stall_count);
                    // Show some debug info
                    $display("A=0x%02x X=0x%02x Y=0x%02x S=0x%02x", dut.A, dut.X, dut.Y, dut.S);
                    $display("N=%b V=%b D=%b I=%b Z=%b C=%b",
                             dut.flag_N_rd, dut.flag_V_rd, dut.flag_D_rd,
                             dut.flag_I_rd, dut.flag_Z_rd, dut.flag_C);
                    $finish(1);
                end
            end else begin
                pc_stall_count = 0;
                prev_pc = dut.pc_rd;
            end
        end
    end

endmodule
