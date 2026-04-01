# Test DIVL2 - Divide Longword 2-operand
# dst = dst / src

.text
    movli 42, r0
    movli 6, r1
    divl2 r1, r0
    movli 7, r2
    cmpl r0, r2, r3
    beql r0, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
