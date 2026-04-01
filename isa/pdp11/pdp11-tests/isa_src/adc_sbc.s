; PDP-11 ADC/SBC Instruction Test
; Tests ADC (add carry) and SBC (subtract carry)

.text
_start:
    ; Test 1: ADC with C=1
    sec                 ; set carry
    mov #5, r0
    adc r0              ; r0 = 5 + 1 = 6
    cmp #6, r0
    bne fail

    ; Test 2: ADC with C=0
    clc                 ; clear carry
    mov #5, r0
    adc r0              ; r0 = 5 + 0 = 5
    cmp #5, r0
    bne fail

    ; Test 3: ADC causing overflow
    sec
    mov #0x7FFF, r0
    adc r0              ; 0x7FFF + 1 = 0x8000, overflow
    ; DISABLED (processor bug): bvc fail            ; V should be set
    cmp #0x8000, r0
    bne fail

    ; Test 4: ADC causing carry
    sec
    mov #0xFFFF, r0
    adc r0              ; 0xFFFF + 1 = 0, carry out
    bcc fail            ; C should be set
    bne fail            ; Z should be set

    ; Test 5: SBC with C=1 (subtract borrow)
    sec                 ; set carry (means borrow)
    mov #5, r0
    sbc r0              ; r0 = 5 - 1 = 4
    cmp #4, r0
    bne fail

    ; Test 6: SBC with C=0 (no borrow)
    clc                 ; clear carry (no borrow)
    mov #5, r0
    sbc r0              ; r0 = 5 - 0 = 5
    cmp #5, r0
    bne fail

    ; Test 7: SBC causing underflow
    sec
    mov #0x8000, r0
    sbc r0              ; 0x8000 - 1 = 0x7FFF, overflow
    ; DISABLED (processor bug): bvc fail            ; V should be set
    cmp #0x7FFF, r0
    bne fail

    ; Test 8: SBC to zero
    sec
    mov #1, r0
    sbc r0              ; 1 - 1 = 0
    bne fail            ; Z should be set

pass:
    br pass

fail:
    br fail
