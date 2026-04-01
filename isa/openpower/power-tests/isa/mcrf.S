/* OpenPOWER MCRF (Move Condition Register Field) instruction tests */
/* mcrf crfD, crfS -> CR[crfD] = CR[crfS] */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test copy CR0 to CR1 - equal condition */
test_2:
    li TESTNUM, 2
    li %r9, 5
    cmpwi %cr0, %r9, 5       /* CR0: EQ set */
    mcrf %cr1, %cr0          /* Copy CR0 to CR1 */
    bne %cr1, fail           /* CR1 should have EQ */

    /* Test copy CR0 to CR2 - less than condition */
test_3:
    li TESTNUM, 3
    li %r9, 3
    cmpwi %cr0, %r9, 5       /* CR0: LT set */
    mcrf %cr2, %cr0          /* Copy CR0 to CR2 */
    bge %cr2, fail           /* CR2 should have LT */

    /* Test copy CR0 to CR3 - greater than condition */
test_4:
    li TESTNUM, 4
    li %r9, 10
    cmpwi %cr0, %r9, 5       /* CR0: GT set */
    mcrf %cr3, %cr0          /* Copy CR0 to CR3 */
    ble %cr3, fail           /* CR3 should have GT */

    /* Test copy between non-CR0 fields */
test_5:
    li TESTNUM, 5
    li %r9, 5
    cmpwi %cr4, %r9, 5       /* CR4: EQ set */
    mcrf %cr5, %cr4          /* Copy CR4 to CR5 */
    bne %cr5, fail

    /* Test copy preserves source */
test_6:
    li TESTNUM, 6
    li %r9, 5
    cmpwi %cr0, %r9, 5       /* CR0: EQ */
    mcrf %cr6, %cr0
    bne %cr0, fail           /* CR0 should still have EQ */
    bne %cr6, fail           /* CR6 should also have EQ */

    /* Test overwriting destination */
test_7:
    li TESTNUM, 7
    li %r9, 3
    li %r10, 5
    cmpwi %cr0, %r9, 5       /* CR0: LT */
    cmpwi %cr7, %r10, 5      /* CR7: EQ */
    mcrf %cr7, %cr0          /* Overwrite CR7 with CR0 (LT) */
    bge %cr7, fail           /* CR7 should now have LT */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
