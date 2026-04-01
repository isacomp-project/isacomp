.text
.globl _start

_start:
    movli 5, r0
    movli 3, r1
    addl2 r0, r1
    movli 8, r2
    bneq r1, r2, fail

    movli 0, r0
    movli 42, r1
    addl2 r0, r1
    movli 42, r2
    bneq r1, r2, fail

    movli 10, r0
    addl2 r0, r0
    movli 20, r2
    bneq r0, r2, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
