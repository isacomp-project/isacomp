; PDP-11 Memory Operations Test
; Derived from vanheusden.com PDP-11 benchmark
; Tests memory read/write patterns used in the benchmark:
; - Direct memory writes via register deferred
; - Autoincrement/autodecrement for sequential memory access
; - Byte memory operations (MOVB through memory)
; - The hex output routine's memory access pattern
;
; Scratch memory at 0x0400 (accessed via register values)

.text
_start:
    mov #0x1000, r6        ; init SP

    ; ============================================================
    ; Test 1: Sequential word write via autoincrement
    ; ============================================================
    mov #0x0400, r2        ; buffer pointer
    mov #0x1111, r0
    mov r0, (r2)+          ; [0x0400] = 0x1111
    mov #0x2222, r0
    mov r0, (r2)+          ; [0x0402] = 0x2222
    mov #0x3333, r0
    mov r0, (r2)+          ; [0x0404] = 0x3333

    ; Verify
    mov #0x0400, r2
    mov (r2)+, r0
    cmp #0x1111, r0
    bne fail
    mov (r2)+, r0
    cmp #0x2222, r0
    bne fail
    mov (r2)+, r0
    cmp #0x3333, r0
    bne fail

    ; ============================================================
    ; Test 2: MOVB to memory via autoincrement
    ; (Matches benchmark: movb (R4),(R2)+ in hex output routine)
    ; ============================================================
    mov #0x0400, r2        ; destination buffer
    mov #0x41, r0          ; 'A'
    movb r0, (r2)+         ; write byte, advance by 1
    mov #0x42, r0          ; 'B'
    movb r0, (r2)+         ; write byte, advance by 1

    ; Read back and verify
    mov #0x0400, r3
    movb (r3)+, r0
    cmp #0x41, r0
    bne fail
    movb (r3)+, r0
    cmp #0x42, r0
    bne fail

    ; ============================================================
    ; Test 3: INC through memory pointer
    ; (Matches benchmark: inc (kw11l_counter))
    ; ============================================================
    mov #0x0400, r1
    mov #0, r0
    mov r0, (r1)           ; [0x0400] = 0

    inc (r1)
    inc (r1)
    inc (r1)
    inc (r1)
    inc (r1)

    mov (r1), r0
    cmp #5, r0
    bne fail

    ; ============================================================
    ; Test 4: MOV through register deferred (save/restore pattern)
    ; (Matches benchmark ISR: mov R0,(kw11l_temp) / mov (kw11l_temp),R0)
    ; ============================================================
    mov #0x0400, r3
    mov #0xDEAD, r0
    mov #0xBEEF, r1
    mov r0, (r3)           ; save R0
    mov r1, 2(r3)          ; save R1

    ; Modify registers
    mov #0, r0
    mov #0, r1

    ; Restore
    mov (r3), r0
    mov 2(r3), r1
    cmp #0xDEAD, r0
    bne fail
    cmp #0xBEEF, r1
    bne fail

    ; ============================================================
    ; Test 5: BIC pattern from benchmark (clear bits)
    ; (Matches benchmark: BIC #200, R1)
    ; ============================================================
    mov #0xFF, r0
    mov #0x80, r1
    bic r1, r0             ; r0 = 0xFF & ~0x80 = 0x7F
    cmp #0x7F, r0
    bne fail

    ; ============================================================
    ; Test 6: ADD to memory (from benchmark: add #1,(run_counter))
    ; ============================================================
    mov #0x0400, r1
    mov #100, r0
    mov r0, (r1)
    add #5, (r1)           ; [0x0400] = 105
    mov (r1), r0
    cmp #105, r0
    bne fail

pass:
    br pass

fail:
    br fail
