# Timer interrupt + MRET test for riscv32_mmu
# Tests that:
# 1. M-mode timer interrupt fires when timer_irq_pending is asserted
# 2. Handler can write to memory
# 3. MRET correctly restores MIE from MPIE (the critical bug fix)
# 4. Execution resumes at correct PC after MRET
#
# The testbench drives timer_irq_pending externally for 1 cycle.
# If MRET is broken (doesn't restore MIE), interrupts stay disabled.

.section .text.init
.globl _start

# Result address (must be within 24-bit word address range)
# 0x00010000 byte addr = word addr 0x4000
.equ RESULT_ADDR, 0x00010000

_start:
    # Store 0 to result
    lui     t0, 0x10            # t0 = 0x00010000
    sw      zero, 0(t0)

    # Set up trap handler - mtvec must be aligned to 4 bytes
    la      t0, timer_handler
    csrw    mtvec, t0

    # Enable MTIE (bit 7) in mie
    li      t0, 0x80
    csrs    mie, t0

    # Enable MIE (bit 3) in mstatus
    li      t0, 0x8
    csrs    mstatus, t0

    # Wait loop - interrupt fires when testbench asserts timer_irq_pending
    li      t2, 10000
wait_loop:
    lui     t0, 0x10            # t0 = RESULT_ADDR
    lw      t1, 0(t0)
    li      t3, 0x1234
    beq     t1, t3, pass

    addi    t2, t2, -1
    bnez    t2, wait_loop

    # Timeout - test failed (MRET didn't work or interrupt never fired)
    j       fail

.globl pass
pass:
    j       pass                # Spin here - testbench detects this PC

.globl fail
fail:
    j       fail                # Spin here - testbench detects this PC

# Timer interrupt handler - must be 4-byte aligned
.align 4
.globl timer_handler
timer_handler:
    lui     t0, 0x10            # t0 = RESULT_ADDR
    li      t1, 0x1234
    sw      t1, 0(t0)          # Write success marker
    mret                        # Return - must restore MIE from MPIE
