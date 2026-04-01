; Test CMP, CPX, CPY instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: CMP equal
test_1:
    ldx #1
    stx $00
    lda #$42
    cmp #$42
    beq test_2
    jmp fail

; Test 2: CMP greater
test_2:
    ldx #2
    stx $00
    lda #$50
    cmp #$30
    bcs t2ok
    jmp fail
t2ok:
    beq fail2
    jmp test_3
fail2:
    jmp fail

; Test 3: CMP less
test_3:
    ldx #3
    stx $00
    lda #$30
    cmp #$50
    bcc t3ok
    jmp fail
t3ok:

; Test 4: CMP zp
test_4:
    ldx #4
    stx $00
    lda #$88
    sta $10
    lda #$88
    cmp $10
    beq test_5
    jmp fail

; Test 5: CPX immediate
test_5:
    ldx #5
    stx $00
    ldx #$42
    cpx #$42
    beq test_6
    jmp fail

; Test 6: CPY immediate
test_6:
    ldx #6
    stx $00
    ldy #$42
    cpy #$42
    beq test_7
    jmp fail

; Test 7: sequential compares
test_7:
    ldx #7
    stx $00
    lda #$50
    cmp #$50
    beq t7a
    jmp fail
t7a:
    cmp #$60
    bcc t7b
    jmp fail
t7b:
    cmp #$40
    bcs pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
