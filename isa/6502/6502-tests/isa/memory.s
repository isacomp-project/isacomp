; Comprehensive memory addressing mode tests
; Tests all addressing modes with store and load operations

    * = $0400

start:
    ldx #0
    stx $00

; Test 1: Zero page - basic
test_1:
    ldx #1
    stx $00
    lda #$11
    sta $10
    lda #$00
    lda $10
    cmp #$11
    beq test_2
    jmp fail

; Test 2: Zero page X - forward
test_2:
    ldx #2
    stx $00
    lda #$22
    ldx #$05
    sta $15,x       ; Store at $15+5=$1A
    lda #$00
    lda $15,x       ; Load from $1A
    cmp #$22
    beq test_3
    jmp fail

; Test 3: Zero page X - wrapping (255+5 wraps to 4)
test_3:
    ldx #3
    stx $00
    lda #$33
    ldx #$05
    sta $FF,x       ; Should wrap to $04
    lda #$00
    lda $04
    cmp #$33
    beq test_4
    jmp fail

; Test 4: Absolute
test_4:
    ldx #4
    stx $00
    lda #$44
    sta $0800
    lda #$00
    lda $0800
    cmp #$44
    beq test_5
    jmp fail

; Test 5: Absolute X
test_5:
    ldx #5
    stx $00
    lda #$55
    ldx #$10
    sta $0800,x     ; Store at $0810
    lda #$00
    lda $0800,x
    cmp #$55
    beq test_6
    jmp fail

; Test 6: Absolute Y
test_6:
    ldx #6
    stx $00
    lda #$66
    ldy #$20
    sta $0800,y     ; Store at $0820
    lda #$00
    lda $0800,y
    cmp #$66
    beq test_7
    jmp fail

; Test 7: Indirect X - (zp,X)
test_7:
    ldx #7
    stx $00
    ; Set up pointer at $30: points to $0900
    lda #$00
    sta $30
    lda #$09
    sta $31
    ; Store value at target
    lda #$77
    sta $0900
    ; Load indirect
    lda #$00
    ldx #$00
    lda ($30,x)
    cmp #$77
    beq test_8
    jmp fail

; Test 8: Indirect Y - (zp),Y
test_8:
    ldx #8
    stx $00
    ; Set up pointer at $40: points to $0A00
    lda #$00
    sta $40
    lda #$0A
    sta $41
    ; Store value at target+5
    lda #$88
    sta $0A05
    ; Load indirect indexed
    lda #$00
    ldy #$05
    lda ($40),y
    cmp #$88
    beq test_9
    jmp fail

; Test 9: Zero page Y (only for LDX/STX)
test_9:
    ldx #9
    stx $00
    lda #$99
    sta $50
    ldy #$05
    ldx $4B,y       ; Load from $50
    cpx #$99
    beq test_10
    jmp fail

; Test 10: Store chain - verify writes don't interfere
test_10:
    ldx #10
    stx $00
    lda #$A1
    sta $60
    lda #$A2
    sta $61
    lda #$A3
    sta $62
    lda #$A4
    sta $63
    ; Verify all values
    lda $60
    cmp #$A1
    bne fail
    lda $61
    cmp #$A2
    bne fail
    lda $62
    cmp #$A3
    bne fail
    lda $63
    cmp #$A4
    beq pass
    jmp fail

pass:
    jmp pass

fail:
    jmp fail
