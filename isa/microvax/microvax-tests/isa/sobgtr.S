.text
.globl _start

_start:
    movli 0, r1
    movli 5, r0
loop:
    incl r1
    sobgtr r0, loop

    movli 5, r2
    bneq r1, r2, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
