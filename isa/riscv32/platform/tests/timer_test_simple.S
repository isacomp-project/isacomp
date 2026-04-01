# Simple timer interrupt test for RV32IMA
# Tests timer interrupt mechanism by:
# 1. Setting mtvec to handler
# 2. Setting mtimecmp via CLINT to trigger quickly
# 3. Enabling interrupts (mie.MTIE and mstatus.MIE)
# 4. Waiting for interrupt to fire
#
# Expected result: handler_called will be non-zero

.section .text
.globl _start

# Memory map
.equ CLINT_BASE,    0x02000000
.equ MTIMECMP_LO,   CLINT_BASE + 0x4000
.equ MTIMECMP_HI,   CLINT_BASE + 0x4004
.equ MTIME_LO,      CLINT_BASE + 0xBFF8
.equ MTIME_HI,      CLINT_BASE + 0xBFFC

# Result addresses
.equ RESULT_ADDR,   0x80010000

_start:
    # Initialize result to 0
    li      t0, RESULT_ADDR
    sw      zero, 0(t0)

    # Set up trap handler
    la      t0, timer_handler
    csrw    mtvec, t0

    # Set mtimecmp to low value (mtime should reach it quickly)
    # First clear high word, then set low word
    li      t0, MTIMECMP_HI
    sw      zero, 0(t0)
    li      t0, MTIMECMP_LO
    li      t1, 50          # Very low - should trigger almost immediately
    sw      t1, 0(t0)

    # Enable timer interrupt in mie (bit 7 = MTIE)
    li      t0, 0x80
    csrs    mie, t0

    # Enable global interrupts in mstatus (bit 3 = MIE)
    li      t0, 0x8
    csrs    mstatus, t0

    # Wait loop - interrupt should fire soon
    li      t2, 1000
wait_loop:
    # Check if handler was called
    li      t0, RESULT_ADDR
    lw      t1, 0(t0)
    bnez    t1, success

    addi    t2, t2, -1
    bnez    t2, wait_loop

    # Timeout - test failed
    li      t0, RESULT_ADDR
    li      t1, 0xDEAD      # Failure marker
    sw      t1, 0(t0)
    j       done

success:
    # Success - handler was called
    j       done

done:
    # Infinite loop or WFI
    wfi
    j       done

# Timer interrupt handler
.align 4
timer_handler:
    # Mark that handler was called
    li      t0, RESULT_ADDR
    li      t1, 0x1234      # Success marker
    sw      t1, 0(t0)

    # Clear timer interrupt by setting mtimecmp to max
    li      t0, MTIMECMP_LO
    li      t1, -1
    sw      t1, 0(t0)
    li      t0, MTIMECMP_HI
    sw      t1, 0(t0)

    # Return from interrupt
    mret
