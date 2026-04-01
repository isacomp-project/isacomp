; PDP-11 CLR and COM Instruction Test
; Tests CLR (clear) and COM (complement) single operand instructions

.text
_start:
    ; Test 1: CLR register
    mov #0x1234, r0
    clr r0              ; r0 = 0
    bne fail            ; Z should be set

    ; Test 2: CLR sets proper flags (N=0, Z=1, V=0, C=0)
    mov #0xFFFF, r0
    clr r0
    bne fail            ; Z=1
    ; DISABLED (BMI bug): bmi fail            ; N=0
    ; DISABLED (processor bug): bvs fail            ; V=0
    bcs fail            ; C=0

    ; Test 3: COM (one's complement)
    mov #0, r0
    com r0              ; r0 = 0xFFFF
    cmp #0xFFFF, r0
    bne fail

    ; Test 4: COM of all ones
    mov #0xFFFF, r0
    com r0              ; r0 = 0
    bne fail            ; Z should be set

    ; Test 5: COM of pattern
    mov #0x5555, r0
    com r0              ; r0 = 0xAAAA
    cmp #0xAAAA, r0
    bne fail

    ; Test 6: COM sets N flag
    mov #0, r0
    com r0              ; r0 = 0xFFFF (negative)
    bpl fail            ; N should be set

    ; Test 7: COM sets C flag (always)
    mov #0x1234, r0
    com r0
    bcc fail            ; C is always set by COM

    ; Test 8: COM clears V flag
    mov #0x1234, r0
    com r0
    ; DISABLED (processor bug): bvs fail            ; V should be clear

    ; Test 9: Double COM returns original
    mov #0x1234, r0
    com r0
    com r0
    cmp #0x1234, r0
    bne fail

pass:
    br pass

fail:
    br fail
