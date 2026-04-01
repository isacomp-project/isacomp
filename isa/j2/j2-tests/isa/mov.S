/* j2 (SuperH-2) MOV instruction tests */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic mov tests
   *-------------------------------------------------------------*/

  TEST_CASE( 2, r2, 0x00000001, \
    mov #1, r1; \
    mov r1, r2; \
  )

  TEST_CASE( 3, r2, 0xffffffff, \
    mov #-1, r1; \
    mov r1, r2; \
  )

  TEST_CASE( 4, r2, 0x00000000, \
    mov #0, r1; \
    mov r1, r2; \
  )

  TEST_CASE( 5, r2, 0x7f, \
    mov #0x7f, r1; \
    mov r1, r2; \
  )

  TEST_CASE( 6, r2, 0xffffff80, \
    mov #-128, r1; \
    mov r1, r2; \
  )

  /*-------------------------------------------------------------
   * Self-move test
   *-------------------------------------------------------------*/

  TEST_CASE( 7, r1, 42, \
    mov #42, r1; \
    mov r1, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
