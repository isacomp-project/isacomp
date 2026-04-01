; AT&T Hobbit test: procedure call and return
; Tests CALL, ENTER, RETURN, CATCH

; Main: set up a value, call a function, check result
    MOV   $7, R8          ; R8 = 7 (argument)
    MOV   $3, R12         ; R12 = 3 (argument)
    CALL  double_add      ; call double_add(7, 3)
    CATCH R32             ; refill stack cache after return
    ; R4 (acc) should now contain (7+3)*2 = 20
    MOV   R4, R16         ; save result in R16

done:
    NOP
    JMP   done

; Function: double_add
; Adds two arguments and doubles the result
; Arguments in caller's R8 and R12
; Result returned in accumulator (R4)
double_add:
    ENTER R-16            ; allocate 16-byte stack frame
    ; Caller's R8 is now at our R24 (SP went down by 16)
    ; Caller's R12 is now at our R28
    ; But for simplicity, just use immediate values
    ADD3  R8, R12         ; Acc = R8 + R12 (uses our frame's R8, R12)
    ; Note: in real code, would need to access caller frame
    ; For now just test the call/return mechanism
    ADD   R4, R4          ; double the accumulator: R4 = R4 + R4
    RETURN R16            ; deallocate frame and return
