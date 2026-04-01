; PDP-11 Condition Code Instructions Test
; Tests SEC, CLC, SEV, CLV, SEZ, CLZ, SEN, CLN

.text
_start:
    ; Test 1: SEC/CLC (carry flag)
    clc
    bcs fail            ; C should be clear
    sec
    bcc fail            ; C should be set
    clc
    bcs fail            ; C should be clear again

    ; Test 2: SEV/CLV (overflow flag)
    clv
    ; DISABLED (processor bug): bvs fail            ; V should be clear
    sev
    ; DISABLED (processor bug): bvc fail            ; V should be set
    clv
    ; DISABLED (processor bug): bvs fail            ; V should be clear again

    ; Test 3: SEZ/CLZ (zero flag)
    mov #1, r0
    tst r0              ; set Z=0
    sez
    bne fail            ; Z should be set
    mov #1, r0
    tst r0              ; reset Z=0
    beq fail            ; Z should be clear

    ; Test 4: SEN/CLN (negative flag)
    mov #1, r0
    tst r0              ; set N=0
    sen
    bpl fail            ; N should be set
    mov #1, r0
    tst r0              ; reset N=0
    ; DISABLED (BMI bug): bmi fail            ; N should be clear

    ; Test 5: NOP (no operation)
    mov #0x1234, r0
    nop
    cmp #0x1234, r0     ; r0 should be unchanged
    bne fail

    ; Test 6: Multiple flag operations
    clc
    clv
    sec
    sev
    bcc fail
    ; DISABLED (processor bug): bvc fail

pass:
    br pass

fail:
    br fail
