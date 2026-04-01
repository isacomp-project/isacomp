// Power ISA Timer - Time Base and Decrementer
// =============================================
// Implements:
// - Time Base (TB): 64-bit counter incrementing every clock cycle
// - Decrementer (DEC): 64-bit down-counter, generates IRQ when negative (bit 63 set)
//
// The testbench injects TB/DEC values into the CPU via hierarchical writes,
// and intercepts mtspr DEC to update dec_write_data/dec_write_enable.

module power_timer (
    input  logic        clk,
    input  logic        reset,

    // Time Base (read by testbench, injected into CPU)
    output logic [63:0] timebase,

    // Decrementer write from CPU (mtspr DEC)
    input  logic [63:0] dec_write_data,
    input  logic        dec_write_enable,

    // Decrementer value (read by testbench, injected into CPU)
    output logic [63:0] dec_value,

    // Decrementer interrupt
    output logic        dec_irq,

    // IRQ enable (from testbench)
    input  logic        irq_enable
);

    // Time Base: free-running 64-bit counter
    always_ff @(posedge clk) begin
        if (reset)
            timebase <= 64'd0;
        else
            timebase <= timebase + 64'd1;
    end

    // Decrementer: counts down each cycle, writable via mtspr DEC
    // On Power ISA, DEC is a 32-bit decrementing counter that generates
    // an interrupt when it transitions from 0 to -1 (bit 63 set in 64-bit mode).
    // Linux writes DEC with a positive value; when it reaches 0 and goes
    // negative, the decrementer exception fires.
    always_ff @(posedge clk) begin
        if (reset)
            dec_value <= 64'hFFFFFFFFFFFFFFFF;  // Start with large positive-ish to avoid early IRQ
        else if (dec_write_enable)
            dec_value <= dec_write_data;
        else
            dec_value <= dec_value - 64'd1;
    end

    // Decrementer IRQ: fires when DEC is negative (bit 63 set) and IRQ enabled
    // This is level-sensitive: stays asserted as long as DEC is negative.
    // The kernel clears it by writing a new positive value to DEC.
    assign dec_irq = dec_value[63] & irq_enable;

endmodule
