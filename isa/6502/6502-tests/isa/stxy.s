; Test STX, STY instructions - all addressing modes
; STX: zp, zp,Y, abs
; STY: zp, zp,X, abs

    * = $0400

start:
    ldx #0
    stx $00

; ============================================================================
; Test 1: STX zero page
; ============================================================================
test_1:
    ldx #1
    stx $00
    ldx #$42
    stx $10
    lda $10
    cmp #$42
    beq test_2
    jmp fail

; ============================================================================
; Test 2: STX zero page,Y
; ============================================================================
test_2:
    ldx #2
    stx $00
    ldx #$55
    ldy #$05
    stx $10,y           ; Store to $15
    lda $15
    cmp #$55
    beq test_3
    jmp fail

; ============================================================================
; Test 3: STX absolute
; ============================================================================
test_3:
    ldx #3
    stx $00
    ldx #$AA
    stx $0500
    lda $0500
    cmp #$AA
    beq test_4
    jmp fail

; ============================================================================
; Test 4: STY zero page
; ============================================================================
test_4:
    ldx #4
    stx $00
    ldy #$33
    sty $20
    lda $20
    cmp #$33
    beq test_5
    jmp fail

; ============================================================================
; Test 5: STY zero page,X
; ============================================================================
test_5:
    ldx #5
    stx $00
    ldy #$66
    ldx #$08
    sty $20,x           ; Store to $28
    lda $28
    cmp #$66
    beq test_6
    jmp fail

; ============================================================================
; Test 6: STY absolute
; ============================================================================
test_6:
    ldx #6
    stx $00
    ldy #$BB
    sty $0510
    lda $0510
    cmp #$BB
    beq test_7
    jmp fail

; ============================================================================
; Test 7: STX preserves X register
; ============================================================================
test_7:
    ldx #7
    stx $00
    ldx #$77
    stx $30
    cpx #$77            ; X should be unchanged
    beq test_8
    jmp fail

; ============================================================================
; Test 8: STY preserves Y register
; ============================================================================
test_8:
    ldx #8
    stx $00
    ldy #$88
    sty $31
    cpy #$88            ; Y should be unchanged
    beq test_9
    jmp fail

; ============================================================================
; Test 9: STX/STY pipeline - consecutive stores
; ============================================================================
test_9:
    ldx #9
    stx $00
    ldx #$11
    ldy #$22
    stx $40
    sty $41
    stx $42
    sty $43
    ; Verify all locations
    lda $40
    cmp #$11
    bne fail
    lda $41
    cmp #$22
    bne fail
    lda $42
    cmp #$11
    bne fail
    lda $43
    cmp #$22
    beq test_10
    jmp fail

; ============================================================================
; Test 10: Store-load hazard with STX
; ============================================================================
test_10:
    ldx #10
    stx $00
    ldx #$99
    stx $50
    lda $50             ; Immediate load after store (RAW hazard)
    cmp #$99
    beq test_11
    jmp fail

; ============================================================================
; Test 11: Store-load hazard with STY
; ============================================================================
test_11:
    ldx #11
    stx $00
    ldy #$CC
    sty $51
    lda $51
    cmp #$CC
    beq test_12
    jmp fail

; ============================================================================
; Test 12: Cross-register store verify
; ============================================================================
test_12:
    ldx #12
    stx $00
    ldx #$12
    ldy #$34
    stx $60
    sty $61
    ; Load back and verify with different registers
    ldx $61             ; Load Y's stored value into X
    cpx #$34
    bne fail
    ldy $60             ; Load X's stored value into Y
    cpy #$12
    beq pass
    jmp fail

; ============================================================================
; All tests passed
; ============================================================================
pass:
    jmp pass
fail:
    jmp fail
