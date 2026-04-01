; PDP-11 CMP Instruction Test
; CMP src, dst computes (src - dst) and sets flags
; Note: subtraction is src - dst, NOT dst - src!

.text
_start:
    ; Test 1: Compare equal values
    mov #5, r0
    mov #5, r1
    cmp r0, r1          ; r0 - r1 = 0, Z=1
    bne fail            ; Z should be set

    ; Test 2: Compare unequal values
    mov #3, r0
    mov #5, r1
    cmp r0, r1          ; r0 - r1 = -2, Z=0
    beq fail            ; Z should NOT be set

    ; Test 3: Verify dest not modified
    mov #10, r0
    mov #20, r1
    cmp r0, r1          ; flags set but r1 unchanged
    cmp #20, r1         ; r1 should still be 20
    bne fail

    ; Test 4: Source greater than dest (signed)
    ; r0=10, r1=5: cmp r0, r1 = 10 - 5 = 5 (positive)
    mov #10, r0
    mov #5, r1
    cmp r0, r1          ; N=0, V=0, so N^V=0
    blt fail            ; BLT branches if N^V=1, should NOT branch

    ; Test 5: Source less than dest (signed)
    ; r0=5, r1=10: cmp r0, r1 = 5 - 10 = -5 (negative)
    mov #5, r0
    mov #10, r1
    cmp r0, r1          ; N=1, V=0, so N^V=1
    bge fail            ; BGE branches if N^V=0, should NOT branch

    ; Test 6: Compare with zero result
    mov #0, r0
    mov #0, r1
    cmp r0, r1          ; 0 - 0 = 0
    bne fail            ; should be equal (Z=1)

    ; Test 7: Compare immediate
    mov #100, r0
    cmp #100, r0        ; 100 - 100 = 0
    bne fail

pass:
    br pass

fail:
    br fail
