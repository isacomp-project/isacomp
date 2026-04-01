/* j2 (SuperH-2) NOT instruction tests */
/* Based on riscv-tests structure */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical NOT tests - bitwise complement
   *-------------------------------------------------------------*/

  /* not 0 = 0xffffffff */
  TEST_CASE( 2, r2, 0xffffffff, \
    mov #0, r1; \
    not r1, r2; \
  )

  /* not -1 = 0 */
  TEST_CASE( 3, r2, 0x00000000, \
    mov #-1, r1; \
    not r1, r2; \
  )

  /* not 1 = 0xfffffffe */
  TEST_CASE( 4, r2, 0xfffffffe, \
    mov #1, r1; \
    not r1, r2; \
  )

  /* not 0x55 (sign-extended) */
  TEST_CASE( 5, r2, 0xffffffaa, \
    mov #0x55, r1; \
    not r1, r2; \
  )

  /*-------------------------------------------------------------
   * Self-destination test
   *-------------------------------------------------------------*/

  TEST_CASE( 6, r1, 0xfffffffe, \
    mov #1, r1; \
    not r1, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
