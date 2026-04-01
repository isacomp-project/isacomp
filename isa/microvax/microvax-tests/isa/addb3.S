# Test ADDB3 - Add Byte 3-operand
# Only affects low byte, preserves upper bits

.text
    movli 0xFF00FF05, r0
    movli 0x03, r1
    addb3 r0, r1, r2
    movli 0x08, r3
    cmpl r2, r3, r4
    beql r2, r3, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
