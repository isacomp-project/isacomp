# Test SUBB3 - Subtract Byte 3-operand
# dst = src2 - src1 (byte)

.text
    movli 3, r0
    movli 10, r1
    subb3 r0, r1, r2
    movli 7, r3
    cmpl r2, r3, r4
    beql r2, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
