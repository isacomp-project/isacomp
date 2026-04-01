.text
.globl _start

_start:
    movli 0x400, r5

    movli 0x1234, r0
    stl r0, 0(r5)
    movli 0, r1
    ldl 0(r5), r1
    bneq r0, r1, fail

    movli 0xABCD, r2
    stl r2, 4(r5)
    ldl 4(r5), r3
    bneq r2, r3, fail

    ldl 0(r5), r4
    movli 0x1234, r6
    bneq r4, r6, fail

    brb pass

pass:
    brb pass

fail:
    brb fail
