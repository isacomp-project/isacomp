# Test ASHL - Arithmetic Shift Left (register count)
# Shift by value in register

.text
    movli 2, r0
    movli 0x0F, r1
    ashl r0, r1, r2
    movli 0x3C, r3
    cmpl r2, r3, r4
    beql r2, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
