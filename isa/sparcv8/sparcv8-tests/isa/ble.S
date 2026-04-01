/* SPARCv8 BLE instruction tests (branch on less or equal, signed) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch taken: val1 <= val2 (signed)
   *-------------------------------------------------------------*/

  TEST_BR_TAKEN( 2, ble, 0, 0 )
  TEST_BR_TAKEN( 3, ble, 0, 1 )
  TEST_BR_TAKEN( 4, ble, 1, 1 )
  TEST_BR_TAKEN( 5, ble, -1, 0 )
  TEST_BR_TAKEN( 6, ble, -1, -1 )
  TEST_BR_TAKEN( 7, ble, -2, -1 )

  /*-------------------------------------------------------------
   * Branch not taken: val1 > val2 (signed)
   *-------------------------------------------------------------*/

  TEST_BR_NOT_TAKEN( 8, ble, 1, 0 )
  TEST_BR_NOT_TAKEN( 9, ble, 0, -1 )
  TEST_BR_NOT_TAKEN( 10, ble, -1, -2 )
  TEST_BR_NOT_TAKEN( 11, ble, 0x7fffffff, 0x80000000 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
