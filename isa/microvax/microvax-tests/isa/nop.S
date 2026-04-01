# Test NOP - No Operation
# Just verify execution continues

.text
    movli 42, r0
    nop
    nop
    nop
    movli 42, r1
    cmpl r0, r1, r2
    beql r0, r1, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
