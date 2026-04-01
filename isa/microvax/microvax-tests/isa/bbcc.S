# Test BBCC - Branch on Bit Clear and Clear
# Test that we branch when bit is clear, and bit gets cleared
# r0 = 0x0F (bits 0-3 set, bit 4 clear)
# r1 = 4 (test bit 4)
# Since bit 4 is clear, we should branch to pass

.text
    movli 0x0F, r0
    movli 4, r1
    bbcc r1, r0, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
