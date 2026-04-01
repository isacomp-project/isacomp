#include "test_macros.h"

RVTEST_CODE_BEGIN

    # Test LDW/STW - word load and store
    # HPPA requires space register in memory ops: stw src,disp(sr,base)
    
test_2:
    ldo 2(%r0), %r28
    ldo 0x100(%r0), %r2
    ldo 42(%r0), %r3
    stw %r3, 0(%sr0,%r2)
    ldw 0(%sr0,%r2), %r1
    ldo 42(%r0), %r29
    cmpb,<> %r1, %r29, fail
    nop

test_3:
    ldo 3(%r0), %r28
    ldo 0x104(%r0), %r2
    ldo 99(%r0), %r3
    stw %r3, 0(%sr0,%r2)
    ldw 0(%sr0,%r2), %r1
    ldo 99(%r0), %r29
    cmpb,<> %r1, %r29, fail
    nop

    TEST_PASSFAIL
    
RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
    TEST_DATA
RVTEST_DATA_END
