# Test MOVW - Move Word
# Copy low word from src to low word of dst

.text
    movli 0xABCD, r0
    clrl r1
    movw r0, r1
    movli 0xABCD, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
