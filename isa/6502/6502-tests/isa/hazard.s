; Pipeline Hazard Tests for 6502
; Tests RAW hazards with varying NOP distances

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: A RAW - 0 NOPs
test_1:
    ldx #1
    stx $00
    lda #$42
    sta $10
    lda $10
    cmp #$42
    beq test_2
    jmp fail

; Test 2: A RAW - 1 NOP
test_2:
    ldx #2
    stx $00
    lda #$43
    nop
    sta $11
    lda $11
    cmp #$43
    beq test_3
    jmp fail

; Test 3: X RAW - 0 NOPs
test_3:
    ldx #3
    stx $00
    ldx #$55
    stx $20
    lda $20
    cmp #$55
    beq test_4
    jmp fail

; Test 4: Y RAW - 0 NOPs
test_4:
    ldx #4
    stx $00
    ldy #$66
    sty $30
    lda $30
    cmp #$66
    beq test_5
    jmp fail

; Test 5: Carry flag RAW
test_5:
    ldx #5
    stx $00
    lda #$00        ; Clear A first
    sec
    clc
    adc #$05        ; A = 0 + 5 + 0 = 5
    cmp #$05
    beq test_6
    jmp fail

; Test 6: Store-load chain
test_6:
    ldx #6
    stx $00
    lda #$AA
    sta $40
    lda $40
    cmp #$AA
    beq test_7
    jmp fail

; Test 7: ADC chain
test_7:
    ldx #7
    stx $00
    clc
    lda #$01
    adc #$01
    adc #$01
    adc #$01
    cmp #$04
    beq test_8
    jmp fail

; Test 8: Transfer chain
test_8:
    ldx #8
    stx $00
    lda #$10
    tax
    txa
    tay
    cmp #$10
    beq t8a
    jmp fail
t8a:
    cpx #$10
    beq t8b
    jmp fail
t8b:
    cpy #$10
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
