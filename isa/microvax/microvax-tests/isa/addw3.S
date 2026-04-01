# Test ADDW3 - Add Word 3-operand
# Only affects low 16 bits, preserves upper bits

.text
    movli 0x0100, r0
    movli 0x0050, r1
    addw3 r0, r1, r2
    movli 0x0150, r3
    cmpl r2, r3, r4
    beql r2, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
