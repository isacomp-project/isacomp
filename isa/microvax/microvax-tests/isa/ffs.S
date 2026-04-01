# Test FFS - Find First Set bit
# Find position of first set bit

.text
    movli 0x10, r0
    ffs r0, r1
    movli 4, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
