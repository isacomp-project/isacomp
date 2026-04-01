/* j2 (SuperH-2) ROTCL instruction tests */
/* ROTCL rotates left through carry, T->LSB, MSB->T */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Rotate with carry left tests
   *-------------------------------------------------------------*/

  /* Test rotcl with T=0 */
  TEST_CASE( 2, r1, 0x00000002, \
    clrt; \
    mov #1, r1; \
    rotcl r1; \
  )

  /* Test rotcl with T=1 */
  TEST_CASE( 3, r1, 0x00000003, \
    sett; \
    mov #1, r1; \
    rotcl r1; \
  )

  /* Test rotcl MSB sets T */
  TEST_CASE( 4, r2, 0x00000001, \
    clrt; \
    mov.l test_4_val, r1; \
    rotcl r1; \
    movt r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x80000000; \
  3: \
  )

  /* Test rotcl clears T when MSB=0 */
  TEST_CASE( 5, r2, 0x00000000, \
    sett; \
    mov #1, r1; \
    rotcl r1; \
    movt r2; \
  )

  /* Test rotcl with T and MSB both set */
  TEST_CASE( 6, r1, 0x00000001, \
    sett; \
    mov.l test_6_val, r1; \
    rotcl r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0x80000000; \
  3: \
  )

  /* Test rotcl multiple times */
  TEST_CASE( 7, r1, 0x00000008, \
    clrt; \
    mov #1, r1; \
    rotcl r1; \
    rotcl r1; \
    rotcl r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
