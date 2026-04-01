#!/usr/bin/env python3
"""Simple 65C02 assembler for test program."""

# Start address
ORG = 0x0400

# Machine code for the test program
# Hand-assembled from test_65c02_instructions.asm
code = bytes([
    # start:
    # Test INC A (0x1A)
    0xA9, 0x7F,         # 0400: LDA #$7F
    0x1A,               # 0402: INC (A)
    0x30, 0x03,         # 0403: BMI test_inc_ok (+3)
    0x4C, 0x63, 0x34,   # 0405: JMP $3463 (fail)
    # test_inc_ok:
    0xC9, 0x80,         # 0408: CMP #$80
    0xF0, 0x03,         # 040A: BEQ test_dec (+3)
    0x4C, 0x63, 0x34,   # 040C: JMP $3463 (fail)

    # test_dec:
    0xA9, 0x01,         # 040F: LDA #$01
    0x3A,               # 0411: DEC (A)
    0xF0, 0x03,         # 0412: BEQ test_dec_ok (+3)
    0x4C, 0x63, 0x34,   # 0414: JMP $3463 (fail)
    # test_dec_ok:

    # test_phx_plx:
    0xA2, 0x42,         # 0417: LDX #$42
    0xDA,               # 0419: PHX
    0xA2, 0x00,         # 041A: LDX #$00
    0xFA,               # 041C: PLX
    0xE0, 0x42,         # 041D: CPX #$42
    0xF0, 0x03,         # 041F: BEQ test_phy_ply (+3)
    0x4C, 0x63, 0x34,   # 0421: JMP $3463 (fail)

    # test_phy_ply:
    0xA0, 0x55,         # 0424: LDY #$55
    0x5A,               # 0426: PHY
    0xA0, 0x00,         # 0427: LDY #$00
    0x7A,               # 0429: PLY
    0xC0, 0x55,         # 042A: CPY #$55
    0xF0, 0x03,         # 042C: BEQ test_bra (+3)
    0x4C, 0x63, 0x34,   # 042E: JMP $3463 (fail)

    # test_bra:
    0x80, 0x03,         # 0431: BRA test_stz (+3)
    0x4C, 0x63, 0x34,   # 0433: JMP $3463 (fail) - unreachable

    # test_stz:
    0xA9, 0xFF,         # 0436: LDA #$FF
    0x85, 0x10,         # 0438: STA $10
    0x64, 0x10,         # 043A: STZ $10
    0xA5, 0x10,         # 043C: LDA $10
    0xF0, 0x03,         # 043E: BEQ test_bit_imm (+3)
    0x4C, 0x63, 0x34,   # 0440: JMP $3463 (fail)

    # test_bit_imm:
    0xA9, 0x0F,         # 0443: LDA #$0F
    0x89, 0xF0,         # 0445: BIT #$F0
    0xF0, 0x03,         # 0447: BEQ test_trb (+3)
    0x4C, 0x63, 0x34,   # 0449: JMP $3463 (fail)

    # test_trb:
    0xA9, 0xFF,         # 044C: LDA #$FF
    0x85, 0x20,         # 044E: STA $20
    0xA9, 0x0F,         # 0450: LDA #$0F
    0x14, 0x20,         # 0452: TRB $20
    0xA5, 0x20,         # 0454: LDA $20
    0xC9, 0xF0,         # 0456: CMP #$F0
    0xF0, 0x03,         # 0458: BEQ test_tsb (+3)
    0x4C, 0x63, 0x34,   # 045A: JMP $3463 (fail)

    # test_tsb:
    0xA9, 0x00,         # 045D: LDA #$00
    0x85, 0x30,         # 045F: STA $30
    0xA9, 0x55,         # 0461: LDA #$55
    0x04, 0x30,         # 0463: TSB $30
    0xA5, 0x30,         # 0465: LDA $30
    0xC9, 0x55,         # 0467: CMP #$55
    0xF0, 0x03,         # 0469: BEQ pass (+3)
    0x4C, 0x63, 0x34,   # 046B: JMP $3463 (fail)

    # pass:
    0x4C, 0x69, 0x34,   # 046E: JMP $3469 (pass)
])

# Create 64KB memory image
mem = bytearray(65536)

# Place code at ORG
for i, b in enumerate(code):
    mem[ORG + i] = b

# Write hex file
with open('imem.hex', 'w') as f:
    for b in mem:
        f.write(f'{b:02x}\n')

print(f"Assembled {len(code)} bytes at ${ORG:04X}")
print(f"Code ends at ${ORG + len(code) - 1:04X}")
print("Written to imem.hex")
