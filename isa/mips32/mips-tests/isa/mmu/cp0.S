/* MIPS32 CP0 Register Access Tests */
/* Tests MFC0 and MTC0 instructions */

#include "mmu_test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test MTC0 and MFC0 with Index register ($0)
   *-------------------------------------------------------------*/

  /* Test 2: Write and read Index register */
test_2:
    li TESTNUM, 2
    li $t1, 5
    mtc0 $t1, $0, 0      /* Write 5 to Index */
    nop
    nop
    mfc0 $t0, $0, 0      /* Read Index */
    andi $t0, $t0, 0x1f  /* Mask to 5 bits */
    li $t9, 5
    bne $t0, $t9, fail
    nop

  /* Test 3: Write and read Wired register ($6) */
test_3:
    li TESTNUM, 3
    li $t1, 8
    mtc0 $t1, $6, 0      /* Write 8 to Wired */
    nop
    nop
    mfc0 $t0, $6, 0      /* Read Wired */
    andi $t0, $t0, 0x1f  /* Mask to 5 bits */
    li $t9, 8
    bne $t0, $t9, fail
    nop

  /* Test 4: Write and read Count register ($9) */
test_4:
    li TESTNUM, 4
    li $t1, 0x12345678
    mtc0 $t1, $9, 0      /* Write to Count */
    nop
    nop
    mfc0 $t0, $9, 0      /* Read Count */
    /* Count may have incremented, just check it's non-zero after write */
    beq $t0, $zero, fail
    nop

  /* Test 5: Write and read Compare register ($11) */
test_5:
    li TESTNUM, 5
    li $t1, 0xDEADBEEF
    mtc0 $t1, $11, 0     /* Write to Compare */
    nop
    nop
    mfc0 $t0, $11, 0     /* Read Compare */
    li $t9, 0xDEADBEEF
    bne $t0, $t9, fail
    nop

  /* Test 6: Write and read Status register ($12) */
test_6:
    li TESTNUM, 6
    mfc0 $t2, $12, 0     /* Save original Status */
    li $t1, 0x00000001   /* Set IE bit */
    mtc0 $t1, $12, 0     /* Write to Status */
    nop
    nop
    mfc0 $t0, $12, 0     /* Read Status */
    andi $t0, $t0, 0x01  /* Check IE bit */
    li $t9, 1
    bne $t0, $t9, fail
    nop
    mtc0 $t2, $12, 0     /* Restore Status */
    nop

  /* Test 7: Write and read EPC register ($14) */
test_7:
    li TESTNUM, 7
    li $t1, 0x80001000
    mtc0 $t1, $14, 0     /* Write to EPC */
    nop
    nop
    mfc0 $t0, $14, 0     /* Read EPC */
    li $t9, 0x80001000
    bne $t0, $t9, fail
    nop

  /* Test 8: Write and read EntryHi register ($10) */
test_8:
    li TESTNUM, 8
    li $t1, 0x12340055   /* VPN2 = 0x91A, ASID = 0x55 */
    mtc0 $t1, $10, 0     /* Write to EntryHi */
    nop
    nop
    mfc0 $t0, $10, 0     /* Read EntryHi */
    /* Check ASID field */
    andi $t3, $t0, 0xFF
    li $t9, 0x55
    bne $t3, $t9, fail
    nop

  /* Test 9: Write and read EntryLo0 register ($2) */
test_9:
    li TESTNUM, 9
    li $t1, 0x00001047   /* PFN=0x41, C=0, D=1, V=1, G=1 */
    mtc0 $t1, $2, 0      /* Write to EntryLo0 */
    nop
    nop
    mfc0 $t0, $2, 0      /* Read EntryLo0 */
    li $t9, 0x00001047
    bne $t0, $t9, fail
    nop

  /* Test 10: Write and read EntryLo1 register ($3) */
test_10:
    li TESTNUM, 10
    li $t1, 0x00002087   /* PFN=0x82, C=0, D=0, V=1, G=1 */
    mtc0 $t1, $3, 0      /* Write to EntryLo1 */
    nop
    nop
    mfc0 $t0, $3, 0      /* Read EntryLo1 */
    li $t9, 0x00002087
    bne $t0, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
