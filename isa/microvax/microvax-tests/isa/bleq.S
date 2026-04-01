.text
.globl _start

_start:
    movli 5, r0
    movli 10, r1
    bleq r0, r1, test2
    brb fail

test2:
    movli 7, r0
    movli 7, r1
    bleq r0, r1, test3
    brb fail

test3:
    movli 15, r0
    movli 8, r1
    bleq r0, r1, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
