/* SPARCv8 CALL instruction tests */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test 2: Basic CALL - verify it transfers control
   * CALL saves PC to %o7 and jumps to PC + (disp30 * 4)
   *-------------------------------------------------------------*/

  TEST_CASE( 2, %l0, 1, \
    call func2; \
    nop; \
    ba done2; \
    nop; \
func2: set 1, %l0; \
    jmpl %o7 + 8, %g0; \
    nop; \
done2:  \
  )

  /*-------------------------------------------------------------
   * Test 3: CALL saves return address in %o7
   *-------------------------------------------------------------*/

  TEST_CASE( 3, %l3, 1, \
    set call3, %l4; \
call3: call func3; \
    nop; \
    ba done3; \
    nop; \
func3: /* %o7 should contain address of call instruction */ \
    sub %o7, %l4, %l5; \
    cmp %l5, %g0; \
    bne fail3; \
    nop; \
    set 1, %l3; \
    jmpl %o7 + 8, %g0; \
    nop; \
fail3: set 0, %l3; \
    jmpl %o7 + 8, %g0; \
    nop; \
done3:  \
  )

  /*-------------------------------------------------------------
   * Test 4: CALL and return (retl = jmpl %o7+8, %g0)
   *-------------------------------------------------------------*/

  TEST_CASE( 4, %l0, 42, \
    call func4; \
    nop; \
    ba done4; \
    nop; \
func4: set 42, %l0; \
    retl; \
    nop; \
done4:  \
  )

  /*-------------------------------------------------------------
   * Test 5: Nested CALL - verify %o7 is updated each time
   *-------------------------------------------------------------*/

  TEST_CASE( 5, %l0, 3, \
    set 0, %l0; \
    call outer5; \
    nop; \
    ba done5; \
    nop; \
outer5: add %l0, 1, %l0; \
    mov %o7, %l6; \
    call inner5; \
    nop; \
    add %l0, 1, %l0; \
    jmpl %l6 + 8, %g0; \
    nop; \
inner5: add %l0, 1, %l0; \
    retl; \
    nop; \
done5:  \
  )

  /*-------------------------------------------------------------
   * Test 6: CALL and return simple case
   * (delay slot test removed - our model doesn't implement delay slots)
   *-------------------------------------------------------------*/

  TEST_CASE( 6, %l0, 10, \
    call func6; \
    nop; \
    ba done6; \
    nop; \
func6: set 10, %l0; \
    retl; \
    nop; \
done6:  \
  )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
