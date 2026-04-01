/* SPARCv8 SUBcc instruction tests */
/* Tests SUB with condition code setting */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic arithmetic tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  subcc, 0x00000000, 0x00000000, 0x00000000 )
  TEST_RR_OP( 3,  subcc, 0x00000000, 0x00000001, 0x00000001 )
  TEST_RR_OP( 4,  subcc, 0xfffffffc, 0x00000003, 0x00000007 )

  /*-------------------------------------------------------------
   * Condition code tests
   *-------------------------------------------------------------*/

  /* Z flag: 5 - 5 = 0 (Z set) */
  TEST_CC_Z_SET( 5, subcc, 0x00000005, 0x00000005 )

  /* Z flag: 5 - 3 = 2 (Z clear) */
  TEST_CC_Z_CLEAR( 6, subcc, 0x00000005, 0x00000003 )

  /* N flag: 0 - 1 = -1 (N set) */
  TEST_CC_N_SET( 7, subcc, 0x00000000, 0x00000001 )

  /* N flag: 5 - 3 = 2 (N clear) */
  TEST_CC_N_CLEAR( 8, subcc, 0x00000005, 0x00000003 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 9, subcc, 2, 13, 11 )
  TEST_RR_SRC2_EQ_DEST( 10, subcc, 3, 14, 11 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
