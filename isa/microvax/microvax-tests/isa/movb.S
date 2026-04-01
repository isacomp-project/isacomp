# Test MOVB - Move Byte
# Copy low byte from src to low byte of dst

.text
    movli 0xAB, r0
    clrl r1
    movb r0, r1
    movli 0xAB, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
