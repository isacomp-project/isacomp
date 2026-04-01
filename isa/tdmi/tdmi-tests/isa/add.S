// TDMI ADD instruction test
// Test ADD Rd, Rn, Rm

.global _start
.text

_start:
    // Initialize test values
    mov r0, #5
    mov r1, #7

    // Test ADD
    add r2, r0, r1    // r2 = 5 + 7 = 12

    // Verify result
    cmp r2, #12
    bne fail

pass:
    b pass

fail:
    b fail
