/* j2 (SuperH-2) ROTCR instruction tests */
/* ROTCR rotates right through carry, T->MSB, LSB->T */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Rotate with carry right tests
   *-------------------------------------------------------------*/

  /* Test rotcr with T=0 */
  TEST_CASE( 2, r1, 0x00000000, \
    clrt; \
    mov #1, r1; \
    rotcr r1; \
  )

  /* Test rotcr with T=1 */
  TEST_CASE( 3, r1, 0x80000000, \
    sett; \
    mov #1, r1; \
    rotcr r1; \
  )

  /* Test rotcr LSB sets T */
  TEST_CASE( 4, r2, 0x00000001, \
    clrt; \
    mov #1, r1; \
    rotcr r1; \
    movt r2; \
  )

  /* Test rotcr clears T when LSB=0 */
  TEST_CASE( 5, r2, 0x00000000, \
    sett; \
    mov #2, r1; \
    rotcr r1; \
    movt r2; \
  )

  /* Test rotcr with T and LSB both set */
  TEST_CASE( 6, r1, 0x80000000, \
    sett; \
    mov #1, r1; \
    rotcr r1; \
  )

  /* Test rotcr multiple times */
  TEST_CASE( 7, r1, 0x10000000, \
    clrt; \
    mov.l test_7_val, r1; \
    rotcr r1; \
    rotcr r1; \
    rotcr r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x80000000; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
