/* j2 (SuperH-2) LDS Rm,GBR instruction tests */
/* Loads a register value into the GBR register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * LDS Rm, GBR - Load to GBR register
   *-------------------------------------------------------------*/

  /* Test 2: Load value to GBR and read back */
  TEST_CASE( 2, r3, 0x12340000, \
    mov.l test_2_val, r1; \
    ldc r1, gbr; \
    stc gbr, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x12340000; \
  3: \
  )

  /* Test 3: Load 0 to GBR */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #0, r1; \
    ldc r1, gbr; \
    stc gbr, r3; \
  )

  /* Test 4: Load -1 to GBR */
  TEST_CASE( 4, r3, 0xffffffff, \
    mov #-1, r1; \
    ldc r1, gbr; \
    stc gbr, r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
