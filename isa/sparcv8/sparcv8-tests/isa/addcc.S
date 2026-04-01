/* SPARCv8 ADDcc instruction tests */
/* Tests ADD with condition code setting */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests (same as ADD)
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  addcc, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  addcc, 0x00000002, 0x00000001, 0x00000001 )
  TEST_RR_OP( 4,  addcc, 0x0000000a, 0x00000003, 0x00000007 )

  TEST_RR_OP( 5,  addcc, 0xffff8000, 0x00000000, 0xffff8000 )
  TEST_RR_OP( 6,  addcc, 0x80000000, 0x80000000, 0x00000000 )
  TEST_RR_OP( 7,  addcc, 0x7fff8000, 0x80000000, 0xffff8000 )

  /*-------------------------------------------------------------
   * Condition code tests
   *-------------------------------------------------------------*/

  /* Z flag: 0 + 0 = 0 (Z set) */
  TEST_CC_Z_SET( 8, addcc, 0x00000000, 0x00000000 )

  /* Z flag: 1 + 1 = 2 (Z clear) */
  TEST_CC_Z_CLEAR( 9, addcc, 0x00000001, 0x00000001 )

  /* N flag: result is negative */
  TEST_CC_N_SET( 10, addcc, 0x80000000, 0x00000001 )

  /* N flag: result is positive */
  TEST_CC_N_CLEAR( 11, addcc, 0x00000001, 0x00000001 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 12, addcc, 24, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 13, addcc, 25, 14, 11 )

  /*-------------------------------------------------------------
   * Zero register tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 14, addcc, 15, 15 )
  TEST_RR_ZEROSRC2( 15, addcc, 32, 32 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
