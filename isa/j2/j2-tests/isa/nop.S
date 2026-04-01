/* j2 (SuperH-2) NOP instruction test */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * NOP tests
   *-------------------------------------------------------------*/

  TEST_CASE( 2, r1, 1, \
    mov #1, r1; \
    nop; \
    nop; \
    nop; \
  )

  TEST_CASE( 3, r2, 5, \
    mov #5, r2; \
    nop; \
  )

  TEST_CASE( 4, r3, 42, \
    nop; \
    mov #42, r3; \
    nop; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
