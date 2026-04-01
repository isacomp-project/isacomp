; Test branch instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: BEQ taken
test_1:
    ldx #1
    stx $00
    lda #$00
    beq test_2
    jmp fail

; Test 2: BNE taken
test_2:
    ldx #2
    stx $00
    lda #$01
    bne test_3
    jmp fail

; Test 3: BCS taken
test_3:
    ldx #3
    stx $00
    sec
    bcs test_4
    jmp fail

; Test 4: BCC taken
test_4:
    ldx #4
    stx $00
    clc
    bcc test_5
    jmp fail

; Test 5: BMI taken
test_5:
    ldx #5
    stx $00
    lda #$80
    bmi test_6
    jmp fail

; Test 6: BPL taken
test_6:
    ldx #6
    stx $00
    lda #$01
    bpl test_7
    jmp fail

; Test 7: BVS taken
test_7:
    ldx #7
    stx $00
    clc
    lda #$7F
    adc #$01
    bvs test_8
    jmp fail

; Test 8: BVC taken
test_8:
    ldx #8
    stx $00
    clv
    bvc test_9
    jmp fail

; Test 9: Loop with DEX
test_9:
    ldx #9
    stx $00
    ldy #$03
loop9:
    dey
    bne loop9
    cpy #$00
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
