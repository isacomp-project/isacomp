/* MIPS32 SQRT.S instruction tests */
/* sqrt.s fd, fs - Floating-Point Square Root Single */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Square root tests - IEEE 754 single precision
   *-------------------------------------------------------------*/

  /* sqrt(4.0) = 2.0 */
  TEST_FP_OP1_S( 2, sqrt.s, 0x40000000, 0x40800000 )

  /* sqrt(1.0) = 1.0 */
  TEST_FP_OP1_S( 3, sqrt.s, 0x3f800000, 0x3f800000 )

  /* sqrt(9.0) = 3.0 */
  TEST_FP_OP1_S( 4, sqrt.s, 0x40400000, 0x41100000 )

  /* sqrt(16.0) = 4.0 */
  TEST_FP_OP1_S( 5, sqrt.s, 0x40800000, 0x41800000 )

  /* sqrt(0.25) = 0.5 */
  TEST_FP_OP1_S( 6, sqrt.s, 0x3f000000, 0x3e800000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
