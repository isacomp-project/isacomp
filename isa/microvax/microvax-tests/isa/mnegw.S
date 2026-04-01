# Test MNEGW - Move Negated Word
# dst = -src (word), sign-extended to longword

.text
    movli 5, r0
    mnegw r0, r1
    movli 0xFFFFFFFB, r2
    cmpl r1, r2, r3
    beql r1, r2, pass
    brb fail

pass:
    brb pass
fail:
    brb fail
