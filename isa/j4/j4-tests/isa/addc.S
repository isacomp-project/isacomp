/* j2 (SuperH-2) ADDC instruction tests */
/* ADDC adds with carry from T bit */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests - Add with carry
   *-------------------------------------------------------------*/

  /* addc with T=0: 1 + 2 + 0 = 3 */
  TEST_CASE( 2, r3, 0x00000003, \
    clrt; \
    mov #1, r1; \
    mov #2, r2; \
    addc r2, r1; \
    mov r1, r3; \
  )

  /* addc with T=1: 1 + 2 + 1 = 4 */
  TEST_CASE( 3, r3, 0x00000004, \
    sett; \
    mov #1, r1; \
    mov #2, r2; \
    addc r2, r1; \
    mov r1, r3; \
  )

  /* addc 0 + 0 + 0 = 0 */
  TEST_CASE( 4, r3, 0x00000000, \
    clrt; \
    mov #0, r1; \
    mov #0, r2; \
    addc r2, r1; \
    mov r1, r3; \
  )

  /* addc 0xffffffff + 0 + 1 = 0 with carry */
  TEST_CASE( 5, r2, 0x00000000, \
    sett; \
    mov #-1, r1; \
    mov #0, r3; \
    addc r3, r1; \
    mov r1, r2; \
  )

  /* addc 0xffffffff + 1 + 0 = 0 with carry */
  TEST_CASE( 6, r2, 0x00000000, \
    clrt; \
    mov #-1, r1; \
    mov #1, r3; \
    addc r3, r1; \
    mov r1, r2; \
  )

  /* addc 0x7fffffff + 0x7fffffff + 1 = 0xffffffff */
  TEST_CASE( 7, r3, 0xffffffff, \
    sett; \
    mov.l test_7_data1, r1; \
    mov.l test_7_data2, r2; \
    addc r2, r1; \
    mov r1, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_data1: \
    .long 0x7fffffff; \
  test_7_data2: \
    .long 0x7fffffff; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
