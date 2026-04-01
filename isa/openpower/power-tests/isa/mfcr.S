/* OpenPOWER MFCR (Move From Condition Register) instruction tests */
/* mfcr rD -> rD = CR */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Test reading CR with EQ bit set in CR0 */
test_2:
    li TESTNUM, 2
    li %r9, 5
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 (bit 2 of CR0) */
    mfcr %r8
    /* CR0[EQ] is bit 2 = bit 29 of CR = 0x20000000 */
    rlwinm %r8, %r8, 0, 0, 3 /* Extract CR0 field (bits 0-3) */
    /* EQ bit should be set: CR0 = 0b0010 = 0x2, shifted = 0x20000000 */
    LOAD_IMM(%r25, 0x20000000)
    cmpw %cr7, %r8, %r25     /* Use CR7 to avoid clobbering test */
    bne %cr7, fail

    /* Test reading CR with LT bit set */
test_3:
    li TESTNUM, 3
    li %r9, 3
    cmpwi %cr0, %r9, 5       /* CR0[LT] = 1 (bit 0 of CR0) */
    mfcr %r8
    rlwinm %r8, %r8, 0, 0, 3
    /* LT bit: CR0 = 0b1000 = 0x8, shifted = 0x80000000 */
    LOAD_IMM(%r25, 0x80000000)
    cmpw %cr7, %r8, %r25
    bne %cr7, fail

    /* Test reading CR with GT bit set */
test_4:
    li TESTNUM, 4
    li %r9, 10
    cmpwi %cr0, %r9, 5       /* CR0[GT] = 1 (bit 1 of CR0) */
    mfcr %r8
    rlwinm %r8, %r8, 0, 0, 3
    /* GT bit: CR0 = 0b0100 = 0x4, shifted = 0x40000000 */
    LOAD_IMM(%r25, 0x40000000)
    cmpw %cr7, %r8, %r25
    bne %cr7, fail

    /* Test reading CR with multiple fields set */
test_5:
    li TESTNUM, 5
    li %r9, 5
    li %r10, 3
    cmpwi %cr0, %r9, 5       /* CR0[EQ] = 1 */
    cmpwi %cr1, %r10, 5      /* CR1[LT] = 1 */
    mfcr %r8
    /* Check CR0 has EQ */
    rlwinm %r11, %r8, 0, 0, 3
    LOAD_IMM(%r25, 0x20000000)
    cmpw %cr7, %r11, %r25
    bne %cr7, fail
    /* Check CR1 has LT */
    rlwinm %r11, %r8, 4, 0, 3  /* Shift CR1 to CR0 position */
    LOAD_IMM(%r25, 0x80000000)
    cmpw %cr7, %r11, %r25
    bne %cr7, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
