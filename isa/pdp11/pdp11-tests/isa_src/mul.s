; PDP-11 MUL Instruction Test
; Tests MUL (multiply) EIS instruction
; MUL src, Rn: R[n]R[n+1] = R[n] * src

.text
_start:
    ; Test 1: Simple multiply
    mov #3, r0
    mov #4, r2
    mul r0, r2          ; r2:r3 = 4 * 3 = 12
    cmp #0, r2          ; high word = 0
    bne fail
    cmp #12, r3         ; low word = 12
    bne fail

    ; Test 2: Multiply by zero
    mov #0, r0
    mov #100, r2
    mul r0, r2          ; r2:r3 = 100 * 0 = 0
    bne fail            ; Z should be set

    ; Test 3: Multiply by one
    mov #1, r0
    mov #0x1234, r2
    mul r0, r2          ; r2:r3 = 0x1234 * 1 = 0x1234
    cmp #0, r2
    bne fail
    cmp #0x1234, r3
    bne fail

    ; Test 4: Larger multiply
    mov #100, r0
    mov #100, r2
    mul r0, r2          ; r2:r3 = 100 * 100 = 10000
    cmp #0, r2          ; high = 0
    bne fail
    cmp #10000, r3      ; low = 10000 (0x2710)
    bne fail

    ; Test 5: Multiply producing 32-bit result
    mov #0x100, r0      ; 256
    mov #0x100, r2      ; 256
    mul r0, r2          ; r2:r3 = 256 * 256 = 65536 = 0x10000
    cmp #1, r2          ; high = 1
    bne fail
    cmp #0, r3          ; low = 0
    bne fail

    ; Test 6: Negative multiply
    mov #0xFFFF, r0     ; -1
    mov #5, r2          ; 5
    mul r0, r2          ; r2:r3 = 5 * -1 = -5
    cmp #0xFFFF, r2     ; high = 0xFFFF (sign extension)
    bne fail
    cmp #0xFFFB, r3     ; low = -5
    bne fail

pass:
    br pass

fail:
    br fail
