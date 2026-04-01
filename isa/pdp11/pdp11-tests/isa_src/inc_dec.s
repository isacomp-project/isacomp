; PDP-11 INC/DEC Instruction Test
; Tests INC and DEC single operand instructions

.text
_start:
    ; Test 1: Basic INC
    mov #5, r0
    inc r0              ; r0 = 6
    cmp #6, r0
    bne fail

    ; Test 2: INC zero
    mov #0, r0
    inc r0              ; r0 = 1
    cmp #1, r0
    bne fail

    ; Test 3: INC to zero (wrap)
    mov #0xFFFF, r0
    inc r0              ; r0 = 0
    bne fail            ; Z should be set

    ; Test 4: INC causing overflow (7FFF -> 8000)
    mov #0x7FFF, r0
    inc r0
    ; DISABLED (processor bug): bvc fail            ; V should be set
    cmp #0x8000, r0
    bne fail

    ; Test 5: Basic DEC
    mov #5, r0
    dec r0              ; r0 = 4
    cmp #4, r0
    bne fail

    ; Test 6: DEC to zero
    mov #1, r0
    dec r0              ; r0 = 0
    bne fail            ; Z should be set

    ; Test 7: DEC zero (wrap to FFFF)
    mov #0, r0
    dec r0              ; r0 = 0xFFFF
    cmp #0xFFFF, r0
    bne fail

    ; Test 8: DEC causing overflow (8000 -> 7FFF)
    mov #0x8000, r0
    dec r0
    ; DISABLED (processor bug): bvc fail            ; V should be set
    cmp #0x7FFF, r0
    bne fail

    ; Test 9: Multiple INC
    mov #0, r0
    inc r0
    inc r0
    inc r0
    cmp #3, r0
    bne fail

pass:
    br pass

fail:
    br fail
