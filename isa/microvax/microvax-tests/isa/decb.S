# Test DECB - Decrement Byte
# Decrement low byte only

.text
    movli 5, r0
    decb r0
    movli 4, r1
    cmpl r0, r1, r2
    beql r0, r1, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
