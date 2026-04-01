/* SPARCv8 LDUB instruction tests (load unsigned byte) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic load unsigned byte tests
   * SPARCv8 is big-endian: byte 0 is MSB
   *-------------------------------------------------------------*/

  /* Load bytes from word 0x00112233 */
  TEST_LD_OP( 2, ldub, 0x00000000, 0, tdat )   /* byte 0 = 0x00 */
  TEST_LD_OP( 3, ldub, 0x00000011, 1, tdat )   /* byte 1 = 0x11 */
  TEST_LD_OP( 4, ldub, 0x00000022, 2, tdat )   /* byte 2 = 0x22 */
  TEST_LD_OP( 5, ldub, 0x00000033, 3, tdat )   /* byte 3 = 0x33 */

  /* Load bytes from word 0xaabbccdd */
  TEST_LD_OP( 6, ldub, 0x000000aa, 0, tdat4 )
  TEST_LD_OP( 7, ldub, 0x000000bb, 1, tdat4 )
  TEST_LD_OP( 8, ldub, 0x000000cc, 2, tdat4 )
  TEST_LD_OP( 9, ldub, 0x000000dd, 3, tdat4 )

  /* Load high bytes (should zero extend, not sign extend) */
  TEST_LD_OP( 10, ldub, 0x000000ff, 0, tdat8 )

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
