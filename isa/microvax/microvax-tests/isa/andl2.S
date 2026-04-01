# Test ANDL2 - AND Longword 2-operand
# dst = dst AND src

.text
    movli 0xFF, r0
    movli 0x0F, r1
    andl2 r1, r0
    movli 0x0F, r2
    cmpl r0, r2, r3
    beql r0, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
