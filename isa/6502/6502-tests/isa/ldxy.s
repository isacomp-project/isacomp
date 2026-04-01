; Test LDX, LDY, STX, STY instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: LDX immediate
test_1:
    ldx #1
    stx $00
    ldx #$42
    cpx #$42
    beq test_2
    jmp fail

; Test 2: LDX Z flag
test_2:
    ldx #2
    stx $00
    ldx #$00
    beq test_3
    jmp fail

; Test 3: LDX N flag
test_3:
    ldx #3
    stx $00
    ldx #$80
    bmi test_4
    jmp fail

; Test 4: LDY immediate
test_4:
    ldx #4
    stx $00
    ldy #$42
    cpy #$42
    beq test_5
    jmp fail

; Test 5: STX zp
test_5:
    ldx #5
    stx $00
    ldx #$55
    stx $10
    lda $10
    cmp #$55
    beq test_6
    jmp fail

; Test 6: STY zp
test_6:
    ldx #6
    stx $00
    ldy #$66
    sty $11
    lda $11
    cmp #$66
    beq test_7
    jmp fail

; Test 7: LDX zp
test_7:
    ldx #7
    stx $00
    lda #$77
    sta $12
    ldx $12
    cpx #$77
    beq test_8
    jmp fail

; Test 8: LDY zp
test_8:
    ldx #8
    stx $00
    lda #$88
    sta $13
    ldy $13
    cpy #$88
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
