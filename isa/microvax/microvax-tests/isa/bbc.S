# Test BBC - Branch on Bit Clear
# Branch if bit at position is clear

.text
    movli 0x0F, r0
    movli 4, r1
    bbc r1, r0, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
