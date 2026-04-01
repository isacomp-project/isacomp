; PDP-11 MOVB Instruction Test
; Tests MOVB (move byte) instruction with sign extension

.text
_start:
    ; Test 1: MOVB small positive value
    mov #0x12, r0
    movb r0, r1         ; r1 = 0x0012 (sign extended)
    cmp #0x0012, r1
    bne fail

    ; Test 2: MOVB value > 127 (negative byte, sign extends)
    mov #0x80, r0       ; 128 = -128 as signed byte
    movb r0, r1         ; r1 = 0xFF80 (sign extended)
    cmp #0xFF80, r1
    bne fail

    ; Test 3: MOVB 0xFF (-1)
    mov #0xFF, r0
    movb r0, r1         ; r1 = 0xFFFF
    cmp #0xFFFF, r1
    bne fail

    ; Test 4: MOVB 0x7F (max positive byte)
    mov #0x7F, r0
    movb r0, r1         ; r1 = 0x007F
    cmp #0x007F, r1
    bne fail

    ; Test 5: MOVB zero
    mov #0, r0
    movb r0, r1
    bne fail            ; Z should be set

    ; Test 6: MOVB sets N flag
    mov #0x80, r0
    movb r0, r1
    bpl fail            ; N should be set (sign extended negative)

    ; Test 7: MOVB from word (uses low byte)
    mov #0x1234, r0
    movb r0, r1         ; only low byte 0x34 is used
    cmp #0x0034, r1     ; 0x34 = 52, positive
    bne fail

    ; Test 8: MOVB high byte set (uses low byte)
    mov #0xFF00, r0
    movb r0, r1         ; only low byte 0x00 is used
    bne fail            ; Z should be set

pass:
    br pass

fail:
    br fail
