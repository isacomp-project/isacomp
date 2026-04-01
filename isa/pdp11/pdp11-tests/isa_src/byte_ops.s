; PDP-11 Byte Operations Test
; Derived from vanheusden.com PDP-11 benchmark
; Tests byte-variant instructions from the benchmark's misc section
;
; Note: This design sign-extends byte results into the full word for
; all byte register operations (not just MOVB). Tests match that behavior.

.text
_start:
    ; Test 1: CLRB (byte result = 0x00, sign-ext = 0x0000)
    mov #0xFFFF, r0
    clrb r0
    cmp #0x0000, r0
    bne fail

    ; Test 2: INCB (byte result = 1, sign-ext = 0x0001)
    mov #0, r0
    incb r0
    cmp #1, r0
    bne fail

    ; Test 3: INCB wrap at byte boundary (0xFF+1 = 0x00, sign-ext = 0x0000)
    mov #0x00FF, r0
    incb r0
    cmp #0, r0
    bne fail

    ; Test 4: DECB (byte result = 1, sign-ext = 0x0001)
    mov #2, r0
    decb r0
    cmp #1, r0
    bne fail

    ; Test 5: NEGB (byte result = 0xFB = -5, sign-ext = 0xFFFB)
    mov #5, r0
    negb r0
    cmp #0xFFFB, r0
    bne fail

    ; Test 6: TSTB zero
    mov #0, r0
    tstb r0
    bne fail

    ; Test 7: TSTB negative byte
    mov #0x80, r0
    tstb r0
    bpl fail

    ; Test 8: COMB (byte result = 0xFF, sign-ext = 0xFFFF)
    mov #0, r0
    comb r0
    cmp #0xFFFF, r0
    bne fail

    ; Test 9: ASLB (byte result = 2, sign-ext = 0x0002)
    mov #1, r0
    aslb r0
    cmp #2, r0
    bne fail

    ; Test 10: ASRB (byte result = 2, sign-ext = 0x0002)
    mov #4, r0
    asrb r0
    cmp #2, r0
    bne fail

    ; Test 11: ASRB preserves byte sign (0x80>>1 = 0xC0, sign-ext = 0xFFC0)
    mov #0x80, r0
    asrb r0
    cmp #0xFFC0, r0
    bne fail

    ; Test 12: ROLB
    clc
    mov #1, r0
    rolb r0
    cmp #2, r0
    bne fail

    ; Test 13: RORB
    clc
    mov #2, r0
    rorb r0
    cmp #1, r0
    bne fail

    ; Test 14: BISB (byte result = 0xFF, sign-ext = 0xFFFF)
    mov #0x0F, r0
    mov #0xF0, r1
    bisb r0, r1
    cmp #0xFFFF, r1
    bne fail

    ; Test 15: BICB (byte result = 0xF0, sign-ext = 0xFFF0)
    mov #0x0F, r0
    mov #0xFF, r1
    bicb r0, r1
    cmp #0xFFF0, r1
    bne fail

    ; Test 16: BITB (Z flag) - does not modify destination
    mov #0x0F, r0
    mov #0xF0, r1
    bitb r0, r1
    bne fail

    ; Test 17: ADCB (byte result = 6, sign-ext = 0x0006)
    sec
    mov #5, r0
    adcb r0
    cmp #6, r0
    bne fail

pass:
    br pass

fail:
    br fail
