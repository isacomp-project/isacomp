# Test AOBLEQ - Add One and Branch if Less or Equal
# Increment index and branch if <= limit

.text
    movli 3, r0
    clrl r1
    clrl r2
loop:
    incl r2
    aobleq r0, r1, loop

    movli 4, r3
    cmpl r2, r3, r4
    beql r2, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
