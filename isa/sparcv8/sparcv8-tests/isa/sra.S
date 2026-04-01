/* SPARCv8 SRA instruction tests (shift right arithmetic) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic shift tests (positive values)
   *-------------------------------------------------------------*/

  /* For negative numbers (MSB=1), arithmetic shift sign-extends */
  TEST_RR_OP( 2,  sra, 0x00000000, 0x00000000, 0 )
  TEST_RR_OP( 3,  sra, 0xc0000000, 0x80000000, 1 )   /* 0x80000000 is negative, sign extends */
  TEST_RR_OP( 4,  sra, 0xff000000, 0x80000000, 7 )
  TEST_RR_OP( 5,  sra, 0xfffe0000, 0x80000000, 14 )
  TEST_RR_OP( 6,  sra, 0xffffffff, 0x80000001, 31 )  /* All 1s from sign extension */

  TEST_RR_OP( 7,  sra, 0x7fffffff, 0x7fffffff, 0 )
  TEST_RR_OP( 8,  sra, 0x3fffffff, 0x7fffffff, 1 )
  TEST_RR_OP( 9,  sra, 0x00ffffff, 0x7fffffff, 7 )
  TEST_RR_OP( 10, sra, 0x0001ffff, 0x7fffffff, 14 )
  TEST_RR_OP( 11, sra, 0x00000000, 0x7fffffff, 31 )

  /*-------------------------------------------------------------
   * Negative value tests (sign extension)
   *-------------------------------------------------------------*/

  TEST_RR_OP( 12, sra, 0x81818181, 0x81818181, 0 )
  TEST_RR_OP( 13, sra, 0xc0c0c0c0, 0x81818181, 1 )
  TEST_RR_OP( 14, sra, 0xff030303, 0x81818181, 7 )
  TEST_RR_OP( 15, sra, 0xfffe0606, 0x81818181, 14 )
  TEST_RR_OP( 16, sra, 0xffffffff, 0x81818181, 31 )

  /* Shift amount uses only low 5 bits */
  TEST_RR_OP( 17, sra, 0x81818181, 0x81818181, 0xffffffe0 )
  TEST_RR_OP( 18, sra, 0xc0c0c0c0, 0x81818181, 0xffffffe1 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 19, sra, 0xff030303, 0x81818181, 7 )
  TEST_RR_SRC2_EQ_DEST( 20, sra, 0xfffe0606, 0x81818181, 14 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 21, 0, sra, 0xff030303, 0x81818181, 7 )
  TEST_RR_DEST_BYPASS( 22, 1, sra, 0xfffe0606, 0x81818181, 14 )
  TEST_RR_DEST_BYPASS( 23, 2, sra, 0xffffffff, 0x81818181, 31 )

  /*-------------------------------------------------------------
   * Zero register tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 24, sra, 0, 15 )
  TEST_RR_ZEROSRC2( 25, sra, 32, 32 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
