.text
.globl _start

_start:
    movli 3, r0
    movli 10, r1
    subl2 r0, r1
    movli 7, r2
    bneq r1, r2, fail

    movli 0, r0
    movli 42, r1
    subl2 r0, r1
    movli 42, r2
    bneq r1, r2, fail

    movli 25, r0
    subl2 r0, r0
    movli 0, r2
    bneq r0, r2, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
