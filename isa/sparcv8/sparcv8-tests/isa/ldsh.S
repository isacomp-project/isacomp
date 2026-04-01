/* SPARCv8 LDSH instruction tests (load signed halfword) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic load signed halfword tests
   * SPARCv8 is big-endian
   *-------------------------------------------------------------*/

  /* Positive halfwords (no sign extension) */
  TEST_LD_OP( 2, ldsh, 0x00000011, 0, tdat )   /* 0x0011 -> 0x00000011 */
  TEST_LD_OP( 3, ldsh, 0x00002233, 2, tdat )   /* 0x2233 -> 0x00002233 */

  /* Negative halfwords (sign extension) */
  TEST_LD_OP( 4, ldsh, 0xffffaabb, 0, tdat4 )  /* 0xaabb -> 0xffffaabb */
  TEST_LD_OP( 5, ldsh, 0xffffccdd, 2, tdat4 )  /* 0xccdd -> 0xffffccdd */

  /* 0xff00 -> sign extended */
  TEST_LD_OP( 6, ldsh, 0xffffff00, 0, tdat8 )
  /* 0x7fff -> no sign extension */
  TEST_LD_OP( 7, ldsh, 0x00007fff, 2, tdat8 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  .align 4
tdat:
tdat0:  .word 0x00112233
tdat4:  .word 0xaabbccdd
tdat8:  .word 0xff007fff
SPARCV8_DATA_END
