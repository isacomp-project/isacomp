/* MIPS32 TLBP Tests */
/* Tests TLB Probe instruction */

#include "mmu_test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Setup: Write some TLB entries for probing
   *-------------------------------------------------------------*/

  /* Write TLB entry 3 with VPN2=0x1000, ASID=0x55 */
setup_entry_3:
    li $t0, 3
    mtc0 $t0, $0, 0      /* Index = 3 */
    lui $t0, 0x1000
    ori $t0, $t0, 0x0055 /* VPN2=0x1000xxx, ASID=0x55 */
    mtc0 $t0, $10, 0     /* EntryHi */
    li $t0, 0x00040047   /* PFN=0x100, D=1, V=1, G=1 */
    mtc0 $t0, $2, 0      /* EntryLo0 */
    li $t0, 0x00040087   /* PFN=0x102, D=0, V=1, G=1 */
    mtc0 $t0, $3, 0      /* EntryLo1 */
    nop
    tlbwi
    nop

  /* Write TLB entry 7 with VPN2=0x2000, ASID=0x77 */
setup_entry_7:
    li $t0, 7
    mtc0 $t0, $0, 0      /* Index = 7 */
    lui $t0, 0x2000
    ori $t0, $t0, 0x0077 /* VPN2=0x2000xxx, ASID=0x77 */
    mtc0 $t0, $10, 0     /* EntryHi */
    li $t0, 0x00080047
    mtc0 $t0, $2, 0
    li $t0, 0x00080087
    mtc0 $t0, $3, 0
    nop
    tlbwi
    nop
    nop

  /*-------------------------------------------------------------
   * Test 2: Probe for entry that exists (entry 3)
   *-------------------------------------------------------------*/
test_2:
    li TESTNUM, 2
    /* Set EntryHi to match entry 3 */
    lui $t0, 0x1000
    ori $t0, $t0, 0x0055
    mtc0 $t0, $10, 0
    nop
    nop
    tlbp
    nop
    nop
    /* Check Index - should be 3 (bit 31 should be 0) */
    mfc0 $t0, $0, 0
    /* Check if bit 31 (probe failure) is clear */
    srl $t1, $t0, 31
    bne $t1, $zero, fail
    nop
    /* Check index value = 3 */
    andi $t1, $t0, 0x1F
    li $t9, 3
    bne $t1, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 3: Probe for entry that exists (entry 7)
   *-------------------------------------------------------------*/
test_3:
    li TESTNUM, 3
    lui $t0, 0x2000
    ori $t0, $t0, 0x0077
    mtc0 $t0, $10, 0
    nop
    nop
    tlbp
    nop
    nop
    mfc0 $t0, $0, 0
    /* Check probe success */
    srl $t1, $t0, 31
    bne $t1, $zero, fail
    nop
    /* Check index = 7 */
    andi $t1, $t0, 0x1F
    li $t9, 7
    bne $t1, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 4: Probe for entry that doesn't exist
   *-------------------------------------------------------------*/
test_4:
    li TESTNUM, 4
    /* Use a VPN2 that wasn't written */
    lui $t0, 0x3000
    ori $t0, $t0, 0x0099
    mtc0 $t0, $10, 0
    nop
    nop
    tlbp
    nop
    nop
    mfc0 $t0, $0, 0
    /* Check bit 31 (probe failure) is SET */
    srl $t1, $t0, 31
    li $t9, 1
    bne $t1, $t9, fail
    nop

  /*-------------------------------------------------------------
   * Test 5: Probe with matching VPN2 but wrong ASID
   *-------------------------------------------------------------*/
test_5:
    li TESTNUM, 5
    /* VPN2 matches entry 3, but ASID is different */
    lui $t0, 0x1000
    ori $t0, $t0, 0x00AA  /* ASID=0xAA, not 0x55 */
    mtc0 $t0, $10, 0
    nop
    nop
    tlbp
    nop
    nop
    mfc0 $t0, $0, 0
    /* Entry 3 has G=1, so should match regardless of ASID */
    srl $t1, $t0, 31
    bne $t1, $zero, fail  /* Should find it (G=1 means global) */
    nop

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
