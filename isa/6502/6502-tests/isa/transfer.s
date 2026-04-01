; Test TAX, TAY, TXA, TYA, TSX, TXS instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: TAX
test_1:
    ldx #1
    stx $00
    lda #$42
    ldx #$00
    tax
    cpx #$42
    beq test_2
    jmp fail

; Test 2: TAY
test_2:
    ldx #2
    stx $00
    lda #$55
    ldy #$00
    tay
    cpy #$55
    beq test_3
    jmp fail

; Test 3: TXA
test_3:
    ldx #3
    stx $00
    ldx #$AA
    lda #$00
    txa
    cmp #$AA
    beq test_4
    jmp fail

; Test 4: TYA
test_4:
    ldx #4
    stx $00
    ldy #$BB
    lda #$00
    tya
    cmp #$BB
    beq test_5
    jmp fail

; Test 5: TSX
test_5:
    ldx #5
    stx $00
    tsx
    cpx #$00
    beq fail5
    jmp test_6
fail5:
    jmp fail

; Test 6: Transfer chain
test_6:
    ldx #6
    stx $00
    lda #$42
    tax
    lda #$00
    txa
    cmp #$42
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
