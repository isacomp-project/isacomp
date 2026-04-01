; AT&T Hobbit test: logical and shift operations
; Tests AND, OR, XOR, SHL, SHR

    MOV   $15, R8         ; R8 = 0x0F (00001111)
    MOV   $-1, R12        ; R12 = 0xFFFFFFFF (all ones)

; Test AND: R12 = R12 & R8 = 0x0000000F
    AND   R8, R12         ; R12 should be 0x0F

; Test OR three-parcel: use OR with larger offsets
    MOV   $0, R16         ; R16 = 0
    OR    R8, R16         ; R16 = 0 | 0x0F = 0x0F

; Test XOR
    MOV   $-1, R20        ; R20 = 0xFFFFFFFF
    XOR   R8, R20         ; R20 = 0xFFFFFFFF ^ 0x0F = 0xFFFFFFF0

; Test SHL3: Acc = R8 << 4 = 0x0F << 4 = 0xF0
    SHL3  $4, R8          ; R4 = 0xF0

; Test SHR3: Acc = R20 >>> 4 (arithmetic) = 0xFFFFFFF0 >>> 4 = 0xFFFFFFFF
    SHR3  $4, R20         ; R4 = 0xFFFFFFFF (sign extended)

done:
    NOP
    JMP   done
