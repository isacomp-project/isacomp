`timescale 1ns / 1ps

module aes_full_clean_tb;

  // Clock and reset
  reg clk;
  reg rst;

  // Instantiate the AES accelerator
  aes_module dut (
    .clk(clk),
    .rst(rst)
  );

  // AES-128 test vectors (NIST FIPS 197 Appendix C.1)
  // Plaintext: 0x00112233445566778899aabbccddeeff
  // Key:       0x000102030405060708090a0b0c0d0e0f
  // Expected Ciphertext: 0x69c4e0d86a7b0430d8cdb78070b4c55a

  reg [127:0] test_plaintext;
  reg [127:0] test_key;
  reg [127:0] expected_ciphertext;
  reg [127:0] read_ciphertext;
  integer i;
  integer pass_count;
  integer fail_count;

  // Clock generation (10ns period = 100MHz)
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  // Memory-mapped register addresses (from ILA model)
  localparam ADDR_CMD      = 16'hFF00;  // Command register
  localparam ADDR_ADDRESS  = 16'hFF02;  // AES address (2 bytes)
  localparam ADDR_LENGTH   = 16'hFF04;  // AES length (2 bytes)
  localparam ADDR_KEY      = 16'hFF10;  // AES key (16 bytes: 0xFF10-0xFF1F)
  localparam ADDR_COUNTER  = 16'hFF20;  // AES counter/plaintext (16 bytes: 0xFF20-0xFF2F)

  localparam CMD_READ  = 2'd1;
  localparam CMD_WRITE = 2'd2;
  localparam CMD_START = 8'd1;

  // Helper task: Write byte to memory-mapped register
  task write_byte(input [15:0] addr, input [7:0] data);
    begin
      @(posedge clk);
      force dut.cmd = CMD_WRITE;
      force dut.outdata = CMD_WRITE;  // Also force outdata for decode conditions
      force dut.cmdaddr = addr;
      force dut.cmddata = data;
      @(posedge clk);
      release dut.cmd;
      release dut.outdata;
      release dut.cmdaddr;
      release dut.cmddata;
    end
  endtask

  // Helper task: Write 128-bit value to register block (little-endian byte order)
  task write_128(input [15:0] base_addr, input [127:0] data);
    integer j;
    begin
      for (j = 0; j < 16; j = j + 1) begin
        write_byte(base_addr + j, data[j*8 +: 8]);  // Little-endian: LSB first
      end
    end
  endtask

  // Helper task: Run a single test
  task run_test(input integer test_num, input string test_name,
                input [127:0] plaintext, input [127:0] key, input [127:0] expected);
    begin
      $display("\n========================================");
      $display("Test %0d: %s", test_num, test_name);
      $display("  Plaintext: %h", plaintext);
      $display("  Key:       %h", key);
      $display("  Expected:  %h", expected);

      // Reset
      rst = 1;
      force dut.cmd = 2'd0;
      force dut.outdata = 2'd0;
      force dut.cmdaddr = 16'd0;
      force dut.cmddata = 8'd0;
      repeat (5) @(posedge clk);
      rst = 0;
      release dut.cmd;
      release dut.outdata;
      release dut.cmdaddr;
      release dut.cmddata;
      repeat (2) @(posedge clk);

      $display("  After reset: aes_status=%0d, aes_key=%h, aes_counter=%h", dut.aes_status, dut.aes_key, dut.aes_counter);

      // Write key and plaintext
      $display("  Writing key...");
      write_128(ADDR_KEY, key);
      $display("  After writing key: aes_status=%0d, aes_key=%h", dut.aes_status, dut.aes_key);
      $display("  Writing counter/plaintext...");
      write_128(ADDR_COUNTER, plaintext);
      $display("  After writing counter: aes_status=%0d, aes_counter=%h", dut.aes_status, dut.aes_counter);
      write_byte(ADDR_LENGTH, 8'd16);
      write_byte(ADDR_LENGTH + 1, 8'd0);

      // Start encryption
      $display("  Starting encryption...");
      write_byte(ADDR_CMD, CMD_START);
      $display("  After START: aes_status=%0d", dut.aes_status);

      // Wait for completion
      $display("  Waiting for round to reach 11...");
      while (dut.round != 11) begin
        @(posedge clk);
        if (dut.round != 11)
          $display("    round=%0d, aes_status=%0d, ciphertext=%h", dut.round, dut.aes_status, dut.ciphertext);
      end
      $display("  Round reached 11!");
      repeat (5) @(posedge clk);

      // Read result
      read_ciphertext = dut.ciphertext;

      // Check result
      @(posedge clk);
      if (read_ciphertext == expected) begin
        $display("✓ Test %0d PASSED", test_num);
        $display("  Ciphertext: %h", read_ciphertext);
        pass_count = pass_count + 1;
      end else begin
        $display("✗ Test %0d FAILED", test_num);
        $display("  Got:        %h", read_ciphertext);
        $display("  Expected:   %h", expected);
        $display("  Difference: %h", read_ciphertext ^ expected);
        fail_count = fail_count + 1;
      end
    end
  endtask

  // Test stimulus
  initial begin
    pass_count = 0;
    fail_count = 0;

    // Initialize waveform dump
    $dumpfile("aes_full_clean_tb.vcd");
    $dumpvars(0, aes_full_clean_tb);

    // Display test info
    $display("================================================================================");
    $display("AES-128 Inlined Accelerator Test - 8 Test Vectors");
    $display("Generated from: aes_full_clean.v");
    $display("NOTE: Reading directly from ciphertext register");
    $display("      (memory writes not implemented)");
    $display("================================================================================");
    $display("Time: %0t", $time);

    // Test 1: NIST FIPS 197 Appendix C.1 (sequential pattern)
    run_test(1, "NIST FIPS 197 Appendix C.1 (sequential pattern)",
             128'h00112233445566778899aabbccddeeff,
             128'h000102030405060708090a0b0c0d0e0f,
             128'h69c4e0d86a7b0430d8cdb78070b4c55a);

    // Test 2: All zeros
    run_test(2, "All zeros",
             128'h00000000000000000000000000000000,
             128'h00000000000000000000000000000000,
             128'h66e94bd4ef8a2c3b884cfa59ca342b2e);

    // Test 3: All ones
    run_test(3, "All ones",
             128'hffffffffffffffffffffffffffffffff,
             128'hffffffffffffffffffffffffffffffff,
             128'hbcbf217cb280cf30b2517052193ab979);

    // Test 4: NIST FIPS 197 Appendix B
    run_test(4, "NIST FIPS 197 Appendix B",
             128'h3243f6a8885a308d313198a2e0370734,
             128'h2b7e151628aed2a6abf7158809cf4f3c,
             128'h3925841d02dc09fbdc118597196a0b32);

    // Test 5: Random hex pattern
    run_test(5, "Random hex pattern",
             128'hdeadbeefcafebabe0123456789abcdef,
             128'h0f0e0d0c0b0a09080706050403020100,
             128'hc3401335e485886e64e3d333a41d6b95);

    // Test 6: Single bit plaintext
    run_test(6, "Single bit plaintext",
             128'h80000000000000000000000000000000,
             128'h00000000000000000000000000000000,
             128'h3ad78e726c1ec02b7ebfe92b23d9ec34);

    // Test 7: Single bit key
    run_test(7, "Single bit key",
             128'h00000000000000000000000000000000,
             128'h80000000000000000000000000000000,
             128'h0edd33d3c621e546455bd8ba1418bec8);

    // Test 8: ASCII text ("Hello, AES-128!!" / "MySecretBey12345")
    run_test(8, "ASCII text pattern",
             128'h48656c6c6f2c204145532d3132382121,
             128'h4d795365637265744265793132333435,
             128'h923056963c12eb2218f5dbf5bfac20da);

    // Print summary
    $display("\n================================================================================");
    $display("Test Summary");
    $display("================================================================================");
    $display("Total tests:  8");
    $display("Passed:       %0d", pass_count);
    $display("Failed:       %0d", fail_count);
    if (fail_count == 0) begin
      $display("\n✓✓✓ ALL TESTS PASSED! ✓✓✓");
      $display("Child ILA function inlining VERIFIED!");
    end else begin
      $display("\n✗✗✗ SOME TESTS FAILED ✗✗✗");
    end
    $display("================================================================================");
    $display("Simulation complete at time %0t", $time);
    $display("================================================================================");
    $finish;
  end

  // Timeout watchdog (8 tests * ~3000 time units each = ~24000, use 50000 for safety)
  initial begin
    #50000;
    $display("\n✗ TIMEOUT: Simulation did not complete in time");
    $finish;
  end

endmodule
