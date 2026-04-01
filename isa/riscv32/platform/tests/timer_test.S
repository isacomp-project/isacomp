# Timer interrupt test for RV32IMA
# Tests that timer interrupts are properly taken when:
# 1. mtime >= mtimecmp
# 2. mie.MTIE (bit 7) is set
# 3. mstatus.MIE (bit 3) is set

.section .text
.globl _start

# Memory map
.equ CLINT_BASE,    0x02000000
.equ MTIMECMP_LO,   CLINT_BASE + 0x4000
.equ MTIMECMP_HI,   CLINT_BASE + 0x4004
.equ MTIME_LO,      CLINT_BASE + 0xBFF8
.equ MTIME_HI,      CLINT_BASE + 0xBFFC

# Test result addresses
.equ TEST_RESULT,   0x80010000
.equ HANDLER_COUNT, 0x80010004

_start:
    # Initialize test result to 0 (pending)
    li      t0, TEST_RESULT
    sw      zero, 0(t0)
    li      t0, HANDLER_COUNT
    sw      zero, 0(t0)

    # Set up trap handler
    la      t0, timer_handler
    csrw    mtvec, t0

    # Set mtimecmp to current mtime + small offset
    # This should cause a timer interrupt soon
    li      t0, MTIME_LO
    lw      t1, 0(t0)           # Read current mtime_lo
    addi    t1, t1, 100         # Add small offset
    li      t0, MTIMECMP_LO
    sw      t1, 0(t0)           # Write mtimecmp_lo
    li      t0, MTIMECMP_HI
    sw      zero, 0(t0)         # Write mtimecmp_hi = 0

    # Enable timer interrupt in mie (bit 7 = MTIE)
    li      t0, 0x80            # MTIE bit
    csrs    mie, t0

    # Enable global interrupts in mstatus (bit 3 = MIE)
    li      t0, 0x8             # MIE bit
    csrs    mstatus, t0

    # Wait for interrupt
    li      t2, 10000           # Timeout counter
wait_loop:
    addi    t2, t2, -1
    beqz    t2, timeout

    # Check if handler was called
    li      t0, HANDLER_COUNT
    lw      t1, 0(t0)
    bnez    t1, test_pass

    j       wait_loop

timeout:
    # Test failed - no interrupt received
    li      t0, TEST_RESULT
    li      t1, 2               # 2 = fail
    sw      t1, 0(t0)
    j       done

test_pass:
    # Test passed - interrupt was received
    li      t0, TEST_RESULT
    li      t1, 1               # 1 = pass
    sw      t1, 0(t0)
    j       done

done:
    # Infinite loop (or could use WFI)
    j       done

# Timer interrupt handler
.align 4
timer_handler:
    # Increment handler count
    li      t0, HANDLER_COUNT
    lw      t1, 0(t0)
    addi    t1, t1, 1
    sw      t1, 0(t0)

    # Clear timer interrupt by setting mtimecmp to max
    li      t0, MTIMECMP_LO
    li      t1, -1              # 0xFFFFFFFF
    sw      t1, 0(t0)
    li      t0, MTIMECMP_HI
    sw      t1, 0(t0)

    # Return from interrupt
    mret
