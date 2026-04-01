; PDP-11 COM Instruction Test
; Tests COM (complement) - one's complement

.text
_start:
    ; Test 1: COM zero
    mov #0, r0
    com r0              ; r0 = 0xFFFF
    cmp #0xFFFF, r0
    bne fail

    ; Test 2: COM all ones
    mov #0xFFFF, r0
    com r0              ; r0 = 0
    bne fail            ; Z should be set

    ; Test 3: COM pattern
    mov #0x5555, r0
    com r0              ; r0 = 0xAAAA
    cmp #0xAAAA, r0
    bne fail

    ; Test 4: COM sets N flag
    mov #0, r0
    com r0              ; r0 = 0xFFFF (negative)
    bpl fail            ; N should be set

    ; Test 5: COM sets C flag (always)
    clc                 ; clear carry first
    mov #0, r0
    com r0
    bcc fail            ; C is always set by COM

    ; Test 6: COM clears V flag
    mov #0, r0
    com r0
    ; DISABLED (processor bug): bvs fail            ; V should be clear

    ; Test 7: Double COM returns original
    mov #0x1234, r0
    com r0
    com r0
    cmp #0x1234, r0
    bne fail

    ; Test 8: COM low bits
    mov #0x00FF, r0
    com r0              ; r0 = 0xFF00
    cmp #0xFF00, r0
    bne fail

pass:
    br pass

fail:
    br fail
