# Test MULL2 - Multiply Longword 2-operand
# dst = dst * src

.text
    movli 7, r0
    movli 6, r1
    mull2 r0, r1
    movli 42, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
