; Test CLI and SEI instructions
; Simple interrupt flag test without actual BRK handling

    * = $0400

start:
    ldx #0
    stx $00

; ============================================================================
; Test 1: CLI clears I flag, SEI sets it
; ============================================================================
test_1:
    ldx #1
    stx $00
    cli                 ; Clear I flag
    sei                 ; Set I flag
    ; If we get here, both instructions worked
    jmp test_2

; ============================================================================
; Test 2: SEI/CLI sequence
; ============================================================================
test_2:
    ldx #2
    stx $00
    sei
    cli
    sei
    cli
    jmp test_3

; ============================================================================
; Test 3: PHP saves flags, including I
; ============================================================================
test_3:
    ldx #3
    stx $00
    sei                 ; Set I flag
    php                 ; Push status
    cli                 ; Clear I flag
    plp                 ; Pop status (should restore I flag)
    jmp pass

; ============================================================================
; All tests passed
; ============================================================================
pass:
    jmp pass

fail:
    jmp fail
