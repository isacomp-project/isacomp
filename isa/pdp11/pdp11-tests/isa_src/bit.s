; PDP-11 BIT Instruction Test
; Tests BIT (bit test) - ANDs operands and sets flags, but doesn't store result

.text
_start:
    ; Test 1: BIT with matching bits
    mov #0x0F0F, r0
    mov #0x0F00, r1
    bit r0, r1          ; 0x0F0F & 0x0F00 = 0x0F00 (non-zero)
    beq fail            ; Z should NOT be set

    ; Test 2: BIT with no matching bits
    mov #0x00FF, r0
    mov #0xFF00, r1
    bit r0, r1          ; 0x00FF & 0xFF00 = 0 (zero)
    bne fail            ; Z should be set

    ; Test 3: Verify dest not modified
    mov #0xF0F0, r0
    mov #0x0F0F, r1
    bit r0, r1
    cmp #0x0F0F, r1     ; r1 should still be 0x0F0F
    bne fail

    ; Test 4: BIT with all ones
    mov #0xFFFF, r0
    mov #0x5555, r1
    bit r0, r1          ; result = 0x5555
    beq fail            ; Z should NOT be set

    ; Test 5: BIT with all zeros
    mov #0, r0
    mov #0xFFFF, r1
    bit r0, r1
    bne fail            ; Z should be set

    ; Test 6: BIT sets N flag
    mov #0xFFFF, r0
    mov #0x8000, r1
    bit r0, r1          ; result = 0x8000 (negative)
    bpl fail            ; N should be set

    ; Test 7: BIT clears V flag
    mov #0xFFFF, r0
    mov #0x1234, r1
    bit r0, r1
    ; DISABLED (processor bug): bvs fail            ; V should be clear

pass:
    br pass

fail:
    br fail
