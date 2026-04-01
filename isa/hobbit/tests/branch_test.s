; AT&T Hobbit test: compare and branch
; Count down from 5 to 0 using CMPGT and JMPTY

; Initialize counter in R8
    MOV   $5, R8          ; R8 = 5 (counter)
    MOV   $0, R12         ; R12 = 0 (zero constant)
    MOV   $0, R16         ; R16 = 0 (accumulator for sum)

; Loop: add counter to sum, decrement counter
loop:
    ADD   R8, R16         ; sum += counter
    ADD   $-1, R8         ; counter--
    CMPGT R8, R12         ; flag = (R8 >s R12) = (counter > 0)?
    JMPTY loop            ; if flag, continue loop

; When done: R16 should contain 5+4+3+2+1 = 15
; R8 should be 0
done:
    NOP
    JMP   done
