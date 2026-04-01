; PDP-11 ASHC Instruction Test
; Derived from vanheusden.com PDP-11 benchmark
; Tests ASHC (Arithmetic Shift Combined) - shifts a 32-bit register pair
; ASHC src, Rn: shifts Rn:Rn|1 as a 32-bit value
;   Positive count = left shift, negative = right shift

.text
_start:
    ; ============================================================
    ; Test 1: ASHC left by 1
    ; R0:R1 = 0x0000:0x0001, shift left 1 -> 0x0000:0x0002
    ; ============================================================
    mov #0, r0
    mov #1, r1
    mov #1, r2             ; shift count
    ashc r2, r0            ; shift R0:R1 left by 1
    cmp #0, r0             ; high word still 0
    bne fail
    cmp #2, r1             ; low word = 2
    bne fail

    ; ============================================================
    ; Test 2: ASHC left crosses word boundary
    ; R0:R1 = 0x0000:0x8000, shift left 1 -> 0x0001:0x0000
    ; ============================================================
    mov #0, r0
    mov #0x8000, r1
    mov #1, r2
    ashc r2, r0
    cmp #1, r0             ; bit shifted into high word
    bne fail
    cmp #0, r1             ; low word = 0
    bne fail

    ; ============================================================
    ; Test 3: ASHC right by 1
    ; R0:R1 = 0x0000:0x0002, shift right 1 -> 0x0000:0x0001
    ; ============================================================
    mov #0, r0
    mov #2, r1
    mov #0xFFFF, r2        ; -1 = shift right 1
    ashc r2, r0
    cmp #0, r0
    bne fail
    cmp #1, r1
    bne fail

    ; ============================================================
    ; Test 4: ASHC right crosses word boundary
    ; R0:R1 = 0x0001:0x0000, shift right 1 -> 0x0000:0x8000
    ; ============================================================
    mov #1, r0
    mov #0, r1
    mov #0xFFFF, r2        ; -1
    ashc r2, r0
    cmp #0, r0
    bne fail
    cmp #0x8000, r1
    bne fail

    ; ============================================================
    ; Test 5: ASHC by 0 (no change)
    ; ============================================================
    mov #0x1234, r0
    mov #0x5678, r1
    mov #0, r2
    ashc r2, r0
    cmp #0x1234, r0
    bne fail
    cmp #0x5678, r1
    bne fail

    ; ============================================================
    ; Test 6: ASHC left by 4
    ; R0:R1 = 0x0000:0x00FF, left 4 -> 0x0000:0x0FF0
    ; ============================================================
    mov #0, r0
    mov #0x00FF, r1
    mov #4, r2
    ashc r2, r0
    cmp #0, r0
    bne fail
    cmp #0x0FF0, r1
    bne fail

    ; ============================================================
    ; Test 7: ASHC right preserves sign (arithmetic shift)
    ; R0:R1 = 0x8000:0x0000, right 1 -> 0xC000:0x0000
    ; ============================================================
    mov #0x8000, r0
    mov #0, r1
    mov #0xFFFF, r2        ; -1
    ashc r2, r0
    cmp #0xC000, r0        ; sign bit preserved and extended
    bne fail

pass:
    br pass

fail:
    br fail
