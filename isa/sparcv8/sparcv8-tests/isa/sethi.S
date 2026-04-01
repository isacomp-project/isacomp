/* SPARCv8 SETHI instruction tests */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * SETHI sets the high 22 bits of rd, clears low 10 bits
   * Format: sethi imm22, rd
   * Result: rd = imm22 << 10
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: SETHI with small immediate
   *-------------------------------------------------------------*/

  TEST_CASE( 2, %l0, 0x400, \
    sethi 1, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 3: SETHI with zero
   *-------------------------------------------------------------*/

  TEST_CASE( 3, %l0, 0, \
    sethi 0, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 4: SETHI setting high bits
   *-------------------------------------------------------------*/

  TEST_CASE( 4, %l0, 0xffc00, \
    sethi 0x3ff, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 5: SETHI with max 22-bit immediate (0x3fffff)
   *-------------------------------------------------------------*/

  TEST_CASE( 5, %l0, 0xfffffc00, \
    sethi 0x3fffff, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 6: SETHI used with OR for full 32-bit constant
   * This is how the "set" pseudo-instruction works
   *-------------------------------------------------------------*/

  TEST_CASE( 6, %l0, 0x12345678, \
    sethi %hi(0x12345678), %l0; \
    or %l0, %lo(0x12345678), %l0; \
  )

  /*-------------------------------------------------------------
   * Test 7: SETHI followed by OR for another constant
   *-------------------------------------------------------------*/

  TEST_CASE( 7, %l0, 0xdeadbeef, \
    sethi %hi(0xdeadbeef), %l0; \
    or %l0, %lo(0xdeadbeef), %l0; \
  )

  /*-------------------------------------------------------------
   * Test 8: SETHI to %g0 has no effect (r0 always 0)
   *-------------------------------------------------------------*/

  TEST_CASE( 8, %l0, 0, \
    sethi 0x3fffff, %g0; \
    mov %g0, %l0; \
  )

  /*-------------------------------------------------------------
   * Test 9: SETHI clears low 10 bits
   *-------------------------------------------------------------*/

  TEST_CASE( 9, %l0, 0x12345400, \
    set 0xffffffff, %l0; \
    sethi %hi(0x12345678), %l0; \
    /* low 10 bits should be 0, not from previous value */ \
    /* %hi(0x12345678) = 0x48d15, sethi gives 0x48d15 << 10 = 0x12345400 */ \
  )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
