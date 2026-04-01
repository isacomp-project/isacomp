`timescale 1ns / 1ps

module sha_seven_tests;

  reg clk, rst;
  sha_full dut (.clk(clk), .rst(rst));

  localparam CMD_WRITE = 2'd2;
  localparam ADDR_START = 16'hFF06;

  integer pass_count, fail_count;

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  task write_byte(input [15:0] addr, input [7:0] data);
    begin
      @(posedge clk);
      force dut.cmd = CMD_WRITE; force dut.cmdaddr = addr; force dut.cmddata = data;
      @(posedge clk);
      release dut.cmd; release dut.cmdaddr; release dut.cmddata;
    end
  endtask

  task run_test(input [255:0] name, input [511:0] block, input [159:0] expected);
    integer cycle;
    reg [159:0] result;
    begin
      $display("Test: %0s", name);
      rst = 1; force dut.cmd = 0; force dut.cmdaddr = 0; force dut.cmddata = 0;
      repeat (5) @(posedge clk); rst = 0; repeat (2) @(posedge clk);

      @(posedge clk);
      force dut.block_0 = block[511:480]; force dut.block_1 = block[479:448];
      force dut.block_2 = block[447:416]; force dut.block_3 = block[415:384];
      force dut.block_4 = block[383:352]; force dut.block_5 = block[351:320];
      force dut.block_6 = block[319:288]; force dut.block_7 = block[287:256];
      force dut.block_8 = block[255:224]; force dut.block_9 = block[223:192];
      force dut.block_10 = block[191:160]; force dut.block_11 = block[159:128];
      force dut.block_12 = block[127:96]; force dut.block_13 = block[95:64];
      force dut.block_14 = block[63:32]; force dut.block_15 = block[31:0];
      force dut.H0_in = 32'h67452301; force dut.H1_in = 32'hEFCDAB89;
      force dut.H2_in = 32'h98BADCFE; force dut.H3_in = 32'h10325476;
      force dut.H4_in = 32'hC3D2E1F0; force dut.round = 8'd0;
      @(posedge clk);

      write_byte(ADDR_START, 8'd1);
      @(posedge clk); force dut.cmd = 0; force dut.cmdaddr = 0; force dut.cmddata = 0;
      @(posedge clk); release dut.cmd; release dut.cmdaddr; release dut.cmddata; release dut.round;

      for (cycle = 0; cycle < 200; cycle = cycle + 1) begin
        @(posedge clk);
        if (dut.round >= 8'd146) break;
      end

      repeat (3) @(posedge clk);
      result = {dut.H0_out, dut.H1_out, dut.H2_out, dut.H3_out, dut.H4_out};

      if (result == expected) begin
        $display("  ✓ PASS");
        pass_count = pass_count + 1;
      end else begin
        $display("  ✗ FAIL");
        $display("    Expected: %h", expected);
        $display("    Got:      %h", result);
        fail_count = fail_count + 1;
      end

      release dut.block_0; release dut.block_1; release dut.block_2; release dut.block_3;
      release dut.block_4; release dut.block_5; release dut.block_6; release dut.block_7;
      release dut.block_8; release dut.block_9; release dut.block_10; release dut.block_11;
      release dut.block_12; release dut.block_13; release dut.block_14; release dut.block_15;
      release dut.H0_in; release dut.H1_in; release dut.H2_in; release dut.H3_in; release dut.H4_in;
    end
  endtask

  initial begin
    pass_count = 0;
    fail_count = 0;

    $display("========================================");
    $display("SHA-1 Seven Test Suite");
    $display("========================================\n");

    // Test 1: "abc" (FIPS 180-4)
    run_test("abc",
             512'h61626380_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000018,
             160'hA9993E36_4706816A_BA3E2571_7850C26C_9CD0D89D);

    // Test 2: empty string
    run_test("empty string",
             512'h80000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000,
             160'hDA39A3EE_5E6B4B0D_3255BFEF_95601890_AFD80709);

    // Test 3: "hello world"
    run_test("hello world",
             512'h68656C6C_6F20776F_726C6480_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000058,
             160'h2AAE6C35_C94FCFB4_15DBE95F_408B9CE9_1EE846ED);

    // Test 4: "test"
    run_test("test",
             512'h74657374_80000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000020,
             160'hA94A8FE5_CCB19BA6_1C4C0873_D391E987_982FBBD3);

    // Test 5: "a" (single character)
    run_test("a",
             512'h61800000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000008,
             160'h86F7E437_FAA5A7FC_E15D1DDC_B9EAEAEA_377667B8);

    // Test 6: "1234567890"
    run_test("1234567890",
             512'h31323334_35363738_39308000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000050,
             160'h01B307AC_BA4F54F5_5AAFC33B_B06BBBF6_CA803E9A);

    // Test 7: "The quick brown fox jumps over the lazy dog"
    run_test("quick brown fox",
             512'h54686520_71756963_6B206272_6F776E20_666F7820_6A756D70_73206F76_65722074_6865206C_617A7920_646F6780_00000000_00000000_00000000_00000000_00000158,
             160'h2FD4E1C6_7A2D28FC_ED849EE1_BB76E739_1B93EB12);

    $display("\n========================================");
    $display("Test Summary");
    $display("========================================");
    $display("  PASSED: %0d", pass_count);
    $display("  FAILED: %0d", fail_count);
    if (fail_count == 0) begin
      $display("  ✓ ALL TESTS PASSED!");
    end else begin
      $display("  ✗ SOME TESTS FAILED");
    end
    $display("========================================\n");
    $finish;
  end

  initial begin
    #100000;  // 100us timeout
    $display("\n✗ TIMEOUT after 100us");
    $finish;
  end

endmodule
