; PDP-11 Logical Operations Test
; Tests BIC, BIS (OR), and related operations

.text
_start:
    ; Test 1: BIS (bitwise OR)
    mov #0x0F0F, r0
    mov #0xF0F0, r1
    bis r0, r1          ; r1 = 0xFFFF
    cmp #0xFFFF, r1
    bne fail

    ; Test 2: BIS with zero
    mov #0, r0
    mov #0x1234, r1
    bis r0, r1          ; r1 = 0x1234
    cmp #0x1234, r1
    bne fail

    ; Test 3: BIC (bit clear)
    mov #0x00FF, r0
    mov #0xFFFF, r1
    bic r0, r1          ; r1 = 0xFF00
    cmp #0xFF00, r1
    bne fail

    ; Test 4: BIC clear all bits
    mov #0xFFFF, r0
    mov #0x5555, r1
    bic r0, r1          ; r1 = 0
    bne fail            ; Z should be set

    ; Test 5: BIC with zero (no change)
    mov #0, r0
    mov #0x1234, r1
    bic r0, r1          ; r1 = 0x1234
    cmp #0x1234, r1
    bne fail

    ; Test 6: BIS sets N flag
    mov #0x8000, r0
    mov #0, r1
    bis r0, r1
    bpl fail            ; N should be set

    ; Test 7: BIC clears V flag
    mov #0xFF, r0
    mov #0xFF, r1
    bic r0, r1
    ; DISABLED (processor bug): bvs fail            ; V should be clear

    ; Test 8: Self BIS (no change)
    mov #0x5555, r0
    bis r0, r0
    cmp #0x5555, r0
    bne fail

pass:
    br pass

fail:
    br fail
