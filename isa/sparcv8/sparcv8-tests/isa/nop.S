/* SPARCv8 NOP instruction tests */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * NOP: No operation (sethi 0, %g0)
   * Just advances PC, has no other effect
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: NOP doesn't modify registers
   *-------------------------------------------------------------*/

  TEST_CASE( 2, %l0, 42, \
    set 42, %l0; \
    nop; \
    nop; \
    nop; \
    /* %l0 should still be 42 */ \
  )

  /*-------------------------------------------------------------
   * Test 3: NOP in delay slot
   *-------------------------------------------------------------*/

  TEST_CASE( 3, %l0, 1, \
    set 0, %l0; \
    ba 1f; \
    nop; \
    set 99, %l0; \
1:  set 1, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 4: Multiple NOPs don't affect computation
   *-------------------------------------------------------------*/

  TEST_CASE( 4, %l0, 15, \
    set 10, %l1; \
    nop; \
    set 5, %l2; \
    nop; \
    nop; \
    add %l1, %l2, %l0; \
    nop; \
  )

  /*-------------------------------------------------------------
   * Test 5: NOP doesn't affect condition codes
   *-------------------------------------------------------------*/

  TEST_CASE( 5, %l0, 1, \
    set 5, %l1; \
    set 5, %l2; \
    subcc %l1, %l2, %g0; /* sets Z flag */ \
    nop; \
    nop; \
    be 1f; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 1, %l0; \
2:  \
  )

  /*-------------------------------------------------------------
   * Test 6: NOP is just sethi 0, %g0
   *-------------------------------------------------------------*/

  TEST_CASE( 6, %l0, 0, \
    set 123, %l0; \
    sethi 0, %g0; /* same as nop */ \
    mov %g0, %l0; \
    /* %g0 is always 0 */ \
  )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
