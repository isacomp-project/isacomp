; Test CLC, SEC, CLD, SED, CLI, SEI, CLV instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: CLC
test_1:
    ldx #1
    stx $00
    sec
    clc
    bcc test_2
    jmp fail

; Test 2: SEC
test_2:
    ldx #2
    stx $00
    clc
    sec
    bcs test_3
    jmp fail

; Test 3: CLV
test_3:
    ldx #3
    stx $00
    clc
    lda #$7F
    adc #$01
    bvs t3a
    jmp fail
t3a:
    clv
    bvc test_4
    jmp fail

; Test 4: CLC for ADC
test_4:
    ldx #4
    stx $00
    sec
    lda #$10
    clc
    adc #$05
    cmp #$15
    beq test_5
    jmp fail

; Test 5: SEC for SBC
test_5:
    ldx #5
    stx $00
    clc
    lda #$20
    sec
    sbc #$05
    cmp #$1B        ; $20 - $05 - (1-1) = $20 - $05 = $1B
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
