; Test ADC (Add with Carry) instruction

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: ADC immediate - basic
test_1:
    ldx #1
    stx $00
    clc
    lda #$10
    adc #$05
    cmp #$15
    beq test_2
    jmp fail

; Test 2: ADC with carry in
test_2:
    ldx #2
    stx $00
    sec
    lda #$10
    adc #$05
    cmp #$16
    beq test_3
    jmp fail

; Test 3: ADC carry out
test_3:
    ldx #3
    stx $00
    clc
    lda #$FF
    adc #$01
    bcs t3ok
    jmp fail
t3ok:
    cmp #$00
    beq test_4
    jmp fail

; Test 4: ADC zero result
test_4:
    ldx #4
    stx $00
    clc
    lda #$00
    adc #$00
    beq test_5
    jmp fail

; Test 5: ADC negative result
test_5:
    ldx #5
    stx $00
    clc
    lda #$7F
    adc #$01
    bmi t5ok
    jmp fail
t5ok:
    cmp #$80
    beq test_6
    jmp fail

; Test 6: ADC overflow
test_6:
    ldx #6
    stx $00
    clc
    lda #$50
    adc #$50
    bvs t6ok
    jmp fail
t6ok:
    cmp #$A0
    beq test_7
    jmp fail

; Test 7: ADC zero page
test_7:
    ldx #7
    stx $00
    lda #$20
    sta $10
    clc
    lda #$10
    adc $10
    cmp #$30
    beq test_8
    jmp fail

; Test 8: ADC chain
test_8:
    ldx #8
    stx $00
    clc
    lda #$01
    adc #$01
    adc #$01
    adc #$01
    cmp #$04
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
