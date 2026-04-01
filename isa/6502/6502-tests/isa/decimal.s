; Test Decimal (BCD) mode - SED, CLD instructions
; Tests ADC and SBC in decimal mode

    * = $0400

start:
    ldx #0
    stx $00
    cld                 ; Start in binary mode

; ============================================================================
; Test 1: CLD - verify binary mode addition
; ============================================================================
test_1:
    ldx #1
    stx $00
    cld                 ; Clear decimal mode
    clc
    lda #$09
    adc #$01
    cmp #$0A            ; Binary: $09 + $01 = $0A
    beq test_2
    jmp fail

; ============================================================================
; Test 2: SED - set decimal mode
; ============================================================================
test_2:
    ldx #2
    stx $00
    sed                 ; Set decimal mode
    clc
    lda #$09
    adc #$01
    cld                 ; Clear decimal mode before compare
    cmp #$10            ; BCD: 09 + 01 = 10 (decimal 10)
    beq test_3
    jmp fail

; ============================================================================
; Test 3: BCD addition with no carry
; ============================================================================
test_3:
    ldx #3
    stx $00
    sed
    clc
    lda #$15
    adc #$23            ; BCD: 15 + 23 = 38
    cld
    cmp #$38
    beq test_4
    jmp fail

; ============================================================================
; Test 4: BCD addition with carry (within digit)
; ============================================================================
test_4:
    ldx #4
    stx $00
    sed
    clc
    lda #$58
    adc #$27            ; BCD: 58 + 27 = 85
    cld
    cmp #$85
    beq test_5
    jmp fail

; ============================================================================
; Test 5: BCD addition with carry out
; ============================================================================
test_5:
    ldx #5
    stx $00
    sed
    clc
    lda #$90
    adc #$20            ; BCD: 90 + 20 = 110, carry set, result = 10
    cld
    bcs t5ok
    jmp fail
t5ok:
    cmp #$10
    beq test_6
    jmp fail

; ============================================================================
; Test 6: BCD - zero result
; ============================================================================
test_6:
    ldx #6
    stx $00
    sed
    clc
    lda #$00
    adc #$00            ; BCD: 00 + 00 = 00
    cld
    beq test_7
    jmp fail

; ============================================================================
; Test 7: BCD chain addition
; ============================================================================
test_7:
    ldx #7
    stx $00
    sed
    clc
    lda #$01
    adc #$01            ; 01 + 01 = 02
    adc #$01            ; 02 + 01 = 03
    adc #$01            ; 03 + 01 = 04
    cld
    cmp #$04
    beq pass
    jmp fail

; ============================================================================
; All tests passed
; ============================================================================
pass:
    jmp pass
fail:
    jmp fail
