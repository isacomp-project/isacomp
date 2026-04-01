; PDP-11 Benchmark Sequence Integration Test
; Derived from vanheusden.com PDP-11 benchmark
; Tests multi-instruction sequences from the benchmark's main loop

.text
_start:
    mov #0x1000, r6

    ; Seq 1: Register arithmetic sequence (from benchmark)
    mov #0123, r0
    add #0123, r0
    sub #0123, r0
    mov r0, r1
    cmp #0123, r1
    bne fail

    ; Seq 2: SP manipulation (from benchmark)
    mov r6, r1
    mov #0123, r6
    add #0123, r6
    sub #0123, r6
    cmp #0123, r6
    bne fail
    mov r1, r6

    ; Seq 3: ASH left and right (from benchmark)
    mov #0xFFFE, r0
    mov #0x0100, r2
    ash r0, r2
    cmp #0x0040, r2
    bne fail

    mov #1, r0
    mov #0x0100, r1
    ash r0, r1
    cmp #0x0200, r1
    bne fail

    ; Seq 4: MUL (from benchmark)
    mov #7, r0
    mov #3, r1
    mul r1, r0
    cmp #21, r1
    bne fail

    ; Seq 5: CMP + branch (from benchmark)
    mov #5, r0
    mov #10, r1
    cmp r0, r1
    beq fail

    mov #5, r0
    mov #5, r1
    cmp r0, r1
    bne fail

    ; Seq 6: Single-operand chain (from benchmark misc)
    clr r0
    bne fail
    inc r0
    cmp #1, r0
    bne fail
    dec r0
    bne fail
    mov #1, r0
    neg r0
    cmp #0xFFFF, r0
    bne fail
    com r0
    bne fail

    ; Seq 7: SWAB
    mov #0x1234, r0
    swab r0
    cmp #0x3412, r0
    bne fail

    ; Seq 8: XOR, BIS, BIC (from benchmark)
    mov #0xFF00, r0
    mov #0x0FF0, r2
    xor r0, r2
    cmp #0xF0F0, r2
    bne fail

    mov #0x00FF, r0
    bis #0xFF00, r0
    cmp #0xFFFF, r0
    bne fail

    mov #0xFFFF, r0
    bic #0x00FF, r0
    cmp #0xFF00, r0
    bne fail

    ; Seq 9: JSR/RTS + JMP (from benchmark)
    mov #0, r0
    jsr pc, my_sub
    jmp after_sub
my_sub:
    mov #42, r0
    rts pc
after_sub:
    cmp #42, r0
    bne fail

pass:
    br pass

fail:
    br fail
