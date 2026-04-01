// TDMI ORR instruction test
// Test ORR Rd, Rn, Rm

.global _start
.text

_start:
    // Initialize test values
    mov r0, #0xF0
    mov r1, #0x0F

    // Test ORR
    orr r2, r0, r1    // r2 = 0xF0 | 0x0F = 0xFF

    // Verify result
    cmp r2, #0xFF
    bne fail

pass:
    b pass

fail:
    b fail
