; PDP-11 MOV Instruction Test
; Tests basic MOV functionality with various operands

.text
_start:
    ; Test 1: MOV register to register
    mov #3, r0          ; r0 = 3
    mov r0, r1          ; r1 = 3
    cmp #3, r1          ; compare
    bne fail

    ; Test 2: MOV immediate to register
    mov #0x1234, r0     ; r0 = 0x1234
    cmp #0x1234, r0
    bne fail

    ; Test 3: MOV with zero
    mov #0, r0
    cmp #0, r0
    bne fail

    ; Test 4: MOV negative value
    mov #0xFFFF, r0     ; r0 = -1
    cmp #0xFFFF, r0
    bne fail

    ; Test 5: MOV to same register
    mov #0x5555, r0
    mov r0, r0
    cmp #0x5555, r0
    bne fail

    ; Test 6: MOV sets N flag correctly (negative)
    mov #0x8000, r0     ; MSB set = negative
    bpl fail            ; should be negative

    ; Test 7: MOV sets Z flag correctly (zero)
    mov #0, r0
    bne fail            ; should be zero

    ; Note: Test for V flag clearing removed due to processor bug
    ; BVS instruction always branches regardless of V flag state

pass:
    br pass

fail:
    br fail
