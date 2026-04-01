`timescale 1ns/1ps
// Generic testbench for TDMI single-step testing with Verilator
// Reads inputs from hex files, runs one cycle, dumps outputs to stdout
// Supports banked registers for FIQ/IRQ/SVC/ABT/UND modes

`ifndef MEM_BASE
`define MEM_BASE 32'h00000000
`endif

module tb_generic;
    reg clk;
    reg reset;
    reg [31:0] init_pc;
    reg [31:0] init_cpsr;

    // Banked register reset values
    reg [31:0] init_rf_irq_sp;
    reg [31:0] init_rf_irq_lr;
    reg [31:0] init_rf_svc_sp;
    reg [31:0] init_rf_svc_lr;
    reg [31:0] init_rf_abt_sp;
    reg [31:0] init_rf_abt_lr;
    reg [31:0] init_rf_und_sp;
    reg [31:0] init_rf_und_lr;
    reg [31:0] init_spsr_fiq;
    reg [31:0] init_spsr_irq;
    reg [31:0] init_spsr_svc;
    reg [31:0] init_spsr_abt;
    reg [31:0] init_spsr_und;

    // Instantiate CPU with all reset ports
    tdmi cpu(
        .clk(clk),
        .reset(reset),
        .reset_cpsr(init_cpsr),
        .reset_pc_rd(init_pc),
        .reset_rf_irq_sp_rd(init_rf_irq_sp),
        .reset_rf_irq_lr_rd(init_rf_irq_lr),
        .reset_rf_svc_sp_rd(init_rf_svc_sp),
        .reset_rf_svc_lr_rd(init_rf_svc_lr),
        .reset_rf_abt_sp_rd(init_rf_abt_sp),
        .reset_rf_abt_lr_rd(init_rf_abt_lr),
        .reset_rf_und_sp_rd(init_rf_und_sp),
        .reset_rf_und_lr_rd(init_rf_und_lr),
        .reset_spsr_fiq_rd(init_spsr_fiq),
        .reset_spsr_irq_rd(init_spsr_irq),
        .reset_spsr_svc_rd(init_spsr_svc),
        .reset_spsr_abt_rd(init_spsr_abt),
        .reset_spsr_und_rd(init_spsr_und)
    );

    // Clock generation - start at 0, first edge at t=5
    initial clk = 0;
    always #5 clk = ~clk;

    // Init registers for reading from file
    reg [31:0] init_regs [0:17];  // 16 regs + PC + CPSR

    // Banked register init values (optional - read from banked.hex if present)
    reg [31:0] init_banked [0:31];  // Space for all banked registers

    initial begin
        // Initialize signals first
        reset = 0;
        init_pc = 0;
        init_cpsr = 0;
        init_rf_irq_sp = 0;
        init_rf_irq_lr = 0;
        init_rf_svc_sp = 0;
        init_rf_svc_lr = 0;
        init_rf_abt_sp = 0;
        init_rf_abt_lr = 0;
        init_rf_und_sp = 0;
        init_rf_und_lr = 0;
        init_spsr_fiq = 0;
        init_spsr_irq = 0;
        init_spsr_svc = 0;
        init_spsr_abt = 0;
        init_spsr_und = 0;

        // Initialize banked registers to 0
        for (integer i = 0; i < 32; i = i + 1) begin
            init_banked[i] = 32'h0;
        end

        // Wait for time > 0
        #1;

        // Read init values: rf.hex has 16 register values
        // init.hex has 2 values: PC, CPSR
        $readmemh("rf.hex", init_regs, 0, 15);
        $readmemh("init.hex", init_regs, 16, 17);

        // Try to read banked registers (optional file)
        // Format: rf_fiq[0-6], rf_irq_sp, rf_irq_lr, rf_svc_sp, rf_svc_lr,
        //         rf_abt_sp, rf_abt_lr, rf_und_sp, rf_und_lr,
        //         spsr_fiq, spsr_irq, spsr_svc, spsr_abt, spsr_und
        $readmemh("banked.hex", init_banked, 0, 19);

        init_pc = init_regs[16];
        init_cpsr = init_regs[17];

        // Set banked register reset values from hex file
        init_rf_irq_sp = init_banked[7];
        init_rf_irq_lr = init_banked[8];
        init_rf_svc_sp = init_banked[9];
        init_rf_svc_lr = init_banked[10];
        init_rf_abt_sp = init_banked[11];
        init_rf_abt_lr = init_banked[12];
        init_rf_und_sp = init_banked[13];
        init_rf_und_lr = init_banked[14];
        init_spsr_fiq = init_banked[15];
        init_spsr_irq = init_banked[16];
        init_spsr_svc = init_banked[17];
        init_spsr_abt = init_banked[18];
        init_spsr_und = init_banked[19];

        // Initialize register file directly
        cpu.rf[0] = init_regs[0];
        cpu.rf[1] = init_regs[1];
        cpu.rf[2] = init_regs[2];
        cpu.rf[3] = init_regs[3];
        cpu.rf[4] = init_regs[4];
        cpu.rf[5] = init_regs[5];
        cpu.rf[6] = init_regs[6];
        cpu.rf[7] = init_regs[7];
        cpu.rf[8] = init_regs[8];
        cpu.rf[9] = init_regs[9];
        cpu.rf[10] = init_regs[10];
        cpu.rf[11] = init_regs[11];
        cpu.rf[12] = init_regs[12];
        cpu.rf[13] = init_regs[13];
        cpu.rf[14] = init_regs[14];
        cpu.rf[15] = init_regs[15];

        // Initialize FIQ banked registers (R8_fiq - R14_fiq)
        cpu.rf_fiq[0] = init_banked[0];   // R8_fiq
        cpu.rf_fiq[1] = init_banked[1];   // R9_fiq
        cpu.rf_fiq[2] = init_banked[2];   // R10_fiq
        cpu.rf_fiq[3] = init_banked[3];   // R11_fiq
        cpu.rf_fiq[4] = init_banked[4];   // R12_fiq
        cpu.rf_fiq[5] = init_banked[5];   // R13_fiq (SP)
        cpu.rf_fiq[6] = init_banked[6];   // R14_fiq (LR)

        // Wait for a clock edge before applying reset
        @(posedge clk);

        // Apply reset pulse - CPSR and PC get loaded on this edge
        reset = 1;
        @(posedge clk);
        #1;
        reset = 0;

        // Execute one instruction
        @(posedge clk);
        #1;

        // Dump results in parseable format
        $display("RESULT_START");
        $display("R0=%08x", cpu.rf[0]);
        $display("R1=%08x", cpu.rf[1]);
        $display("R2=%08x", cpu.rf[2]);
        $display("R3=%08x", cpu.rf[3]);
        $display("R4=%08x", cpu.rf[4]);
        $display("R5=%08x", cpu.rf[5]);
        $display("R6=%08x", cpu.rf[6]);
        $display("R7=%08x", cpu.rf[7]);
        $display("R8=%08x", cpu.rf[8]);
        $display("R9=%08x", cpu.rf[9]);
        $display("R10=%08x", cpu.rf[10]);
        $display("R11=%08x", cpu.rf[11]);
        $display("R12=%08x", cpu.rf[12]);
        $display("R13=%08x", cpu.rf[13]);
        $display("R14=%08x", cpu.rf[14]);
        $display("R15=%08x", cpu.pc_rd + 32'd8);  // R15 reads as PC+8
        $display("CPSR=%08x", cpu.cpsr);
        $display("PC=%08x", cpu.pc_rd);

        // Dump banked registers
        $display("R8_fiq=%08x", cpu.rf_fiq[0]);
        $display("R9_fiq=%08x", cpu.rf_fiq[1]);
        $display("R10_fiq=%08x", cpu.rf_fiq[2]);
        $display("R11_fiq=%08x", cpu.rf_fiq[3]);
        $display("R12_fiq=%08x", cpu.rf_fiq[4]);
        $display("R13_fiq=%08x", cpu.rf_fiq[5]);
        $display("R14_fiq=%08x", cpu.rf_fiq[6]);
        $display("R13_irq=%08x", cpu.rf_irq_sp_rd);
        $display("R14_irq=%08x", cpu.rf_irq_lr_rd);
        $display("R13_svc=%08x", cpu.rf_svc_sp_rd);
        $display("R14_svc=%08x", cpu.rf_svc_lr_rd);
        $display("R13_abt=%08x", cpu.rf_abt_sp_rd);
        $display("R14_abt=%08x", cpu.rf_abt_lr_rd);
        $display("R13_und=%08x", cpu.rf_und_sp_rd);
        $display("R14_und=%08x", cpu.rf_und_lr_rd);

        // Dump SPSR registers
        $display("SPSR_fiq=%08x", cpu.spsr_fiq_rd);
        $display("SPSR_irq=%08x", cpu.spsr_irq_rd);
        $display("SPSR_svc=%08x", cpu.spsr_svc_rd);
        $display("SPSR_abt=%08x", cpu.spsr_abt_rd);
        $display("SPSR_und=%08x", cpu.spsr_und_rd);

        $display("RESULT_END");

        $finish;
    end

endmodule
