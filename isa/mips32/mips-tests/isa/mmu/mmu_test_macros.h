/* MIPS32 MMU Test Macros */

#ifndef __MIPS32_MMU_TEST_MACROS_H
#define __MIPS32_MMU_TEST_MACROS_H

#include "../test_macros.h"

/*-----------------------------------------------------------------------
 * CP0 Register Numbers
 *-----------------------------------------------------------------------*/
#define CP0_INDEX     $0
#define CP0_RANDOM    $1
#define CP0_ENTRYLO0  $2
#define CP0_ENTRYLO1  $3
#define CP0_CONTEXT   $4
#define CP0_PAGEMASK  $5
#define CP0_WIRED     $6
#define CP0_BADVADDR  $8
#define CP0_COUNT     $9
#define CP0_ENTRYHI   $10
#define CP0_COMPARE   $11
#define CP0_STATUS    $12
#define CP0_CAUSE     $13
#define CP0_EPC       $14
#define CP0_PRID      $15
#define CP0_CONFIG    $16
#define CP0_ERROREPC  $30

/*-----------------------------------------------------------------------
 * CP0 Status Register bits
 *-----------------------------------------------------------------------*/
#define STATUS_IE     0x00000001  /* Interrupt Enable */
#define STATUS_EXL    0x00000002  /* Exception Level */
#define STATUS_ERL    0x00000004  /* Error Level */
#define STATUS_KSU    0x00000018  /* Kernel/Supervisor/User mode */
#define STATUS_BEV    0x00400000  /* Bootstrap Exception Vector */

/*-----------------------------------------------------------------------
 * CP0 Cause Register exception codes
 *-----------------------------------------------------------------------*/
#define EXC_INT       0   /* Interrupt */
#define EXC_MOD       1   /* TLB Modification */
#define EXC_TLBL      2   /* TLB Miss (Load/Fetch) */
#define EXC_TLBS      3   /* TLB Miss (Store) */
#define EXC_ADEL      4   /* Address Error (Load/Fetch) */
#define EXC_ADES      5   /* Address Error (Store) */
#define EXC_SYS       8   /* Syscall */
#define EXC_BP        9   /* Breakpoint */

/*-----------------------------------------------------------------------
 * TLB Entry format
 *-----------------------------------------------------------------------*/
/* EntryHi: VPN2[31:13], 0[12:8], ASID[7:0] */
/* EntryLo0/1: PFN[25:6], C[5:3], D[2], V[1], G[0] */

#define ENTRYLO_G     0x00000001  /* Global bit */
#define ENTRYLO_V     0x00000002  /* Valid bit */
#define ENTRYLO_D     0x00000004  /* Dirty bit */
#define ENTRYLO_C     0x00000038  /* Coherency bits */

/*-----------------------------------------------------------------------
 * Test macros for MFC0/MTC0
 *-----------------------------------------------------------------------*/

#define TEST_MFC0(testnum, result, cp0reg, sel) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    mfc0 $t0, cp0reg, sel; \
    li $t9, result; \
    bne $t0, $t9, fail; \
    nop;

#define TEST_MTC0_MFC0(testnum, val, cp0reg, sel) \
test_ ## testnum: \
    li TESTNUM, testnum; \
    li $t1, val; \
    mtc0 $t1, cp0reg, sel; \
    nop; \
    nop; \
    mfc0 $t0, cp0reg, sel; \
    bne $t0, $t1, fail; \
    nop;

/*-----------------------------------------------------------------------
 * TLB test macros
 *-----------------------------------------------------------------------*/

/* Write a TLB entry at index 'idx' with specified VPN2, ASID, PFN0, PFN1 */
#define TLB_WRITE_ENTRY(idx, vpn2, asid, pfn0, pfn1) \
    li $t0, idx; \
    mtc0 $t0, CP0_INDEX, 0; \
    li $t0, ((vpn2 << 13) | asid); \
    mtc0 $t0, CP0_ENTRYHI, 0; \
    li $t0, ((pfn0 << 6) | ENTRYLO_V | ENTRYLO_D | ENTRYLO_G); \
    mtc0 $t0, CP0_ENTRYLO0, 0; \
    li $t0, ((pfn1 << 6) | ENTRYLO_V | ENTRYLO_D | ENTRYLO_G); \
    mtc0 $t0, CP0_ENTRYLO1, 0; \
    nop; \
    tlbwi; \
    nop;

/* Read TLB entry at current Index */
#define TLB_READ_ENTRY() \
    tlbr; \
    nop; \
    nop;

/* Probe TLB for current EntryHi VPN2 */
#define TLB_PROBE() \
    tlbp; \
    nop; \
    nop;

/*-----------------------------------------------------------------------
 * Exception handler setup for MMU tests
 *-----------------------------------------------------------------------*/

/* MMU test code begins - sets up exception vectors */
#define MMU_TEST_CODE_BEGIN \
    .set noreorder; \
    .set noat; \
    .text; \
    .globl _start; \
    _start: \
    li $sp, 0x1ffc; \
    li $2, 0; \
    li $3, 0; \
    /* Set BEV=0 to use RAM exception vectors */ \
    mfc0 $t0, CP0_STATUS, 0; \
    li $t1, ~STATUS_BEV; \
    and $t0, $t0, $t1; \
    mtc0 $t0, CP0_STATUS, 0; \
    nop; \
    /* Jump over exception handlers to test code */ \
    j test_start; \
    nop; \
    /* TLB Refill handler at 0x80 offset from base */ \
    .org 0x80; \
tlb_refill_handler: \
    j tlb_refill_handler; \
    nop; \
    /* General exception handler at 0x180 offset */ \
    .org 0x180; \
general_exception_handler: \
    j general_exception_handler; \
    nop; \
    /* Test code starts here */ \
    .org 0x200; \
test_start:

#endif /* __MIPS32_MMU_TEST_MACROS_H */
