; AT&T Hobbit: Interrupt handler skeleton
;
; When an interrupt occurs, the hardware pushes an event block
; onto the interrupt stack:
;   ISP-12: (unused, available for handler data)
;   ISP-8:  PC of interrupted instruction  (R8 wrt new ISP)
;   ISP-4:  PSW at time of interrupt       (R12 wrt new ISP)
;   ISP -= 16
;   PC = *(VB + 16 + 4*level)
;   PSW &= 0xFFFF0000  (kernel mode, ISP, no trace, interrupts masked)
;
; The handler returns with KRET, which:
;   Restores PC from ISP+8, PSW from ISP+12
;   ISP += 16

; ============================================================
; Vector table (would be at address pointed to by VB register)
; VB+0:   KCALL handler address
; VB+4:   Exception PC
; VB+8:   Niladic trap handler
; VB+12:  Unimplemented instruction handler
; VB+16:  NMI handler
; VB+20:  Interrupt level 1
; VB+24:  Interrupt level 2
; ...
; ============================================================

; Main program: simple loop that increments a counter
; Stack layout: R4=acc, R8=counter, R12=limit

main:
    MOV   $0, R8          ; counter = 0
    MOV   $-1, R12        ; limit = 0xFFFFFFFF (loop forever)

main_loop:
    ADD   $1, R8          ; counter++
    CMPGT R12, R8         ; flag = (limit > counter)?
    JMPTY main_loop       ; keep looping if counter < limit

    ; Should never reach here in normal operation
    NOP
    JMP   main_loop

; ============================================================
; Timer interrupt handler
; Increments a tick counter at a fixed memory location
; ============================================================
timer_handler:
    ; Hardware has already saved PC and PSW on interrupt stack
    ; We are now in kernel mode, using ISP

    ; In a real handler, we would:
    ; 1. Save any registers we need (via KCALL frame)
    ; 2. Do interrupt work
    ; 3. Return with KRET

    ; Simple handler: just return
    KRET                  ; restore PC and PSW from interrupt stack

; ============================================================
; KCALL handler (system call)
; The KCALL instruction saves:
;   ISP-4:  source operand (syscall number, in R4 wrt new ISP)
;   ISP-8:  return PC       (in R8 wrt new ISP)
;   ISP-12: PSW             (in R12 wrt new ISP)
; ============================================================
syscall_handler:
    ; R4 (wrt ISP) contains the syscall number
    ; Handle syscall based on number...

    ; For now, just return
    KRET                  ; restore PC and PSW
