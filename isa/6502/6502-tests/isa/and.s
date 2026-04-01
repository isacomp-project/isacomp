; Test AND, ORA, EOR instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: AND immediate
test_1:
    ldx #1
    stx $00
    lda #$FF
    and #$0F
    cmp #$0F
    beq test_2
    jmp fail

; Test 2: AND zero result
test_2:
    ldx #2
    stx $00
    lda #$F0
    and #$0F
    beq test_3
    jmp fail

; Test 3: AND N flag
test_3:
    ldx #3
    stx $00
    lda #$FF
    and #$80
    bmi t3ok
    jmp fail
t3ok:
    cmp #$80
    beq test_4
    jmp fail

; Test 4: ORA immediate
test_4:
    ldx #4
    stx $00
    lda #$0F
    ora #$F0
    cmp #$FF
    beq test_5
    jmp fail

; Test 5: ORA zero page
test_5:
    ldx #5
    stx $00
    lda #$AA
    sta $10
    lda #$55
    ora $10
    cmp #$FF
    beq test_6
    jmp fail

; Test 6: EOR immediate
test_6:
    ldx #6
    stx $00
    lda #$FF
    eor #$0F
    cmp #$F0
    beq test_7
    jmp fail

; Test 7: EOR self = 0
test_7:
    ldx #7
    stx $00
    lda #$AA
    eor #$AA
    beq test_8
    jmp fail

; Test 8: Logical chain
test_8:
    ldx #8
    stx $00
    lda #$FF
    and #$F0
    ora #$0A
    eor #$0F
    cmp #$F5
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
