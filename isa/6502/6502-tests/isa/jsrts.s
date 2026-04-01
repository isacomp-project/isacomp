; Test JSR and RTS instructions
; This test checks that subroutine calls work correctly

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: Simple JSR/RTS
test_1:
    ldx #1
    stx $00
    lda #$00        ; Clear A
    jsr subr1       ; Call subroutine
    cmp #$42        ; A should be set by subroutine
    beq test_2
    jmp fail

; Test 2: JSR preserves X
test_2:
    ldx #2
    stx $00
    ldx #$AA
    jsr subr2       ; This subr doesn't touch X
    cpx #$AA        ; X should still be $AA
    beq test_3
    jmp fail

; Test 3: Nested JSR (2 levels)
test_3:
    ldx #3
    stx $00
    lda #$00
    jsr outer       ; Calls inner
    cmp #$88        ; A should be set by inner
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail

; Subroutine for test 1
subr1:
    lda #$42
    rts

; Subroutine for test 2
subr2:
    lda #$55        ; Modify A only
    rts

; Outer subroutine for test 3
outer:
    jsr inner       ; Call inner
    rts

; Inner subroutine for test 3
inner:
    lda #$88
    rts
