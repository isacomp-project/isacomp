; Edge case tests for pipeline boundary conditions
; Tests boundary values, overflow, underflow, and flag edge cases

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: ADC overflow boundary (127 + 1)
test_1:
    ldx #1
    stx $00
    clc
    lda #$7F        ; 127
    adc #$01        ; Should overflow to -128 ($80)
    bvs t1ok        ; V should be set
    jmp fail
t1ok:
    cmp #$80
    beq test_2
    jmp fail

; Test 2: SBC underflow boundary (-128 - 1)
test_2:
    ldx #2
    stx $00
    sec
    lda #$80        ; -128
    sbc #$01        ; Should underflow to 127 ($7F)
    bvs t2ok        ; V should be set
    jmp fail
t2ok:
    cmp #$7F
    beq test_3
    jmp fail

; Test 3: ADC no overflow at boundary (126 + 1)
test_3:
    ldx #3
    stx $00
    clc
    lda #$7E        ; 126
    adc #$01        ; Should be 127, no overflow
    bvc t3ok        ; V should be clear
    jmp fail
t3ok:
    cmp #$7F
    beq test_4
    jmp fail

; Test 4: Carry chain test (255 + 1)
test_4:
    ldx #4
    stx $00
    clc
    lda #$FF
    adc #$01        ; Should be 0 with carry
    bcs t4ok
    jmp fail
t4ok:
    cmp #$00
    beq test_5
    jmp fail

; Test 5: Back-to-back writes same location
test_5:
    ldx #5
    stx $00
    lda #$11
    sta $10
    lda #$22
    sta $10
    lda #$33
    sta $10
    lda $10
    cmp #$33        ; Only last write should persist
    beq test_6
    jmp fail

; Test 6: INC/DEC boundary (255 + 1)
test_6:
    ldx #6
    stx $00
    lda #$FF
    sta $10
    inc $10
    lda $10
    cmp #$00        ; Should wrap to 0
    beq test_7
    jmp fail

; Test 7: DEC boundary (0 - 1)
test_7:
    ldx #7
    stx $00
    lda #$00
    sta $10
    dec $10
    lda $10
    cmp #$FF        ; Should wrap to 255
    beq test_8
    jmp fail

; Test 8: ASL carry at boundary
test_8:
    ldx #8
    stx $00
    clc
    lda #$FF
    asl             ; $FF << 1 = $FE, C=1
    bcs t8ok
    jmp fail
t8ok:
    cmp #$FE
    beq test_9
    jmp fail

; Test 9: LSR at boundary (1 >> 1)
test_9:
    ldx #9
    stx $00
    clc
    lda #$01
    lsr             ; 1 >> 1 = 0, C=1
    bcs t9ok
    jmp fail
t9ok:
    beq test_10     ; Result should be 0
    jmp fail

; Test 10: Double carry operation
test_10:
    ldx #10
    stx $00
    clc
    lda #$80
    adc #$80        ; $80 + $80 = $100, result=$00, C=1
    bcs t10ok
    jmp fail
t10ok:
    adc #$00        ; $00 + $00 + 1 = $01
    cmp #$01
    beq test_11
    jmp fail

; Test 11: Zero flag edge case with transfer
test_11:
    ldx #11
    stx $00
    lda #$00
    tax             ; X=0, Z=1
    beq t11ok       ; Should branch
    jmp fail
t11ok:
    ldx #$01
    txa             ; A=1, Z=0
    bne test_12
    jmp fail

; Test 12: Negative flag edge case
test_12:
    ldx #12
    stx $00
    lda #$7F        ; Not negative
    bpl t12a
    jmp fail
t12a:
    lda #$80        ; Negative
    bmi pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
