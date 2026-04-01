/* OpenPOWER EXTSW (Extend Sign Word) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * EXTSW tests - extsw rA, rS (sign-extend word to 64 bits)
     *-------------------------------------------------------------*/

    /* Positive values (bit 31 = 0) */
test_2:
    li TESTNUM, 2
    li %r9, 0
    extsw %r8, %r9
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_IMM(%r9, 0x7fffffff)
    extsw %r8, %r9
    LOAD_IMM(%r25, 0x7fffffff)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 1
    extsw %r8, %r9
    li %r25, 1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative values (bit 31 = 1) */
test_5:
    li TESTNUM, 5
    LOAD_IMM(%r9, 0x80000000)
    extsw %r8, %r9
    /* Result should be 0xffffffff80000000 */
    lis %r25, 0x8000
    extsw %r25, %r25   /* Use extsw to create expected value */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, -1
    extsw %r8, %r9
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    LOAD_IMM(%r9, 0xfffffffe)
    extsw %r8, %r9
    li %r25, -2
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Various patterns */
test_8:
    li TESTNUM, 8
    LOAD_IMM(%r9, 0x12345678)
    extsw %r8, %r9
    LOAD_IMM(%r25, 0x12345678)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0xfedcba98)
    extsw %r8, %r9
    /* Should sign-extend to 0xfffffffffedcba98 */
    LOAD_IMM(%r25, 0xfedcba98)
    extsw %r25, %r25
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_10:
    li TESTNUM, 10
    li %r9, -1
    extsw %r9, %r9
    li %r25, -1
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
