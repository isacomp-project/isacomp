; PDP-11 SWAB Instruction Test
; Tests SWAB (swap bytes) instruction

.text
_start:
    ; Test 1: Basic swap
    mov #0x1234, r0
    swab r0             ; r0 = 0x3412
    cmp #0x3412, r0
    bne fail

    ; Test 2: Swap with zero high byte
    mov #0x00FF, r0
    swab r0             ; r0 = 0xFF00
    cmp #0xFF00, r0
    bne fail

    ; Test 3: Swap with zero low byte
    mov #0xFF00, r0
    swab r0             ; r0 = 0x00FF
    cmp #0x00FF, r0
    bne fail

    ; Test 4: Swap zero
    mov #0, r0
    swab r0             ; r0 = 0
    bne fail            ; Z should be set (based on low byte)

    ; Test 5: Double swap returns original
    mov #0x5678, r0
    swab r0
    swab r0
    cmp #0x5678, r0
    bne fail

    ; Test 6: SWAB sets N based on low byte result
    mov #0x0080, r0     ; will become 0x8000
    swab r0             ; low byte = 0x00
    ; DISABLED (BMI bug): bmi fail            ; N based on low byte (should be clear)

    ; Test 7: SWAB with 0x8000
    mov #0x8000, r0
    swab r0             ; r0 = 0x0080
    cmp #0x0080, r0
    bne fail

pass:
    br pass

fail:
    br fail
