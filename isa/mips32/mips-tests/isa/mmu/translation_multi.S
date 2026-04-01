/* MIPS32 MMU Multiple Translation Verification Test
 *
 * Tests multiple TLB entries with different non-identity mappings:
 *   Entry 0: VPN2=0x10 (VA 0x20000) -> PFN=0x80 (PA 0x80000)
 *   Entry 1: VPN2=0x20 (VA 0x40000) -> PFN=0x30 (PA 0x30000)
 */

#include "mmu_test_macros.h"

RVTEST_CODE_BEGIN

    /* Setup TLB Entry 0: VPN2=0x10 -> PFN=0x80 */
test_1:
    li TESTNUM, 1
    li $t0, 0
    mtc0 $t0, $0, 0
    li $t0, 0x00020000
    mtc0 $t0, $10, 0
    li $t0, 0x00002007           /* PFN=0x80 << 6 = 0x2000 */
    mtc0 $t0, $2, 0
    li $t0, 0x00002047
    mtc0 $t0, $3, 0
    nop
    tlbwi
    nop

    /* Setup TLB Entry 1: VPN2=0x20 -> PFN=0x30 */
test_2:
    li TESTNUM, 2
    li $t0, 1
    mtc0 $t0, $0, 0
    li $t0, 0x00040000
    mtc0 $t0, $10, 0
    li $t0, 0x00000C07           /* PFN=0x30 << 6 = 0xC00 */
    mtc0 $t0, $2, 0
    li $t0, 0x00000C47
    mtc0 $t0, $3, 0
    nop
    tlbwi
    nop

    /* Write via VA 0x20000 -> PA 0x80000 */
test_3:
    li TESTNUM, 3
    li $t0, 0x00020000
    li $t1, 0x11111111
    sw $t1, 0($t0)
    nop

    /* Write via VA 0x40000 -> PA 0x30000 */
test_4:
    li TESTNUM, 4
    li $t0, 0x00040000
    li $t2, 0x22222222
    sw $t2, 0($t0)
    nop

    /* Verify PA 0x80000 via kseg0 */
test_5:
    li TESTNUM, 5
    li $t0, 0x80080000
    lw $t3, 0($t0)
    li $t4, 0x11111111
    bne $t3, $t4, fail
    nop

    /* Verify PA 0x30000 via kseg0 */
test_6:
    li TESTNUM, 6
    li $t0, 0x80030000
    lw $t3, 0($t0)
    li $t4, 0x22222222
    bne $t3, $t4, fail
    nop

    /* Reverse: write via kseg0, read via TLB */
test_7:
    li TESTNUM, 7
    li $t0, 0x80080000
    li $t1, 0xAAAAAAAA
    sw $t1, 0($t0)
    nop
    li $t0, 0x00020000
    lw $t2, 0($t0)
    bne $t1, $t2, fail
    nop

    TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
