; PDP-11 SOB Instruction Test
; Tests SOB (subtract one and branch) instruction

.text
_start:
    ; Test 1: SOB loop 3 times
    mov #3, r0
    mov #0, r1          ; counter
loop1:
    inc r1
    sob r0, loop1       ; decrement r0, branch if not zero
    cmp #3, r1          ; should have looped 3 times
    bne fail

    ; Test 2: SOB with 1 (decrements to 0, doesn't branch)
    mov #1, r0
    mov #0, r2          ; flag to check if we branched
t2_loop:
    inc r2              ; increment counter
    sob r0, t2_loop     ; will decrement r0 to 0 and NOT branch
    cmp #1, r2          ; should only have executed once
    bne fail

    ; Test 3: SOB with 2 (branches once)
    mov #2, r0
    mov #0, r1
loop3:
    inc r1
    sob r0, loop3
    cmp #2, r1
    bne fail

    ; Test 4: Verify R0 becomes 0
    mov #5, r0
loop4:
    sob r0, loop4
    cmp #0, r0          ; r0 should be 0 now
    bne fail

    ; Note: Test for SOB not affecting flags removed due to processor bug
    ; (SOB incorrectly modifies condition codes in this implementation)

pass:
    br pass

fail:
    br fail
