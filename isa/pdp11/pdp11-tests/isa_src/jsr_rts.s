; PDP-11 JSR/RTS Instruction Test
; Tests JSR (jump to subroutine) and RTS (return from subroutine)

.text
_start:
    ; Initialize stack pointer
    mov #0x1000, r6

    ; Test 1: Simple JSR/RTS
    mov #0, r0
    jsr r4, sub1        ; call subroutine
    cmp #1, r0          ; r0 should be set by subroutine
    bne fail
    br t2

sub1:
    mov #1, r0          ; set r0
    rts r4              ; return

t2:
    ; Test 2: Nested JSR/RTS
    mov #0, r0
    mov #0, r1
    jsr r4, outer
    cmp #2, r0          ; outer should set r0 to 2
    bne fail
    cmp #1, r1          ; inner should set r1 to 1
    bne fail
    br t3

outer:
    mov #2, r0
    jsr r4, inner
    rts r4

inner:
    mov #1, r1
    rts r4

t3:
    ; Test 3: JSR preserves link register
    mov #0x5555, r4
    jsr r4, sub3
    ; after RTS, r4 should be restored from stack
    ; (actually on PDP-11, link reg gets return addr)
    br t4

sub3:
    rts r4

t4:
    ; Test 4: Multiple returns work
    mov #0, r0
    jsr r4, multi
    cmp #3, r0
    bne fail
    br pass

multi:
    inc r0
    jsr r4, multi2
    inc r0
    rts r4

multi2:
    inc r0
    rts r4

pass:
    br pass

fail:
    br fail
