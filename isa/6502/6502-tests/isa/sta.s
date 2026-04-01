; Test STA (Store Accumulator) instruction - all addressing modes
; Tests: sta_zp, sta_zpx, sta_abs, sta_abx, sta_aby, sta_inx, sta_iny

    * = $0400

start:
    ldx #0
    stx $00             ; Test number

; ============================================================================
; Test 1: STA zero page
; ============================================================================
test_1:
    ldx #1
    stx $00
    lda #$42
    sta $10             ; Store to ZP
    lda #$00            ; Clear A
    lda $10             ; Load back
    cmp #$42
    beq _ok0
    jmp fail
_ok0:

; ============================================================================
; Test 2: STA zero page,X
; ============================================================================
test_2:
    ldx #2
    stx $00
    lda #$55
    ldx #$05
    sta $10,x           ; Store to $15
    lda #$00
    lda $15             ; Load back directly
    cmp #$55
    beq _ok1
    jmp fail
_ok1:

; ============================================================================
; Test 3: STA absolute
; ============================================================================
test_3:
    ldx #3
    stx $00
    lda #$AA
    sta $0500           ; Store to absolute
    lda #$00
    lda $0500           ; Load back
    cmp #$AA
    beq _ok2
    jmp fail
_ok2:

; ============================================================================
; Test 4: STA absolute,X
; ============================================================================
test_4:
    ldx #4
    stx $00
    lda #$BB
    ldx #$10
    sta $0500,x         ; Store to $0510
    lda #$00
    lda $0510           ; Load back directly
    cmp #$BB
    beq _ok3
    jmp fail
_ok3:

; ============================================================================
; Test 5: STA absolute,Y
; ============================================================================
test_5:
    ldx #5
    stx $00
    lda #$CC
    ldy #$20
    sta $0500,y         ; Store to $0520
    lda #$00
    lda $0520           ; Load back
    cmp #$CC
    beq _ok4
    jmp fail
_ok4:

; ============================================================================
; Test 6: STA (indirect,X)
; ============================================================================
test_6:
    ldx #6
    stx $00
    ; Set up pointer at $20: points to $0600
    lda #$00
    sta $20
    lda #$06
    sta $21
    ; Store via indirect
    lda #$DD
    ldx #$00
    sta ($20,x)         ; Store to ($0600)
    lda #$00
    lda $0600           ; Load back directly
    cmp #$DD
    beq _ok5
    jmp fail
_ok5:

; ============================================================================
; Test 7: STA (indirect),Y
; ============================================================================
test_7:
    ldx #7
    stx $00
    ; Set up pointer at $30: points to $0700
    lda #$00
    sta $30
    lda #$07
    sta $31
    ; Store via indirect indexed
    lda #$EE
    ldy #$05
    sta ($30),y         ; Store to $0705
    lda #$00
    lda $0705           ; Load back
    cmp #$EE
    beq _ok6
    jmp fail
_ok6:

; ============================================================================
; Test 8: STA - verify A unchanged
; ============================================================================
test_8:
    ldx #8
    stx $00
    lda #$77
    sta $40
    cmp #$77            ; A should still be $77
    beq _ok7
    jmp fail
_ok7:

; ============================================================================
; Test 9: STA - multiple stores (pipeline test)
; ============================================================================
test_9:
    ldx #9
    stx $00
    lda #$11
    sta $50
    sta $51
    sta $52
    sta $53
    ; Verify all locations
    lda $50
    cmp #$11
    beq _ok8
    jmp fail
_ok8:
    lda $51
    cmp #$11
    beq _ok9
    jmp fail
_ok9:
    lda $52
    cmp #$11
    beq _ok10
    jmp fail
_ok10:
    lda $53
    cmp #$11
    beq _ok11
    jmp fail
_ok11:

; ============================================================================
; Test 10: Store-load hazard test
; ============================================================================
test_10:
    ldx #10
    stx $00
    lda #$99
    sta $60             ; Store
    lda $60             ; Load immediately after (RAW hazard)
    cmp #$99
    beq _ok12
    jmp fail
_ok12:

; ============================================================================
; All tests passed
; ============================================================================
    jmp pass
pass:
    jmp pass
fail:
    jmp fail
