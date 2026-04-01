/* j2 (SuperH-2) DIV1 instruction tests */
/* DIV1 performs one step of division algorithm */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Division step 1 tests - Single division step
   *-------------------------------------------------------------*/

  /* Test basic div1 after div0u */
  /* div1 shifts Rn left, brings in T, compares with Rm, subtracts if >= */
  /* shll r1: 10 << 1 = 20 */
  /* div1: shifted = 20 << 1 = 40; 40 >= 2; r1 = 40-2 = 38 = 0x26 */
  TEST_CASE( 2, r1, 0x00000026, \
    mov #10, r1; \
    mov #2, r2; \
    div0u; \
    shll r1; \
    div1 r2, r1; \
  )

  /* Test div1 after div0s with same signs */
  /* Same as test 2: r1 = 0x26 */
  TEST_CASE( 3, r1, 0x00000026, \
    mov #10, r1; \
    mov #2, r2; \
    div0s r2, r1; \
    shll r1; \
    div1 r2, r1; \
  )

  /* Test div1 remainder accumulation */
  /* Start with r3=5 (> divisor 2), T=0 */
  /* div1: shifted = 10; 10 >= 2; r3 = 10-2 = 8; T = 1 */
  TEST_CASE( 4, r3, 0x00000008, \
    mov #5, r3; \
    mov #2, r2; \
    div0u; \
    div1 r2, r3; \
  )

  /* Test div1 T bit setting */
  TEST_CASE( 5, r4, 0x00000001, \
    mov #10, r1; \
    mov #3, r2; \
    div0u; \
    shll r1; \
    div1 r2, r1; \
    movt r4; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
