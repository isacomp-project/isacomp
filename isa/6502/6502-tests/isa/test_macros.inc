; 6502 Test Macros for ISAComp
; Based on riscv-tests structure adapted for 6502 architecture
;
; Register usage:
;   A - Accumulator (result register for most tests)
;   X - Index register (used for test number tracking)
;   Y - Index register (used for loop counters, etc.)
;   $00 - Test number storage (zero page)
;   $01-$0F - Scratch space (zero page)
;   $10-$1F - Test data storage (zero page)

; ============================================================================
; Test Environment Setup
; ============================================================================

; Start address for tests (code begins here)
TEST_START = $0400

; Pass/fail addresses (monitored by testbench)
PASS_ADDR = $FF00
FAIL_ADDR = $FF10

; Zero page locations
TESTNUM = $00       ; Current test number
SCRATCH = $01       ; Scratch area starts here
TESTDATA = $10      ; Test data area

; ============================================================================
; Test Framework Macros (implemented as code patterns)
; ============================================================================

; Usage in test files:
;
; TEST_BEGIN:
;   .org TEST_START
;   ; Initialize
;   ldx #0          ; Clear test number
;   stx TESTNUM
;
; For each test:
;   ; Test N: description
;   inc TESTNUM     ; or: ldx #N / stx TESTNUM
;   ; ... test code ...
;   ; Compare result in A with expected
;   cmp #expected
;   bne fail
;
; TEST_END:
;   jmp pass
;
; pass:
;   .org PASS_ADDR
;   jmp pass
;
; fail:
;   .org FAIL_ADDR
;   jmp fail

; ============================================================================
; Common Test Patterns
; ============================================================================

; Pattern: TEST_IMM_OP
; Tests immediate mode operation
; Input: A = val1, operation with #val2
; Verify: result == expected
;
; Example:
;   lda #$10        ; Load first operand
;   clc             ; Clear carry for ADC
;   adc #$05        ; Add immediate
;   cmp #$15        ; Compare with expected
;   bne fail        ; Branch if not equal

; Pattern: TEST_ZP_OP
; Tests zero page mode operation
; Setup: Store val2 at zero page location
; Input: A = val1, operation with ZP address
;
; Example:
;   lda #$20        ; Store operand in ZP
;   sta $10
;   lda #$10        ; Load first operand
;   clc
;   adc $10         ; Add from ZP
;   cmp #$30        ; Compare with expected
;   bne fail

; Pattern: TEST_ABS_OP
; Tests absolute mode operation
; Similar to ZP but with 16-bit address

; Pattern: TEST_INDEXED_OP
; Tests indexed addressing modes (,X or ,Y)
;
; Example:
;   ldx #$02        ; Set index
;   lda data,x      ; Load from data+2
;   cmp #expected
;   bne fail

; Pattern: TEST_INDIRECT_OP
; Tests indirect addressing modes
;
; Example for ($ZP),Y:
;   lda #<data      ; Store pointer in ZP
;   sta $10
;   lda #>data
;   sta $11
;   ldy #$02        ; Set index
;   lda ($10),y     ; Load indirect indexed
;   cmp #expected
;   bne fail

; Pattern: TEST_BRANCH
; Tests conditional branch
;
; Example:
;   lda #$00        ; Set Z flag
;   beq branch_taken
;   jmp fail        ; Should not reach here
; branch_taken:
;   ; Continue...

; Pattern: TEST_FLAG
; Tests flag operations
;
; Example:
;   sec             ; Set carry
;   bcs carry_set
;   jmp fail
; carry_set:
;   clc             ; Clear carry
;   bcc carry_clear
;   jmp fail
; carry_clear:
;   ; Continue...

; ============================================================================
; NOP Insertion for Pipeline Testing
; ============================================================================

; These patterns insert NOPs between producer and consumer instructions
; to test pipeline forwarding/stalling at different distances

; 0 NOPs - back-to-back (tests bypass/forwarding)
; 1 NOP  - 1 cycle gap
; 2 NOPs - 2 cycle gap
; etc.

; For a 3-stage pipeline (F/D/XMW):
; - Producer in XMW, consumer in Decode = RAW hazard
; - 0 NOPs: immediate hazard (requires stall or bypass)
; - 1 NOP: hazard with 1 cycle gap
; - 2+ NOPs: no hazard (producer completes before consumer needs data)
