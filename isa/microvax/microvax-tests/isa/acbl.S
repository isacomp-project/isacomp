# Test ACBL - Add Compare and Branch Longword
# Loop from 0 to 5, adding 1 each iteration

.text
    movli 5, r0
    movli 0, r1
loop:
    incl r2
    acbl r0, r1, 1, loop

    movli 6, r3
    cmpl r1, r3, r4
    beql r1, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
