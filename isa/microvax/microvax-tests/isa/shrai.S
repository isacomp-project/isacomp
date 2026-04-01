# Test SHRAI - Shift Right Arithmetic Immediate
# Sign-extending right shift

.text
    movli 0xF0, r0
    shrai 4, r0, r1
    movli 0x0F, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
