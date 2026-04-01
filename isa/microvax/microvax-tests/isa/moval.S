# Test MOVAL - Move Address of Longword
# Compute address and store in register

.text
    movli 0x100, r0
    moval r0, r1, 8
    movli 0x108, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
