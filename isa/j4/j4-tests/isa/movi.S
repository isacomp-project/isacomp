/* j2 (SuperH-2) MOV immediate instruction tests */
/* MOV #imm, Rn loads sign-extended 8-bit immediate */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Move immediate tests
   *-------------------------------------------------------------*/

  /* Test mov #0 */
  TEST_CASE( 2, r1, 0x00000000, \
    mov #0, r1; \
  )

  /* Test mov #1 */
  TEST_CASE( 3, r1, 0x00000001, \
    mov #1, r1; \
  )

  /* Test mov #-1 */
  TEST_CASE( 4, r1, 0xffffffff, \
    mov #-1, r1; \
  )

  /* Test mov #127 (max positive) */
  TEST_CASE( 5, r1, 0x0000007f, \
    mov #127, r1; \
  )

  /* Test mov #-128 (min negative) */
  TEST_CASE( 6, r1, 0xffffff80, \
    mov #-128, r1; \
  )

  /* Test mov #-2 */
  TEST_CASE( 7, r2, 0xfffffffe, \
    mov #-2, r2; \
  )

  /* Test mov #50 */
  TEST_CASE( 8, r3, 0x00000032, \
    mov #50, r3; \
  )

  /* Test mov #-50 */
  TEST_CASE( 9, r4, 0xffffffce, \
    mov #-50, r4; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
