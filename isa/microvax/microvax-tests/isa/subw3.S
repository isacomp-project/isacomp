# Test SUBW3 - Subtract Word 3-operand
# dst = src2 - src1 (word)

.text
    movli 0x50, r0
    movli 0x150, r1
    subw3 r0, r1, r2
    movli 0x100, r3
    cmpl r2, r3, r4
    beql r2, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
