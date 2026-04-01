// TDMI LDR/STR instruction test
// Test LDR and STR with immediate offset

.global _start
.text

_start:
    // Set up data address
    ldr r0, =data_area

    // Test STR
    mov r1, #0x12
    str r1, [r0, #0]

    // Test LDR
    ldr r2, [r0, #0]

    // Verify
    cmp r2, #0x12
    bne fail

pass:
    b pass

fail:
    b fail

.data
data_area:
    .word 0
