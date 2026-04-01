/* OpenPOWER FNMADD instruction tests */
/* fnmadd frt, fra, frc, frb - Floating Negative Multiply-Add Double */
/* frt = -((fra * frc) + frb) */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic negative fused multiply-add tests
   *-------------------------------------------------------------*/

  /* -((2.0 * 3.0) + 1.0) = -7.0 */
  /* -7.0 = 0xc01c000000000000 */
  TEST_FP_OP3_D( 2, fnmadd, 0xc01c0000, 0x00000000,
                 0x40000000, 0x00000000,   /* fra = 2.0 */
                 0x40080000, 0x00000000,   /* frc = 3.0 */
                 0x3ff00000, 0x00000000 )  /* frb = 1.0 */

  /* -((1.0 * 1.0) + 1.0) = -2.0 */
  TEST_FP_OP3_D( 3, fnmadd, 0xc0000000, 0x00000000,
                 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000,
                 0x3ff00000, 0x00000000 )

  /* -((2.0 * 2.0) + (-5.0)) = -(4 - 5) = -(-1) = 1.0 */
  TEST_FP_OP3_D( 4, fnmadd, 0x3ff00000, 0x00000000,
                 0x40000000, 0x00000000,
                 0x40000000, 0x00000000,
                 0xc0140000, 0x00000000 )

  /* -((0.0 * 3.0) + 5.0) = -5.0 */
  TEST_FP_OP3_D( 5, fnmadd, 0xc0140000, 0x00000000,
                 0x00000000, 0x00000000,
                 0x40080000, 0x00000000,
                 0x40140000, 0x00000000 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
