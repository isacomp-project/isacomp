/* j2 (SuperH-2) NEG instruction tests */
/* Based on riscv-tests structure */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests - NEG negates the value
   *-------------------------------------------------------------*/

  /* neg 0 = 0 */
  TEST_CASE( 2, r2, 0x00000000, \
    mov #0, r1; \
    neg r1, r2; \
  )

  /* neg 1 = -1 */
  TEST_CASE( 3, r2, 0xffffffff, \
    mov #1, r1; \
    neg r1, r2; \
  )

  /* neg -1 = 1 */
  TEST_CASE( 4, r2, 0x00000001, \
    mov #-1, r1; \
    neg r1, r2; \
  )

  /* neg 0x7f = 0xffffff81 */
  TEST_CASE( 5, r2, 0xffffff81, \
    mov #0x7f, r1; \
    neg r1, r2; \
  )

  /* neg -128 = 128 */
  TEST_CASE( 6, r2, 0x00000080, \
    mov #-128, r1; \
    neg r1, r2; \
  )

  /*-------------------------------------------------------------
   * Self-destination test
   *-------------------------------------------------------------*/

  TEST_CASE( 7, r1, 0xfffffffe, \
    mov #2, r1; \
    neg r1, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
