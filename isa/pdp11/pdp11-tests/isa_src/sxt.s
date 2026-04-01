; PDP-11 SXT Instruction Test
; Tests SXT (sign extend) instruction
; Sets dst to 0 if N=0, or 0xFFFF if N=1

.text
_start:
    ; Test 1: SXT with N=0 (positive)
    mov #0x7FFF, r0
    tst r0              ; sets N=0
    sxt r1              ; r1 = 0
    bne fail

    ; Test 2: SXT with N=1 (negative)
    mov #0x8000, r0
    tst r0              ; sets N=1
    sxt r1              ; r1 = 0xFFFF
    cmp #0xFFFF, r1
    bne fail

    ; Test 3: SXT after positive result
    mov #1, r0
    mov #1, r1
    add r0, r1          ; result = 2, N=0
    sxt r2              ; r2 = 0
    bne fail

    ; Test 4: SXT after negative result
    mov #0, r0
    mov #0xFFFF, r1
    add r0, r1          ; result = -1, N=1
    sxt r2              ; r2 = 0xFFFF
    cmp #0xFFFF, r2
    bne fail

    ; Test 5: SXT to same register (with N=0)
    mov #1, r0
    tst r0
    sxt r0              ; r0 = 0
    bne fail

    ; Test 6: SXT to same register (with N=1)
    mov #0x8000, r0
    tst r0
    sxt r0              ; r0 = 0xFFFF
    cmp #0xFFFF, r0
    bne fail

pass:
    br pass

fail:
    br fail
