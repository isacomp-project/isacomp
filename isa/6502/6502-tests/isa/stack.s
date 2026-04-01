; Test PHA, PLA, PHP, PLP instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: PHA/PLA
test_1:
    ldx #1
    stx $00
    lda #$42
    pha
    lda #$00
    pla
    cmp #$42
    beq test_2
    jmp fail

; Test 2: LIFO order
test_2:
    ldx #2
    stx $00
    lda #$11
    pha
    lda #$22
    pha
    pla
    cmp #$22
    beq t2a
    jmp fail
t2a:
    pla
    cmp #$11
    beq test_3
    jmp fail

; Test 3: PLA Z flag
test_3:
    ldx #3
    stx $00
    lda #$00
    pha
    lda #$FF
    pla
    beq test_4
    jmp fail

; Test 4: PHP/PLP carry
test_4:
    ldx #4
    stx $00
    sec
    php
    clc
    plp
    bcs test_5
    jmp fail

; Test 5: PHP/PLP zero
test_5:
    ldx #5
    stx $00
    lda #$00
    php
    lda #$01
    plp
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
