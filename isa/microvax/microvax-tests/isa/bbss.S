# Test BBSS - Branch on Bit Set and Set
# Test that we branch when bit is set, and bit remains set

.text
    movli 0x10, r0
    movli 4, r1
    bbss r1, r0, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
