.text
.globl _start

_start:
    movli 20, r0
    movli 4, r1
    divl3 r1, r0, r2
    movli 5, r3
    bneq r2, r3, fail

    movli 100, r0
    movli 10, r1
    divl3 r1, r0, r2
    movli 10, r3
    bneq r2, r3, fail

    movli 7, r0
    movli 2, r1
    divl3 r1, r0, r2
    movli 3, r3
    bneq r2, r3, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
