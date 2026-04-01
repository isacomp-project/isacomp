/* OpenPOWER CRXOR (Condition Register XOR) instruction tests */
/* crxor crbD, crbA, crbB -> CR[crbD] = CR[crbA] ^ CR[crbB] */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test XOR of two true conditions -> false */
test_2:
    li TESTNUM, 2
    li %r9, 5
    li %r10, 5
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 1 */
    crxor 2, 2, 6            /* CR0[EQ] = 1 ^ 1 = 0 */
    beq %cr0, fail           /* Fail if EQ still set */

    /* Test XOR of true and false -> true */
test_3:
    li TESTNUM, 3
    li %r9, 5
    li %r10, 10
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 0 */
    crxor 2, 2, 6            /* CR0[EQ] = 1 ^ 0 = 1 */
    bne %cr0, fail

    /* Test XOR of false and true -> true */
test_4:
    li TESTNUM, 4
    li %r9, 10
    li %r10, 5
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 0 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 1 */
    crxor 2, 2, 6            /* CR0[EQ] = 0 ^ 1 = 1 */
    bne %cr0, fail

    /* Test XOR of two false conditions -> false */
test_5:
    li TESTNUM, 5
    li %r9, 10
    li %r10, 20
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 0 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 0 */
    crxor 2, 2, 6            /* CR0[EQ] = 0 ^ 0 = 0 */
    beq %cr0, fail

    /* Test clearing a bit (XOR with itself) */
test_6:
    li TESTNUM, 6
    li %r9, 5
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 */
    crxor 2, 2, 2            /* CR0[EQ] = 1 ^ 1 = 0 */
    beq %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
