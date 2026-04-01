/* j2 (SuperH-2) DIV0U instruction tests */
/* DIV0U initializes division (unsigned) - clears Q, M, T bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Division step 0 tests - Unsigned division initialization
   *-------------------------------------------------------------*/

  /* Test div0u clears T bit */
  TEST_CASE( 2, r1, 0x00000000, \
    sett; \
    div0u; \
    movt r1; \
  )

  /* Test div0u when T already clear */
  TEST_CASE( 3, r1, 0x00000000, \
    clrt; \
    div0u; \
    movt r1; \
  )

  /* Test div0u multiple times */
  TEST_CASE( 4, r1, 0x00000000, \
    sett; \
    div0u; \
    div0u; \
    div0u; \
    movt r1; \
  )

  /* Test div0u after div0s */
  TEST_CASE( 5, r3, 0x00000000, \
    mov #-5, r1; \
    mov #3, r2; \
    div0s r2, r1; \
    div0u; \
    movt r3; \
  )

  /* Test div0u consistency */
  TEST_CASE( 6, r1, 0x00000000, \
    sett; \
    sett; \
    div0u; \
    movt r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
