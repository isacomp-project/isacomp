.text
.globl _start

_start:
    movli 10, r0
    addli 5, r0
    movli 15, r1
    bneq r0, r1, fail

    movli 100, r0
    addli 200, r0
    movli 300, r1
    bneq r0, r1, fail

    movli 0, r0
    addli 42, r0
    movli 42, r1
    bneq r0, r1, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
