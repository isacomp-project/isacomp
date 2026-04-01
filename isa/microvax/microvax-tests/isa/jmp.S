# Test JMP - Jump indirect through register
# PC = rf[target_reg]
# pass label is at address 16 (4 instructions * 4 bytes)

.text
    movli 16, r0
    jmp r0
    brb fail
    brb fail

pass:
    brb pass
fail:
    brb fail
