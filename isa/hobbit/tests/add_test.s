; AT&T Hobbit test: basic arithmetic
; Tests ADD, ADD3, SUB, MOV instructions
; Uses stack offsets R4 (accumulator), R8, R12, R16, R20

; Initialize values in the stack frame
    MOV   $5, R8          ; R8 = 5
    MOV   $3, R12         ; R12 = 3

; Test ADD: R12 = R12 + R8 = 3 + 5 = 8
    ADD   R8, R12         ; R12 should be 8

; Test ADD with immediate: R8 = R8 + 10 = 5 + 10 = 15
    ADD   $10, R8         ; R8 should be 15

; Test ADD3: Acc = R8 + R12 = 15 + 8 = 23
    ADD3  R8, R12         ; R4 (accumulator) should be 23

; Test MOV between stack locations
    MOV   R8, R16         ; R16 = R8 = 15
    MOV   R12, R20        ; R20 = R12 = 8

; Done - loop forever
done:
    NOP
    JMP   done
