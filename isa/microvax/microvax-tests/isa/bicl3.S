# Test BICL3 - Bit Clear Longword 3-operand
# result = src2 AND NOT src1

.text
    movli 0x0F, r0
    movli 0xFF, r1
    bicl3 r0, r1, r2
    movli 0xF0, r3
    cmpl r2, r3, r4
    beql r2, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
