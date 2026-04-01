/* j2 (SuperH-2) EXTS.B and EXTS.W instruction tests */
/* Sign extends byte or word to 32 bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Sign extend byte tests (EXTS.B)
   *-------------------------------------------------------------*/

  /* Test 2: Positive byte 0x7F stays 0x7F */
  TEST_CASE( 2, r2, 0x0000007f, \
    mov #0x7f, r1; \
    exts.b r1, r2; \
  )

  /* Test 3: Zero stays zero */
  TEST_CASE( 3, r2, 0x00000000, \
    mov #0, r1; \
    exts.b r1, r2; \
  )

  /* Test 4: Negative byte 0x80 sign extends to 0xFFFFFF80 */
  TEST_CASE( 4, r2, 0xffffff80, \
    mov #-128, r1; \
    exts.b r1, r2; \
  )

  /* Test 5: -1 stays -1 */
  TEST_CASE( 5, r2, 0xffffffff, \
    mov #-1, r1; \
    exts.b r1, r2; \
  )

  /*-------------------------------------------------------------
   * Sign extend word tests (EXTS.W)
   *-------------------------------------------------------------*/

  /* Test 6: Positive word stays positive */
  TEST_CASE( 6, r2, 0x0000007f, \
    mov #0x7f, r1; \
    exts.w r1, r2; \
  )

  /* Test 7: -1 stays -1 with exts.w */
  TEST_CASE( 7, r2, 0xffffffff, \
    mov #-1, r1; \
    exts.w r1, r2; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
