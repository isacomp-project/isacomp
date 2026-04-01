; PDP-11 Addressing Modes Test
; Derived from vanheusden.com PDP-11 benchmark
; Tests addressing modes 0, 1, 2, 4, 6 used in the benchmark
; Scratch memory at 0x0400 (accessed via register values)

.text
_start:
    mov #0x1000, r6

    ; Test 1: Mode 0 - Register to Register
    mov #0x1234, r0
    mov r0, r1
    cmp #0x1234, r1
    bne fail

    ; Test 2: Mode 1 - Register Deferred store/load
    mov #0xABCD, r0
    mov #0x0400, r1
    mov r0, (r1)
    mov (r1), r2
    cmp #0xABCD, r2
    bne fail

    ; Test 3: Mode 2 - Autoincrement write
    mov #0x0400, r1
    mov #0x1111, r0
    mov r0, (r1)+
    cmp #0x0402, r1
    bne fail
    mov #0x0400, r3
    mov (r3), r4
    cmp #0x1111, r4
    bne fail

    ; Test 4: Mode 2 - Autoincrement read
    mov #0x0400, r1
    mov #0x2222, r0
    mov r0, (r1)
    mov #0x0400, r1
    mov (r1)+, r2
    cmp #0x2222, r2
    bne fail
    cmp #0x0402, r1
    bne fail

    ; Test 5: Mode 4 - Autodecrement
    mov #0x0404, r1
    mov #0x3333, r0
    mov r0, -(r1)
    cmp #0x0402, r1
    bne fail
    mov (r1), r2
    cmp #0x3333, r2
    bne fail

    ; Test 6: Double autodecrement (from benchmark)
    mov #0x0408, r1
    mov #0x4444, r0
    mov r0, -(r1)
    mov #0x5555, r0
    mov r0, -(r1)
    cmp #0x0404, r1
    bne fail
    mov (r1)+, r2
    cmp #0x5555, r2
    bne fail
    mov (r1), r2
    cmp #0x4444, r2
    bne fail

    ; Test 7: Mode 6 - Index mode write/read
    mov #0x0400, r1
    mov #0x6666, r0
    mov r0, (r1)
    mov #0x7777, r0
    mov r0, 2(r1)
    mov 2(r1), r2
    cmp #0x7777, r2
    bne fail
    mov (r1), r2
    cmp #0x6666, r2
    bne fail

    ; Test 8: INC through memory pointer (from benchmark)
    mov #0x0400, r1
    mov #10, r0
    mov r0, (r1)
    inc (r1)
    inc (r1)
    mov (r1), r2
    cmp #12, r2
    bne fail

pass:
    br pass

fail:
    br fail
