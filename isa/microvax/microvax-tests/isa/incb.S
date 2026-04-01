# Test INCB - Increment Byte
# Increment low byte only, wraps at 0xFF

.text
    movli 5, r0
    incb r0
    movli 6, r1
    cmpl r0, r1, r2
    beql r0, r1, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
