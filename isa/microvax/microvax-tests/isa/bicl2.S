# Test BICL2 - Bit Clear Longword 2-operand
# dst = dst AND NOT src

.text
    movli 0xFF, r0
    movli 0x0F, r1
    bicl2 r1, r0
    movli 0xF0, r2
    cmpl r0, r2, r3
    beql r0, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
