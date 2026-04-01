# Test JSB/RSB - Jump to Subroutine / Return from Subroutine
# JSB pushes return address, RSB pops and returns

.text
    movli 0x1000, r14
    jsb subroutine
    movli 42, r2
    cmpl r0, r2, r3
    beql r0, r2, pass
    brb fail

subroutine:
    movli 42, r0
    rsb

pass:
    brb pass
fail:
    brb fail
