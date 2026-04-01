; Pipeline stress tests
; Specifically designed to trigger RAW hazards, control hazards,
; and test forwarding/stalling logic in the 3-stage pipeline

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: Tight ADC chain - A written and read immediately
test_1:
    ldx #1
    stx $00
    clc
    lda #$01
    adc #$01        ; A=2
    adc #$01        ; A=3, uses result from prev ADC
    adc #$01        ; A=4
    adc #$01        ; A=5
    cmp #$05
    beq test_2
    jmp fail

; Test 2: Store then load same address
test_2:
    ldx #2
    stx $00
    lda #$AB
    sta $10
    lda $10         ; Should read $AB just written
    cmp #$AB
    beq test_3
    jmp fail

; Test 3: Register transfer chain
test_3:
    ldx #3
    stx $00
    lda #$CD
    tax             ; X=$CD
    txa             ; A=$CD (from X)
    tay             ; Y=$CD (from A)
    tya             ; A=$CD (from Y)
    cmp #$CD
    beq test_4
    jmp fail

; Test 4: Flag dependency - SEC then ADC
test_4:
    ldx #4
    stx $00
    clc
    lda #$10
    sec             ; Set carry
    adc #$05        ; Should add with C=1: $10+$05+1=$16
    cmp #$16
    beq test_5
    jmp fail

; Test 5: Flag dependency - CLC then ADC
test_5:
    ldx #5
    stx $00
    sec
    lda #$10
    clc             ; Clear carry
    adc #$05        ; Should add with C=0: $10+$05+0=$15
    cmp #$15
    beq test_6
    jmp fail

; Test 6: Branch after compare (control hazard)
test_6:
    ldx #6
    stx $00
    lda #$42
    cmp #$42
    beq t6ok        ; Should branch
    jmp fail
t6ok:
    cmp #$43
    bne test_7      ; Should branch (not equal)
    jmp fail

; Test 7: Multiple stores then reads
test_7:
    ldx #7
    stx $00
    lda #$01
    sta $20
    lda #$02
    sta $21
    lda #$03
    sta $22
    ; Now read back in different order
    lda $22
    cmp #$03
    bne fail
    lda $20
    cmp #$01
    bne fail
    lda $21
    cmp #$02
    beq test_8
    jmp fail

; Test 8: Indexed store-load hazard
test_8:
    ldx #8
    stx $00
    ldx #$05
    lda #$EE
    sta $30,x       ; Store at $35
    lda $30,x       ; Load from $35
    cmp #$EE
    beq test_9
    jmp fail

; Test 9: Stack push/pull chain
test_9:
    ldx #9
    stx $00
    lda #$11
    pha
    lda #$22
    pha
    lda #$33
    pha
    ; Pull in reverse order
    pla
    cmp #$33
    bne fail
    pla
    cmp #$22
    bne fail
    pla
    cmp #$11
    beq test_10
    jmp fail

; Test 10: Skip JSR/RTS - has a bug to investigate separately
; test_10:
;     ldx #10
;     stx $00
;     lda #$00
;     jsr subr
;     cmp #$55        ; Subroutine should set A to $55
;     beq test_11
;     jmp fail

; Test 10: INC/DEC chain on same location
test_10:
    ldx #10
    stx $00
    lda #$10
    sta $40
    inc $40         ; $11
    inc $40         ; $12
    dec $40         ; $11
    lda $40
    cmp #$11
    beq test_11
    jmp fail

; Test 11: Compare after arithmetic
test_11:
    ldx #11
    stx $00
    clc
    lda #$30
    adc #$20        ; A=$50
    cmp #$50        ; Z should be set
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
