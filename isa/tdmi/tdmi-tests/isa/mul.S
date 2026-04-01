// TDMI MUL instruction test
// Test MUL Rd, Rm, Rs

.global _start
.text

_start:
    // Initialize test values
    mov r0, #5
    mov r1, #7

    // Test MUL
    mul r2, r0, r1    // r2 = 5 * 7 = 35

    // Verify result
    cmp r2, #35
    bne fail

pass:
    b pass

fail:
    b fail
