/* MIPS32 UART Output Test */
/* Tests simple console output by writing to a memory-mapped "UART" address */
/* The testbench monitors this address and prints characters */

#include "../test_macros.h"

/* UART address - in kseg1 (uncached, unmapped) */
/* Physical address 0x000FF000 maps to 0xA00FF000 in kseg1 */
/* Using address within 1MB physical memory range */
#define UART_TX_ADDR    0xA00FF000

    .set noreorder
    .set noat

RVTEST_CODE_BEGIN

    li TESTNUM, 1

    /* Print "Hello\n" */
    li $t0, UART_TX_ADDR

    li $t1, 'H'
    sw $t1, 0($t0)

    li $t1, 'e'
    sw $t1, 0($t0)

    li $t1, 'l'
    sw $t1, 0($t0)

    li $t1, 'l'
    sw $t1, 0($t0)

    li $t1, 'o'
    sw $t1, 0($t0)

    li $t1, '\n'
    sw $t1, 0($t0)

    /* Test passed if we get here */
    TEST_PASSFAIL

RVTEST_CODE_END

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
  TEST_DATA
RVTEST_DATA_END
