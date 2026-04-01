/* MIPS32 LWC1/SWC1 instruction tests */
/* lwc1 ft, offset(base) - Load Word to FPR */
/* swc1 ft, offset(base) - Store Word from FPR */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * LWC1 tests
   *-------------------------------------------------------------*/

  /* Load 1.0 */
  TEST_FP_LD_OP( 2, lwc1, 0x3f800000, 0, fdat1 )

  /* Load 2.0 with offset */
  TEST_FP_LD_OP( 3, lwc1, 0x40000000, 4, fdat1 )

  /* Load 3.0 */
  TEST_FP_LD_OP( 4, lwc1, 0x40400000, 8, fdat1 )

  /* Load with negative offset */
  TEST_FP_LD_OP( 5, lwc1, 0x3f800000, -12, fdat4 )

  /*-------------------------------------------------------------
   * SWC1 tests
   *-------------------------------------------------------------*/

  /* Store and verify 1.5 */
  TEST_FP_ST_OP( 6, 0x3fc00000, 0, fdat_wr1 )

  /* Store and verify 100.0 */
  TEST_FP_ST_OP( 7, 0x42c80000, 0, fdat_wr2 )

  /* Store and verify -1.0 */
  TEST_FP_ST_OP( 8, 0xbf800000, 0, fdat_wr3 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
  .align 2
fdat1: .word 0x3f800000  /* 1.0 */
fdat2: .word 0x40000000  /* 2.0 */
fdat3: .word 0x40400000  /* 3.0 */
fdat4: .word 0x40800000  /* 4.0 */

fdat_wr1: .word 0
fdat_wr2: .word 0
fdat_wr3: .word 0
RVTEST_DATA_END
