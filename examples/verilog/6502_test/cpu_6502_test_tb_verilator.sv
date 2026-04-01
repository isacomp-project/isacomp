`timescale 1ns/1ps
module cpu_6502_test_tb;

    // DPI imports for reference simulator
    import "DPI-C" function void dpi_6502_init(
        input shortint unsigned reset_pc,
        input byte unsigned reset_a,
        input byte unsigned reset_x,
        input byte unsigned reset_y,
        input byte unsigned reset_s,
        input byte unsigned reset_flags
    );

    import "DPI-C" function void dpi_6502_load_mem_byte(
        input shortint unsigned addr,
        input byte unsigned value
    );

    import "DPI-C" function void dpi_6502_finalize_mem();

    import "DPI-C" function void dpi_6502_step();

    import "DPI-C" function int dpi_6502_compare(
        input shortint unsigned rtl_pc,
        input byte unsigned rtl_a,
        input byte unsigned rtl_x,
        input byte unsigned rtl_y,
        input byte unsigned rtl_s,
        input bit rtl_n,
        input bit rtl_v,
        input bit rtl_d,
        input bit rtl_i,
        input bit rtl_z,
        input bit rtl_c
    );

    import "DPI-C" function byte unsigned dpi_6502_get_instr();

    import "DPI-C" function void dpi_6502_rtl_mem_write(
        input shortint unsigned addr,
        input byte unsigned value
    );

    // Checkpoint loading DPI functions (for faster debugging - use make_checkpoint tool)
    import "DPI-C" function longint dpi_6502_load_checkpoint();
    import "DPI-C" function void dpi_6502_get_checkpoint_state(
        output shortint unsigned out_pc,
        output byte unsigned out_a,
        output byte unsigned out_x,
        output byte unsigned out_y,
        output byte unsigned out_s,
        output byte unsigned out_status
    );
    import "DPI-C" function byte unsigned dpi_6502_get_checkpoint_mem(
        input shortint unsigned addr
    );

    // Clock and reset
    reg clk;
    reg reset;

    // Processor interface - dynamic reset values for checkpoint loading
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
        .reset_flag_V(reset_flag_V_val),
        .reset_flag_N(reset_flag_N_val),
        .reset_flag_Z(reset_flag_Z_val),
        .reset_flag_D(reset_flag_D_val),
        .reset_Y(reset_Y_val),
        .reset_flag_I(reset_flag_I_val),
        .reset_X(reset_X_val),
        .reset_S(reset_S_val)
    );

    // Clock generation
    initial clk = 0;
    always #5 clk = ~clk;  // 10ns period = 100MHz

    // Test execution
    integer cycle_count;
    longint start_cycle;
    reg [15:0] prev_pc;
    reg [15:0] prev_prev_pc;  // Track PC from 2 instructions ago
    integer pc_stall_count;
    reg [15:0] pass_pc;
    reg [15:0] fail_pc;
    reg [7:0] prev_mem_01fe;

    // Variables for checkpoint loading
    shortint unsigned ckpt_pc;
    byte unsigned ckpt_a, ckpt_x, ckpt_y, ckpt_s, ckpt_status;

    initial begin
        pass_pc = 16'h3469;  // Dormann test pass address
        fail_pc = 16'h3463;  // Dormann test fail address

        $display("Pass address: 0x%04x", pass_pc);
        $display("Fail address: 0x%04x", fail_pc);

        // Always start from reset (cycle 0)
        start_cycle = 0;
        $display("Starting from reset");

        // Default reset values
        reset_pc = 16'h0400;
        reset_A_val = 8'h00;
        reset_X_val = 8'h00;
        reset_Y_val = 8'h00;
        reset_S_val = 8'hFF;
        reset_flag_N_val = 1'b0;
        reset_flag_V_val = 1'b0;
        reset_flag_D_val = 1'b0;
        reset_flag_I_val = 1'b1;  // Match reference init (status = 0x24)
        reset_flag_Z_val = 1'b0;
        reset_flag_C_val = 1'b0;

        // Load memory from imem.hex
        $display("Loading memory from imem.hex");
        $readmemh("imem.hex", dut.mainmem);
        $display("IRQ vector: 0x%02x%02x (at 0xFFFE:0xFFFF)", dut.mainmem[16'hFFFF], dut.mainmem[16'hFFFE]);

        // Load memory to reference simulator
        for (int i = 0; i < 65536; i = i + 1) begin
            dpi_6502_load_mem_byte(i[15:0], dut.mainmem[i]);
        end
        dpi_6502_finalize_mem();

        // Initialize reference to match RTL reset values
        dpi_6502_init(
            reset_pc,        // PC = 0x0400
            8'h00,           // A = 0
            8'h00,           // X = 0
            8'h00,           // Y = 0
            8'hFF,           // S = 0xFF
            8'h24            // status = 0x24 (flag_I=1)
        );

        // Reset sequence
        cycle_count = 0;
        pc_stall_count = 0;
        prev_pc = 16'h0;
        prev_mem_01fe = 8'h00;
        reset = 1;

        repeat(5) @(posedge clk);
        reset = 0;

        $display("Reset released, starting execution...");
        $display("Initial PC: 0x%04x", dut.pc_rd);

        // Monitor execution
        forever begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            // Track RTL memory writes - call DPI before step
            // Check if any write enable signal is active and call DPI
            if (!reset) begin
                if (dut.pha_enable || dut.php_enable || dut.sta_abs_enable || dut.sta_abs_x_enable ||
                    dut.sta_abs_y_enable || dut.sta_ind_x_enable || dut.sta_ind_y_enable ||
                    dut.sta_zp_enable || dut.sta_zp_x_enable || dut.stx_abs_enable ||
                    dut.stx_zp_enable || dut.stx_zp_y_enable || dut.sty_abs_enable ||
                    dut.sty_zp_enable || dut.sty_zp_x_enable ||
                    dut.asl_abs_enable || dut.asl_abs_x_enable || dut.asl_zp_enable || dut.asl_zp_x_enable ||
                    dut.lsr_abs_enable || dut.lsr_abs_x_enable || dut.lsr_zp_enable || dut.lsr_zp_x_enable ||
                    dut.rol_abs_enable || dut.rol_abs_x_enable || dut.rol_zp_enable || dut.rol_zp_x_enable ||
                    dut.ror_abs_enable || dut.ror_abs_x_enable || dut.ror_zp_enable || dut.ror_zp_x_enable ||
                    dut.inc_abs_enable || dut.inc_abs_x_enable || dut.inc_zp_enable || dut.inc_zp_x_enable ||
                    dut.dec_abs_enable || dut.dec_abs_x_enable || dut.dec_zp_enable || dut.dec_zp_x_enable) begin
                    if (cycle_count <= 10) $display("[TB] RTL write: addr=0x%04x data=0x%02x", dut.mainmem_write_addr_mux, dut.mainmem_write_data_mux[7:0]);
                    dpi_6502_rtl_mem_write(dut.mainmem_write_addr_mux, dut.mainmem_write_data_mux[7:0]);
                end
                if (dut.brk_enable) begin
                    // BRK writes 3 bytes to stack: PC high, PC low, status
                    dpi_6502_rtl_mem_write(dut.brk_stack_addr_hi, dut.mainmem_stack_addr_hi_wr[7:0]);
                    dpi_6502_rtl_mem_write(dut.brk_stack_addr_lo, dut.mainmem_stack_addr_lo_wr[7:0]);
                    dpi_6502_rtl_mem_write(dut.stack_addr_mid, dut.mainmem_stack_addr_wr[7:0]);
                end
                if (dut.jsr_enable) begin
                    // JSR writes return address to stack (2 bytes)
                    dpi_6502_rtl_mem_write(dut.jsr_stack_addr_hi[15:0], dut.mainmem_stack_addr_hi_wr[7:0]);
                    dpi_6502_rtl_mem_write(dut.jsr_stack_addr_lo[15:0], dut.mainmem_stack_addr_lo_wr[7:0]);
                end
            end

            // Co-simulation: Step reference and compare state
            if (!reset && dut.pc_rd != prev_pc) begin
                // PC changed - instruction completed, step reference
                dpi_6502_step();

                // Compare RTL state with reference
                if (dpi_6502_compare(
                    dut.pc_rd,
                    dut.A,
                    dut.X,
                    dut.Y,
                    dut.S,
                    dut.flag_N,
                    dut.flag_V,
                    dut.flag_D,
                    dut.flag_I,
                    dut.flag_Z,
                    dut.flag_C
                ) != 0) begin
                    $display("*** CO-SIMULATION MISMATCH at cycle %0d ***", cycle_count);
                    $display("RTL instr=0x%02x, Ref instr=0x%02x", dut.instr, dpi_6502_get_instr());
                    $finish(1);
                end
            end

            // Debug: Print PC periodically (every 100k cycles for progress tracking)
            if (cycle_count % 100000 == 0) begin
                $display("Cycle %0d: PC = 0x%04x", cycle_count, dut.pc_rd);
            end

            // Debug traces for LDA zp and ADC zp near failure
            // Memory is packed 4 bytes per word: mainmem[addr>>2][(addr&3)*8 +: 8]
            if (cycle_count >= 1960 && cycle_count <= 1975) begin
                $display("  [TRACE] cycle %0d: PC=0x%04x instr=0x%02x A=0x%02x flag_D=%b flag_Z=%b flag_C=%b",
                         cycle_count, dut.pc_rd, dut.instr, dut.A, dut.flag_D, dut.flag_Z, dut.flag_C);
                if (dut.instr == 8'h65) begin  // ADC zp
                    $display("    ADC zp: zp_addr=0x%02x A_rd=0x%02x data=0x%02x flag_C_rd=%b",
                             dut.zp_direct_addr, dut.A_rd, dut.adc_zp_data, dut.flag_C_rd);
                    $display("    ADC zp: bin_result=0x%04x bcd_result=0x%04x result=0x%04x A_wr_mux=0x%02x",
                             dut.adc_zp_bin_result, dut.adc_zp_bcd_result, dut.adc_zp_result, dut.A_wr_mux[7:0]);
                    $display("    ADC zp BCD: low_sum=%d low_adj=%d after_low=%x high_adj=%d",
                             dut.adc_zp_low_nibble_sum, dut.adc_zp_low_adjust, dut.adc_zp_after_low_adj, dut.adc_zp_high_adjust);
                end
            end
            if (cycle_count >= 1 && cycle_count <= 35) begin
                $display("  [TRACE] cycle %0d: PC=0x%04x instr=0x%02x A=0x%02x flag_D=%b flag_C=%b byte[0]=0x%02x byte[1]=0x%02x",
                         cycle_count, dut.pc_rd, dut.instr, dut.A, dut.flag_D, dut.flag_C,
                         dut.mainmem[0][7:0], dut.mainmem[0][15:8]);
                if (dut.instr == 8'hA5) begin  // LDA zp
                    $display("    LDA zp: zp_addr=0x%02x data_read=0x%02x A_wr_mux=0x%02x mainmem[zp]=0x%02x",
                             dut.zp_direct_addr, dut.mainmem_zp_direct_addr_rd, dut.A_wr_mux[7:0],
                             dut.mainmem[dut.zp_direct_addr]);
                end
                if (dut.instr == 8'h65) begin  // ADC zp
                    $display("    ADC zp: zp_addr=0x%02x adc_zp_data=0x%02x mainmem[zp]=0x%02x mainmem_zp_direct_addr_rd=0x%02x",
                             dut.zp_direct_addr, dut.adc_zp_data, dut.mainmem[dut.zp_direct_addr], dut.mainmem_zp_direct_addr_rd);
                    $display("    ADC zp: A_rd=0x%02x carry_in=%b flag_D_rd=%b",
                             dut.A_rd, dut.carry_in, dut.flag_D_rd);
                    $display("    ADC zp: bin_result=0x%04x bcd_result=0x%04x result=0x%04x A_wr_mux=0x%02x",
                             dut.adc_zp_bin_result, dut.adc_zp_bcd_result, dut.adc_zp_result, dut.A_wr_mux[7:0]);
                end
                if (dut.instr == 8'h85) begin  // STA zp
                    $display("    STA zp: zp_addr=0x%02x write_addr=0x%04x write_data=0x%02x",
                             dut.zp_direct_addr, dut.mainmem_write_addr_mux, dut.mainmem_write_data_mux[7:0]);
                end
            end

            // Debug traces commented out for full test run
            // Uncomment specific traces when debugging
            /*
            // Trace CMP immediate instructions
            if (dut.instr == 8'hc9) begin
                $display("CMP at cycle %0d: PC=0x%04x A=0x%02x imm=0x%02x Z_before=%b",
                         cycle_count, dut.pc_rd, dut.A, dut.mainmem[dut.pc_rd + 1], dut.flag_Z);
            end

            // Trace PLP instructions
            if (dut.instr == 8'h28) begin
                $display("PLP at cycle %0d: PC=0x%04x S=0x%02x→0x%02x read_addr=0x%04x read_val=0x%02x",
                         cycle_count, dut.pc_rd, dut.S, dut.S_wr_mux[7:0],
                         {8'h01, dut.S + 8'd1}, dut.mainmem[{8'h01, dut.S + 8'd1}]);
            end

            // Trace STX zp instructions (opcode 0x86)
            if (dut.instr == 8'h86) begin
                $display("STX zp at cycle %0d: PC=0x%04x operand=0x%02x zp_direct_addr=0x%02x X=0x%02x write_addr=0x%04x write_data=0x%02x write_en=%b",
                         cycle_count, dut.pc_rd, dut.mainmem[dut.pc_rd + 1], dut.zp_direct_addr,
                         dut.X, dut.mainmem_write_addr_mux[15:0], dut.mainmem_write_data_mux[7:0],
                         dut.mainmem_write_enable);
            end

            // Trace LDX zp instructions (opcode 0xA6)
            if (dut.instr == 8'hA6) begin
                $display("LDX zp at cycle %0d: PC=0x%04x operand=0x%02x zp_direct_addr=0x%02x mem[zp]=0x%02x mainmem_zp_direct_addr_rd=0x%02x X_wr=0x%02x",
                         cycle_count, dut.pc_rd, dut.mainmem[dut.pc_rd + 1], dut.zp_direct_addr,
                         dut.mainmem[dut.mainmem[dut.pc_rd + 1]], dut.mainmem_zp_direct_addr_rd,
                         dut.X_wr_mux[7:0]);
            end

            // Trace memory at address 0x0b (failing address)
            if (cycle_count >= 40925 && cycle_count <= 40940) begin
                $display("  [TRACE] cycle %0d: mem[0x0b]=0x%02x PC=0x%04x instr=0x%02x A=0x%02x X=0x%02x",
                         cycle_count, dut.mainmem[16'h0b], dut.pc_rd, dut.instr, dut.A, dut.X);
            end

            // Trace LDA abs,X instructions (opcode 0xBD)
            if (dut.instr == 8'hbd) begin
                $display("LDA abs,X at cycle %0d: PC=0x%04x base=0x%04x X=0x%02x effective_addr=0x%04x mem_val=0x%02x A_wr=0x%02x",
                         cycle_count, dut.pc_rd,
                         {dut.mainmem[dut.pc_rd + 2], dut.mainmem[dut.pc_rd + 1]},
                         dut.X,
                         {dut.mainmem[dut.pc_rd + 2], dut.mainmem[dut.pc_rd + 1]} + {8'd0, dut.X},
                         dut.mainmem[{dut.mainmem[dut.pc_rd + 2], dut.mainmem[dut.pc_rd + 1]} + {8'd0, dut.X}],
                         dut.A_wr_mux[7:0]);
            end
            */

            // Monitor memory at 0x01FE to track PHP/PLP issue
            // Commented out for performance
            //if (cycle_count >= 40600 && cycle_count <= 40860) begin
            //    if (dut.mainmem[16'h01fe] != prev_mem_01fe) begin
            //        $display("[MEM WRITE] Cycle %0d: mem[0x01fe] changed from 0x%02x to 0x%02x (PC=0x%04x instr=0x%02x)",
            //                 cycle_count, prev_mem_01fe, dut.mainmem[16'h01fe], dut.pc_rd, dut.instr);
            //        prev_mem_01fe = dut.mainmem[16'h01fe];
            //    end
            //end

            if (cycle_count >= 31000000) begin
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
                    $display("Test completed (infinite loop detected)");
                    $display("FAILED - stuck at PC=0x%04x", dut.pc_rd);
                    $finish(1);
                end
            end else begin
                pc_stall_count = 0;
                prev_pc = dut.pc_rd;
            end
        end
    end

endmodule
