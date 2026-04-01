; Test NOP instruction
; NOP should not affect any registers or flags
; Tests pipeline behavior with NOPs interspersed

    * = $0400

start:
    ldx #0
    stx $00

; ============================================================================
; Test 1: NOP doesn't affect A
; ============================================================================
test_1:
    ldx #1
    stx $00
    lda #$42
    nop
    cmp #$42
    beq test_2
    jmp fail

; ============================================================================
; Test 2: NOP doesn't affect X
; ============================================================================
test_2:
    ldx #2
    stx $00
    ldx #$55
    nop
    cpx #$55
    beq test_3
    jmp fail

; ============================================================================
; Test 3: NOP doesn't affect Y
; ============================================================================
test_3:
    ldx #3
    stx $00
    ldy #$AA
    nop
    cpy #$AA
    beq test_4
    jmp fail

; ============================================================================
; Test 4: NOP doesn't affect carry flag
; ============================================================================
test_4:
    ldx #4
    stx $00
    sec
    nop
    bcs t4ok
    jmp fail
t4ok:
    clc
    nop
    bcc test_5
    jmp fail

; ============================================================================
; Test 5: NOP doesn't affect zero flag
; ============================================================================
test_5:
    ldx #5
    stx $00
    lda #$00            ; Set Z flag
    nop
    beq t5ok
    jmp fail
t5ok:
    lda #$01            ; Clear Z flag
    nop
    bne test_6
    jmp fail

; ============================================================================
; Test 6: NOP doesn't affect negative flag
; ============================================================================
test_6:
    ldx #6
    stx $00
    lda #$80            ; Set N flag
    nop
    bmi t6ok
    jmp fail
t6ok:
    lda #$01            ; Clear N flag
    nop
    bpl test_7
    jmp fail

; ============================================================================
; Test 7: Multiple NOPs in sequence
; ============================================================================
test_7:
    ldx #7
    stx $00
    lda #$33
    nop
    nop
    nop
    nop
    nop
    cmp #$33
    beq test_8
    jmp fail

; ============================================================================
; Test 8: NOP between load and use (pipeline)
; ============================================================================
test_8:
    ldx #8
    stx $00
    lda #$12
    nop                 ; NOP between load and store
    sta $10
    lda #$00
    lda $10
    cmp #$12
    beq test_9
    jmp fail

; ============================================================================
; Test 9: NOP in arithmetic sequence
; ============================================================================
test_9:
    ldx #9
    stx $00
    clc
    lda #$10
    nop
    adc #$05
    nop
    adc #$05
    cmp #$1A
    beq test_10
    jmp fail

; ============================================================================
; Test 10: NOP doesn't affect overflow flag
; ============================================================================
test_10:
    ldx #10
    stx $00
    clc
    lda #$50
    adc #$50            ; Triggers overflow
    nop
    bvs t10ok
    jmp fail
t10ok:
    clv                 ; Clear overflow
    nop
    bvc test_11
    jmp fail

; ============================================================================
; Test 11: NOP in memory store sequence
; ============================================================================
test_11:
    ldx #11
    stx $00
    lda #$AA
    sta $20
    nop
    sta $21
    nop
    sta $22
    ; Verify all stores
    lda $20
    cmp #$AA
    bne fail
    lda $21
    cmp #$AA
    bne fail
    lda $22
    cmp #$AA
    beq test_12
    jmp fail

; ============================================================================
; Test 12: Long NOP sequence (stress test)
; ============================================================================
test_12:
    ldx #12
    stx $00
    lda #$FF
    ldx #$EE
    ldy #$DD
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    ; All registers must be preserved
    cmp #$FF
    bne fail
    cpx #$EE
    bne fail
    cpy #$DD
    beq pass
    jmp fail

; ============================================================================
; All tests passed
; ============================================================================
pass:
    jmp pass
fail:
    jmp fail
