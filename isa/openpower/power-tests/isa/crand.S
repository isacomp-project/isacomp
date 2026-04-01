/* OpenPOWER CRAND (Condition Register AND) instruction tests */
/* crand crbD, crbA, crbB -> CR[crbD] = CR[crbA] & CR[crbB] */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test AND of two true conditions -> true */
test_2:
    li TESTNUM, 2
    li %r9, 5
    li %r10, 5
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 1 */
    crand 2, 2, 6            /* CR0[EQ] = CR0[EQ] & CR1[EQ] = 1 & 1 = 1 */
    bne %cr0, fail           /* Fail if CR0[EQ] not set */

    /* Test AND of true and false -> false */
test_3:
    li TESTNUM, 3
    li %r9, 5
    li %r10, 10
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 0 */
    crand 2, 2, 6            /* CR0[EQ] = 1 & 0 = 0 */
    beq %cr0, fail           /* Fail if CR0[EQ] is set */

    /* Test AND of false and true -> false */
test_4:
    li TESTNUM, 4
    li %r9, 10
    li %r10, 5
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 0 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 1 */
    crand 2, 2, 6            /* CR0[EQ] = 0 & 1 = 0 */
    beq %cr0, fail

    /* Test AND of two false conditions -> false */
test_5:
    li TESTNUM, 5
    li %r9, 10
    li %r10, 20
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 0 */
    cmpwi %cr1, %r10, 5      /* CR1[EQ] = 0 */
    crand 2, 2, 6            /* CR0[EQ] = 0 & 0 = 0 */
    beq %cr0, fail

    /* Test with LT bits */
test_6:
    li TESTNUM, 6
    li %r9, 3
    li %r10, 2
    cmpwi %cr0, %r9, 5       /* CR0[LT] = 1 (3 < 5) */
    cmpwi %cr1, %r10, 5      /* CR1[LT] = 1 (2 < 5) */
    crand 0, 0, 4            /* CR0[LT] = CR0[LT] & CR1[LT] = 1 */
    bge %cr0, fail           /* Fail if LT not set */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
