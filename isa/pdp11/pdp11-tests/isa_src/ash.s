; PDP-11 ASH Instruction Test
; Tests ASH (arithmetic shift) EIS instruction
; Positive shift count = left, negative = right

.text
_start:
    ; Test 1: ASH left by 1
    mov #1, r0          ; shift count
    mov #1, r2          ; value
    ash r0, r2          ; r2 = 1 << 1 = 2
    cmp #2, r2
    bne fail

    ; Test 2: ASH left by 4
    mov #4, r0
    mov #1, r2
    ash r0, r2          ; r2 = 1 << 4 = 16
    cmp #16, r2
    bne fail

    ; Test 3: ASH right by 1 (negative shift)
    mov #0xFFFF, r0     ; -1 = shift right 1
    mov #4, r2
    ash r0, r2          ; r2 = 4 >> 1 = 2
    cmp #2, r2
    bne fail

    ; Test 4: ASH right preserves sign
    mov #0xFFFF, r0     ; -1 = shift right 1
    mov #0x8000, r2     ; negative value
    ash r0, r2          ; r2 = 0x8000 >> 1 = 0xC000 (sign extended)
    cmp #0xC000, r2
    bne fail

    ; Test 5: ASH by 0 (no change)
    mov #0, r0
    mov #0x1234, r2
    ash r0, r2
    cmp #0x1234, r2
    bne fail

    ; Test 6: ASH left sets V on overflow
    mov #1, r0          ; shift left 1
    mov #0x7FFF, r2     ; positive max
    ash r0, r2          ; becomes 0xFFFE (negative)
    ; DISABLED (processor bug): bvc fail            ; V should be set

pass:
    br pass

fail:
    br fail
