/* OpenPOWER CROR (Condition Register OR) instruction tests */
/* cror crbD, crbA, crbB -> CR[crbD] = CR[crbA] | CR[crbB] */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test OR of two true conditions -> true */
test_2:
    li TESTNUM, 2
    li %r9, 5
    li %r10, 5
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 1 */
    cror 2, 2, 6             /* CR0[EQ] = 1 | 1 = 1 */
    bne %cr0, fail

    /* Test OR of true and false -> true */
test_3:
    li TESTNUM, 3
    li %r9, 5
    li %r10, 10
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 0 */
    cror 2, 2, 6             /* CR0[EQ] = 1 | 0 = 1 */
    bne %cr0, fail

    /* Test OR of false and true -> true */
test_4:
    li TESTNUM, 4
    li %r9, 10
    li %r10, 5
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 0 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 1 */
    cror 2, 2, 6             /* CR0[EQ] = 0 | 1 = 1 */
    bne %cr0, fail

    /* Test OR of two false conditions -> false */
test_5:
    li TESTNUM, 5
    li %r9, 10
    li %r10, 20
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 0 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 0 */
    cror 2, 2, 6             /* CR0[EQ] = 0 | 0 = 0 */
    beq %cr0, fail

    /* Test combining LT and GT */
test_6:
    li TESTNUM, 6
    li %r9, 3
    li %r10, 10
    cmpwi %cr0, %r9, 5       /* CR0[LT] = 1, CR0[GT] = 0 */
    cmpwi %cr1, %r10, 5      /* CR1[LT] = 0, CR1[GT] = 1 */
    cror 0, 0, 5             /* CR0[LT] = CR0[LT] | CR1[GT] = 1 | 1 = 1 */
    bge %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
