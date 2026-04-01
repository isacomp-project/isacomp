/* SPARCv8 SLL instruction tests (shift left logical) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic shift tests
   *-------------------------------------------------------------*/

  TEST_RR_OP( 2,  sll, 0x00000001, 0x00000001, 0 )
  TEST_RR_OP( 3,  sll, 0x00000002, 0x00000001, 1 )
  TEST_RR_OP( 4,  sll, 0x00000080, 0x00000001, 7 )
  TEST_RR_OP( 5,  sll, 0x00004000, 0x00000001, 14 )
  TEST_RR_OP( 6,  sll, 0x80000000, 0x00000001, 31 )

  TEST_RR_OP( 7,  sll, 0xffffffff, 0xffffffff, 0 )
  TEST_RR_OP( 8,  sll, 0xfffffffe, 0xffffffff, 1 )
  TEST_RR_OP( 9,  sll, 0xffffff80, 0xffffffff, 7 )
  TEST_RR_OP( 10, sll, 0xffffc000, 0xffffffff, 14 )
  TEST_RR_OP( 11, sll, 0x80000000, 0xffffffff, 31 )

  TEST_RR_OP( 12, sll, 0x21212121, 0x21212121, 0 )
  TEST_RR_OP( 13, sll, 0x42424242, 0x21212121, 1 )
  TEST_RR_OP( 14, sll, 0x90909080, 0x21212121, 7 )
  TEST_RR_OP( 15, sll, 0x48484000, 0x21212121, 14 )
  TEST_RR_OP( 16, sll, 0x80000000, 0x21212121, 31 )

  /* Shift amount uses only low 5 bits */
  TEST_RR_OP( 17, sll, 0x21212121, 0x21212121, 0xffffffe0 )
  TEST_RR_OP( 18, sll, 0x42424242, 0x21212121, 0xffffffe1 )

  /*-------------------------------------------------------------
   * Source/Destination tests
   *-------------------------------------------------------------*/

  TEST_RR_SRC1_EQ_DEST( 19, sll, 0x00000080, 0x00000001, 7 )
  TEST_RR_SRC2_EQ_DEST( 20, sll, 0x00004000, 0x00000001, 14 )

  /*-------------------------------------------------------------
   * Bypassing tests
   *-------------------------------------------------------------*/

  TEST_RR_DEST_BYPASS( 21, 0, sll, 0x00000080, 0x00000001, 7 )
  TEST_RR_DEST_BYPASS( 22, 1, sll, 0x00004000, 0x00000001, 14 )
  TEST_RR_DEST_BYPASS( 23, 2, sll, 0x80000000, 0x00000001, 31 )

  /*-------------------------------------------------------------
   * Zero register tests
   *-------------------------------------------------------------*/

  TEST_RR_ZEROSRC1( 24, sll, 0, 15 )
  TEST_RR_ZEROSRC2( 25, sll, 32, 32 )

  /*-------------------------------------------------------------
   * Immediate tests
   *-------------------------------------------------------------*/

  TEST_RI_OP( 26, sll, 0x00000080, 0x00000001, 7 )
  TEST_RI_OP( 27, sll, 0x00004000, 0x00000001, 14 )

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
