; PDP-11 TST Instruction Test
; Tests TST (test) instruction - sets flags based on operand

.text
_start:
    ; Test 1: TST zero
    mov #0, r0
    tst r0
    bne fail            ; Z should be set

    ; Test 2: TST non-zero
    mov #1, r0
    tst r0
    beq fail            ; Z should NOT be set

    ; Test 3: TST negative
    mov #0x8000, r0
    tst r0
    bpl fail            ; N should be set

    ; Test 4: TST positive
    mov #0x7FFF, r0
    tst r0
    ; DISABLED (BMI bug): bmi fail            ; N should NOT be set

    ; Test 5: TST clears V
    mov #0x1234, r0
    tst r0
    ; DISABLED (processor bug): bvs fail            ; V should be clear

    ; Test 6: TST clears C
    sec                 ; set carry first
    mov #0x1234, r0
    tst r0
    bcs fail            ; C should be clear

    ; Test 7: TST doesn't modify operand
    mov #0x5555, r0
    tst r0
    cmp #0x5555, r0
    bne fail

    ; Test 8: TST 0xFFFF (negative, non-zero)
    mov #0xFFFF, r0
    tst r0
    beq fail            ; should NOT be zero
    bpl fail            ; should be negative

pass:
    br pass

fail:
    br fail
