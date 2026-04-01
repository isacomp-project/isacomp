/* OpenPOWER FSEL instruction tests */
/* fsel frt, fra, frc, frb - Floating Select */
/* If fra >= 0.0 then frt = frc, else frt = frb */

#include "../test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic select tests
   * Format: TEST_FSEL_D(testnum, res_hi, res_lo,
   *                     fra_hi, fra_lo, frc_hi, frc_lo, frb_hi, frb_lo)
   *-------------------------------------------------------------*/

  /* fra = 1.0 >= 0, select frc = 2.0 */
  TEST_FSEL_D( 2, 0x40000000, 0x00000000,
               0x3ff00000, 0x00000000,   /* fra = 1.0 (>= 0) */
               0x40000000, 0x00000000,   /* frc = 2.0 (selected) */
               0x40080000, 0x00000000 )  /* frb = 3.0 (not selected) */

  /* fra = -1.0 < 0, select frb = 3.0 */
  TEST_FSEL_D( 3, 0x40080000, 0x00000000,
               0xbff00000, 0x00000000,   /* fra = -1.0 (< 0) */
               0x40000000, 0x00000000,   /* frc = 2.0 (not selected) */
               0x40080000, 0x00000000 )  /* frb = 3.0 (selected) */

  /* fra = 0.0 >= 0, select frc = 5.0 */
  TEST_FSEL_D( 4, 0x40140000, 0x00000000,
               0x00000000, 0x00000000,   /* fra = 0.0 (>= 0) */
               0x40140000, 0x00000000,   /* frc = 5.0 (selected) */
               0x40180000, 0x00000000 )  /* frb = 6.0 (not selected) */

  /* fra = -0.0: Note -0.0 is treated as >= 0 by fsel! */
  /* This is a key difference from a simple sign check */
  TEST_FSEL_D( 5, 0x40140000, 0x00000000,
               0x80000000, 0x00000000,   /* fra = -0.0 (>= 0 for fsel) */
               0x40140000, 0x00000000,   /* frc = 5.0 (selected) */
               0x40180000, 0x00000000 )  /* frb = 6.0 (not selected) */

  /* fra = small positive */
  TEST_FSEL_D( 6, 0x40000000, 0x00000000,
               0x3e700000, 0x00000000,   /* fra = small positive */
               0x40000000, 0x00000000,   /* frc = 2.0 (selected) */
               0x40080000, 0x00000000 )  /* frb = 3.0 */

  /* fra = small negative */
  TEST_FSEL_D( 7, 0x40080000, 0x00000000,
               0xbe700000, 0x00000000,   /* fra = small negative */
               0x40000000, 0x00000000,   /* frc = 2.0 */
               0x40080000, 0x00000000 )  /* frb = 3.0 (selected) */

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
