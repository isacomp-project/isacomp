/* j2 (SuperH-2) SUBC instruction tests */
/* SUBC subtracts with borrow from T bit */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests - Subtract with carry
   *-------------------------------------------------------------*/

  /* subc with T=0: 5 - 2 - 0 = 3 */
  TEST_CASE( 2, r3, 0x00000003, \
    clrt; \
    mov #5, r1; \
    mov #2, r2; \
    subc r2, r1; \
    mov r1, r3; \
  )

  /* subc with T=1: 5 - 2 - 1 = 2 */
  TEST_CASE( 3, r3, 0x00000002, \
    sett; \
    mov #5, r1; \
    mov #2, r2; \
    subc r2, r1; \
    mov r1, r3; \
  )

  /* subc 0 - 0 - 0 = 0 */
  TEST_CASE( 4, r3, 0x00000000, \
    clrt; \
    mov #0, r1; \
    mov #0, r2; \
    subc r2, r1; \
    mov r1, r3; \
  )

  /* subc 0 - 1 - 0 = 0xffffffff */
  TEST_CASE( 5, r2, 0xffffffff, \
    clrt; \
    mov #0, r1; \
    mov #1, r3; \
    subc r3, r1; \
    mov r1, r2; \
  )

  /* subc 0 - 0 - 1 = 0xffffffff */
  TEST_CASE( 6, r2, 0xffffffff, \
    sett; \
    mov #0, r1; \
    mov #0, r3; \
    subc r3, r1; \
    mov r1, r2; \
  )

  /* subc 10 - 5 - 1 = 4 */
  TEST_CASE( 7, r3, 0x00000004, \
    sett; \
    mov #10, r1; \
    mov #5, r2; \
    subc r2, r1; \
    mov r1, r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
