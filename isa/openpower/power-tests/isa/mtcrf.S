/* OpenPOWER MTCRF (Move To Condition Register Fields) instruction tests */
/* mtcrf FXM, rS -> CR = (rS & mask) | (CR & ~mask) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test writing to CR0 only */
test_2:
    li TESTNUM, 2
    /* Set CR0 to EQ (0b0010 = 0x2 in high nibble) */
    LOAD_IMM(%r9, 0x20000000)
    mtcrf 0x80, %r9          /* Write to CR0 only (FXM bit 0) */
    beq %cr0, test_2_pass
    b fail
test_2_pass:

    /* Test writing LT to CR0 */
test_3:
    li TESTNUM, 3
    LOAD_IMM(%r9, 0x80000000)  /* LT bit in CR0 */
    mtcrf 0x80, %r9
    blt %cr0, test_3_pass
    b fail
test_3_pass:

    /* Test writing GT to CR0 */
test_4:
    li TESTNUM, 4
    LOAD_IMM(%r9, 0x40000000)  /* GT bit in CR0 */
    mtcrf 0x80, %r9
    bgt %cr0, test_4_pass
    b fail
test_4_pass:

    /* Test writing to CR1 */
test_5:
    li TESTNUM, 5
    LOAD_IMM(%r9, 0x02000000)  /* EQ bit in CR1 position */
    mtcrf 0x40, %r9          /* Write to CR1 only (FXM bit 1) */
    beq %cr1, test_5_pass
    b fail
test_5_pass:

    /* Test writing to multiple CR fields */
test_6:
    li TESTNUM, 6
    LOAD_IMM(%r9, 0x22000000)  /* EQ in both CR0 and CR1 */
    mtcrf 0xc0, %r9          /* Write to CR0 and CR1 */
    beq %cr0, test_6a
    b fail
test_6a:
    beq %cr1, test_6_pass
    b fail
test_6_pass:

    /* Test that unselected CR fields are preserved */
test_7:
    li TESTNUM, 7
    /* First set CR0 to EQ */
    LOAD_IMM(%r9, 0x20000000)
    mtcrf 0x80, %r9
    /* Now write to CR1 only, CR0 should be preserved */
    LOAD_IMM(%r9, 0x08000000)  /* LT in CR1 */
    mtcrf 0x40, %r9
    /* CR0 should still have EQ */
    beq %cr0, test_7a
    b fail
test_7a:
    /* CR1 should have LT */
    blt %cr1, test_7_pass
    b fail
test_7_pass:

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
