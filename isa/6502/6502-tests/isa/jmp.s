; Test JMP, JSR, RTS instructions

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: JMP absolute
test_1:
    ldx #1
    stx $00
    jmp test_2
    jmp fail

; Test 2: JSR/RTS basic
test_2:
    ldx #2
    stx $00
    jsr sub1
    cmp #$42
    beq test_3
    jmp fail

sub1:
    lda #$42
    rts

; Test 3: Nested JSR
test_3:
    ldx #3
    stx $00
    jsr sub2
    cmp #$99
    beq test_4
    jmp fail

sub2:
    lda #$11
    jsr sub3
    rts

sub3:
    lda #$99
    rts

; Test 4: Multiple JSR calls
test_4:
    ldx #4
    stx $00
    lda #$00
    jsr add1
    jsr add1
    jsr add1
    cmp #$03
    beq test_5
    jmp fail

add1:
    clc
    adc #$01
    rts

; Test 5: JMP indirect (pointer in zero page)
test_5:
    ldx #5
    stx $00
    ; Set up indirect pointer at $0050/$0051 to point to pass label
    lda #<pass
    sta $50
    lda #>pass
    sta $51
    jmp ($0050)
    jmp fail        ; should not reach here

pass:
    jmp pass

fail:
    jmp fail
