.text
.globl _start

_start:
    movli 0x500, sp

    movli 0x1234, r0
    pushl r0

    movli 0, r1
    popl r1
    bneq r0, r1, fail

    movli 0xABCD, r2
    movli 0x5678, r3
    pushl r2
    pushl r3

    popl r4
    bneq r4, r3, fail
    popl r5
    bneq r5, r2, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
