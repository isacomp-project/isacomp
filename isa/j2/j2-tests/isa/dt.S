/* j2 (SuperH-2) DT instruction tests */
/* DT Rn - Decrements Rn, sets T=1 if result is 0, else T=0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Decrement and Test tests
   *-------------------------------------------------------------*/

  /* Test 2: DT 1 = 0, T should be set */
  TEST_CASE( 2, r3, 0x00000001, \
    mov #1, r1; \
    dt r1; \
    movt r3; \
  )

  /* Verify r1 is now 0 */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #1, r1; \
    dt r1; \
  )

  /* Test 4: DT 2 = 1, T should be clear */
  TEST_CASE( 4, r3, 0x00000000, \
    mov #2, r1; \
    dt r1; \
    movt r3; \
  )

  /* Verify r1 is now 1 */
  TEST_CASE( 5, r1, 0x00000001, \
    mov #2, r1; \
    dt r1; \
  )

  /* Test 6: DT 0 = -1, T should be clear */
  TEST_CASE( 6, r3, 0x00000000, \
    mov #0, r1; \
    dt r1; \
    movt r3; \
  )

  /* Test 7: Loop counting - count from 3 to 0 */
  /* After 3 iterations, r2 should be 3 */
  TEST_CASE( 7, r2, 0x00000003, \
    mov #3, r1; \
    mov #0, r2; \
1:  add #1, r2; \
    dt r1; \
    bf 1b; \
    nop; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
