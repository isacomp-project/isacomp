/* MIPS32 TLBWI/TLBR Tests */
/* Tests TLB Write Indexed and TLB Read instructions */

#include "mmu_test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test TLBWI: Write TLB entry and read it back
   *-------------------------------------------------------------*/

  /* Test 2: Write TLB entry 0 and read back EntryHi */
test_2:
    li TESTNUM, 2
    /* Set Index = 0 */
    li $t0, 0
    mtc0 $t0, $0, 0      /* Index */
    /* Set EntryHi: VPN2 = 0x80001, ASID = 0x42 */
    li $t0, 0x00003042   /* VPN2 = 0x1, ASID = 0x42 */
    mtc0 $t0, $10, 0     /* EntryHi */
    /* Set EntryLo0: PFN = 0x1, D=1, V=1, G=1 */
    li $t0, 0x00000047
    mtc0 $t0, $2, 0      /* EntryLo0 */
    /* Set EntryLo1: PFN = 0x2, D=1, V=1, G=1 */
    li $t0, 0x00000087
    mtc0 $t0, $3, 0      /* EntryLo1 */
    nop
    /* Write TLB */
    tlbwi
    nop
    nop
    /* Clear registers */
    mtc0 $zero, $10, 0
    mtc0 $zero, $2, 0
    mtc0 $zero, $3, 0
    nop
    nop
    /* Read TLB entry back */
    tlbr
    nop
    nop
    /* Check EntryHi */
    mfc0 $t0, $10, 0
    andi $t1, $t0, 0xFF  /* ASID */
    li $t9, 0x42
    bne $t1, $t9, fail
    nop

  /* Test 3: Check EntryLo0 after TLBR */
test_3:
    li TESTNUM, 3
    mfc0 $t0, $2, 0      /* EntryLo0 */
    li $t9, 0x00000047
    bne $t0, $t9, fail
    nop

  /* Test 4: Check EntryLo1 after TLBR */
test_4:
    li TESTNUM, 4
    mfc0 $t0, $3, 0      /* EntryLo1 */
    li $t9, 0x00000087
    bne $t0, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 5: Write to TLB entry 5 and read back
   *-------------------------------------------------------------*/
test_5:
    li TESTNUM, 5
    /* Set Index = 5 */
    li $t0, 5
    mtc0 $t0, $0, 0
    /* Set EntryHi: VPN2 = 0x12345, ASID = 0xAB */
    lui $t0, 0x1234
    ori $t0, $t0, 0x50AB
    mtc0 $t0, $10, 0
    /* Set EntryLo0: PFN = 0x100, D=1, V=1, G=0 */
    li $t0, 0x00004006
    mtc0 $t0, $2, 0
    /* Set EntryLo1: PFN = 0x101, D=0, V=1, G=0 */
    li $t0, 0x00004042
    mtc0 $t0, $3, 0
    nop
    tlbwi
    nop
    nop
    /* Clear and read back */
    mtc0 $zero, $10, 0
    mtc0 $zero, $2, 0
    mtc0 $zero, $3, 0
    nop
    nop
    tlbr
    nop
    nop
    /* Check ASID */
    mfc0 $t0, $10, 0
    andi $t1, $t0, 0xFF
    li $t9, 0xAB
    bne $t1, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 6: Multiple TLB entries - verify isolation
   *-------------------------------------------------------------*/
test_6:
    li TESTNUM, 6
    /* Write entry 0 with ASID = 0x11 */
    li $t0, 0
    mtc0 $t0, $0, 0
    li $t0, 0x00002011
    mtc0 $t0, $10, 0
    li $t0, 0x00000047
    mtc0 $t0, $2, 0
    li $t0, 0x00000087
    mtc0 $t0, $3, 0
    nop
    tlbwi
    nop

    /* Write entry 1 with ASID = 0x22 */
    li $t0, 1
    mtc0 $t0, $0, 0
    li $t0, 0x00004022
    mtc0 $t0, $10, 0
    li $t0, 0x000000C7
    mtc0 $t0, $2, 0
    li $t0, 0x00000107
    mtc0 $t0, $3, 0
    nop
    tlbwi
    nop
    nop

    /* Read entry 0 back */
    li $t0, 0
    mtc0 $t0, $0, 0
    mtc0 $zero, $10, 0
    nop
    tlbr
    nop
    nop
    mfc0 $t0, $10, 0
    andi $t1, $t0, 0xFF
    li $t9, 0x11
    bne $t1, $t9, fail
    nop

  /* Test 7: Verify entry 1 wasn't corrupted */
test_7:
    li TESTNUM, 7
    li $t0, 1
    mtc0 $t0, $0, 0
    mtc0 $zero, $10, 0
    nop
    tlbr
    nop
    nop
    mfc0 $t0, $10, 0
    andi $t1, $t0, 0xFF
    li $t9, 0x22
    bne $t1, $t9, fail
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
