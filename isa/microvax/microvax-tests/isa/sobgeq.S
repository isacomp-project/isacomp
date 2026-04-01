# Test SOBGEQ - Subtract One and Branch if Greater or Equal
# Decrement and branch if >= 0

.text
    movli 3, r0
    clrl r1
loop:
    incl r1
    sobgeq r0, loop

    movli 4, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
