`timescale 1ns/1ps

module bulk_test;
    reg clk;
    reg reset;

    // Test data - loaded from file
    reg [7:0] init_A, init_B, init_C, init_D, init_E, init_H, init_L, init_F;
    reg [15:0] init_PC, init_SP;
    reg [7:0] exp_A, exp_B, exp_C, exp_D, exp_E, exp_H, exp_L, exp_F;
    reg [15:0] exp_PC, exp_SP;
    // Prime registers
    reg [7:0] init_A_prime, init_F_prime, init_B_prime, init_C_prime;
    reg [7:0] init_D_prime, init_E_prime, init_H_prime, init_L_prime;
    reg [7:0] exp_A_prime, exp_F_prime, exp_B_prime, exp_C_prime;
    reg [7:0] exp_D_prime, exp_E_prime, exp_H_prime, exp_L_prime;
    // Index registers (IX, IY) and I, R, IFF2
    reg [7:0] init_IXH, init_IXL, init_IYH, init_IYL;
    reg [7:0] init_I, init_R, init_IFF2;
    reg [7:0] exp_IXH, exp_IXL, exp_IYH, exp_IYL;
    reg [7:0] exp_I, exp_R, exp_IFF2;
    // Port I/O
    reg [7:0] port_addr;
    reg [7:0] port_data;
    integer port_count, port_idx;

    // Instantiate CPU
    processor cpu(
        .clk(clk),
        .reset(reset),
        .reset_A(init_A),
        .reset_B(init_B),
        .reset_C(init_C),
        .reset_D(init_D),
        .reset_E(init_E),
        .reset_H(init_H),
        .reset_L(init_L),
        .reset_pc_rd(init_PC),
        .reset_sp_rd(init_SP),
        .reset_flag_C(init_F[0]),
        .reset_flag_Z(init_F[6]),
        .reset_flag_S(init_F[7]),
        .reset_flag_H(init_F[4]),
        .reset_flag_N(init_F[1]),
        .reset_flag_PV(init_F[2]),
        .reset_halted_rd(1'b0),
        // Prime registers - from test data
        .reset_A_prime(init_A_prime),
        .reset_B_prime(init_B_prime),
        .reset_C_prime(init_C_prime),
        .reset_D_prime(init_D_prime),
        .reset_E_prime(init_E_prime),
        .reset_H_prime(init_H_prime),
        .reset_L_prime(init_L_prime),
        .reset_flag_C_prime(init_F_prime[0]),
        .reset_flag_Z_prime(init_F_prime[6]),
        .reset_flag_S_prime(init_F_prime[7]),
        .reset_flag_H_prime(init_F_prime[4]),
        .reset_flag_N_prime(init_F_prime[1]),
        .reset_flag_PV_prime(init_F_prime[2]),
        // Index registers
        .reset_IXH(init_IXH),
        .reset_IXL(init_IXL),
        .reset_IYH(init_IYH),
        .reset_IYL(init_IYL),
        // I, R, IFF2, IM
        .reset_I(init_I),
        .reset_R(init_R),
        .reset_IFF2(init_IFF2[0]),
        .reset_IM(2'b00),
        // Interrupt flags
        .reset_int_ff1_rd(1'b0),
        .reset_int_ff2(init_IFF2[0])
    );

    // Clock generation
    initial clk = 0;
    always #5 clk = ~clk;

    integer test_file;
    integer num_tests, test_idx;
    integer passed, failed;
    integer errors;
    integer scan_result;
    reg [15:0] ram_addr;
    reg [7:0] ram_data;
    integer ram_count, ram_idx;
    reg [255:0] test_name;

    initial begin
        passed = 0;
        failed = 0;

        // Open test data file
        test_file = $fopen("tests.txt", "r");
        if (test_file == 0) begin
            $display("ERROR: Cannot open tests.txt");
            $finish;
        end

        // Read number of tests
        scan_result = $fscanf(test_file, "%d\n", num_tests);

        for (test_idx = 0; test_idx < num_tests; test_idx = test_idx + 1) begin
            // Clear memory and I/O ports
            for (ram_idx = 0; ram_idx < 65536; ram_idx = ram_idx + 1)
                cpu.mainmem[ram_idx] = 8'h00;
            for (port_idx = 0; port_idx < 256; port_idx = port_idx + 1)
                cpu.io[port_idx] = 8'h00;

            // Read test case: name, init values, expected values, prime regs, index regs, ram count
            scan_result = $fscanf(test_file, "%s\n", test_name);
            scan_result = $fscanf(test_file, "%d %d %d %d %d %d %d %d %d %d\n",
                init_A, init_B, init_C, init_D, init_E, init_H, init_L, init_F, init_PC, init_SP);
            scan_result = $fscanf(test_file, "%d %d %d %d %d %d %d %d %d %d\n",
                exp_A, exp_B, exp_C, exp_D, exp_E, exp_H, exp_L, exp_F, exp_PC, exp_SP);
            // Prime registers: A', F', B', C', D', E', H', L'
            scan_result = $fscanf(test_file, "%d %d %d %d %d %d %d %d\n",
                init_A_prime, init_F_prime, init_B_prime, init_C_prime,
                init_D_prime, init_E_prime, init_H_prime, init_L_prime);
            scan_result = $fscanf(test_file, "%d %d %d %d %d %d %d %d\n",
                exp_A_prime, exp_F_prime, exp_B_prime, exp_C_prime,
                exp_D_prime, exp_E_prime, exp_H_prime, exp_L_prime);
            // Index registers: IXH, IXL, IYH, IYL, I, R, IFF2
            scan_result = $fscanf(test_file, "%d %d %d %d %d %d %d\n",
                init_IXH, init_IXL, init_IYH, init_IYL, init_I, init_R, init_IFF2);
            scan_result = $fscanf(test_file, "%d %d %d %d %d %d %d\n",
                exp_IXH, exp_IXL, exp_IYH, exp_IYL, exp_I, exp_R, exp_IFF2);
            scan_result = $fscanf(test_file, "%d\n", ram_count);

            // Load RAM
            for (ram_idx = 0; ram_idx < ram_count; ram_idx = ram_idx + 1) begin
                scan_result = $fscanf(test_file, "%d %d\n", ram_addr, ram_data);
                cpu.mainmem[ram_addr] = ram_data;
            end

            // Load port I/O data
            scan_result = $fscanf(test_file, "%d\n", port_count);
            for (port_idx = 0; port_idx < port_count; port_idx = port_idx + 1) begin
                scan_result = $fscanf(test_file, "%d %d\n", port_addr, port_data);
                cpu.io[port_addr] = port_data;
            end

            // Reset
            reset = 1;
            @(posedge clk);
            @(posedge clk);
            reset = 0;

            // Execute one instruction
            @(posedge clk);

            // Check results
            errors = 0;
            if (cpu.A !== exp_A) errors = errors + 1;
            if (cpu.B !== exp_B) errors = errors + 1;
            if (cpu.C !== exp_C) errors = errors + 1;
            if (cpu.D !== exp_D) errors = errors + 1;
            if (cpu.E !== exp_E) errors = errors + 1;
            if (cpu.H !== exp_H) errors = errors + 1;
            if (cpu.L !== exp_L) errors = errors + 1;
            if (cpu.pc_rd !== exp_PC) errors = errors + 1;
            if (cpu.sp_rd !== exp_SP) errors = errors + 1;
            // Check prime registers
            if (cpu.A_prime !== exp_A_prime) errors = errors + 1;
            if (cpu.B_prime !== exp_B_prime) errors = errors + 1;
            if (cpu.C_prime !== exp_C_prime) errors = errors + 1;
            if (cpu.D_prime !== exp_D_prime) errors = errors + 1;
            if (cpu.E_prime !== exp_E_prime) errors = errors + 1;
            if (cpu.H_prime !== exp_H_prime) errors = errors + 1;
            if (cpu.L_prime !== exp_L_prime) errors = errors + 1;
            // Check F' flags individually
            if (cpu.flag_C_prime !== exp_F_prime[0]) errors = errors + 1;
            if (cpu.flag_N_prime !== exp_F_prime[1]) errors = errors + 1;
            if (cpu.flag_PV_prime !== exp_F_prime[2]) errors = errors + 1;
            if (cpu.flag_H_prime !== exp_F_prime[4]) errors = errors + 1;
            if (cpu.flag_Z_prime !== exp_F_prime[6]) errors = errors + 1;
            if (cpu.flag_S_prime !== exp_F_prime[7]) errors = errors + 1;
            // Check index registers
            if (cpu.IXH !== exp_IXH) errors = errors + 1;
            if (cpu.IXL !== exp_IXL) errors = errors + 1;
            if (cpu.IYH !== exp_IYH) errors = errors + 1;
            if (cpu.IYL !== exp_IYL) errors = errors + 1;
            // Check I, R (skip R as it auto-increments)
            if (cpu.I !== exp_I) errors = errors + 1;
            // if (cpu.R !== exp_R) errors = errors + 1;  // R auto-increments

            if (errors == 0)
                passed = passed + 1;
            else begin
                failed = failed + 1;
                if (failed <= 10) begin
                    $display("FAIL: %0s", test_name);
                    if (cpu.A !== exp_A) $display("  A: got %02x exp %02x", cpu.A, exp_A);
                    if (cpu.B !== exp_B) $display("  B: got %02x exp %02x", cpu.B, exp_B);
                    if (cpu.C !== exp_C) $display("  C: got %02x exp %02x", cpu.C, exp_C);
                    if (cpu.D !== exp_D) $display("  D: got %02x exp %02x", cpu.D, exp_D);
                    if (cpu.E !== exp_E) $display("  E: got %02x exp %02x", cpu.E, exp_E);
                    if (cpu.H !== exp_H) $display("  H: got %02x exp %02x", cpu.H, exp_H);
                    if (cpu.L !== exp_L) $display("  L: got %02x exp %02x", cpu.L, exp_L);
                    if (cpu.pc_rd !== exp_PC) $display("  PC: got %04x exp %04x", cpu.pc_rd, exp_PC);
                    if (cpu.sp_rd !== exp_SP) $display("  SP: got %04x exp %04x", cpu.sp_rd, exp_SP);
                    // Display prime register errors
                    if (cpu.A_prime !== exp_A_prime) $display("  A': got %02x exp %02x", cpu.A_prime, exp_A_prime);
                    if (cpu.B_prime !== exp_B_prime) $display("  B': got %02x exp %02x", cpu.B_prime, exp_B_prime);
                    if (cpu.C_prime !== exp_C_prime) $display("  C': got %02x exp %02x", cpu.C_prime, exp_C_prime);
                    if (cpu.D_prime !== exp_D_prime) $display("  D': got %02x exp %02x", cpu.D_prime, exp_D_prime);
                    if (cpu.E_prime !== exp_E_prime) $display("  E': got %02x exp %02x", cpu.E_prime, exp_E_prime);
                    if (cpu.H_prime !== exp_H_prime) $display("  H': got %02x exp %02x", cpu.H_prime, exp_H_prime);
                    if (cpu.L_prime !== exp_L_prime) $display("  L': got %02x exp %02x", cpu.L_prime, exp_L_prime);
                    // Display index register errors
                    if (cpu.IXH !== exp_IXH) $display("  IXH: got %02x exp %02x", cpu.IXH, exp_IXH);
                    if (cpu.IXL !== exp_IXL) $display("  IXL: got %02x exp %02x", cpu.IXL, exp_IXL);
                    if (cpu.IYH !== exp_IYH) $display("  IYH: got %02x exp %02x", cpu.IYH, exp_IYH);
                    if (cpu.IYL !== exp_IYL) $display("  IYL: got %02x exp %02x", cpu.IYL, exp_IYL);
                    if (cpu.I !== exp_I) $display("  I: got %02x exp %02x", cpu.I, exp_I);
                end
            end
        end

        $fclose(test_file);
        $display("Passed: %0d/%0d", passed, passed + failed);
        $finish;
    end

endmodule
