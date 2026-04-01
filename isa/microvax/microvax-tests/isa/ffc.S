# Test FFC - Find First Clear bit
# Find position of first clear bit

.text
    movli 0x0F, r0
    ffc r0, r1
    movli 4, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
