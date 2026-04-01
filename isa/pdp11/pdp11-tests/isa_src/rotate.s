; PDP-11 Rotate Instructions Test
; Tests ROR (rotate right) and ROL (rotate left)

.text
_start:
    ; Test 1: ROR (rotate right through carry)
    clc                 ; clear carry
    mov #2, r0
    ror r0              ; r0 = 1, C = 0
    cmp #1, r0
    bne fail

    ; Test 2: ROR with C=1
    sec                 ; set carry
    mov #0, r0
    ror r0              ; r0 = 0x8000, C = 0
    cmp #0x8000, r0
    bne fail

    ; Test 3: ROR sets C from LSB
    clc
    mov #1, r0
    ror r0              ; LSB=1 goes to C
    bcc fail            ; C should be set

    ; Test 4: ROL (rotate left through carry)
    clc                 ; clear carry
    mov #1, r0
    rol r0              ; r0 = 2, C = 0
    cmp #2, r0
    bne fail

    ; Test 5: ROL with C=1
    sec                 ; set carry
    mov #0, r0
    rol r0              ; r0 = 1, C = 0
    cmp #1, r0
    bne fail

    ; Test 6: ROL sets C from MSB
    clc
    mov #0x8000, r0
    rol r0              ; MSB=1 goes to C
    bcc fail            ; C should be set

    ; Test 7: Full rotation (16 ROR + C)
    sec
    mov #0, r0
    ror r0              ; 0x8000
    cmp #0x8000, r0
    bne fail

    ; Test 8: ROL pattern
    clc
    mov #0x5555, r0
    rol r0              ; r0 = 0xAAAA
    cmp #0xAAAA, r0
    bne fail

pass:
    br pass

fail:
    br fail
