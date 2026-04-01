# Test CVTBL - Convert Byte to Longword (sign-extend)
# Takes byte and sign-extends to 32 bits

.text
    movli 0x80, r0
    cvtbl r0, r1
    movli 0xFFFFFF80, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
