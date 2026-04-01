# Test ROTL - Rotate Left
# Rotate 0x0F left by 4 should give 0xF0

.text
    movli 0x0F, r0
    movli 4, r1
    rotl r1, r0, r2
    movli 0xF0, r3
    cmpl r2, r3, r4
    beql r2, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
