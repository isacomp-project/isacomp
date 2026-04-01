; PDP-11 JMP Instruction Test
; Derived from vanheusden.com PDP-11 benchmark
; The benchmark uses JMP for loop back (jmp loop_) and skip (jmp after_my_routine)
; JMP sets PC to effective address of operand

.text
_start:
    ; ============================================================
    ; Test 1: JMP forward (absolute via label)
    ; ============================================================
    jmp t1_ok
    br fail                ; should be skipped
t1_ok:

    ; ============================================================
    ; Test 2: JMP backward
    ; ============================================================
    br t2_start
t2_target:
    br t2_ok               ; if we got here, JMP worked
t2_start:
    jmp t2_target
    br fail
t2_ok:

    ; ============================================================
    ; Test 3: JMP with register deferred
    ; ============================================================
    mov #t3_target, r0
    jmp (r0)
    br fail
t3_target:

    ; ============================================================
    ; Test 4: JMP in sequence (multiple jumps)
    ; Matches benchmark pattern: jmp start, jmp loop_, jmp after_my_routine
    ; ============================================================
    mov #0, r0
    jmp t4_a
    br fail
t4_a:
    inc r0
    jmp t4_b
    br fail
t4_b:
    inc r0
    jmp t4_c
    br fail
t4_c:
    cmp #2, r0
    bne fail

    ; ============================================================
    ; Test 5: JMP combined with JSR/RTS (subroutine call pattern)
    ; This matches the benchmark pattern:
    ;   jsr pc, my_routine
    ;   jmp after_my_routine
    ; my_routine: rts pc
    ; after_my_routine: ...
    ; ============================================================
    mov #0x1000, r6        ; init SP
    mov #0, r0
    jsr pc, t5_sub
    jmp t5_after
t5_sub:
    mov #1, r0
    rts pc
t5_after:
    cmp #1, r0
    bne fail

pass:
    br pass

fail:
    br fail
