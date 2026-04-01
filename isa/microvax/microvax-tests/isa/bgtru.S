# Test BGTRU - Branch if Greater Than Unsigned
# Tests unsigned comparison where signed would give different result

.text
    movli 0xFFFFFFFF, r0
    movli 1, r1
    bgtru r0, r1, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
