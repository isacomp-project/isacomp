# RISC-V Zfinx Test - FADD.S using integer registers
# Tests single-precision FP addition with values in x registers
#
# IEEE 754 single-precision format:
#   1.0  = 0x3F800000
#   2.0  = 0x40000000
#   2.5  = 0x40200000
#   3.0  = 0x40400000
#   3.5  = 0x40600000
#   -1.0 = 0xBF800000

#include "riscv_test.h"
#include "test_macros.h"

RVTEST_RV32U
RVTEST_CODE_BEGIN

    # Initialize fcsr to round-to-nearest-even (frm=0)
    csrwi fcsr, 0

    #-------------------------------------------------------------
    # Test 1: 1.0 + 2.5 = 3.5
    #-------------------------------------------------------------
test_1:
    li TESTNUM, 1
    li x10, 0x3F800000    # 1.0 in IEEE 754
    li x11, 0x40200000    # 2.5 in IEEE 754
    fadd.s x12, x10, x11  # x12 = 1.0 + 2.5 = 3.5
    li x7, 0x40600000     # Expected: 3.5 in IEEE 754
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 2: 2.0 + 1.0 = 3.0
    #-------------------------------------------------------------
test_2:
    li TESTNUM, 2
    li x10, 0x40000000    # 2.0 in IEEE 754
    li x11, 0x3F800000    # 1.0 in IEEE 754
    fadd.s x12, x10, x11  # x12 = 2.0 + 1.0 = 3.0
    li x7, 0x40400000     # Expected: 3.0 in IEEE 754
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 3: FSUB.S - 2.5 - 1.0 = 1.5 (0x3FC00000)
    #-------------------------------------------------------------
test_3:
    li TESTNUM, 3
    li x10, 0x40200000    # 2.5 in IEEE 754
    li x11, 0x3F800000    # 1.0 in IEEE 754
    fsub.s x12, x10, x11  # x12 = 2.5 - 1.0 = 1.5
    li x7, 0x3FC00000     # Expected: 1.5 in IEEE 754
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 4: FMUL.S - 2.0 * 2.5 = 5.0 (0x40A00000)
    #-------------------------------------------------------------
test_4:
    li TESTNUM, 4
    li x10, 0x40000000    # 2.0 in IEEE 754
    li x11, 0x40200000    # 2.5 in IEEE 754
    fmul.s x12, x10, x11  # x12 = 2.0 * 2.5 = 5.0
    li x7, 0x40A00000     # Expected: 5.0 in IEEE 754
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 5: FCVT.S.W - Convert integer 5 to float 5.0
    #-------------------------------------------------------------
test_5:
    li TESTNUM, 5
    li x10, 5             # Integer 5
    fcvt.s.w x12, x10     # x12 = (float)5 = 5.0
    li x7, 0x40A00000     # Expected: 5.0 in IEEE 754
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 6: FCVT.W.S - Convert float 5.0 to integer 5
    #-------------------------------------------------------------
test_6:
    li TESTNUM, 6
    li x10, 0x40A00000    # 5.0 in IEEE 754
    fcvt.w.s x12, x10     # x12 = (int)5.0 = 5
    li x7, 5              # Expected: integer 5
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 7: FSGNJ.S (copy sign) - should copy x10 entirely when rs1==rs2
    #-------------------------------------------------------------
test_7:
    li TESTNUM, 7
    li x10, 0x40200000    # 2.5 in IEEE 754
    fsgnj.s x12, x10, x10 # x12 = 2.5 (copy)
    li x7, 0x40200000     # Expected: 2.5
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 8: FSGNJN.S (negate) - should negate when rs1==rs2
    #-------------------------------------------------------------
test_8:
    li TESTNUM, 8
    li x10, 0x40200000    # 2.5 in IEEE 754
    fsgnjn.s x12, x10, x10 # x12 = -2.5 (negate)
    li x7, 0xC0200000     # Expected: -2.5 in IEEE 754
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 9: FEQ.S - compare equal
    #-------------------------------------------------------------
test_9:
    li TESTNUM, 9
    li x10, 0x40200000    # 2.5
    li x11, 0x40200000    # 2.5
    feq.s x12, x10, x11   # x12 = (2.5 == 2.5) = 1
    li x7, 1
    bne x12, x7, fail

    #-------------------------------------------------------------
    # Test 10: FLT.S - compare less than
    #-------------------------------------------------------------
test_10:
    li TESTNUM, 10
    li x10, 0x3F800000    # 1.0
    li x11, 0x40200000    # 2.5
    flt.s x12, x10, x11   # x12 = (1.0 < 2.5) = 1
    li x7, 1
    bne x12, x7, fail

    TEST_PASSFAIL

RVTEST_CODE_END

  .data
RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
