; Test INC, DEC, INX, DEX, INY, DEY instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: INC zp
test_1:
    ldx #1
    stx $00
    lda #$42
    sta $10
    inc $10
    lda $10
    cmp #$43
    beq test_2
    jmp fail

; Test 2: INC wrap
test_2:
    ldx #2
    stx $00
    lda #$FF
    sta $10
    inc $10
    lda $10
    cmp #$00
    beq test_3
    jmp fail

; Test 3: DEC zp
test_3:
    ldx #3
    stx $00
    lda #$42
    sta $10
    dec $10
    lda $10
    cmp #$41
    beq test_4
    jmp fail

; Test 4: DEC wrap
test_4:
    ldx #4
    stx $00
    lda #$00
    sta $10
    dec $10
    lda $10
    cmp #$FF
    beq test_5
    jmp fail

; Test 5: INX
test_5:
    ldx #5
    stx $00
    ldx #$42
    inx
    cpx #$43
    beq test_6
    jmp fail

; Test 6: DEX
test_6:
    ldx #6
    stx $00
    ldx #$42
    dex
    cpx #$41
    beq test_7
    jmp fail

; Test 7: INY
test_7:
    ldx #7
    stx $00
    ldy #$42
    iny
    cpy #$43
    beq test_8
    jmp fail

; Test 8: DEY
test_8:
    ldx #8
    stx $00
    ldy #$42
    dey
    cpy #$41
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
