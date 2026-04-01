# Test CLRW - Clear Word
# Clear low word only

.text
    movli 0xFFFF, r0
    clrw r0
    clrl r1
    cmpl r0, r1, r2
    beql r0, r1, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
