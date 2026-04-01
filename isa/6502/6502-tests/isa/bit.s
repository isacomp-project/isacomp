; Test BIT instruction - tests bits without modifying accumulator
; BIT sets N and V from memory value, Z from A AND mem

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: BIT - Z flag when A AND mem = 0
test_1:
    ldx #1
    stx $00
    lda #$F0
    sta $10
    lda #$0F        ; A AND $F0 = 0
    bit $10
    beq test_2      ; Z should be set
    jmp fail

; Test 2: BIT - Z flag when A AND mem != 0
test_2:
    ldx #2
    stx $00
    lda #$FF
    sta $10
    lda #$0F        ; A AND $FF = $0F != 0
    bit $10
    bne test_3      ; Z should be clear
    jmp fail

; Test 3: BIT - N flag from bit 7 of memory
test_3:
    ldx #3
    stx $00
    lda #$80        ; bit 7 set
    sta $10
    lda #$FF
    bit $10
    bmi test_4      ; N should be set (bit 7 of mem)
    jmp fail

; Test 4: BIT - N flag clear
test_4:
    ldx #4
    stx $00
    lda #$7F        ; bit 7 clear
    sta $10
    lda #$FF
    bit $10
    bpl test_5      ; N should be clear
    jmp fail

; Test 5: BIT - V flag from bit 6 of memory
test_5:
    ldx #5
    stx $00
    lda #$40        ; bit 6 set
    sta $10
    lda #$FF
    bit $10
    bvs test_6      ; V should be set (bit 6 of mem)
    jmp fail

; Test 6: BIT - V flag clear
test_6:
    ldx #6
    stx $00
    lda #$BF        ; bit 6 clear
    sta $10
    lda #$FF
    bit $10
    bvc test_7      ; V should be clear
    jmp fail

; Test 7: BIT - A is not modified
test_7:
    ldx #7
    stx $00
    lda #$12
    sta $10
    lda #$34
    bit $10
    cmp #$34        ; A should still be $34
    beq test_8
    jmp fail

; Test 8: BIT absolute
test_8:
    ldx #8
    stx $00
    lda #$C0        ; bits 7 and 6 set
    sta $0800
    lda #$FF
    bit $0800
    bmi t8a
    jmp fail
t8a:
    bvs pass        ; both N and V should be set
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
