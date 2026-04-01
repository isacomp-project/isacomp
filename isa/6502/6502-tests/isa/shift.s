; Test ASL, LSR, ROL, ROR instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: ASL acc
test_1:
    ldx #1
    stx $00
    lda #$01
    asl
    cmp #$02
    beq test_2
    jmp fail

; Test 2: ASL carry out
test_2:
    ldx #2
    stx $00
    clc
    lda #$80
    asl
    bcs t2ok
    jmp fail
t2ok:
    cmp #$00
    beq test_3
    jmp fail

; Test 3: LSR acc
test_3:
    ldx #3
    stx $00
    lda #$02
    lsr
    cmp #$01
    beq test_4
    jmp fail

; Test 4: LSR carry out
test_4:
    ldx #4
    stx $00
    clc
    lda #$01
    lsr
    bcs t4ok
    jmp fail
t4ok:
    cmp #$00
    beq test_5
    jmp fail

; Test 5: ROL acc
test_5:
    ldx #5
    stx $00
    clc
    lda #$01
    rol
    cmp #$02
    beq test_6
    jmp fail

; Test 6: ROL carry in
test_6:
    ldx #6
    stx $00
    sec
    lda #$01
    rol
    cmp #$03
    beq test_7
    jmp fail

; Test 7: ROR acc
test_7:
    ldx #7
    stx $00
    clc
    lda #$02
    ror
    cmp #$01
    beq test_8
    jmp fail

; Test 8: ROR carry in
test_8:
    ldx #8
    stx $00
    sec
    lda #$02
    ror
    cmp #$81
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
