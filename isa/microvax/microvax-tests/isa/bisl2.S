# Test BISL2 - Bit Set (OR) Longword 2-operand
# dst = dst OR src

.text
    movli 0xF0, r0
    movli 0x0F, r1
    bisl2 r1, r0
    movli 0xFF, r2
    cmpl r0, r2, r3
    beql r0, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
