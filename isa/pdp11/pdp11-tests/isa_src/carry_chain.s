; PDP-11 Carry Chain Test
; Derived from vanheusden.com PDP-11 benchmark
; Tests ADD + ADC multi-word arithmetic pattern
; Scratch memory at 0x0400

.text
_start:
    mov #0x1000, r6

    ; Test 1: ADD + ADC, no carry
    mov #0x0400, r1
    mov #0, r0
    mov r0, (r1)
    mov r0, 2(r1)
    add #1, (r1)
    adc 2(r1)
    mov (r1), r0
    cmp #1, r0
    bne fail
    mov 2(r1), r0
    cmp #0, r0
    bne fail

    ; Test 2: ADD causing carry into next word
    mov #0x0400, r1
    mov #0xFFFF, r0
    mov r0, (r1)
    mov #0, r0
    mov r0, 2(r1)
    add #1, (r1)
    adc 2(r1)
    mov (r1), r0
    cmp #0, r0
    bne fail
    mov 2(r1), r0
    cmp #1, r0
    bne fail

    ; Test 3: Double carry (48-bit pattern from benchmark)
    mov #0x0400, r1
    mov #0xFFFF, r0
    mov r0, (r1)
    mov r0, 2(r1)
    mov #0, r0
    mov r0, 4(r1)
    add #1, (r1)
    adc 2(r1)
    adc 4(r1)
    mov (r1), r0
    cmp #0, r0
    bne fail
    mov 2(r1), r0
    cmp #0, r0
    bne fail
    mov 4(r1), r0
    cmp #1, r0
    bne fail

    ; Test 4: ADC register form
    mov #0xFFFF, r0
    add #1, r0
    mov #10, r1
    adc r1
    cmp #11, r1
    bne fail

    ; Test 5: SOB loop with carry chain (from benchmark)
    mov #0x0400, r1
    mov #0, r0
    mov r0, (r1)
    mov r0, 2(r1)
    mov #5, r5
inc_loop:
    add #1, (r1)
    adc 2(r1)
    sob r5, inc_loop
    mov (r1), r0
    cmp #5, r0
    bne fail

pass:
    br pass

fail:
    br fail
