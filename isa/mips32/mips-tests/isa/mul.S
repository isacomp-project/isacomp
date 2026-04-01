/* MIPS32 MUL instruction tests */
/* mul rd, rs, rt - Multiply to GPR (low 32 bits) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic MUL tests
   *-------------------------------------------------------------*/

  /* Test 2: 0 * 0 = 0 */
  TEST_RR_OP( 2, mul, 0x00000000, 0x00000000, 0x00000000 )

  /* Test 3: 1 * 1 = 1 */
  TEST_RR_OP( 3, mul, 0x00000001, 0x00000001, 0x00000001 )

  /* Test 4: 3 * 7 = 21 */
  TEST_RR_OP( 4, mul, 21, 3, 7 )

  /* Test 5: 13 * 11 = 143 */
  TEST_RR_OP( 5, mul, 143, 13, 11 )

  /* Test 6: Large positive * 2 */
  TEST_RR_OP( 6, mul, 0xFFFFFFFE, 0x7FFFFFFF, 2 )

  /* Test 7: -1 * -1 = 1 */
  TEST_RR_OP( 7, mul, 1, 0xFFFFFFFF, 0xFFFFFFFF )

  /* Test 8: -1 * 1 = -1 */
  TEST_RR_OP( 8, mul, 0xFFFFFFFF, 0xFFFFFFFF, 1 )

  /* Test 9: 0 * large = 0 */
  TEST_RR_OP( 9, mul, 0, 0, 0x7FFFFFFF )

  /* Test 10: 100 * 100 = 10000 */
  TEST_RR_OP( 10, mul, 10000, 100, 100 )

  /* Test 11: Power of 2 multiply */
  TEST_RR_OP( 11, mul, 0x00001000, 0x00000100, 0x00000010 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 12, mul, 143, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 13, mul, 154, 14, 11 )
  TEST_RR_SRC12_EQ_DEST( 14, mul, 169, 13 )

  /*-------------------------------------------------------------
   * Zero register tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 15, mul, 0, 31 )
  TEST_RR_ZEROSRC2( 16, mul, 0, 32 )
  TEST_RR_ZEROSRC12( 17, mul, 0 )
  TEST_RR_ZERODEST( 18, mul, 14, 11 )

  TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
