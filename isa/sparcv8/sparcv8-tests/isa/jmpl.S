/* SPARCv8 JMPL instruction tests (jump and link) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test 2: Basic jmpl with register+immediate addressing
   * JMPL saves PC to rd, then jumps to rs1+simm13
   *-------------------------------------------------------------*/

  TEST_CASE( 2, %l0, 1, \
    set 1f, %l1; \
    jmpl %l1, %l2; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 1, %l0; \
2:  \
  )

  /*-------------------------------------------------------------
   * Test 3: JMPL saves return address (PC) in destination register
   *-------------------------------------------------------------*/

  TEST_CASE( 3, %l3, 1, \
    set 1f, %l1; \
    set here3, %l4; \
here3: jmpl %l1, %l2; \
    nop; \
    set 0, %l3; \
    ba 2f; \
    nop; \
1:  /* %l2 should contain address of jmpl instruction */ \
    sub %l2, %l4, %l5; \
    cmp %l5, %g0; \
    bne 3f; \
    nop; \
    set 1, %l3; \
    ba 2f; \
    nop; \
3:  set 0, %l3; \
2:  \
  )

  /*-------------------------------------------------------------
   * Test 4: JMPL with register+register addressing
   *-------------------------------------------------------------*/

  TEST_CASE( 4, %l0, 1, \
    set target4, %l1; \
    set 0, %l2; \
    jmpl %l1 + %l2, %l3; \
    nop; \
    set 0, %l0; \
    ba done4; \
    nop; \
target4: set 1, %l0; \
done4:  \
  )

  /*-------------------------------------------------------------
   * Test 5: JMPL with offset (register + immediate)
   *-------------------------------------------------------------*/

  TEST_CASE( 5, %l0, 1, \
    set base5, %l1; \
    jmpl %l1 + 8, %l3; \
    nop; \
base5: set 0, %l0; \
    ba done5; \
    nop; \
    set 1, %l0; \
done5:  \
  )

  /*-------------------------------------------------------------
   * Test 6: JMPL to %g0 discards return address (like JMP)
   *-------------------------------------------------------------*/

  TEST_CASE( 6, %l0, 1, \
    set 1f, %l1; \
    jmpl %l1, %g0; \
    nop; \
    set 0, %l0; \
    ba 2f; \
    nop; \
1:  set 1, %l0; \
2:  \
  )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
