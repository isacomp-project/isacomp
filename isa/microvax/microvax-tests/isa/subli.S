.text
.globl _start

_start:
    movli 20, r0
    subli 5, r0
    movli 15, r1
    bneq r0, r1, fail

    movli 100, r0
    subli 100, r0
    movli 0, r1
    bneq r0, r1, fail

    movli 50, r0
    subli 10, r0
    subli 15, r0
    movli 25, r1
    bneq r0, r1, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
