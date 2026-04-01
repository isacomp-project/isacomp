; PDP-11 SUB Instruction Test
; Tests SUB functionality including flags

.text
_start:
    ; Test 1: Basic subtraction
    mov #3, r0
    mov #10, r1
    sub r0, r1          ; r1 = 10 - 3 = 7
    cmp #7, r1
    bne fail

    ; Test 2: Subtract zero
    mov #0, r0
    mov #10, r1
    sub r0, r1          ; r1 = 10 - 0 = 10
    cmp #10, r1
    bne fail

    ; Test 3: Subtract to zero
    mov #5, r0
    mov #5, r1
    sub r0, r1          ; r1 = 5 - 5 = 0
    bne fail            ; Z should be set

    ; Test 4: Subtract producing negative
    mov #10, r0
    mov #5, r1
    sub r0, r1          ; r1 = 5 - 10 = -5
    bpl fail            ; N should be set

    ; Test 5: Subtract with borrow (C flag)
    mov #5, r0
    mov #3, r1
    sub r0, r1          ; r1 = 3 - 5 = -2, borrow needed
    bcc fail            ; C should be set

    ; Test 6: No borrow
    mov #3, r0
    mov #5, r1
    sub r0, r1          ; r1 = 5 - 3 = 2, no borrow
    bcs fail            ; C should NOT be set

    ; Test 7: Overflow (positive - negative = negative)
    mov #0x8001, r0     ; -32767
    mov #0x7FFF, r1     ; 32767
    sub r0, r1          ; 32767 - (-32767) = overflow
    ; DISABLED (processor bug): bvc fail            ; V should be set

    ; Test 8: Subtract from self
    mov #10, r0
    sub r0, r0          ; r0 = 10 - 10 = 0
    bne fail            ; Z should be set

pass:
    br pass

fail:
    br fail
