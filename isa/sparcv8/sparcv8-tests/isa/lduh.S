/* SPARCv8 LDUH instruction tests (load unsigned halfword) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic load unsigned halfword tests
   * SPARCv8 is big-endian: halfword 0 is upper half
   *-------------------------------------------------------------*/

  /* Load halfwords from word 0x00112233 */
  TEST_LD_OP( 2, lduh, 0x00000011, 0, tdat )   /* halfword 0 = 0x0011 */
  TEST_LD_OP( 3, lduh, 0x00002233, 2, tdat )   /* halfword 1 = 0x2233 */

  /* Load halfwords from word 0xaabbccdd */
  TEST_LD_OP( 4, lduh, 0x0000aabb, 0, tdat4 )
  TEST_LD_OP( 5, lduh, 0x0000ccdd, 2, tdat4 )

  /* Load high halfwords (should zero extend, not sign extend) */
  TEST_LD_OP( 6, lduh, 0x0000ff00, 0, tdat8 )
  TEST_LD_OP( 7, lduh, 0x0000ff00, 2, tdat8 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  .align 4
tdat:
tdat0:  .word 0x00112233
tdat4:  .word 0xaabbccdd
tdat8:  .word 0xff00ff00
SPARCV8_DATA_END
