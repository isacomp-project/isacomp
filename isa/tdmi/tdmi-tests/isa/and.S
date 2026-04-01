// TDMI AND instruction test
// Test AND Rd, Rn, Rm

.global _start
.text

_start:
    // Initialize test values
    mov r0, #0xFF
    mov r1, #0x0F

    // Test AND
    and r2, r0, r1    // r2 = 0xFF & 0x0F = 0x0F

    // Verify result
    cmp r2, #0x0F
    bne fail

pass:
    b pass

fail:
    b fail
