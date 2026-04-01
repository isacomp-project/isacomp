# Test CVTWL - Convert Word to Longword (sign-extend)
# Sign-extend 16-bit to 32-bit

.text
    movli 0x8000, r0
    cvtwl r0, r1
    movli 0xFFFF8000, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
