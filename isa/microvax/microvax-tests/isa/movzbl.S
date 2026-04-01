# Test MOVZBL - Move Zero-extended Byte to Longword
# Takes byte and zero-extends to 32 bits

.text
    movli 0xFFFFFF80, r0
    movzbl r0, r1
    movli 0x80, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
