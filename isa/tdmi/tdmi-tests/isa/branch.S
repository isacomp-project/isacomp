// TDMI Branch instruction test
// Test B and BL

.global _start
.text

_start:
    mov r0, #0
    b test1
    mov r0, #1    // Should be skipped

test1:
    cmp r0, #0
    bne fail

    // Test BL (branch with link)
    bl subroutine

    // Check return value
    cmp r0, #42
    bne fail

pass:
    b pass

fail:
    b fail

subroutine:
    mov r0, #42
    mov pc, lr    // Return
