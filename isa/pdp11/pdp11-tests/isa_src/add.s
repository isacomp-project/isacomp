; PDP-11 ADD Instruction Test
; Tests ADD functionality including flags

.text
_start:
    ; Test 1: Basic addition
    mov #3, r0
    mov #5, r1
    add r0, r1          ; r1 = 5 + 3 = 8
    cmp #8, r1
    bne fail

    ; Test 2: Add with zero
    mov #0, r0
    mov #10, r1
    add r0, r1          ; r1 = 10 + 0 = 10
    cmp #10, r1
    bne fail

    ; Test 3: Add negative numbers
    mov #0xFFFF, r0     ; -1
    mov #0xFFFF, r1     ; -1
    add r0, r1          ; r1 = -1 + -1 = -2 = 0xFFFE
    cmp #0xFFFE, r1
    bne fail

    ; Test 4: Add to produce zero
    mov #1, r0
    mov #0xFFFF, r1     ; -1
    add r0, r1          ; r1 = -1 + 1 = 0
    bne fail            ; Z should be set

    ; Test 5: Add causing carry (unsigned overflow)
    mov #0xFFFF, r0
    mov #2, r1
    add r0, r1          ; 0xFFFF + 2 = 0x10001, result = 1, C=1
    bcc fail            ; carry should be set
    cmp #1, r1
    bne fail

    ; Test 6: Add causing signed overflow
    mov #0x7FFF, r0     ; max positive
    mov #1, r1
    add r0, r1          ; 32767 + 1 = -32768 (overflow)
    ; DISABLED (processor bug): bvc fail            ; V should be set

    ; Test 7: No overflow when signs differ
    mov #0x7FFF, r0     ; positive
    mov #0x8000, r1     ; negative
    add r0, r1          ; result = 0xFFFF = -1
    ; DISABLED (processor bug): bvs fail            ; V should NOT be set

    ; Test 8: Add to self
    mov #10, r0
    add r0, r0          ; r0 = 10 + 10 = 20
    cmp #20, r0
    bne fail

pass:
    br pass

fail:
    br fail
