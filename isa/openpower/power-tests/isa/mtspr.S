/* OpenPOWER MTSPR (Move To Special Purpose Register) instruction tests */
/* mtspr SPR, rS -> SPR = rS */

#include "test_macros.h"

/* SPR numbers */
#define SPR_LR   8
#define SPR_CTR  9
#define SPR_XER  1

RVTEST_CODE_BEGIN

    /* Test writing to LR */
test_2:
    li TESTNUM, 2
    mflr %r20                /* Save original LR */
    LOAD_IMM(%r9, 0xdeadbeef)
    mtspr SPR_LR, %r9        /* Write to LR */
    mflr %r8                 /* Read it back */
    mtlr %r20                /* Restore LR */
    LOAD_IMM(%r25, 0xdeadbeef)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Test writing to CTR */
test_3:
    li TESTNUM, 3
    LOAD_IMM(%r9, 0xcafebabe)
    mtspr SPR_CTR, %r9       /* Write to CTR */
    mfctr %r8                /* Read it back */
    LOAD_IMM(%r25, 0xcafebabe)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Test CTR for branching after mtspr */
test_4:
    li TESTNUM, 4
    li %r8, 0
    LOAD_ADDR(%r9, target1)
    mtspr SPR_CTR, %r9       /* Set CTR to target */
    bctr                     /* Branch to CTR */
    b fail

target1:
    li %r8, 1
    li %r25, 1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Test LR for return after mtspr */
test_5:
    li TESTNUM, 5
    li %r8, 0
    bl setup_return
    li %r25, 2
    cmpd %cr0, %r8, %r25
    bne %cr0, fail
    b test_6

setup_return:
    mflr %r20                /* Save return address */
    LOAD_ADDR(%r9, target2)
    mtspr SPR_LR, %r9        /* Set LR to new target */
    blr                      /* Return to modified LR */

target2:
    li %r8, 2
    mtlr %r20                /* Restore original LR */
    blr                      /* Return to test_5 continuation */

    /* Test writing 64-bit value to CTR */
test_6:
    li TESTNUM, 6
    li %r9, 1
    sldi %r9, %r9, 40        /* Large 64-bit value */
    ori %r9, %r9, 0x1234
    mtspr SPR_CTR, %r9
    mfspr %r8, SPR_CTR
    cmpd %cr0, %r8, %r9
    bne %cr0, fail

    /* Test mtlr/mtctr aliases */
test_7:
    li TESTNUM, 7
    li %r9, 0x5678
    mtctr %r9                /* Alias for mtspr CTR, r */
    mfctr %r8
    li %r25, 0x5678
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
