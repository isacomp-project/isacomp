/* MIPS32R2 WSBH instruction tests */
/* wsbh rd, rt - Word Swap Bytes Within Halfwords */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic WSBH tests
   * Swaps bytes within each 16-bit halfword
   * 0xAABBCCDD -> 0xBBAADDCC
   *-------------------------------------------------------------*/

  /* Test 2: Zero stays zero */
  TEST_CASE( 2, $t0, 0x00000000,
    li $t1, 0x00000000;
    wsbh $t0, $t1;
  )

  /* Test 3: All ones stays all ones */
  TEST_CASE( 3, $t0, 0xFFFFFFFF,
    li $t1, 0xFFFFFFFF;
    wsbh $t0, $t1;
  )

  /* Test 4: Basic swap 0x12345678 -> 0x34127856 */
  TEST_CASE( 4, $t0, 0x34127856,
    li $t1, 0x12345678;
    wsbh $t0, $t1;
  )

  /* Test 5: 0xAABBCCDD -> 0xBBAADDCC */
  TEST_CASE( 5, $t0, 0xBBAADDCC,
    li $t1, 0xAABBCCDD;
    wsbh $t0, $t1;
  )

  /* Test 6: Low halfword only */
  TEST_CASE( 6, $t0, 0x00002211,
    li $t1, 0x00001122;
    wsbh $t0, $t1;
  )

  /* Test 7: High halfword only */
  TEST_CASE( 7, $t0, 0x22110000,
    li $t1, 0x11220000;
    wsbh $t0, $t1;
  )

  /* Test 8: 0x01020304 -> 0x02010403 */
  TEST_CASE( 8, $t0, 0x02010403,
    li $t1, 0x01020304;
    wsbh $t0, $t1;
  )

  /* Test 9: 0x00FF00FF -> 0xFF00FF00 */
  TEST_CASE( 9, $t0, 0xFF00FF00,
    li $t1, 0x00FF00FF;
    wsbh $t0, $t1;
  )

  /* Test 10: 0xFF00FF00 -> 0x00FF00FF */
  TEST_CASE( 10, $t0, 0x00FF00FF,
    li $t1, 0xFF00FF00;
    wsbh $t0, $t1;
  )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
