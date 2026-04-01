/* j2 (SuperH-2) EXTU.B and EXTU.W instruction tests */
/* Zero extends byte or word to 32 bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Zero extend byte tests (EXTU.B)
   *-------------------------------------------------------------*/

  /* Test 2: 0x7F stays 0x7F */
  TEST_CASE( 2, r2, 0x0000007f, \
    mov #0x7f, r1; \
    extu.b r1, r2; \
  )

  /* Test 3: Zero stays zero */
  TEST_CASE( 3, r2, 0x00000000, \
    mov #0, r1; \
    extu.b r1, r2; \
  )

  /* Test 4: -128 (0xFFFFFF80) masked to 0x80 */
  TEST_CASE( 4, r2, 0x00000080, \
    mov #-128, r1; \
    extu.b r1, r2; \
  )

  /* Test 5: -1 (0xFFFFFFFF) masked to 0xFF */
  TEST_CASE( 5, r2, 0x000000ff, \
    mov #-1, r1; \
    extu.b r1, r2; \
  )

  /*-------------------------------------------------------------
   * Zero extend word tests (EXTU.W)
   *-------------------------------------------------------------*/

  /* Test 6: 0x7F with extu.w */
  TEST_CASE( 6, r2, 0x0000007f, \
    mov #0x7f, r1; \
    extu.w r1, r2; \
  )

  /* Test 7: -1 (0xFFFFFFFF) masked to 0xFFFF */
  TEST_CASE( 7, r2, 0x0000ffff, \
    mov #-1, r1; \
    extu.w r1, r2; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
