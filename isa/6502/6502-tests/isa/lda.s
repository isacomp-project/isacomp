; Test LDA (Load Accumulator) instruction - all addressing modes
; Tests: lda_imm, lda_zp, lda_zpx, lda_abs, lda_abx, lda_aby, lda_inx, lda_iny

    * = $0400

start:
    ldx #0
    stx $00             ; Test number in ZP $00

; ============================================================================
; Test 1: LDA immediate
; ============================================================================
test_1:
    ldx #1
    stx $00
    lda #$42            ; Load $42
    cmp #$42            ; Verify
    beq test_2
    jmp fail

; ============================================================================
; Test 2: LDA immediate - zero (tests Z flag)
; ============================================================================
test_2:
    ldx #2
    stx $00
    lda #$00            ; Load 0
    beq t2a             ; Z should be set
    jmp fail
t2a:
    cmp #$00
    beq test_3
    jmp fail

; ============================================================================
; Test 3: LDA immediate - negative (tests N flag)
; ============================================================================
test_3:
    ldx #3
    stx $00
    lda #$80            ; Load negative value
    bmi t3a             ; N should be set
    jmp fail
t3a:
    cmp #$80
    beq test_4
    jmp fail

; ============================================================================
; Test 4: LDA zero page
; ============================================================================
test_4:
    ldx #4
    stx $00
    lda #$55            ; Store test value
    sta $10
    lda #$00            ; Clear A
    lda $10             ; Load from ZP
    cmp #$55
    beq test_5
    jmp fail

; ============================================================================
; Test 5: LDA zero page,X
; ============================================================================
test_5:
    ldx #5
    stx $00
    lda #$AA
    sta $15             ; Store at $15
    lda #$00
    ldx #$05            ; X = 5
    lda $10,x           ; Load from $10+5 = $15
    cmp #$AA
    beq test_6
    jmp fail

; ============================================================================
; Test 6: LDA absolute
; ============================================================================
test_6:
    ldx #6
    stx $00
    lda #$33
    sta $0800           ; Store at absolute address
    lda #$00
    lda $0800           ; Load from absolute
    cmp #$33
    beq test_7
    jmp fail

; ============================================================================
; Test 7: LDA absolute,X
; ============================================================================
test_7:
    ldx #7
    stx $00
    lda #$77
    sta $0805           ; Store at $0805
    lda #$00
    ldx #$05
    lda $0800,x         ; Load from $0800+5
    cmp #$77
    beq test_8
    jmp fail

; ============================================================================
; Test 8: LDA absolute,Y
; ============================================================================
test_8:
    ldx #8
    stx $00
    lda #$88
    sta $080A           ; Store at $080A
    lda #$00
    ldy #$0A
    lda $0800,y         ; Load from $0800+$0A
    cmp #$88
    beq test_9
    jmp fail

; ============================================================================
; Test 9: LDA (indirect,X)
; ============================================================================
test_9:
    ldx #9
    stx $00
    ; Set up pointer at $20: points to $0900
    lda #$00
    sta $20             ; Low byte of pointer
    lda #$09
    sta $21             ; High byte of pointer
    ; Store test value at $0900
    lda #$99
    sta $0900
    ; Load via (ZP,X)
    lda #$00
    ldx #$00
    lda ($20,x)         ; Load from address at ($20+0)
    cmp #$99
    beq test_10
    jmp fail

; ============================================================================
; Test 10: LDA (indirect),Y
; ============================================================================
test_10:
    ldx #10
    stx $00
    ; Set up pointer at $30: points to $0A00
    lda #$00
    sta $30             ; Low byte
    lda #$0A
    sta $31             ; High byte
    ; Store test value at $0A05
    lda #$BB
    sta $0A05
    ; Load via (ZP),Y
    lda #$00
    ldy #$05
    lda ($30),y         ; Load from ($0A00)+5
    cmp #$BB
    beq test_11
    jmp fail

; ============================================================================
; Test 11: LDA - back to back loads (pipeline hazard test)
; ============================================================================
test_11:
    ldx #11
    stx $00
    lda #$11
    sta $40
    lda #$22
    sta $41
    lda $40             ; Load first value
    sta $42             ; Store it
    lda $41             ; Load second value immediately
    cmp #$22            ; Should be $22
    beq t11a
    jmp fail
t11a:
    lda $42             ; Verify first value was stored correctly
    cmp #$11
    beq test_12
    jmp fail

; ============================================================================
; Test 12: LDA - multiple sequential loads (pipeline stress)
; ============================================================================
test_12:
    ldx #12
    stx $00
    lda #$01
    sta $50
    lda #$02
    sta $51
    lda #$03
    sta $52
    lda #$04
    sta $53
    ; Now load them back in sequence
    lda $50
    cmp #$01
    beq t12a
    jmp fail
t12a:
    lda $51
    cmp #$02
    beq t12b
    jmp fail
t12b:
    lda $52
    cmp #$03
    beq t12c
    jmp fail
t12c:
    lda $53
    cmp #$04
    beq pass
    jmp fail

; ============================================================================
; Pass/Fail handlers - placed right after code
; ============================================================================
pass:
    jmp pass            ; Infinite loop at pass address

fail:
    jmp fail            ; Infinite loop at fail address
