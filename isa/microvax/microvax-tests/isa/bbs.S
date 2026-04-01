# Test BBS - Branch on Bit Set
# Branch if bit at position is set

.text
    movli 0x10, r0
    movli 4, r1
    bbs r1, r0, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
