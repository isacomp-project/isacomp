# Minimal test kernel for ISAComp Alpha64
# Entry: $16 = HWRPB PA (0x10000000), $30 = stack, pal_mode=0
# PC = 0xFFFFFC0001010000 (KSEG VA for PA 0x01010000)
# Tests: KSEG loads, KSEG stores, UART output

    .set noat
    .set noreorder

    .text
    .globl _start
    .ent _start
_start:

    # Build KSEG base in $2
    lda     $2, -1($31)             # $2 = 0xFFFFFFFFFFFFFFFF
    sll     $2, 42, $2              # $2 = 0xFFFFFC0000000000

    # Build UART PA (0x80020000) in $1, clear upper bits
    ldah    $1, -0x7FFE($31)        # $1 = 0xFFFFFFFF80020000
    zapnot  $1, 0x0F, $1            # $1 = 0x0000000080020000

    # KSEG UART VA
    bis     $2, $1, $1              # $1 = 0xFFFFFC0080020000

    # Write "ISAComp Alpha64 OK\n" to UART (one char at a time)
    lda     $3, 0x49($31)
    stq     $3, 0($1)              # 'I'
    lda     $3, 0x53($31)
    stq     $3, 0($1)              # 'S'
    lda     $3, 0x41($31)
    stq     $3, 0($1)              # 'A'
    lda     $3, 0x43($31)
    stq     $3, 0($1)              # 'C'
    lda     $3, 0x6F($31)
    stq     $3, 0($1)              # 'o'
    lda     $3, 0x6D($31)
    stq     $3, 0($1)              # 'm'
    lda     $3, 0x70($31)
    stq     $3, 0($1)              # 'p'
    lda     $3, 0x20($31)
    stq     $3, 0($1)              # ' '
    lda     $3, 0x41($31)
    stq     $3, 0($1)              # 'A'
    lda     $3, 0x6C($31)
    stq     $3, 0($1)              # 'l'
    lda     $3, 0x70($31)
    stq     $3, 0($1)              # 'p'
    lda     $3, 0x68($31)
    stq     $3, 0($1)              # 'h'
    lda     $3, 0x61($31)
    stq     $3, 0($1)              # 'a'
    lda     $3, 0x36($31)
    stq     $3, 0($1)              # '6'
    lda     $3, 0x34($31)
    stq     $3, 0($1)              # '4'
    lda     $3, 0x20($31)
    stq     $3, 0($1)              # ' '
    lda     $3, 0x4F($31)
    stq     $3, 0($1)              # 'O'
    lda     $3, 0x4B($31)
    stq     $3, 0($1)              # 'K'
    lda     $3, 0x0A($31)
    stq     $3, 0($1)              # '\n'

    # Read HWRPB magic via KSEG
    ldah    $4, 0x1000($31)         # $4 = 0x10000000
    bis     $2, $4, $4              # $4 = 0xFFFFFC0010000000
    ldq     $5, 8($4)               # $5 = HWRPB magic

    # Check low 32 bits = 0x50525748 ("HWRP")
    zapnot  $5, 0x0F, $6            # $6 = low 32 bits
    ldah    $7, 0x5052($31)
    lda     $7, 0x5748($7)          # $7 = 0x50525748
    zapnot  $7, 0x0F, $7
    cmpeq   $6, $7, $6
    beq     $6, hwrpb_fail

    # Print "HWRPB OK\n"
    lda     $3, 0x48($31)
    stq     $3, 0($1)
    lda     $3, 0x57($31)
    stq     $3, 0($1)
    lda     $3, 0x52($31)
    stq     $3, 0($1)
    lda     $3, 0x50($31)
    stq     $3, 0($1)
    lda     $3, 0x42($31)
    stq     $3, 0($1)
    lda     $3, 0x20($31)
    stq     $3, 0($1)
    lda     $3, 0x4F($31)
    stq     $3, 0($1)
    lda     $3, 0x4B($31)
    stq     $3, 0($1)
    lda     $3, 0x0A($31)
    stq     $3, 0($1)
    br      $31, done

hwrpb_fail:
    lda     $3, 0x46($31)
    stq     $3, 0($1)
    lda     $3, 0x41($31)
    stq     $3, 0($1)
    lda     $3, 0x49($31)
    stq     $3, 0($1)
    lda     $3, 0x4C($31)
    stq     $3, 0($1)
    lda     $3, 0x0A($31)
    stq     $3, 0($1)

done:
    call_pal 0x0000
1:  br      $31, 1b

    .end _start
