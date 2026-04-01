; PDP-11 Shift Instructions Test
; Tests ASL (arithmetic shift left) and ASR (arithmetic shift right)

.text
_start:
    ; Test 1: ASL (shift left)
    mov #1, r0
    asl r0              ; r0 = 2
    cmp #2, r0
    bne fail

    ; Test 2: ASL multiple bits
    mov #0x0055, r0
    asl r0              ; r0 = 0x00AA
    cmp #0x00AA, r0
    bne fail

    ; Test 3: ASL sets C from MSB
    mov #0x8000, r0
    asl r0              ; MSB=1 goes to C
    bcc fail            ; C should be set

    ; Test 4: ASL without carry
    mov #0x4000, r0
    asl r0              ; MSB=0 goes to C
    bcs fail            ; C should NOT be set

    ; Test 5: ASR (shift right arithmetic)
    mov #4, r0
    asr r0              ; r0 = 2
    cmp #2, r0
    bne fail

    ; Test 6: ASR preserves sign bit (negative)
    mov #0x8000, r0
    asr r0              ; r0 = 0xC000 (sign extended)
    cmp #0xC000, r0
    bne fail

    ; Test 7: ASR preserves sign bit (positive)
    mov #0x4000, r0
    asr r0              ; r0 = 0x2000
    cmp #0x2000, r0
    bne fail

    ; Test 8: ASR sets C from LSB
    mov #1, r0
    asr r0              ; LSB=1 goes to C
    bcc fail            ; C should be set

    ; Test 9: ASL zero stays zero
    mov #0, r0
    asl r0
    bne fail            ; Z should be set

pass:
    br pass

fail:
    br fail
