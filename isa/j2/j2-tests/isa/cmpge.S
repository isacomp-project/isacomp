/* j2 (SuperH-2) CMP/GE instruction tests */
/* CMP/GE sets T if Rn >= Rm (signed) */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Comparison tests - Greater or equal (signed)
   *-------------------------------------------------------------*/

  /* Test 5 >= 3 (true) */
  TEST_CASE( 2, r3, 0x00000001, \
    mov #5, r1; \
    mov #3, r2; \
    cmp/ge r2, r1; \
    movt r3; \
  )

  /* Test 3 >= 5 (false) */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #3, r1; \
    mov #5, r2; \
    cmp/ge r2, r1; \
    movt r3; \
  )

  /* Test 5 >= 5 (true) */
  TEST_CASE( 4, r3, 0x00000001, \
    mov #5, r1; \
    mov #5, r2; \
    cmp/ge r2, r1; \
    movt r3; \
  )

  /* Test 0 >= 0 (true) */
  TEST_CASE( 5, r3, 0x00000001, \
    mov #0, r1; \
    mov #0, r2; \
    cmp/ge r2, r1; \
    movt r3; \
  )

  /* Test -1 >= -2 (true) */
  TEST_CASE( 6, r3, 0x00000001, \
    mov #-1, r1; \
    mov #-2, r2; \
    cmp/ge r2, r1; \
    movt r3; \
  )

  /* Test -2 >= -1 (false) */
  TEST_CASE( 7, r3, 0x00000000, \
    mov #-2, r1; \
    mov #-1, r2; \
    cmp/ge r2, r1; \
    movt r3; \
  )

  /* Test 1 >= -1 (true) */
  TEST_CASE( 8, r3, 0x00000001, \
    mov #1, r1; \
    mov #-1, r2; \
    cmp/ge r2, r1; \
    movt r3; \
  )

  /* Test -1 >= 1 (false) */
  TEST_CASE( 9, r3, 0x00000000, \
    mov #-1, r1; \
    mov #1, r2; \
    cmp/ge r2, r1; \
    movt r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
