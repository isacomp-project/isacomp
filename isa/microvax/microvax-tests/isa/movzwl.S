# Test MOVZWL - Move Zero-extended Word to Longword
# Takes word and zero-extends to 32 bits

.text
    movli 0xFFFF, r0
    movzwl r0, r1
    movli 0xFFFF, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
