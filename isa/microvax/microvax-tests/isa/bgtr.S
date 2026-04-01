.text
.globl _start

_start:
    movli 10, r0
    movli 5, r1
    bgtr r0, r1, test2
    brb fail

test2:
    movli 3, r0
    movli 8, r1
    bgtr r0, r1, fail

    movli 7, r0
    movli 7, r1
    bgtr r0, r1, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
