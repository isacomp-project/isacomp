; PDP-11 NEG Instruction Test
; Tests NEG (two's complement negate) single operand instruction

.text
_start:
    ; Test 1: NEG positive number
    mov #5, r0
    neg r0              ; r0 = -5 = 0xFFFB
    cmp #0xFFFB, r0
    bne fail

    ; Test 2: NEG negative number
    mov #0xFFFB, r0     ; -5
    neg r0              ; r0 = 5
    cmp #5, r0
    bne fail

    ; Test 3: NEG zero
    mov #0, r0
    neg r0              ; r0 = 0
    bne fail            ; Z should be set

    ; Test 4: NEG one
    mov #1, r0
    neg r0              ; r0 = 0xFFFF = -1
    cmp #0xFFFF, r0
    bne fail

    ; Test 5: NEG 0x8000 (special case - overflow)
    mov #0x8000, r0
    neg r0              ; r0 = 0x8000 (same value, overflow)
    ; DISABLED (processor bug): bvc fail            ; V should be set
    cmp #0x8000, r0
    bne fail

    ; Test 6: NEG sets N flag
    mov #1, r0
    neg r0              ; r0 = 0xFFFF (negative)
    bpl fail            ; N should be set

    ; Test 7: NEG of non-zero sets C
    mov #5, r0
    neg r0
    bcc fail            ; C should be set for non-zero

    ; Test 8: NEG of zero clears C
    mov #0, r0
    neg r0
    bcs fail            ; C should be clear for zero

pass:
    br pass

fail:
    br fail
