/* j2 (SuperH-2) EXTS.W instruction tests */
/* EXTS.W sign-extends word to long */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Extension tests - Sign extend word
   *-------------------------------------------------------------*/

  /* Test exts.w with positive value 0x7fff */
  TEST_CASE( 2, r2, 0x00007fff, \
    mov.l test_2_val, r1; \
    exts.w r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x00007fff; \
  3: \
  )

  /* Test exts.w with negative value 0x8000 -> 0xffff8000 */
  TEST_CASE( 3, r2, 0xffff8000, \
    mov.l test_3_val, r1; \
    exts.w r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_val: \
    .long 0x00008000; \
  3: \
  )

  /* Test exts.w with 0xffff -> 0xffffffff */
  TEST_CASE( 4, r2, 0xffffffff, \
    mov.l test_4_val, r1; \
    exts.w r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x0000ffff; \
  3: \
  )

  /* Test exts.w with 0x0000 */
  TEST_CASE( 5, r2, 0x00000000, \
    mov #0, r1; \
    exts.w r1, r2; \
  )

  /* Test exts.w with 0x0001 */
  TEST_CASE( 6, r2, 0x00000001, \
    mov #1, r1; \
    exts.w r1, r2; \
  )

  /* Test exts.w ignores upper bits */
  TEST_CASE( 7, r2, 0xffff8000, \
    mov.l test_7_val, r1; \
    exts.w r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x12348000; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
