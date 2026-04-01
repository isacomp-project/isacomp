; AT&T Hobbit: Loop from the 1987 CRISP Branch Folding paper
; (Ditzel & McLellan, "Branch Folding in the CRISP Microprocessor")
;
; Original C code (Figure 3):
;   main() {
;       int i, j, zeros, ones, sum;
;       j = ones = zeros = 0;
;       for (i = 0; i < 1024; i++) {
;           sum += i;
;           if (i & 1)
;               odd++;
;           else
;               even++;
;           j = sum;
;       }
;   }
;
; CRISP assembly from Table 3 (adapted to Hobbit assembler syntax):
; Stack layout: R4=acc, R8=sum, R12=i, R16=j, R20=odd, R24=even
;
; The paper showed the compiler generates:
;   add sum,i       -> ADD R12, R8
;   and3 i,1        -> AND3 $1, R12 (result in acc)
;   cmp.= Accum,0   -> CMPEQ $0, R4
;   ifTjmpy _5      -> JMPTY is_even (flag true = equal = even)
;   add odd,1        -> ADD $1, R20
;   jmp _6           -> JMP next
;   add even,1       -> ADD $1, R24
;   mov j,sum        -> MOV R8, R16
;   add i,1          -> ADD $1, R12
;   cmp.s< i,1024   -> (use CMPGT with reversed operands)
;   ifTjmpn _4      -> JMPTN loop (predict not taken)

; Initialize variables
    MOV   $0, R8          ; sum = 0
    MOV   $0, R12         ; i = 0
    MOV   $0, R16         ; j = 0
    MOV   $0, R20         ; odd = 0
    MOV   $0, R24         ; even = 0

loop:
    ; sum += i
    ADD   R12, R8         ; sum = sum + i

    ; acc = i & 1
    AND3  $1, R12         ; R4 = i & 1

    ; if (acc == 0) goto is_even
    CMPEQ $0, R4          ; flag = (0 == R4)?
    JMPTY is_even         ; if flag (i.e., i is even), jump

    ; odd++
    ADD   $1, R20
    JMP   next

is_even:
    ; even++
    ADD   $1, R24

next:
    ; j = sum
    MOV   R8, R16         ; j = sum

    ; i++
    ADD   $1, R12         ; i = i + 1

    ; if (i < 1024) goto loop
    ; We use CMPGT: flag = ($1024 >s i) = (1024 > i)
    ; Since 1024 doesn't fit in imm5, use three-parcel form
    CMPGT $1024, R12      ; flag = (1024 >s i)?
    JMPTN loop            ; if i < 1024, continue (predict not taken)

done:
    ; At this point:
    ;   R8  (sum)  = 0+1+2+...+1023 = 523776
    ;   R12 (i)    = 1024
    ;   R16 (j)    = 523776
    ;   R20 (odd)  = 512
    ;   R24 (even) = 512
    NOP
    JMP   done
