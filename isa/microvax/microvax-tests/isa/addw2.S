# Test ADDW2 - Add Word 2-operand
# dst[15:0] = dst[15:0] + src[15:0]

.text
    movli 0x100, r0
    movli 0x50, r1
    addw2 r0, r1
    movli 0x150, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
