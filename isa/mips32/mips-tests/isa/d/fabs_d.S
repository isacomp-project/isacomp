/* MIPS32 ABS.D instruction tests */
/* abs.d fd, fs - Floating-Point Absolute Value Double */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic ABS.D tests - IEEE 754 double precision
   *-------------------------------------------------------------*/

  /* abs(1.0) = 1.0 */
  TEST_FP_OP1_D( 2, abs.d, 0x3ff00000, 0x00000000, 0x3ff00000, 0x00000000 )

  /* abs(-1.0) = 1.0 */
  TEST_FP_OP1_D( 3, abs.d, 0x3ff00000, 0x00000000, 0xbff00000, 0x00000000 )

  /* abs(0.0) = 0.0 */
  TEST_FP_OP1_D( 4, abs.d, 0x00000000, 0x00000000, 0x00000000, 0x00000000 )

  /* abs(-0.0) = 0.0 */
  TEST_FP_OP1_D( 5, abs.d, 0x00000000, 0x00000000, 0x80000000, 0x00000000 )

  /* abs(-5.0) = 5.0 */
  TEST_FP_OP1_D( 6, abs.d, 0x40140000, 0x00000000, 0xc0140000, 0x00000000 )

  /* abs(100.0) = 100.0 (100.0 = 0x40590000_00000000) */
  TEST_FP_OP1_D( 7, abs.d, 0x40590000, 0x00000000, 0x40590000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
