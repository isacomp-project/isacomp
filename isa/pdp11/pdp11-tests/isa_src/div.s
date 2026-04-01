; PDP-11 DIV Instruction Test
; Tests DIV (divide) EIS instruction
; DIV src, Rn: R[n] = R[n]R[n+1] / src, R[n+1] = remainder

.text
_start:
    ; Test 1: Simple divide
    mov #0, r0          ; dividend high
    mov #12, r1         ; dividend low = 12
    mov #4, r2          ; divisor
    div r2, r0          ; 12 / 4 = 3 remainder 0
    cmp #3, r0          ; quotient
    bne fail
    cmp #0, r1          ; remainder
    bne fail

    ; Test 2: Divide with remainder
    mov #0, r0
    mov #13, r1         ; 13
    mov #4, r2          ; 4
    div r2, r0          ; 13 / 4 = 3 remainder 1
    cmp #3, r0
    bne fail
    cmp #1, r1
    bne fail

    ; Test 3: Divide by one
    mov #0, r0
    mov #100, r1
    mov #1, r2
    div r2, r0          ; 100 / 1 = 100 remainder 0
    cmp #100, r0
    bne fail
    cmp #0, r1
    bne fail

    ; Test 4: Zero dividend
    mov #0, r0
    mov #0, r1
    mov #5, r2
    div r2, r0          ; 0 / 5 = 0 remainder 0
    cmp #0, r0
    bne fail
    cmp #0, r1
    bne fail

    ; Test 5: Larger dividend (32-bit)
    mov #1, r0          ; high word = 1
    mov #0, r1          ; low word = 0, dividend = 0x10000 = 65536
    mov #0x100, r2      ; divisor = 256
    div r2, r0          ; 65536 / 256 = 256 remainder 0
    cmp #0x100, r0      ; quotient = 256
    bne fail
    cmp #0, r1          ; remainder = 0
    bne fail

pass:
    br pass

fail:
    br fail
