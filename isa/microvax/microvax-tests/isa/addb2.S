# Test ADDB2 - Add Byte 2-operand
# dst[7:0] = dst[7:0] + src[7:0]

.text
    movli 5, r0
    movli 3, r1
    addb2 r0, r1
    movli 8, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
