# Test INCW - Increment Word
# Increment low word only

.text
    movli 0x100, r0
    incw r0
    movli 0x101, r1
    cmpl r0, r1, r2
    beql r0, r1, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
