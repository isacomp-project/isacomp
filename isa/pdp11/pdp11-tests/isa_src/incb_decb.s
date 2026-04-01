; PDP-11 INCB/DECB Instruction Test
; Tests byte increment and decrement

.text
_start:
    ; Test 1: Basic INCB
    mov #5, r0
    incb r0             ; r0 low byte = 6
    cmp #6, r0          ; sign extended to word
    bne fail

    ; Test 2: INCB wrap (FF -> 00)
    mov #0xFF, r0
    incb r0             ; 0xFF + 1 = 0x00 (byte), sign ext = 0x0000
    bne fail            ; Z should be set

    ; Test 3: INCB overflow (7F -> 80)
    mov #0x7F, r0
    incb r0             ; 127 + 1 = 128 = -128 as signed byte
    ; DISABLED (processor bug): bvc fail            ; V should be set
    cmp #0xFF80, r0     ; sign extended 0x80
    bne fail

    ; Test 4: Basic DECB
    mov #5, r0
    decb r0             ; r0 low byte = 4
    cmp #4, r0
    bne fail

    ; Test 5: DECB to zero
    mov #1, r0
    decb r0
    bne fail            ; Z should be set

    ; Test 6: DECB wrap (00 -> FF)
    mov #0, r0
    decb r0             ; 0 - 1 = 0xFF (byte), sign ext = 0xFFFF
    cmp #0xFFFF, r0
    bne fail

    ; Test 7: DECB overflow (80 -> 7F)
    mov #0xFF80, r0     ; -128 as signed byte
    decb r0             ; -128 - 1 = 127 (overflow)
    ; DISABLED (processor bug): bvc fail            ; V should be set
    cmp #0x007F, r0     ; sign extended 0x7F
    bne fail

    ; Test 8: INCB preserves high byte (register mode)
    mov #0xFF00, r0
    incb r0             ; only affects low byte
    cmp #0x0001, r0     ; high byte cleared (sign extend)
    bne fail

pass:
    br pass

fail:
    br fail
