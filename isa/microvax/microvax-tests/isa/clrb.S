# Test CLRB - Clear Byte
# Clear low byte only, preserve upper bits

.text
    movli 0xFF, r0
    clrb r0
    clrl r1
    cmpl r0, r1, r2
    beql r0, r1, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
