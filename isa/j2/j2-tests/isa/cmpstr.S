/* j2 (SuperH-2) CMP/STR instruction tests */
/* CMP/STR sets T=1 if any byte pair in Rm and Rn are equal */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * CMP/STR - Compare strings (byte-by-byte equality)
   *-------------------------------------------------------------*/

  /* Test 2: All bytes different -> T=0 */
test_2:
    mov.l test_2_val1, r1
    mov.l test_2_val2, r2
    cmp/str r2, r1
    bt fail           /* T should be 0 */
    bra test_3
    nop
    .align 2
test_2_val1:
    .long 0x01020304
test_2_val2:
    .long 0x11121314

  /* Test 3: Byte 0 matches -> T=1 */
test_3:
    mov.l test_3_val1, r1
    mov.l test_3_val2, r2
    cmp/str r2, r1
    bf fail           /* T should be 1 */
    bra test_4
    nop
    .align 2
test_3_val1:
    .long 0x01020304
test_3_val2:
    .long 0x11121304   /* byte 0 matches: 0x04 */

  /* Test 4: Byte 1 matches -> T=1 */
test_4:
    mov.l test_4_val1, r1
    mov.l test_4_val2, r2
    cmp/str r2, r1
    bf fail           /* T should be 1 */
    bra test_5
    nop
    .align 2
test_4_val1:
    .long 0x01020304
test_4_val2:
    .long 0x11120314   /* byte 1 matches: 0x03 */

  /* Test 5: Byte 2 matches -> T=1 */
test_5:
    mov.l test_5_val1, r1
    mov.l test_5_val2, r2
    cmp/str r2, r1
    bf fail           /* T should be 1 */
    bra test_6
    nop
    .align 2
test_5_val1:
    .long 0x01020304
test_5_val2:
    .long 0x11021314   /* byte 2 matches: 0x02 */

  /* Test 6: Byte 3 matches -> T=1 */
test_6:
    mov.l test_6_val1, r1
    mov.l test_6_val2, r2
    cmp/str r2, r1
    bf fail           /* T should be 1 */
    bra test_7
    nop
    .align 2
test_6_val1:
    .long 0x01020304
test_6_val2:
    .long 0x01121314   /* byte 3 matches: 0x01 */

  /* Test 7: All bytes same -> T=1 */
test_7:
    mov.l test_7_val, r1
    mov.l test_7_val, r2
    cmp/str r2, r1
    bf fail           /* T should be 1 */
    bra test_8
    nop
    .align 2
test_7_val:
    .long 0xaabbccdd

  /* Test 8: Zero bytes match -> T=1 */
test_8:
    mov.l test_8_val1, r1
    mov.l test_8_val2, r2
    cmp/str r2, r1
    bf fail           /* T should be 1 (0x00 bytes match) */
    bra test_end
    nop
    .align 2
test_8_val1:
    .long 0x00112233
test_8_val2:
    .long 0x00aabbcc

test_end:
  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
