# Test BLEQU - Branch if Less Than or Equal Unsigned
# Tests unsigned comparison

.text
    movli 5, r0
    movli 10, r1
    blequ r0, r1, test2
    brb fail

test2:
    movli 5, r2
    blequ r0, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
