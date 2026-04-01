// TDMI SUB instruction test
// Test SUB Rd, Rn, Rm

.global _start
.text

_start:
    // Initialize test values
    mov r0, #20
    mov r1, #7

    // Test SUB
    sub r2, r0, r1    // r2 = 20 - 7 = 13

    // Verify result
    cmp r2, #13
    bne fail

pass:
    b pass

fail:
    b fail
