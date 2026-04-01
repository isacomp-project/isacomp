// TDMI MOV instruction test
// Test MOV Rd, Rm and MOV Rd, #imm

.global _start
.text

_start:
    // Test MOV immediate
    mov r0, #42
    cmp r0, #42
    bne fail

    // Test MOV register
    mov r1, r0
    cmp r1, #42
    bne fail

pass:
    b pass

fail:
    b fail
