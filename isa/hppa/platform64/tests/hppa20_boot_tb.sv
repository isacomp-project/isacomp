// HPPA 2.0 (PA-RISC 2.0) Linux Boot Testbench
// Loads and boots Linux kernel in Verilator simulation
//
// Memory Map:
//   0x00000000 - 0x00000FFF: Page Zero (firmware interface)
//   0x00001000 - 0x000FFFFF: Boot stub / firmware
//   0x00100000 - 0x037FFFFF: Kernel image
//   0x03800000 - 0x03EFFFFF: Initrd
//   0x03F00000 - 0x03FFFFFF: Peripheral I/O
//     0x03F00000: NS16550A UART (word-aligned, reg-shift=2)
//
// PA-RISC is big-endian. The kernel entry point is at 0x00100000.
// The boot stub at 0x00001000 sets up minimal state and jumps to the kernel.
//
// umem is [63:0] (64-bit words), indexed by byte_addr >> 3.
// Within each 64-bit word (big-endian word order):
//   bits[63:32] = 32-bit word at byte address N*8     (addr[2]==0)
//   bits[31:0]  = 32-bit word at byte address N*8+4   (addr[2]==1)
// Big-endian byte ordering within each 32-bit half.

`timescale 1ns/1ps

module hppa20_boot_tb;
    // =========================================================================
    // Clock Generation (50MHz = 20ns period)
    // =========================================================================
    reg clk = 0;
    always #10 clk = ~clk;

    // =========================================================================
    // Constants - Memory Layout
    // =========================================================================
    localparam MEMORY_BASE     = 32'h00000000;
    localparam MEMORY_SIZE     = 32'h04000000;  // 64MB
    localparam PAGE_ZERO       = 32'h00000000;
    localparam BOOT_STUB_ADDR  = 32'h00001000;  // Boot stub at 4KB
    localparam KERNEL_LOAD     = 32'h00100000;  // Kernel at 1MB
    localparam INITRD_BASE     = 32'h03800000;  // Initrd at 56MB
    localparam FDT_ADDR        = 32'h00000800;  // FDT at 2KB in page zero area
    localparam PDC_STUB_ADDR   = 32'h0F000000;  // PDC firmware in ROM (outside 64MB RAM)
    localparam IODC_STUB_ADDR  = 32'h0F000400;  // IODC entry in ROM
    localparam PAGE_OFFSET     = 32'h10000000;  // Linux VA base for PA-RISC 32-bit

    // Peripheral addresses (NS16550A, reg-shift=2)
    localparam UART_BASE       = 32'h03F00000;
    localparam UART_THR        = 32'h03F00000;  // +0x00: TX/RX data
    localparam UART_IER        = 32'h03F00004;  // +0x04: Interrupt Enable
    localparam UART_IIR        = 32'h03F00008;  // +0x08: Interrupt Ident (read) / FCR (write)
    localparam UART_LCR        = 32'h03F0000C;  // +0x0C: Line Control
    localparam UART_MCR        = 32'h03F00010;  // +0x10: Modem Control
    localparam UART_LSR        = 32'h03F00014;  // +0x14: Line Status
    localparam UART_MSR        = 32'h03F00018;  // +0x18: Modem Status
    localparam UART_SCR        = 32'h03F0001C;  // +0x1C: Scratch

    // umem index base for UART (UART_BASE >> 3)
    localparam UART_UMEM_BASE  = UART_BASE >> 3;

    // UART register state for 8250 autodetect support
    reg [7:0] uart_ier = 8'h00;    // Interrupt Enable Register
    reg [7:0] uart_iir = 8'h01;    // Interrupt Ident: 0x01 = no interrupt, no FIFO
    reg [7:0] uart_lcr = 8'h00;    // Line Control Register
    reg [7:0] uart_mcr = 8'h00;    // Modem Control Register
    reg [7:0] uart_scr = 8'h00;    // Scratch Register
    reg        uart_fifo_en = 0;    // FIFO enabled flag

    // =========================================================================
    // External interrupt/timer inputs to CPU (driven as ports)
    // =========================================================================
    reg        timer_irq_pending_tb;
    reg [63:0] ext_irq_lines_tb;

    // CR16 write push output from CPU (ext isa_state push)
    wire [63:0] cr16_write_value;
    wire        cr16_write_valid;

    // EIRR (CR23) managed externally - testbench handles set/clear
    reg  [63:0] eirr_reg;
    wire [63:0] cr23_clear_value;
    wire        cr23_clear_valid;

    // =========================================================================
    // Reset and Entry Point
    // =========================================================================
    reg reset;
    integer reset_counter;
    reg [63:0] entry_point;
    integer max_cycles;

    // =========================================================================
    // HPPA 2.0 CPU Instance (64-bit ports)
    // =========================================================================
    hppa20 cpu (
        .clk(clk),
        .reset(reset),

        // Reset state - boot stub entry
        .reset_pc(entry_point),

        // PSW: privileged mode, interrupts disabled (all zeros = safe)
        .reset_psw(64'h00000000_00000000),

        // Privilege level: 0 = most privileged (kernel)
        .reset_priv_level_rd(2'b00),

        // Control registers (64-bit for PA-RISC 2.0)
        .reset_cr0_rd(64'h0),       // Recovery counter
        .reset_cr8_rd(64'h0),       // Protection ID 1
        .reset_cr9_rd(64'h0),       // Protection ID 2
        .reset_cr10_rd(64'h0),      // CCR
        .reset_cr11_rd(64'h0),      // SAR2 (PA-RISC 2.0)
        .reset_cr14_rd(64'h0),      // IVA (Linux installs its own)
        .reset_cr15_rd(64'h0),      // EIEM = 0 (all interrupts masked)
        .reset_cr17_rd(64'h0),      // IIASQ front = 0
        .reset_cr17_back(64'h0),    // IIASQ back = 0
        .reset_cr18_rd(64'h0),      // IIAOQ front
        .reset_cr18_back(64'h0),    // IIAOQ back
        .reset_cr19_rd(64'h0),      // IIR
        .reset_cr20_rd(64'h0),      // ISR
        .reset_cr21_rd(64'h0),      // IOR
        .reset_cr22_rd(64'h0),      // IPSW
        .reset_cr24_rd(64'h0),      // TR0
        .reset_cr25_rd(64'h0),      // TR1
        .reset_cr26_rd(64'h0),      // TR2
        .reset_cr27_rd(64'h0),      // TR3
        .reset_cr28_rd(64'h0),      // TR4
        .reset_cr29_rd(64'h0),      // TR5
        .reset_cr30_rd(64'h0),      // TR6 (current task)
        .reset_cr31_rd(64'h0),      // TR7

        // SAR (6-bit for PA-RISC 2.0)
        .reset_sar_rd(6'h0),

        // Space registers (all zero - flat address space)
        .reset_sr0_rd(64'h0),
        .reset_sr1_rd(64'h0),
        .reset_sr2_rd(64'h0),
        .reset_sr3_rd(64'h0),
        .reset_sr4_rd(64'h0),
        .reset_sr5_rd(64'h0),
        .reset_sr6_rd(64'h0),
        .reset_sr7_rd(64'h0),

        // TLB staging and replacement state (52-bit VPN/PPN for PA-RISC 2.0)
        .reset_dtlb_ins_pending_rd(1'b0),
        .reset_dtlb_ins_ppn(52'h0),
        .reset_dtlb_ins_space(64'h0),
        .reset_dtlb_ins_vpn(52'h0),
        .reset_dtlb_next_rd(4'h0),
        .reset_itlb_ins_pending_rd(1'b0),
        .reset_itlb_ins_ppn(52'h0),
        .reset_itlb_ins_space(64'h0),
        .reset_itlb_ins_vpn(52'h0),
        .reset_itlb_next_rd(4'h0),

        // FP status
        .reset_fpsr_rd(64'h0),

        // Shadow registers (PA-RISC 2.0 interruption shadows, 64-bit)
        .reset_shadow_r1(64'h0),
        .reset_shadow_r8(64'h0),
        .reset_shadow_r9(64'h0),
        .reset_shadow_r16(64'h0),
        .reset_shadow_r17(64'h0),
        .reset_shadow_r24(64'h0),
        .reset_shadow_r25(64'h0),

        // Delay slot / branch state
        .reset_delay_slot(1'b0),
        .reset_branch_target_rd(64'h0),
        .reset_branch_target_space_rd(64'h0),
        .reset_code_iasq(64'h0),

        // CR16 free-running cycle counter (ext isa_state - driven from testbench)
        .cr16_rd(timer_counter),
        .cr16_wr(timer_counter),

        // External interrupt inputs (driven from testbench)
        .timer_irq_pending_rd(timer_irq_pending_tb),
        .timer_irq_pending_wr(timer_irq_pending_tb),
        .ext_irq_lines_rd(ext_irq_lines_tb),
        .ext_irq_lines_wr(ext_irq_lines_tb),

        // EIRR (CR23) - externally managed (ext isa_state)
        .cr23_rd(eirr_reg),
        .cr23_wr(eirr_reg),

        // CR16 write push output (CPU -> testbench for timer compare)
        .cr16_write_wr(cr16_write_value),
        .cr16_write_wr_valid(cr16_write_valid),

        // CR23 clear push output (CPU -> testbench for EIRR write-one-to-clear)
        .cr23_clear_wr(cr23_clear_value),
        .cr23_clear_wr_valid(cr23_clear_valid)
    );

    // =========================================================================
    // Memory access helpers (tasks for 32-bit writes to 64-bit umem)
    // PA-RISC big-endian: addr[2]==0 -> upper [63:32], addr[2]==1 -> lower [31:0]
    // =========================================================================
    task write_mem32(input [31:0] addr, input [31:0] data);
        if (addr[2] == 1'b0)
            cpu.umem[addr[31:3]][63:32] = data;
        else
            cpu.umem[addr[31:3]][31:0] = data;
    endtask

    function automatic [31:0] read_mem32(input [31:0] addr);
        if (addr[2] == 1'b0)
            return cpu.umem[addr[31:3]][63:32];
        else
            return cpu.umem[addr[31:3]][31:0];
    endfunction

    // =========================================================================
    // Free-Running Timer Counter (CR16 is ext isa_state - driven via ports)
    // 64-bit for PA-RISC 2.0
    // =========================================================================
    reg [63:0] timer_counter;
    reg [63:0] itmr_compare;
    reg        itmr_armed;

    always @(posedge clk) begin
        if (reset) begin
            timer_counter        <= 64'h0;
            itmr_compare         <= 64'hFFFFFFFF_FFFFFFFF;
            itmr_armed           <= 1'b0;
            timer_irq_pending_tb <= 1'b0;
            ext_irq_lines_tb     <= 64'h0;
            eirr_reg             <= 64'h0;
        end else begin
            timer_counter        <= timer_counter + 1;
            timer_irq_pending_tb <= 1'b0;   // default: clear each cycle

            // EIRR write-one-to-clear from CPU (MTCTL to CR23 pushes clear mask)
            if (cr23_clear_valid)
                eirr_reg <= eirr_reg & ~cr23_clear_value;

            // Arm timer when CPU writes CR16 via MTCTL (push port)
            if (cr16_write_valid) begin
                itmr_compare <= cr16_write_value;
                itmr_armed   <= 1'b1;
                $display("[%0d] TIMER_ARM: compare=%016x counter=%016x delta=%0d PC=%016x",
                         cycle_count, cr16_write_value, timer_counter,
                         cr16_write_value - timer_counter, cpu.pc_rd);
            end

            // Timer fires: set EIRR bit 63 and assert timer_irq_pending
            // PA-RISC timer IRQ is at bit 0 (MSB) = Verilog bit 63 of 64-bit EIRR
            // 64-bit kernel: EIEM_MASK(TIMER_IRQ) = 1UL<<63 = 0x8000000000000000
            // 32-bit kernel: EIEM_MASK(TIMER_IRQ) = 1UL<<31 = 0x0000000080000000
            if (itmr_armed && timer_counter == itmr_compare) begin
                eirr_reg             <= eirr_reg | 64'h8000000080000000;
                timer_irq_pending_tb <= 1'b1;   // pulse for one cycle
                itmr_armed           <= 1'b0;
                $display("[%0d] TIMER_FIRE: compare=%016x EIRR=%016x EIEM=%016x PSW_I=%0b",
                         cycle_count, itmr_compare, eirr_reg | 64'h8000000080000000,
                         cpu.cr15_rd, cpu.psw[0]);
            end
        end
    end

    // =========================================================================
    // Memory Watchpoint - track writes to specific PA for debugging
    // =========================================================================
    wire store_enable = cpu.umem_write_enable;
    wire [31:0] cpu_write_addr = cpu.umem_write_addr_mux;
    wire [63:0] cpu_write_data64 = cpu.umem_write_data_mux;

    // kobj->sd debug traces removed (bug was delay-slot interrupt in interruption.isa)

    // =========================================================================
    // UART Monitor - intercept writes to UART TX register
    // =========================================================================

    integer uart_fd;
    initial begin
        uart_fd = $fopen("uart_output.txt", "w");
    end
    final begin
        if (uart_fd) $fclose(uart_fd);
    end

    always @(posedge clk) begin
        if (!reset && store_enable && cpu_write_addr == UART_THR) begin
            // Big-endian PA-RISC with big-endian word order:
            // UART_THR addr[2]=0 → upper word [63:32], byte_offset=0 → bits[63:56]
            if (cpu_write_data64[63:56] >= 8'h20 && cpu_write_data64[63:56] <= 8'h7E ||
                cpu_write_data64[63:56] == 8'h0A || cpu_write_data64[63:56] == 8'h0D) begin
                $write("%c", cpu_write_data64[63:56]);
                $fflush();
                $fwrite(uart_fd, "%c", cpu_write_data64[63:56]);
                $fflush(uart_fd);
            end else if (cpu_write_data64[39:32] >= 8'h20 && cpu_write_data64[39:32] <= 8'h7E ||
                         cpu_write_data64[39:32] == 8'h0A || cpu_write_data64[39:32] == 8'h0D) begin
                // Fallback: try bits[39:32] (word store, byte at [7:0] of upper word)
                $write("%c", cpu_write_data64[39:32]);
                $fflush();
                $fwrite(uart_fd, "%c", cpu_write_data64[39:32]);
                $fflush(uart_fd);
            end
        end
        // Handle UART register writes (for 8250 autodetect support)
        if (!reset && store_enable && cpu_write_addr[31:12] == 20'h03F00) begin
            reg [7:0] wr_byte;
            wr_byte = cpu_write_addr[2] ? cpu_write_data64[31:24] : cpu_write_data64[63:56];
            // Log first 100 UART writes for diagnostics
            if (uart_write_count < 100) begin
                uart_write_count <= uart_write_count + 1;
                $display("[%0d] UART_WR: addr=%08x data=%016x byte=%02x PC=%016x PSW=%016x",
                         cycle_count, cpu_write_addr, cpu_write_data64, wr_byte,
                         cpu.pc_rd, cpu.psw);
            end
            case (cpu_write_addr & 32'h03F000FC)
                UART_IER: uart_ier = wr_byte & 8'h0F;
                UART_IIR: begin  // Write goes to FCR
                    uart_fifo_en = wr_byte[0];
                    uart_iir = wr_byte[0] ? 8'hC1 : 8'h01;
                end
                UART_LCR: uart_lcr = wr_byte;
                UART_MCR: uart_mcr = wr_byte;
                UART_SCR: uart_scr = wr_byte;
                default: ;
            endcase
        end

        // Mirror UART registers into umem for CPU reads
        if (!reset) begin
            cpu.umem[UART_UMEM_BASE + 32'h0][63:32] = 32'h00000000;
            cpu.umem[UART_UMEM_BASE + 32'h0][31:0]  = {uart_ier, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h1][63:32] = {uart_iir, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h1][31:0]  = {uart_lcr, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h2][63:32] = {uart_mcr, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h2][31:0]  = {8'h60, 24'h0};
            cpu.umem[UART_UMEM_BASE + 32'h3][63:32] = uart_mcr[4] ?
                {uart_mcr[3], uart_mcr[2], uart_mcr[0], uart_mcr[1], 4'b0000, 24'h0} :
                32'h00000000;
            cpu.umem[UART_UMEM_BASE + 32'h3][31:0]  = {uart_scr, 24'h0};
        end
    end

    // =========================================================================
    // Kernel Debug Locks Disable
    // =========================================================================
    initial begin
        @(negedge reset);
        cpu.umem[32'h20188c][31:0] = 32'h0;  // debug_locks = 0
    end

    // =========================================================================
    // Simulation Monitor
    // =========================================================================
    integer cycle_count;
    reg [63:0] last_pc;
    reg [31:0] stuck_counter;
    reg initialized;

    // Enhanced debugging state
    reg [63:0] last_cr14;
    reg [63:0] last_psw;
    integer    post_exc_trace;     // countdown for post-exception PC trace
    integer    post_c_trace;       // countdown for post PSW.C trace
    reg        first_exc_seen;
    integer    dtlb_trap_count;    // count data trap occurrences
    integer    handler_trace_count; // count handler traces shown
    integer    handler_cycle_trace; // countdown for handler cycle tracing
    integer    tlb_flush_trace;     // limit flush_tlb_all_local trace lines
    reg [51:0] last_dtlb_vpn [0:15];  // track DTLB changes
    reg        last_dtlb_valid [0:15];
    integer    iasq_diag_count;     // IASQ diagnostic counter
    reg [63:0] prev_r16;            // Track rf[16] changes
    integer    r16_change_count;    // Count of rf[16] change events
    reg [63:0] prev_rp_mem;         // Track rp save location changes
    integer    rp_watch_count;      // Limit rp watchpoint output
    reg [63:0] prev_r3;             // Track r3 changes
    reg [63:0] prev_r28_exec;       // Track R28 during execve for EFAULT detection
    integer    r3_watch_count;      // Limit r3 watchpoint output
    integer    uart_write_count;    // Count UART writes
    integer    firmware_hit_count;  // Count firmware PC hits
    integer    psw_c_total;         // Total PSW.C transitions
    integer    start_parisc_trace_count;  // start_parisc FPU check trace
    integer    rfi_trace_count;           // RFI instruction trace
    integer    panic_trace_count;         // panic() function trace
    integer    handle_int_trace_count;    // handle_interruption trace
    integer    dbit_trace_count;           // dbit_trap_20w trace
    integer    parisc_term_trace_count;   // parisc_terminate trace
    integer    start_kernel_trace_count;  // start_kernel entry trace
    integer    post_start_kernel_trace;   // countdown for post start_kernel trace
    integer    post_break_trace;          // countdown for post break handler trace
    integer    post_strscpy_trace;        // countdown for sized_strscpy trace
    integer    post_cputype_trace;        // countdown for parisc_get_cpu_type trace
    integer    put_task_trace_count;      // put_task_struct_rcu_user entry trace
    integer    vsnprintf_trace_count;     // vsnprintf entry trace
    integer    pre_dtlb_trace_count;      // pre-DTLB-fault instruction trace
    integer    next_memfn_count;           // __next_mem_pfn_range call counter
    integer    next_memfn_cmp_count;       // __next_mem_pfn_range cmp counter
    integer    post_fw_trace;             // post-firmware instruction trace countdown
    integer    release_task_trace_count;  // release_task entry trace
    integer    put_pid_trace_count;       // put_pid entry trace
    integer    rfi_return_trace_count;    // RFI return trace
    integer    post_rfi_trace;            // post-RFI instruction trace countdown
    integer    udelay_trace_count;        // __udelay loop trace (limited)
    integer    vsnprintf_pad_trace;       // vsnprintf padding loop trace
    reg [63:0] prev_eiem;           // Track EIEM (CR15) changes
    // Per-trap-code counters (trap codes 0-31)
    integer    trap_code_count [0:31];
    integer    total_trap_count;
    // PC history ring buffer for crash debugging
    reg [63:0] pc_hist [0:15];
    integer    pc_hist_idx;
    reg        bad_pc_caught;
    reg        mem_watch_fired;
    reg [63:0] prev_compound_head;   // Track compound_head at PA 0x000EC040
    integer    compound_watch_count; // Limit compound_head watchpoint output
    reg [63:0] prev_mem_map;         // Track mem_map variable changes
    reg [63:0] prev_saved_cmd;       // Track saved_command_line pointer changes
    integer    dtlb_diag_count;
    integer    desc_read_trace_count;
    // SLUB freelist watchpoint for kmalloc-512 corruption debug
    reg        slub512_watch_armed;
    reg [63:0] slub512_percpu_pa;        // Physical address of per-CPU struct
    reg [63:0] slub512_prev_freelist;    // Previous freelist value
    // init_pod_type memory watchpoint (PA 0x00708580, umem[0x0E10B0])
    reg        ipt_watch_armed;
    reg [63:0] ipt_watch_prev;
    // Memory watchpoint for the corrupt freelist slot (PA 0x8de300)
    reg        memwatch_armed;
    reg [63:0] memwatch_pa;              // PA of memory to watch
    reg [63:0] memwatch_prev;            // Previous value at watched address
    // Slab page store watchpoint: trace ALL stores to a specific page
    reg        slab_page_watch_armed;
    reg [19:0] slab_page_watch_pfn;      // Page frame number to watch (PA >> 12)
    integer    slab_page_store_count;
    // Task_struct per-CPU watch: freelist at PA 0x0ee6a0, slab at PA 0x0ee6b0
    reg [63:0] task_fl_prev;             // Previous freelist value for task_struct cache
    reg [63:0] task_slab_prev;           // Previous slab pointer for task_struct cache
    // Page allocator tracing
    reg [63:0] mem_map_base;             // Runtime mem_map pointer (read from 0x4072de28)
    reg        mem_map_resolved;         // Set once we've read mem_map
    reg [63:0] alloc_pages_order;        // Saved order from __alloc_pages_noprof entry
    reg        alloc_pages_active;       // Tracking an __alloc_pages call

    always @(posedge clk) begin
        if (!initialized) begin
            reset         <= 1'b1;
            reset_counter <= 10;
            cycle_count   <= 0;
            initialized   <= 1'b1;
            stuck_counter <= 0;
            last_cr14     <= 64'h0;
            last_psw      <= 64'h0;
            post_exc_trace <= 0;
            post_c_trace   <= 0;
            first_exc_seen <= 0;
            dtlb_trap_count <= 0;
            handler_trace_count <= 0;
            handler_cycle_trace <= 0;
            tlb_flush_trace <= 0;
            iasq_diag_count <= 0;
            prev_r16 <= 64'h0;
            r16_change_count <= 0;
            prev_rp_mem <= 64'h0;
            rp_watch_count <= 0;
            prev_r3 <= 64'h0;
            r3_watch_count <= 0;
            uart_write_count <= 0;
            firmware_hit_count <= 0;
            psw_c_total <= 0;
            start_parisc_trace_count <= 0;
            rfi_trace_count <= 0;
            panic_trace_count <= 0;
            handle_int_trace_count <= 0;
            dbit_trace_count <= 0;
            parisc_term_trace_count <= 0;
            start_kernel_trace_count <= 0;
            post_start_kernel_trace <= 0;
            next_memfn_count <= 0;
            next_memfn_cmp_count <= 0;
            post_break_trace <= 0;
            post_strscpy_trace <= 0;
            post_cputype_trace <= 0;
            put_task_trace_count <= 0;
            vsnprintf_trace_count <= 0;
            pre_dtlb_trace_count <= 0;
            post_fw_trace <= 0;
            release_task_trace_count <= 0;
            put_pid_trace_count <= 0;
            rfi_return_trace_count <= 0;
            post_rfi_trace <= 0;
            udelay_trace_count <= 0;
            vsnprintf_pad_trace <= 0;
            prev_eiem <= 64'h0;
            pc_hist_idx <= 0;
            bad_pc_caught <= 0;
            mem_watch_fired <= 0;
            prev_compound_head <= 64'h0;
            compound_watch_count <= 0;
            prev_mem_map <= 64'h0;
            prev_saved_cmd <= 64'h0;
            dtlb_diag_count <= 0;
            desc_read_trace_count <= 0;
            slub512_watch_armed <= 0;
            slub512_percpu_pa <= 64'h0;
            slub512_prev_freelist <= 64'h0;
            ipt_watch_armed <= 0;
            ipt_watch_prev <= 64'h0;
            memwatch_armed <= 0;
            memwatch_pa <= 64'h0;
            memwatch_prev <= 64'h0;
            slab_page_watch_armed <= 0;
            slab_page_watch_pfn <= 20'h0;
            slab_page_store_count <= 0;
            task_fl_prev <= 64'h0;
            task_slab_prev <= 64'h0;
            mem_map_base <= 64'h0;
            mem_map_resolved <= 0;
            alloc_pages_order <= 64'h0;
            alloc_pages_active <= 0;
            total_trap_count <= 0;
            for (integer ii = 0; ii < 32; ii = ii + 1) begin
                trap_code_count[ii] <= 0;
            end
            for (integer ii = 0; ii < 16; ii = ii + 1) begin
                pc_hist[ii] <= 64'h0;
            end
            for (integer ii = 0; ii < 16; ii = ii + 1) begin
                last_dtlb_vpn[ii] <= 52'h0;
                last_dtlb_valid[ii] <= 1'b0;
            end
        end else if (reset_counter > 0) begin
            reset_counter <= reset_counter - 1;
            if (reset_counter == 1) begin
                reset <= 1'b0;
                $display("");
                $display("=== HPPA 2.0 Linux Boot Started ===");
            end
        end else begin
            cycle_count <= cycle_count + 1;
            last_pc     <= cpu.pc_rd;
            last_psw    <= cpu.psw;

            // PC history recording
            pc_hist[pc_hist_idx] <= cpu.pc_rd;
            pc_hist_idx <= (pc_hist_idx + 1) & 15;

            // Catch jump to invalid PC 0x20202020
            if (cpu.pc_rd == 64'h20202020 && !bad_pc_caught) begin
                bad_pc_caught <= 1;
                $display("[%0d] BAD_PC: PC=0x20202020 detected! Dumping PC history:", cycle_count);
                for (integer hi = 0; hi < 16; hi = hi + 1) begin
                    $display("  pc_hist[%0d] = %016x", (pc_hist_idx + hi) & 15, pc_hist[(pc_hist_idx + hi) & 15]);
                end
                $display("  R2(rp)=%016x R3=%016x SP=%016x", cpu.rf[2], cpu.rf[3], cpu.rf[30]);
                $display("  R26=%016x R25=%016x R24=%016x R23=%016x", cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[23]);
                $display("  CR18=%016x CR22=%016x PSW=%016x", cpu.cr18_rd, cpu.cr22_rd, cpu.psw);
            end

            // CR14 (IVA) change monitor
            if (cpu.cr14_rd != last_cr14) begin
                $display("[%0d] CR14_CHANGE: %016x -> %016x (PC=%016x PSW=%016x)",
                         cycle_count, last_cr14, cpu.cr14_rd, cpu.pc_rd, cpu.psw);
                last_cr14 <= cpu.cr14_rd;
            end

            // EIEM (CR15) change monitor
            if (cpu.cr15_rd != prev_eiem) begin
                $display("[%0d] EIEM_CHANGE: %016x -> %016x (PC=%016x PSW=%016x)",
                         cycle_count, prev_eiem, cpu.cr15_rd, cpu.pc_rd, cpu.psw);
                prev_eiem <= cpu.cr15_rd;
            end

            // PSW.C (code translation) change monitor
            if (cpu.psw[18] != last_psw[18]) begin
                psw_c_total <= psw_c_total + 1;
                // Only log first 20 and then every 1000th transition
                if (psw_c_total < 20 || psw_c_total % 1000 == 0)
                    $display("[%0d] PSW_C_CHANGE: %0d -> %0d (PC=%016x PSW=%016x) [#%0d]",
                             cycle_count, last_psw[18], cpu.psw[18], cpu.pc_rd, cpu.psw, psw_c_total);
                // Start instruction trace after 2nd firmware return (PSW_C_CHANGE #4, entering virtual mode)
                if (psw_c_total == 4 && !last_psw[18] && cpu.psw[18])
                    post_fw_trace <= 500;
                // When entering handler (C goes 1->0), show faulting info and trace handler
                if (last_psw[18] && !cpu.psw[18] && handler_trace_count < 50) begin
                    handler_trace_count <= handler_trace_count + 1;
                    handler_cycle_trace <= 50;  // trace up to 50 cycles of handler
                    $display("[%0d] HANDLER_ENTRY: CR18(fault_pc)=%016x CR21(fault_addr)=%016x CR20(fault_space)=%016x",
                             cycle_count, cpu.cr18_rd, cpu.cr21_rd, cpu.cr20_rd);
                    $display("[%0d] HANDLER_ENTRY: CR19(IIR)=%08x CR22(IPSW)=%016x dtlb_next=%0d",
                             cycle_count, cpu.cr19_rd[31:0], cpu.cr22_rd, cpu.dtlb_next_rd);
                    for (integer kk = 0; kk < 16; kk = kk + 1) begin
                        if (cpu.dtlb_valid[kk])
                            $display("[%0d]   DTLB[%0d]: vpn=%013x ppn=%013x space=%016x prot=%016x",
                                     cycle_count, kk, cpu.dtlb_vpn[kk], cpu.dtlb_ppn[kk],
                                     cpu.dtlb_space[kk], cpu.dtlb_prot[kk]);
                    end
                end
            end

            // Handler cycle trace (detailed instruction-by-instruction when PSW.C=0)
            if (handler_cycle_trace > 0 && !cpu.psw[18]) begin
                handler_cycle_trace <= handler_cycle_trace - 1;
                $display("[%0d] HNDL: PC=%016x instr=%08x R1=%016x R8=%016x R9=%016x R16=%016x R29=%016x",
                         cycle_count, cpu.pc_rd,
                         cpu.pc_rd[2] ? cpu.umem[cpu.pc_rd[25:3]][31:0]
                                      : cpu.umem[cpu.pc_rd[25:3]][63:32],
                         cpu.rf[1], cpu.rf[8], cpu.rf[9], cpu.rf[16], cpu.rf[29]);
                // Extra register dump at flush_tlb_all_local
                if (cpu.pc_rd >= 64'h0000000000400060 && cpu.pc_rd <= 64'h00000000004000c0)
                    $display("        R20=%016x R21=%016x R22=%016x R23=%016x R28=%016x R29=%016x R31=%016x",
                             cpu.rf[20], cpu.rf[21], cpu.rf[22], cpu.rf[23],
                             cpu.rf[28], cpu.rf[29], cpu.rf[31]);
            end

            // Debug trace for flush_tlb_all_local (fitmanymiddle loop at PA 0x400088)
            if (cpu.pc_rd >= 64'h0000000000400060 && cpu.pc_rd <= 64'h00000000004000c0 && !cpu.psw[18] && tlb_flush_trace < 100) begin
                tlb_flush_trace <= tlb_flush_trace + 1;
                $display("[%0d] TLB_FLUSH: PC=%016x R20=%016x R21=%016x R22=%016x R23(arg3)=%016x R28=%016x R29=%016x R31=%016x",
                         cycle_count, cpu.pc_rd,
                         cpu.rf[20], cpu.rf[21], cpu.rf[22], cpu.rf[23],
                         cpu.rf[28], cpu.rf[29], cpu.rf[31]);
            end

            // Post-firmware instruction trace (every instruction after 2nd firmware return)
            if (post_fw_trace > 0) begin
                post_fw_trace <= post_fw_trace - 1;
                $display("[%0d] FW: PC=%016x instr=%08x R2=%016x R3=%016x R25=%016x R26=%016x R28=%016x R27(dp)=%016x SP=%016x null=%0d ds=%0d",
                         cycle_count, cpu.pc_rd,
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.rf[2], cpu.rf[3], cpu.rf[25], cpu.rf[26],
                         cpu.rf[28], cpu.rf[27], cpu.rf[30],
                         cpu.in_nullified, cpu.delay_slot_rd);
            end

            // IASQ diagnostic: trace at intr_check_sig ldw 1a0(r16)
            if (cpu.pc_rd == 64'h0000000010412084 && iasq_diag_count < 20) begin
                iasq_diag_count <= iasq_diag_count + 1;
                $display("[%0d] DIAG_CHK: PC=10412084 r16=%016x r20=%016x CR30=%016x r19=%016x",
                         cycle_count, cpu.rf[16], cpu.rf[20], cpu.cr30_rd, cpu.rf[19]);
            end
            // Trace at copy r25, r16 in intr_save continuation (0x10412700)
            if (cpu.pc_rd == 64'h0000000010412700 && iasq_diag_count < 20) begin
                $display("[%0d] DIAG_R16SET: PC=10412700 r16=%016x r25=%016x ret1=%016x",
                         cycle_count, cpu.rf[16], cpu.rf[25], cpu.rf[29]);
            end
            // Trace dup_fd entry and prologue
            if (cpu.pc_rd == 64'h00000000402c66f8) begin  // dup_fd entry: copy r3,r1
                $display("[%0d] DUP_FD_ENTRY: R26(oldf)=%016x R25(punch_hole)=%016x rp=%016x sp=%016x R3=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2], cpu.rf[30], cpu.rf[3]);
            end
            if (cpu.pc_rd == 64'h00000000402c66fc) begin  // std rp,-10(sp)
                $display("[%0d] DUP_FD_PRO1: std_rp: R2=%016x R3=%016x SP=%016x",
                         cycle_count, cpu.rf[2], cpu.rf[3], cpu.rf[30]);
            end
            if (cpu.pc_rd == 64'h00000000402c6700) begin  // copy sp,r3
                $display("[%0d] DUP_FD_PRO2: copy_sp_r3: R3(before)=%016x SP=%016x",
                         cycle_count, cpu.rf[3], cpu.rf[30]);
            end
            if (cpu.pc_rd == 64'h00000000402c6704) begin  // std,ma r1,d0(sp)
                $display("[%0d] DUP_FD_PRO3: std_ma: R1=%016x R3=%016x SP=%016x",
                         cycle_count, cpu.rf[1], cpu.rf[3], cpu.rf[30]);
            end
            if (cpu.pc_rd == 64'h00000000402c6708) begin  // addil (first instr after prologue)
                $display("[%0d] DUP_FD_PRO4: after_prologue: R3=%016x SP=%016x",
                         cycle_count, cpu.rf[3], cpu.rf[30]);
            end
            if (cpu.pc_rd == 64'h00000000402c6858) begin  // ldd 8(r6),r11 — load new_fdt->fd
                $display("[%0d] DUP_FD_LOAD_FD: R6(new_fdt+)=%016x R11(before)=%016x R8(old_fdt+)=%016x",
                         cycle_count, cpu.rf[6], cpu.rf[11], cpu.rf[8]);
            end
            if (cpu.pc_rd == 64'h00000000402c6864) begin  // copy r11,r9
                $display("[%0d] DUP_FD_COPY_R9: R11=%016x R9(before)=%016x R7(open_files)=%016x",
                         cycle_count, cpu.rf[11], cpu.rf[9], cpu.rf[7]);
            end
            if (cpu.pc_rd == 64'h00000000402c69bc) begin  // std r10,0(r9) — the faulting store
                $display("[%0d] DUP_FD_STORE: R9(new_fds)=%016x R10(file)=%016x R8(count)=%016x R7(open_files)=%016x",
                         cycle_count, cpu.rf[9], cpu.rf[10], cpu.rf[8], cpu.rf[7]);
            end
            // Trace loop control: extrd,u and cmpb at end of dup_fd loop
            if (cpu.pc_rd == 64'h00000000402c69c8) begin  // extrd,u,* r8,63,32,r8
                $display("[%0d] DUP_FD_EXTRD: R8(before)=%016x",
                         cycle_count, cpu.rf[8]);
            end
            if (cpu.pc_rd == 64'h00000000402c686c) begin  // cmpb,<> r8,r7,0x402c6994
                $display("[%0d] DUP_FD_CMPB: R8=%016x R7=%016x (equal=%0d)",
                         cycle_count, cpu.rf[8], cpu.rf[7], cpu.rf[8] == cpu.rf[7]);
            end
            // Trace the b,l branch to loop top
            if (cpu.pc_rd == 64'h00000000402c69cc) begin  // b,l 402c686c,r0
                $display("[%0d] DUP_FD_BL: R8=%016x R7=%016x ret0=%016x r13=%016x",
                         cycle_count, cpu.rf[8], cpu.rf[7], cpu.rf[28], cpu.rf[13]);
            end

            // Cycle-by-cycle trace near dup_fd crash (cycles 5651140-5651210)
            if (cycle_count >= 5651140 && cycle_count <= 5651210) begin
                $display("[%0d] TRACE: PC=%016x PSW=%016x instr=%08x R2=%016x R3=%016x R6=%016x R7=%016x R8=%016x R9=%016x",
                         cycle_count, cpu.pc_rd, cpu.psw,
                         cpu.pc_rd[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.rf[2], cpu.rf[3], cpu.rf[6], cpu.rf[7], cpu.rf[8], cpu.rf[9]);
            end

            // Memory watchpoint: detect writes to saved-R3 location
            // __clear_open_fd saves dup_fd's R3 (0x406125d0) at VA 0x406126a0, PA 0x006126a0
            // umem word index = 0x006126a0 >> 3 = 0x0C24D4
            // Active during interrupt window
            if (cycle_count >= 5644200 && cycle_count <= 5647000) begin
                if (cpu.umem[26'hC24D4] != prev_rp_mem && rp_watch_count < 40) begin
                    rp_watch_count <= rp_watch_count + 1;
                    $display("[%0d] MEM_WATCH_R3: PA=006126a0 old=%016x new=%016x PC=%016x PSW=%016x R2=%016x R3=%016x SP=%016x",
                             cycle_count, prev_rp_mem, cpu.umem[26'hC24D4], cpu.pc_rd, cpu.psw, cpu.rf[2], cpu.rf[3], cpu.rf[30]);
                end
                prev_rp_mem <= cpu.umem[26'hC24D4];
            end

            // R3 change monitor during dup_fd execution
            // R3 should be 0x406125d0 inside dup_fd (set at cycle ~5642849)
            // Track changes starting just before the interrupt (5644200+) to catch corruption
            if (cycle_count >= 5644200 && cycle_count <= 5652000) begin
                if (cpu.rf[3] != prev_r3 && r3_watch_count < 500) begin
                    r3_watch_count <= r3_watch_count + 1;
                    $display("[%0d] R3_CHANGE: old=%016x new=%016x PC=%016x PSW=%016x R2=%016x SP=%016x",
                             cycle_count, prev_r3, cpu.rf[3], cpu.pc_rd, cpu.psw, cpu.rf[2], cpu.rf[30]);
                end
                prev_r3 <= cpu.rf[3];
            end

            // LDD,MB debug: trace rf write ports during all ldd_mb executions in dup_fd window
            if (cpu.ldd_mb_enable && cycle_count >= 5644200 && cycle_count <= 5652000) begin
                $display("[%0d] LDD_MB_DBG: PC=%016x port0_en=%0d port0_addr=%0d port0_data=%016x port1_en=%0d port1_addr=%0d port1_data=%016x",
                         cycle_count, cpu.pc_rd,
                         cpu.rf_write_enable, cpu.rf_write_addr_mux, cpu.rf_write_data_mux[63:0],
                         cpu.rf_write_enable_1, cpu.rf_write_addr_mux_1[4:0], cpu.rf_write_data_mux_1[63:0]);
                $display("[%0d] LDD_MB_DBG: da_pa=%016x umem_rd=%016x ldd_mb_addr=%016x R3=%016x SP=%016x in_null=%0d ds=%0d",
                         cycle_count, cpu.ldd_mb_da_pa, cpu.umem_da_pa_rd, cpu.ldd_mb_addr,
                         cpu.rf[3], cpu.rf[30], cpu.in_nullified, cpu.delay_slot_rd);
            end

            // === __bitmap_set debug traces ===
            // __bitmap_set entry: map=r26, start=r25, nbits=r24
            if (cpu.pc_rd == 64'h00000000403b11a0) begin
                $display("[%0d] BITMAP_SET: map=%016x start=%0d nbits=%0d  r2=%016x  bm6=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2],
                         cpu.umem[26'h076128]);
            end
            // MTSAR at 0x403b11fc: sub r0,r24,r24 then mtsar r24
            if (cpu.pc_rd == 64'h00000000403b11f8) begin
                $display("[%0d] BM_SUB: r24_before=%016x r0=%016x (will compute r24=0-r24=%016x, bits[5:0]=%0d)",
                         cycle_count, cpu.rf[24], cpu.rf[0],
                         64'h0 - cpu.rf[24], (64'h0 - cpu.rf[24]) & 64'h3F);
            end
            if (cpu.pc_rd == 64'h00000000403b11fc) begin
                $display("[%0d] BM_MTSAR: r24=%016x r24[5:0]=%0d SAR_before=%0d",
                         cycle_count, cpu.rf[24], cpu.rf[24][5:0], cpu.sar);
            end
            // SHRPD at 0x403b1200: shrpd,* r0,ret0,sar,ret0
            if (cpu.pc_rd == 64'h00000000403b1200) begin
                $display("[%0d] BM_SHRPD_IN: SAR=%0d ret0=%016x r0=%016x null=%0d ds=%0d",
                         cycle_count, cpu.sar, cpu.rf[28], cpu.rf[0], cpu.in_nullified, cpu.delay_slot_rd);
            end
            // After SHRPD: 0x403b1204 (AND is next)
            if (cpu.pc_rd == 64'h00000000403b1204) begin
                $display("[%0d] BM_SHRPD: shrpd_result(ret0)=%016x left_mask(r31)=%016x SAR=%0d",
                         cycle_count, cpu.rf[28], cpu.rf[31], cpu.sar);
            end
            // STD in single-word path at 0x403b1210
            if (cpu.pc_rd == 64'h00000000403b1210) begin
                $display("[%0d] BM_STD: addr(r26)=%016x val(ret0)=%016x r31=%016x mask=%016x SAR=%0d",
                         cycle_count, cpu.rf[26], cpu.rf[28], cpu.rf[31],
                         cpu.rf[28] & ~cpu.rf[31], cpu.sar);
            end
            // pcpu_alloc_noprof return (check for duplicate offsets)
            // pcpu_alloc_area return at 0x403c45cc (approximate)
            if (cpu.pc_rd == 64'h00000000403c4418) begin
                $display("[%0d] PCPU_ALLOC_AREA: ret0=%016x r26=%016x r25=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[26], cpu.rf[25]);
            end


            // Trace at handle_interruption entry (64-bit: 0x40157ef8)
            if (cpu.pc_rd == 64'h0000000040157ef8) begin
                automatic logic [63:0] regs_pa;
                automatic logic [25:0] regs_word_addr;
                regs_pa = cpu.rf[25] - 64'h40000000;
                regs_word_addr = regs_pa[28:3];
                $display("[%0d] HANDLE_INTERRUPTION: code(R26)=%0d regs(R25)=%016x fault_addr(CR21)=%016x fault_space(CR20)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.cr21_rd, cpu.cr20_rd);
                $display("[%0d] HANDLE_INTERRUPTION: CR18(iiaoq)=%016x CR19(IIR)=%08x CR22(IPSW)=%016x",
                         cycle_count, cpu.cr18_rd, cpu.cr19_rd[31:0], cpu.cr22_rd);
                // Dump pt_regs from memory: iaoq at offset 0x250 (word offset +0x4a)
                $display("[%0d] PT_REGS: iaoq[0]=%016x iaoq[1]=%016x iir=%016x ior=%016x ipsw=%016x",
                         cycle_count,
                         cpu.umem[regs_word_addr + 26'h4a],  // iaoq[0] at +0x250
                         cpu.umem[regs_word_addr + 26'h4b],  // iaoq[1] at +0x258
                         cpu.umem[regs_word_addr + 26'h52],  // iir at +0x290
                         cpu.umem[regs_word_addr + 26'h54],  // ior at +0x2A0
                         cpu.umem[regs_word_addr + 26'h55]); // ipsw at +0x2A8
                // Dump some general registers from pt_regs
                $display("[%0d] PT_REGS: gr0(psw)=%016x gr1=%016x gr2(rp)=%016x gr26=%016x gr29(ret1)=%016x gr30(sp)=%016x",
                         cycle_count,
                         cpu.umem[regs_word_addr],            // gr[0] at +0x00
                         cpu.umem[regs_word_addr + 26'h1],    // gr[1] at +0x08
                         cpu.umem[regs_word_addr + 26'h2],    // gr[2] at +0x10
                         cpu.umem[regs_word_addr + 26'h1a],   // gr[26] at +0xD0
                         cpu.umem[regs_word_addr + 26'h1d],   // gr[29] at +0xE8
                         cpu.umem[regs_word_addr + 26'h1e]);  // gr[30] at +0xF0
            end

            // ============================================================
            // RF[16] write monitor - detect all write paths to register 16
            // ============================================================
            prev_r16 <= cpu.rf[16];
            // Monitor port0: rf_write_enable with addr==16
            if (cpu.rf_write_enable && cpu.rf_write_addr_mux == 5'd16 && r16_change_count < 80) begin
                r16_change_count <= r16_change_count + 1;
                $display("[%0d] RF16_WR_PORT0: PC=%016x data=%016x PSW=%016x rf16_before=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf_write_data_mux[63:0], cpu.psw, cpu.rf[16]);
            end
            // Monitor port1: rf_write_enable_1 with addr==16
            if (cpu.rf_write_enable_1 && cpu.rf_write_addr_mux_1 == 32'd16 && r16_change_count < 80) begin
                r16_change_count <= r16_change_count + 1;
                $display("[%0d] RF16_WR_PORT1: PC=%016x data=%016x PSW=%016x rf16_before=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf_write_data_mux_1, cpu.psw, cpu.rf[16]);
            end
            // Monitor RFIR shadow restore to r16
            if (cpu.rf_3_rfi_active_guarded_enable && r16_change_count < 80) begin
                r16_change_count <= r16_change_count + 1;
                $display("[%0d] RF16_WR_RFIR: PC=%016x shadow_r16=%016x PSW=%016x rf16_before=%016x",
                         cycle_count, cpu.pc_rd, cpu.shadow_r16, cpu.psw, cpu.rf[16]);
            end

            // Firmware PC monitor: detect execution in ROM area (0x0F000000-0x0F000FFF)
            if (cpu.pc_rd[31:12] == 20'h0F000 && firmware_hit_count < 20) begin
                firmware_hit_count <= firmware_hit_count + 1;
                $display("[%0d] FIRMWARE: PC=%016x PSW=%016x R26=%016x R25=%016x R24=%016x R2=%016x",
                         cycle_count, cpu.pc_rd, cpu.psw,
                         cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2]);
            end

            // Earlycon/PDC console function watchpoints (FLATMEM kernel)
            if (cpu.pc_rd == 64'h000000004015c068)  // pdc_iodc_print
                $display("[%0d] PDC_IODC_PRINT: R26=%016x R25=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[30]);
            if (cpu.pc_rd == 64'h0000000040164b88)  // pdc_console_write
                $display("[%0d] PDC_CONSOLE_WRITE: R26=%016x R25=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[30]);
            if (cpu.pc_rd == 64'h0000000040162f80)  // real32_call_asm
                $display("[%0d] REAL32_CALL_ASM: R26=%016x R25=%016x R24=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[30]);
            if (cpu.pc_rd == 64'h0000000040126c98)  // setup_earlycon
                $display("[%0d] SETUP_EARLYCON: R26=%016x R25=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[30]);
            if (cpu.pc_rd == 64'h00000000401c9108)  // register_console
                $display("[%0d] REGISTER_CONSOLE: R26=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[30]);
            if (cpu.pc_rd == 64'h00000000401011d0)  // parse_early_param
                $display("[%0d] PARSE_EARLY_PARAM: SP=%016x R2=%016x",
                         cycle_count, cpu.rf[30], cpu.rf[2]);
            if (cpu.pc_rd == 64'h00000000401165c8)  // mm_core_init
                $display("[%0d] MM_CORE_INIT: SP=%016x R2=%016x",
                         cycle_count, cpu.rf[30], cpu.rf[2]);

            // ============================================================
            // init_pod_type debug traces
            // ============================================================
            // Entry: 0x4010d8e8 - r26=pt, r25=cpus_share_pod
            if (cpu.pc_rd == 64'h000000004010d8e8) begin
                $display("[%0d] INIT_POD_TYPE: entry r26(pt)=%016x r25(fn)=%016x r2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end
            // 1st kcalloc return: 0x4010d92c - std ret0,18(r5) stores cpu_pod
            if (cpu.pc_rd == 64'h000000004010d92c) begin
                $display("[%0d] IPT_KCALLOC1: ret0(cpu_pod)=%016x r5(pt)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5]);
            end
            // 2nd kcalloc return: 0x4010d96c - std ret0,8(r5) stores pod_cpus
            if (cpu.pc_rd == 64'h000000004010d96c) begin
                $display("[%0d] IPT_KCALLOC2: ret0(pod_cpus)=%016x r5(pt)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5]);
            end
            // 3rd kcalloc return: 0x4010d998 - std ret0,10(r5) stores pod_node
            if (cpu.pc_rd == 64'h000000004010d998) begin
                $display("[%0d] IPT_KCALLOC3: ret0(pod_node)=%016x r5(pt)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5]);
                // Dump struct before store
                begin
                    reg [63:0] pt_pa;
                    pt_pa = cpu.rf[5] - 64'h40000000;
                    $display("[%0d] IPT_STRUCT_BEFORE: [0]=%016x [8]=%016x [10]=%016x [18]=%016x",
                             cycle_count,
                             cpu.umem[pt_pa >> 3],
                             cpu.umem[(pt_pa + 64'h8) >> 3],
                             cpu.umem[(pt_pa + 64'h10) >> 3],
                             cpu.umem[(pt_pa + 64'h18) >> 3]);
                end
            end
            // After 3rd kcalloc store: 0x4010d99c - ldd 8(r5),r31
            if (cpu.pc_rd == 64'h000000004010d99c) begin
                begin
                    reg [63:0] pt_pa2;
                    pt_pa2 = cpu.rf[5] - 64'h40000000;
                    $display("[%0d] IPT_AFTER_STORE3: [10]=%016x r31=%016x store_enable=%b wr_addr=%08x wr_data=%016x",
                             cycle_count,
                             cpu.umem[(pt_pa2 + 64'h10) >> 3],
                             cpu.rf[31], store_enable, cpu_write_addr, cpu_write_data64);
                end
            end
            // cmpclr at 0x4010d9a0
            if (cpu.pc_rd == 64'h000000004010d9a0) begin
                $display("[%0d] IPT_CMPCLR: r0=%016x r31=%016x ret0=%016x nullified=%0d",
                         cycle_count, cpu.rf[0], cpu.rf[31], cpu.rf[28], cpu.in_nullified);
            end
            // cmpb at 0x4010d9a8
            if (cpu.pc_rd == 64'h000000004010d9a8) begin
                $display("[%0d] IPT_CMPB: r0=%016x ret0=%016x nullified=%0d",
                         cycle_count, cpu.rf[0], cpu.rf[28], cpu.in_nullified);
            end
            // Loop head at 0x4010d9b0
            if (cpu.pc_rd == 64'h000000004010d9b0) begin
                $display("[%0d] IPT_LOOP: ret0(i)=%016x r19(nr_pods)=%016x r31=%016x nullified=%0d",
                         cycle_count, cpu.rf[28], cpu.rf[19], cpu.rf[31], cpu.in_nullified);
            end
            // Pod_node load at 0x4010d9f0 - ldd 10(r5),ret0
            if (cpu.pc_rd == 64'h000000004010d9f0) begin
                begin
                    reg [63:0] pt_pa3;
                    pt_pa3 = cpu.rf[5] - 64'h40000000;
                    $display("[%0d] IPT_LOAD_PODNODE: r5=%016x [10]_from_umem=%016x r31=%016x ret0_before=%016x",
                             cycle_count, cpu.rf[5],
                             cpu.umem[(pt_pa3 + 64'h10) >> 3],
                             cpu.rf[31], cpu.rf[28]);
                end
            end
            // Crash instruction at 0x4010d9f8 - stw r0,0(ret0)
            if (cpu.pc_rd == 64'h000000004010d9f8) begin
                $display("[%0d] IPT_CRASH: ret0(addr)=%016x r0=%016x r31=%016x r5=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[0], cpu.rf[31], cpu.rf[5]);
            end
            // Memory watchpoint on pod_node slot: PA 0x00708580 / umem[0x0E10B0]
            // Arm when we see the 3rd kcalloc store (r5=0x40708570, store to r5+0x10)
            if (cpu.pc_rd == 64'h000000004010d998 && cpu.rf[5] == 64'h0000000040708570) begin
                ipt_watch_armed <= 1;
                ipt_watch_prev <= cpu.umem[26'h0E10B0];
                $display("[%0d] IPT_WATCH_ARM: umem[0E10B0]=%016x ret0=%016x",
                         cycle_count, cpu.umem[26'h0E10B0], cpu.rf[28]);
            end
            if (ipt_watch_armed) begin
                if (cpu.umem[26'h0E10B0] != ipt_watch_prev) begin
                    $display("[%0d] IPT_WATCH_HIT: old=%016x new=%016x PC=%016x store_en=%b wr_addr=%08x wr_data=%016x",
                             cycle_count, ipt_watch_prev, cpu.umem[26'h0E10B0],
                             cpu.pc_rd, store_enable, cpu_write_addr, cpu_write_data64);
                    $display("[%0d] IPT_WATCH_HIT: r5=%016x ret0=%016x r31=%016x r19=%016x PSW=%016x",
                             cycle_count, cpu.rf[5], cpu.rf[28], cpu.rf[31], cpu.rf[19], cpu.psw);
                    ipt_watch_prev <= cpu.umem[26'h0E10B0];
                end
            end

            // SLAB DEBUG TRACES
            // do_kmem_cache_create entry (0x402789c8)
            // r26=s, r25=name, r24=size, r23=args
            if (cpu.pc_rd == 64'h00000000402789c8) begin
                $display("[%0d] DO_KMEM_CREATE: r26(s)=%016x r25(name)=%016x r24(size)=%016x r23(args)=%016x r22(flags)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[23], cpu.rf[22]);
            end
            // calculate_sizes entry (0x40271968)
            // r26=args, r25=s
            if (cpu.pc_rd == 64'h0000000040271968) begin
                $display("[%0d] CALC_SIZES: r26(args)=%016x r25(s)=%016x r2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end
            // After calculate_sizes returns in do_kmem_cache_create (0x40278a60)
            // cmpb,*<> r0,ret0 - ret0=return value of calculate_sizes
            if (cpu.pc_rd == 64'h0000000040278a60) begin
                $display("[%0d] CALC_SIZES_RET: ret0=%016x (0=FAIL, 1=ok) r5(s)=%016x r6(args/flags)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5], cpu.rf[6]);
            end
            // calculate_sizes failure path (0x40278a68) - ldi -EINVAL
            if (cpu.pc_rd == 64'h0000000040278a68) begin
                $display("[%0d] CALC_SIZES_FAIL: entering error path, r5(s)=%016x",
                         cycle_count, cpu.rf[5]);
                // Dump s struct from memory (PA = s - 0x40000000)
                begin
                    reg [63:0] s_pa;
                    s_pa = cpu.rf[5] - 64'h40000000;
                    $display("[%0d] S_STRUCT: [0]=%016x [8]=%016x [10]=%016x [18]=%016x [20]=%016x [28]=%016x [30]=%016x [38]=%016x",
                             cycle_count,
                             cpu.umem[(s_pa) >> 3],
                             cpu.umem[(s_pa + 64'h8) >> 3],
                             cpu.umem[(s_pa + 64'h10) >> 3],
                             cpu.umem[(s_pa + 64'h18) >> 3],
                             cpu.umem[(s_pa + 64'h20) >> 3],
                             cpu.umem[(s_pa + 64'h28) >> 3],
                             cpu.umem[(s_pa + 64'h30) >> 3],
                             cpu.umem[(s_pa + 64'h38) >> 3]);
                end
            end
            // alloc_kmem_cache_cpus check (0x40278dfc)
            // cmpb,*= r0,ret0 - ret0 from __alloc_percpu
            if (cpu.pc_rd == 64'h0000000040278dfc) begin
                $display("[%0d] ALLOC_CPUS_RET: ret0=%016x (0=FAIL) r5(s)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5]);
            end
            // slab_state check (0x40278e14)
            // cmpib,<< 2,ret0 - ret0 = slab_state
            if (cpu.pc_rd == 64'h0000000040278e14) begin
                $display("[%0d] SLAB_STATE_CHECK: ret0(slab_state)=%016x (0=DOWN,1=PARTIAL,2=UP)",
                         cycle_count, cpu.rf[28]);
            end
            // DETAILED calculate_sizes / calculate_order traces
            // s->align load at 0x40271a38: ldw 4c(r5),r6
            if (cpu.pc_rd == 64'h0000000040271a38) begin
                $display("[%0d] CS_ALIGN_LD: s->align will load from 0x4c(r5=%016x), r8(freeptr_area)=%0d",
                         cycle_count, cpu.rf[5], cpu.rf[8][31:0]);
            end
            // s->size store at 0x40271a7c: stw r6,18(r5)
            if (cpu.pc_rd == 64'h0000000040271a7c) begin
                $display("[%0d] CS_SIZE_STORE: s->size=%0d (0x%x) r5(s)=%016x align(r6_was)=%0d",
                         cycle_count, cpu.rf[6][31:0], cpu.rf[6][31:0], cpu.rf[5], cpu.rf[6][31:0]);
            end
            // slub_min_objects check at 0x40271aa4: cmpb,*<> r0,ret0
            if (cpu.pc_rd == 64'h0000000040271aa4) begin
                $display("[%0d] CS_MIN_OBJ: slub_min_objects=%0d r7(size_zext)=%0d",
                         cycle_count, cpu.rf[28][31:0], cpu.rf[7][31:0]);
            end
            // Before first division (order_objects) at 0x40271b08: bve,l
            if (cpu.pc_rd == 64'h0000000040271b08) begin
                $display("[%0d] CS_DIV1_CALL: r26(num)=%0d r25(den)=%0d ret0(min_obj)=%0d",
                         cycle_count, cpu.rf[26][31:0], cpu.rf[25][31:0], cpu.rf[28][31:0]);
            end
            // After first division at 0x40271b10: ldi 1,r26
            if (cpu.pc_rd == 64'h0000000040271b10) begin
                $display("[%0d] CS_DIV1_RET: ret0=%016x ret1=%016x (max_obj=%0d, min_obj=%0d)",
                         cycle_count, cpu.rf[28], cpu.rf[29],
                         cpu.rf[29][31:0], cpu.rf[28][31:0]);
            end
            // Before get_order call at 0x40271b34: bve,l
            if (cpu.pc_rd == 64'h0000000040271b34) begin
                $display("[%0d] CS_GETORD_CALL: r26(min_obj)=%0d r25(size)=%0d product=%0d",
                         cycle_count, cpu.rf[26][31:0], cpu.rf[25][31:0],
                         cpu.rf[26][31:0] * cpu.rf[25][31:0]);
            end
            // After get_order fls at 0x40271b3c: extrd,u,* ret1,63,32,ret1
            if (cpu.pc_rd == 64'h0000000040271b3c) begin
                $display("[%0d] CS_GETORD_RET: ret0=%016x ret1=%016x r20(slub_min_order)=%0d",
                         cycle_count, cpu.rf[28], cpu.rf[29], cpu.rf[20][31:0]);
            end
            // min_order = max(slub_min_order, get_order) at 0x40271bc0
            if (cpu.pc_rd == 64'h0000000040271bc0) begin
                $display("[%0d] CS_MIN_ORD: ret0(order)=%0d r20(slub_min_order)=%0d r23=%0d r7=%0d",
                         cycle_count, cpu.rf[28][31:0], cpu.rf[20][31:0],
                         cpu.rf[23][31:0], cpu.rf[7][31:0]);
            end
            // Before calc_slab_order division at 0x40271be8: bve,l
            if (cpu.pc_rd == 64'h0000000040271be8) begin
                $display("[%0d] CS_SLAB_DIV: r26(slab_sz)=%0d r25(obj_sz)=%0d r23(order)=%0d ret0=%016x",
                         cycle_count, cpu.rf[26][31:0], cpu.rf[25][31:0],
                         cpu.rf[23][31:0], cpu.rf[28]);
            end
            // After calc_slab_order division at 0x40271bf0: cmpb,>>= ret0,ret1
            if (cpu.pc_rd == 64'h0000000040271bf0) begin
                $display("[%0d] CS_SLAB_RES: ret0=%016x ret1=%016x (rem=%0d thresh=%0d)",
                         cycle_count, cpu.rf[28], cpu.rf[29],
                         cpu.rf[29][31:0], cpu.rf[28][31:0]);
            end
            // oo_make store at 0x40271cd0: stw r19,2c(r5)
            if (cpu.pc_rd == 64'h0000000040271cd0) begin
                $display("[%0d] CS_OO_STORE: r19(oo)=0x%08x r5(s)=%016x order=%0d objs=%0d",
                         cycle_count, cpu.rf[19][31:0], cpu.rf[5],
                         cpu.rf[19][31:16], cpu.rf[19][15:0]);
            end
            // Successful calc_slab_order path at 0x40271edc
            if (cpu.pc_rd == 64'h0000000040271edc) begin
                $display("[%0d] CS_SLAB_OK: going to oo_make path, ret0=%0d r20=%0d r23(min_order)=%0d r31=%0d",
                         cycle_count, cpu.rf[28][31:0], cpu.rf[20][31:0],
                         cpu.rf[23][31:0], cpu.rf[31][31:0]);
            end
            // calculate_order fallback: get_order(size) at 0x40271ee4
            if (cpu.pc_rd == 64'h0000000040271ee4) begin
                $display("[%0d] CS_FALLBACK: r7=%016x, computing get_order(size) fallback",
                         cycle_count, cpu.rf[7]);
            end
            // calculate_sizes return at 0x40271eac
            if (cpu.pc_rd == 64'h0000000040271eac) begin
                $display("[%0d] CS_RETURN: ret0=%016x (0=fail)",
                         cycle_count, cpu.rf[28]);
            end
            // Also trace calc_slab_order loop iteration (fraction loop) at 0x40271e34
            if (cpu.pc_rd == 64'h0000000040271e34) begin
                $display("[%0d] CS_FRAC_LOOP: r31(order)=%0d r19(max_order)=%0d r21(frac)=%0d r22(slab_sz)=%0d",
                         cycle_count, cpu.rf[31][31:0], cpu.rf[19][31:0],
                         cpu.rf[21][31:0], cpu.rf[22][31:0]);
            end
            // check_slab_order comparison at 0x40271e74
            if (cpu.pc_rd == 64'h0000000040271e74) begin
                $display("[%0d] CS_FRAC_CMP: ret1(rem)=%0d r24(thresh)=%0d",
                         cycle_count, cpu.rf[29][31:0], cpu.rf[24][31:0]);
            end
            // order_objects MAX_OBJS check at 0x40271b54
            if (cpu.pc_rd == 64'h0000000040271b54) begin
                $display("[%0d] CS_MAXOBJ_CHK: ret0=%016x ret1=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[29]);
            end
            // PWQ allocation traces
            // alloc_unbound_pwq: after kmem_cache_alloc_node returns (0x401a26b4)
            // ret0 = allocated pwq pointer, r5 = pool
            if (cpu.pc_rd == 64'h00000000401a26b4) begin
                $display("[%0d] PWQ_ALLOC_RET: ret0(pwq)=%016x r5(pool)=%016x r8(wq)=%016x low8=%02x",
                         cycle_count, cpu.rf[28], cpu.rf[5], cpu.rf[8], cpu.rf[28][7:0]);
            end
            // alloc_unbound_pwq: just before calling kmem_cache_alloc_node (0x401a26ac)
            // r26 = pwq_cache, r25 = GFP flags, r24 = node
            if (cpu.pc_rd == 64'h00000000401a26ac) begin
                $display("[%0d] PWQ_ALLOC_CALL: r26(cache)=%016x r25(gfp)=%016x r24(node)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24]);
                // Dump cache struct s->size (offset 0x18) and s->align (offset 0x4C) from memory
                begin
                    reg [63:0] cache_pa;
                    cache_pa = cpu.rf[26] - 64'h40000000;
                    // offset 0x18 = s->size (32-bit), 0x4C = s->align (32-bit)
                    $display("[%0d] PWQ_CACHE_INFO: [0x18]=%016x [0x48]=%016x [0x28]=%016x",
                             cycle_count,
                             cpu.umem[(cache_pa + 64'h18) >> 3],
                             cpu.umem[(cache_pa + 64'h48) >> 3],
                             cpu.umem[(cache_pa + 64'h28) >> 3]);
                end
            end
            // SLUB fast path: freelist read at 0x402751ec
            // ldw 28(r5),ret0 loads s->offset, then ldd ret0(r6),r7 reads next ptr
            if (cpu.pc_rd == 64'h00000000402751ec) begin
                $display("[%0d] SLUB_FAST: r5(s)=%016x r6(freelist)=%016x r22(c)=%016x r2(caller)=%016x",
                         cycle_count, cpu.rf[5], cpu.rf[6], cpu.rf[22], cpu.rf[2]);
                // Arm freelist watchpoint on first fast path hit for kmalloc-512
                if (cpu.rf[5] == 64'h0000000040801600 && !slub512_watch_armed) begin
                    slub512_percpu_pa <= cpu.rf[22] - 64'h40000000;
                    slub512_watch_armed <= 1;
                    slub512_prev_freelist <= cpu.rf[6];
                    $display("[%0d] SLUB512_WATCH_ARM: percpu_va=%016x percpu_pa=%016x initial_freelist=%016x",
                             cycle_count, cpu.rf[22], cpu.rf[22] - 64'h40000000, cpu.rf[6]);
                end
                // Read the actual next pointer from memory for kmalloc-512 (s->offset=0x100)
                if (cpu.rf[5] == 64'h0000000040801600 && cpu.rf[6] != 64'h0) begin
                    reg [63:0] next_pa;
                    next_pa = (cpu.rf[6] - 64'h40000000) + 64'h100;
                    $display("[%0d] SLUB_FAST512_MEM: object=%016x next_at_pa=%016x next_val=%016x",
                             cycle_count, cpu.rf[6], next_pa, cpu.umem[next_pa >> 3]);
                end
            end
            // Also trace kmem_cache_alloc_noprof (0x402756e0) fast path at 0x402758a0
            if (cpu.pc_rd == 64'h00000000402758a0) begin
                $display("[%0d] SLUB_FAST_NP: r5(s)=%016x r6(freelist)=%016x r22(c)=%016x r2(caller)=%016x",
                         cycle_count, cpu.rf[5], cpu.rf[6], cpu.rf[22], cpu.rf[2]);
                if (cpu.rf[5] == 64'h0000000040801600 && cpu.rf[6] != 64'h0) begin
                    reg [63:0] next_pa_np;
                    next_pa_np = (cpu.rf[6] - 64'h40000000) + 64'h100;
                    $display("[%0d] SLUB_FAST_NP512_MEM: object=%016x next_at_pa=%016x next_val=%016x",
                             cycle_count, cpu.rf[6], next_pa_np, cpu.umem[next_pa_np >> 3]);
                end
            end
            // Trace kmem_cache_alloc_noprof entry (0x402756e0)
            if (cpu.pc_rd == 64'h00000000402756e0) begin
                if (cpu.rf[26] == 64'h0000000040801600) begin
                    $display("[%0d] SLUB_ALLOC_NP_ENTRY: r26(s)=%016x r25(gfp)=%016x r2(caller)=%016x",
                             cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
                end
            end
            // SLUB freelist watchpoint: detect when per-CPU freelist for kmalloc-512 changes
            if (slub512_watch_armed) begin
                reg [63:0] cur_freelist;
                cur_freelist = cpu.umem[slub512_percpu_pa >> 3];
                if (cur_freelist != slub512_prev_freelist) begin
                    $display("[%0d] SLUB512_FREELIST_CHG: old=%016x new=%016x PC=%016x PSW=%016x r2=%016x",
                             cycle_count, slub512_prev_freelist, cur_freelist,
                             cpu.pc_rd, cpu.psw, cpu.rf[2]);
                    // Check alignment: kmalloc-512 objects must be 512-byte aligned (low 9 bits = 0)
                    if (cur_freelist != 64'h0 && cur_freelist[8:0] != 9'h0) begin
                        $display("[%0d] *** SLUB512_BAD_FREELIST: %016x is NOT 512-byte aligned! low9=0x%03x ***",
                                 cycle_count, cur_freelist, cur_freelist[8:0]);
                        $display("  PC=%016x PSW=%016x SP=%016x r2=%016x r3=%016x",
                                 cpu.pc_rd, cpu.psw, cpu.rf[30], cpu.rf[2], cpu.rf[3]);
                        $display("  r4=%016x r5=%016x r6=%016x r7=%016x r8=%016x r9=%016x",
                                 cpu.rf[4], cpu.rf[5], cpu.rf[6], cpu.rf[7], cpu.rf[8], cpu.rf[9]);
                        $display("  r22=%016x r23=%016x r24=%016x r25=%016x r26=%016x ret0=%016x",
                                 cpu.rf[22], cpu.rf[23], cpu.rf[24], cpu.rf[25], cpu.rf[26], cpu.rf[28]);
                        $display("  percpu_pa=%016x umem[percpu]=%016x umem[percpu+1]=%016x",
                                 slub512_percpu_pa, cpu.umem[slub512_percpu_pa >> 3],
                                 cpu.umem[(slub512_percpu_pa >> 3) + 1]);
                    end
                    // Arm memory watch on EVERY freelist change (not just slow path)
                    // Watch the next pointer slot (obj + s->offset=0x100) of the new freelist head
                    if (cur_freelist != 64'h0 && cur_freelist >= 64'h40000000) begin
                        memwatch_pa <= (cur_freelist - 64'h40000000) + 64'h100;
                        memwatch_prev <= cpu.umem[((cur_freelist - 64'h40000000) + 64'h100) >> 3];
                        memwatch_armed <= 1;
                        $display("[%0d] MEMWATCH_ARM: freelist=%016x watch_pa=%016x initial_val=%016x",
                                 cycle_count, cur_freelist,
                                 (cur_freelist - 64'h40000000) + 64'h100,
                                 cpu.umem[((cur_freelist - 64'h40000000) + 64'h100) >> 3]);
                    end
                    slub512_prev_freelist <= cur_freelist;
                end
            end
            // Hardware store watchpoint on per-CPU freelist address for kmalloc-512
            if (slub512_watch_armed && store_enable) begin
                // Check if the store targets the per-CPU freelist word (8 bytes at slub512_percpu_pa)
                if (cpu_write_addr[31:3] == slub512_percpu_pa[31:3]) begin
                    $display("[%0d] SLUB512_PERCPU_STORE: addr=%08x data=%016x PC=%016x PSW=%016x r2=%016x",
                             cycle_count, cpu_write_addr, cpu_write_data64,
                             cpu.pc_rd, cpu.psw, cpu.rf[2]);
                end
            end
            // Slab page store watchpoint: trace ALL stores to the first kmalloc-512 slab page
            // Arm when first ___slab_alloc (0x40273eb0) is entered for kmalloc-512
            if (cpu.pc_rd == 64'h0000000040273eb0 && cpu.rf[26] == 64'h0000000040801600 && !slab_page_watch_armed) begin
                slab_page_watch_armed <= 1;
                slab_page_store_count <= 0;
                $display("[%0d] SLAB_PAGE_WATCH: arming for first kmalloc-512 slab alloc, s=%016x",
                         cycle_count, cpu.rf[26]);
            end
            // At ___slab_alloc return (0x40274638, copy r6,ret0), capture slab start from r6
            if (cpu.pc_rd == 64'h0000000040274638 && slab_page_watch_armed && slab_page_watch_pfn == 20'h0) begin
                slab_page_watch_pfn <= (cpu.rf[6] - 64'h40000000) >> 12;
                $display("[%0d] SLAB_PAGE_WATCH_PFN: slab_va=%016x slab_pa=%016x pfn=%05x",
                         cycle_count, cpu.rf[6], cpu.rf[6] - 64'h40000000,
                         (cpu.rf[6] - 64'h40000000) >> 12);
                // Dump the first few freelist pointer locations in the slab page
                begin
                    reg [63:0] slab_pa;
                    slab_pa = cpu.rf[6] - 64'h40000000;
                    $display("[%0d] SLAB_DUMP: obj0+100=%016x obj1+100=%016x obj2+100=%016x obj3+100=%016x",
                             cycle_count,
                             cpu.umem[(slab_pa + 64'h100) >> 3],
                             cpu.umem[(slab_pa + 64'h300) >> 3],
                             cpu.umem[(slab_pa + 64'h500) >> 3],
                             cpu.umem[(slab_pa + 64'h700) >> 3]);
                    $display("[%0d] SLAB_DUMP: obj0+000=%016x obj1+000=%016x obj2+000=%016x obj3+000=%016x",
                             cycle_count,
                             cpu.umem[(slab_pa) >> 3],
                             cpu.umem[(slab_pa + 64'h200) >> 3],
                             cpu.umem[(slab_pa + 64'h400) >> 3],
                             cpu.umem[(slab_pa + 64'h600) >> 3]);
                end
            end
            // Log stores to the slab page (limited to first 100)
            if (slab_page_watch_armed && slab_page_watch_pfn != 20'h0 && store_enable &&
                cpu_write_addr[31:12] == slab_page_watch_pfn && slab_page_store_count < 100) begin
                slab_page_store_count <= slab_page_store_count + 1;
                $display("[%0d] SLAB_STORE[%0d]: addr=%08x data=%016x PC=%016x instr=%08x r2=%016x",
                         cycle_count, slab_page_store_count, cpu_write_addr, cpu_write_data64,
                         cpu.pc_rd,
                         cpu.pc_rd[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.rf[2]);
            end
            // Memory watchpoint: detect writes to the watched address
            if (memwatch_armed) begin
                reg [63:0] cur_memval;
                cur_memval = cpu.umem[memwatch_pa >> 3];
                if (cur_memval != memwatch_prev) begin
                    $display("[%0d] MEMWATCH_HIT: pa=%016x old=%016x new=%016x PC=%016x PSW=%016x SP=%016x r2=%016x",
                             cycle_count, memwatch_pa, memwatch_prev, cur_memval,
                             cpu.pc_rd, cpu.psw, cpu.rf[30], cpu.rf[2]);
                    // Check if new value is a bad freelist pointer
                    if (cur_memval != 64'h0 && cur_memval[8:0] != 9'h0 &&
                        cur_memval >= 64'h40000000 && cur_memval < 64'h44000000) begin
                        $display("[%0d] *** MEMWATCH_BAD_NEXT: %016x is NOT 512-byte aligned! Likely freelist corruption ***",
                                 cycle_count, cur_memval);
                        $display("  store_enable=%b write_addr=%08x write_data=%016x",
                                 store_enable, cpu_write_addr, cpu_write_data64);
                    end
                    memwatch_prev <= cur_memval;
                end
            end
            // Watch stores to the task_struct per-CPU data region (PA 0x0ee6a0-0x0ee6b7)
            if (store_enable && cpu_write_addr >= 32'h000ee6a0 && cpu_write_addr < 32'h000ee6b8) begin
                $display("[%0d] TASK_PCPU_STORE: addr=%08x data=%016x PC=%016x r2=%016x r5=%016x r10=%016x",
                         cycle_count, cpu_write_addr, cpu_write_data64, cpu.pc_rd, cpu.rf[2], cpu.rf[5], cpu.rf[10]);
            end
            // Trace ALL ___slab_alloc "install new slab" writes: std r17,10(r10) at 0x40274618
            // This dumps cache (r5), cpu_slab (r10), and slab page (r17)
            if (cpu.pc_rd == 64'h0000000040274618) begin
                $display("[%0d] SLAB_INSTALL: cache(r5)=%016x cpu_slab(r10)=%016x slab_page(r17)=%016x",
                         cycle_count, cpu.rf[5], cpu.rf[10], cpu.rf[17]);
                // Flag overlapping cpu_slab addresses
                if (cpu.rf[10] >= 64'h00000000400ee6a0 && cpu.rf[10] < 64'h00000000400ee6c0 && cpu.rf[5] != 64'h0000000040802540) begin
                    $display("[%0d] *** OVERLAP_DETECTED: cache %016x has cpu_slab %016x in task_struct range! ***",
                             cycle_count, cpu.rf[5], cpu.rf[10]);
                end
            end
            // Trace __bitmap_set entry: PC=0x403b11a0, r26=map, r25=start, r24=nbits
            if (cpu.pc_rd == 64'h00000000403b11a0) begin
                $display("[%0d] BITMAP_SET: map=%016x start=%0d nbits=%0d  r2=%016x  bm6=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2],
                         cpu.umem[64'h0ec250 >> 3]);
            end
            // Trace STD inside __bitmap_set single-word path: PC=0x403b1210
            if (cpu.pc_rd == 64'h00000000403b1210) begin
                $display("[%0d] BM_STD: addr(r26)=%016x val(ret0)=%016x r31=%016x mask=%016x SAR=%0d",
                         cycle_count, cpu.rf[26], cpu.rf[28], cpu.rf[31],
                         cpu.rf[28] & ~cpu.rf[31], cpu.sar);
            end
            // Trace STD inside __bitmap_set multi-word path: PC=0x403b122c
            if (cpu.pc_rd == 64'h000000004003b122c) begin
                $display("[%0d] BM_STD_MW: addr(r26-8)=%016x val(ret0)=%016x",
                         cycle_count, cpu.rf[26] - 64'h8, cpu.rf[28]);
            end
            // At MTSAR (0x403b11fc): trace what SAR is being set to
            if (cpu.pc_rd == 64'h00000000403b11fc) begin
                $display("[%0d] BM_MTSAR: r24=%016x r24[5:0]=%0d SAR_before=%0d",
                         cycle_count, cpu.rf[24], cpu.rf[24][5:0], cpu.sar);
            end
            // At SHRPD (0x403b1200): trace SAR and inputs BEFORE execution
            if (cpu.pc_rd == 64'h00000000403b1200) begin
                $display("[%0d] BM_SHRPD_IN: SAR=%0d ret0=%016x r0=%016x null=%0d",
                         cycle_count, cpu.sar, cpu.rf[28], cpu.rf[0], cpu.in_nullified);
            end
            // After SHRPD at 0x403b1204 (AND is next)
            if (cpu.pc_rd == 64'h00000000403b1204) begin
                $display("[%0d] BM_SHRPD: shrpd_result(ret0)=%016x left_mask(r31)=%016x SAR=%0d",
                         cycle_count, cpu.rf[28], cpu.rf[31], cpu.sar);
            end
            // Trace pcpu_alloc_noprof return: PC=0x40232b08, ret0=result
            if (cpu.pc_rd == 64'h0000000040232b08) begin
                $display("[%0d] PCPU_ALLOC_RET: ret0=%016x  r2=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[2]);
            end
            // Trace pcpu_alloc_area return: PC=0x40232470, ret0=result (r6<<2)
            if (cpu.pc_rd == 64'h0000000040232470) begin
                $display("[%0d] PCPU_AREA_RET: ret0=%016x  r6=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[6]);
            end
            // Also dump at specific cycles for debugging
            if (cycle_count == 6460320 || cycle_count == 7500000 || cycle_count == 19245120) begin
                $display("[%0d] TASK_PCPU_DUMP: umem[0ee6a0>>3]=%016x umem[0ee6a8>>3]=%016x umem[0ee6b0>>3]=%016x",
                         cycle_count,
                         cpu.umem[64'h0ee6a0 >> 3],
                         cpu.umem[64'h0ee6a8 >> 3],
                         cpu.umem[64'h0ee6b0 >> 3]);
            end
            // Trace at 0x402750b0: ldd 0(r22),r6 - loads freelist from cpu_slab
            if (cpu.pc_rd == 64'h00000000402750b0 && cpu.rf[5] == 64'h0000000040802540) begin
                reg [63:0] cs_va, cs_pa;
                cs_va = cpu.rf[22];
                cs_pa = cs_va - 64'h40000000;
                $display("[%0d] TASK_SLUB_FL: cpu_slab=%016x(r22) umem[cs+0]=%016x umem[cs+8]=%016x umem[cs+10]=%016x",
                         cycle_count, cs_va, cpu.umem[cs_pa >> 3],
                         cpu.umem[(cs_pa + 64'h8) >> 3],
                         cpu.umem[(cs_pa + 64'h10) >> 3]);
            end
            // SLUB fast path: after reading next freelist ptr (0x402751f0)
            // ldd ret0(r6),r7: ret0=s->offset, r6=current object, r7=next object
            if (cpu.pc_rd == 64'h00000000402751f0) begin
                // Log for task_struct cache (r5=0x40802540)
                if (cpu.rf[5] == 64'h0000000040802540) begin
                    $display("[%0d] SLUB_FAST_TASK: offset(ret0)=%016x object(r6)=%016x next(r7)=%016x r2=%016x",
                             cycle_count, cpu.rf[28], cpu.rf[6], cpu.rf[7], cpu.rf[2]);
                end
                // Only log for kmalloc-512 (r5=0x40801600)
                if (cpu.rf[5] == 64'h0000000040801600) begin
                    // Compute expected PA for the freelist read: VA = object + offset, PA = VA - PAGE_OFFSET
                    begin
                        reg [63:0] expected_va, expected_pa, umem_val;
                        expected_va = cpu.rf[6] + cpu.rf[28];  // object + s->offset
                        expected_pa = expected_va - 64'h40000000;
                        umem_val = cpu.umem[expected_pa >> 3];
                        $display("[%0d] SLUB_FAST_NEXT512: offset(ret0)=%016x object(r6)=%016x next(r7)=%016x r2=%016x",
                                 cycle_count, cpu.rf[28], cpu.rf[6], cpu.rf[7], cpu.rf[2]);
                        $display("  expected_va=%016x expected_pa=%016x umem_at_pa=%016x %s",
                                 expected_va, expected_pa, umem_val,
                                 (umem_val == cpu.rf[7]) ? "MATCH" : "***MISMATCH***");
                        // Also compare with value at nearby PAs to detect address shifts
                        $display("  umem_at_pa-8=%016x umem_at_pa+8=%016x umem_at_obj+100=%016x",
                                 cpu.umem[(expected_pa >> 3) - 1],
                                 cpu.umem[(expected_pa >> 3) + 1],
                                 cpu.umem[((cpu.rf[6] - 64'h40000000 + 64'h100) >> 3)]);
                    end
                    // Check if the next pointer is misaligned
                    if (cpu.rf[7] != 64'h0 && cpu.rf[7][8:0] != 9'h0) begin
                        $display("[%0d] *** BAD_NEXT_PTR: next=%016x from offset %016x of object %016x ***",
                                 cycle_count, cpu.rf[7], cpu.rf[28], cpu.rf[6]);
                        // Dump the memory around the read address
                        begin
                            reg [63:0] read_pa;
                            read_pa = (cpu.rf[6] - 64'h40000000) + cpu.rf[28];
                            $display("  read_pa=%016x umem[pa>>3]=%016x umem[pa>>3+1]=%016x",
                                     read_pa, cpu.umem[read_pa >> 3], cpu.umem[(read_pa >> 3) + 1]);
                            $display("  obj_pa=%016x umem[obj]=%016x umem[obj+1]=%016x umem[obj+2]=%016x",
                                     cpu.rf[6] - 64'h40000000,
                                     cpu.umem[(cpu.rf[6] - 64'h40000000) >> 3],
                                     cpu.umem[((cpu.rf[6] - 64'h40000000) >> 3) + 1],
                                     cpu.umem[((cpu.rf[6] - 64'h40000000) >> 3) + 2]);
                        end
                    end
                end
            end
            // kmem_cache_alloc_node_noprof entry (0x40275020)
            if (cpu.pc_rd == 64'h0000000040275020) begin
                $display("[%0d] SLUB_ALLOC_ENTRY: r26(s)=%016x r25(gfp)=%016x r24(node)=%016x r2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2]);
            end
            // kmem_cache_free entry (0x40277330) - trace frees to task_struct cache
            if (cpu.pc_rd == 64'h0000000040277330) begin
                if (cpu.rf[26] == 64'h0000000040802540) begin
                    $display("[%0d] SLUB_FREE_TASK: r26(s)=%016x r25(obj)=%016x r2(caller)=%016x obj_mod=%04x",
                             cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2], cpu.rf[25][15:0]);
                end
            end
            // kmem_cache_free entry (0x40277330) - trace frees to kmalloc-512
            if (cpu.pc_rd == 64'h0000000040277330) begin
                if (cpu.rf[26] == 64'h0000000040801600) begin
                    $display("[%0d] SLUB_FREE_512: r26(s)=%016x r25(obj)=%016x r2(caller)=%016x low8=%02x",
                             cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2], cpu.rf[25][7:0]);
                end
            end
            // kfree entry (0x40276878) - trace all kfree calls
            if (cpu.pc_rd == 64'h0000000040276878) begin
                $display("[%0d] KFREE_ENTRY: r26(obj)=%016x r2(caller)=%016x low8=%02x",
                         cycle_count, cpu.rf[26], cpu.rf[2], cpu.rf[26][7:0]);
            end
            // Resolve mem_map base address (at VA 0x4072de28 = PA 0x72de28)
            // mem_map is a pointer; read it once after paging_init
            if (!mem_map_resolved && cycle_count > 1000000) begin
                reg [63:0] mm_val;
                mm_val = cpu.umem[64'h72de28 >> 3];
                if (mm_val != 64'h0 && mm_val != mem_map_base) begin
                    mem_map_base <= mm_val;
                    mem_map_resolved <= 1;
                    $display("[%0d] MEM_MAP_RESOLVED: mem_map=%016x", cycle_count, mm_val);
                end
            end
            // __alloc_pages_noprof entry (0x4026d130): save order and log
            if (cpu.pc_rd == 64'h000000004026d130) begin
                alloc_pages_order <= cpu.rf[25];  // r25 = order (before extrd,u)
                alloc_pages_active <= 1;
            end
            // __alloc_pages_noprof return path (0x4026d1d0): r12 = struct page* result
            // sizeof(struct page) = 56 (0x38) on this config!
            if (cpu.pc_rd == 64'h000000004026d1d0 && mem_map_resolved) begin
                reg [63:0] page_ptr, page_offset, pfn, phys, alloc_end;
                page_ptr = cpu.rf[12];
                alloc_pages_active <= 0;
                if (page_ptr != 64'h0 && page_ptr > mem_map_base) begin
                    page_offset = page_ptr - mem_map_base;
                    // Division by 56: pfn = page_offset / 56
                    // 56 = 8*7, so divide by 8 then by 7
                    pfn = (page_offset / 56);
                    phys = pfn << 12;  // PAGE_SIZE = 4096
                    alloc_end = phys + (64'h1000 << alloc_pages_order[3:0]);
                    // Log all allocations that include pages 0x8d8000-0x8e0000
                    if (phys < 64'h8e0000 && alloc_end > 64'h8d8000) begin
                        $display("[%0d] ALLOC_PAGES_HIT: page=%016x pfn=0x%0x phys=%016x order=%0d caller=%016x",
                                 cycle_count, page_ptr, pfn, phys, alloc_pages_order[3:0], cpu.rf[2]);
                    end
                end
            end
            // Also check the second return path at 0x4026ded4
            if (cpu.pc_rd == 64'h000000004026ded4 && mem_map_resolved) begin
                reg [63:0] page_ptr2, page_offset2, pfn2, phys2, alloc_end2;
                page_ptr2 = cpu.rf[12];
                alloc_pages_active <= 0;
                if (page_ptr2 != 64'h0 && page_ptr2 > mem_map_base) begin
                    page_offset2 = page_ptr2 - mem_map_base;
                    pfn2 = (page_offset2 / 56);
                    phys2 = pfn2 << 12;
                    alloc_end2 = phys2 + (64'h1000 << alloc_pages_order[3:0]);
                    if (phys2 < 64'h8e0000 && alloc_end2 > 64'h8d8000) begin
                        $display("[%0d] ALLOC_PAGES_HIT2: page=%016x pfn=0x%0x phys=%016x order=%0d caller=%016x",
                                 cycle_count, page_ptr2, pfn2, phys2, alloc_pages_order[3:0], cpu.rf[2]);
                    end
                end
            end
            // __free_pages entry (0x4026c068): r26 = page, r25 = order
            if (cpu.pc_rd == 64'h000000004026c068 && mem_map_resolved) begin
                reg [63:0] free_offset, free_pfn, free_phys, free_end;
                if (cpu.rf[26] > mem_map_base) begin
                    free_offset = cpu.rf[26] - mem_map_base;
                    free_pfn = (free_offset / 56);
                    free_phys = free_pfn << 12;
                    free_end = free_phys + (64'h1000 << cpu.rf[25][3:0]);
                    if (free_phys < 64'h8e0000 && free_end > 64'h8d8000) begin
                        $display("[%0d] FREE_PAGES_HIT: page=%016x pfn=0x%0x phys=%016x order=%0d caller=%016x",
                                 cycle_count, cpu.rf[26], free_pfn, free_phys, cpu.rf[25][3:0], cpu.rf[2]);
                    end
                end
            end
            // === SLAB ORDER DEBUGGING ===
            // Trace ALL non-zero-order calls to __alloc_pages_noprof
            if (cpu.pc_rd == 64'h000000004026d130 && cpu.rf[25][31:0] > 0 && cpu.rf[25][31:0] < 20) begin
                $display("[%0d] ALLOC_ORDER_GT0: gfp=%08x order=%0d nid=%0d caller=%016x",
                         cycle_count, cpu.rf[26][31:0], cpu.rf[25][31:0], cpu.rf[24][31:0], cpu.rf[2]);
            end
            // Trace new_slab entry (0x40272948)
            if (cpu.pc_rd == 64'h0000000040272948) begin
                $display("[%0d] NEW_SLAB_ENTRY: s=%016x flags=%016x node=%016x caller=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2]);
            end
            // Trace at depd,z before first alloc_slab_page call in new_slab (0x40272a3c)
            // At this PC, r7=s->oo (loaded), r24=about to be set to oo<<32
            if (cpu.pc_rd == 64'h0000000040272a3c) begin
                $display("[%0d] NEW_SLAB_OO_DEPD: r7(oo)=%08x r24(before)=%016x r5(s)=%016x",
                         cycle_count, cpu.rf[7][31:0], cpu.rf[24], cpu.rf[5]);
            end
            // After depd,z at 0x40272a40: r24 should have oo<<32
            if (cpu.pc_rd == 64'h0000000040272a40) begin
                $display("[%0d] NEW_SLAB_OO_AFTER: r24(oo<<32)=%016x r7=%016x",
                         cycle_count, cpu.rf[24], cpu.rf[7]);
            end
            // Trace at fallback depd,z for s->min (0x40272a6c)
            if (cpu.pc_rd == 64'h0000000040272a6c) begin
                $display("[%0d] NEW_SLAB_MIN_DEPD: r7(min)=%08x r24(before)=%016x",
                         cycle_count, cpu.rf[7][31:0], cpu.rf[24]);
            end
            // alloc_slab_page entry (0x402718b0): r26=flags, r25=node, r24=oo(shifted)
            if (cpu.pc_rd == 64'h00000000402718b0) begin
                $display("[%0d] ALLOC_SLAB_PAGE: r26(flags)=%016x r25(node)=%016x r24(oo<<32)=%016x caller=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2]);
            end
            // After extrd,u extracts order in alloc_slab_page (0x402718d8)
            if (cpu.pc_rd == 64'h00000000402718d8) begin
                $display("[%0d] ALLOC_SLAB_ORDER: r24(order)=%016x ret0(flags_ze)=%016x",
                         cycle_count, cpu.rf[24], cpu.rf[28]);
            end

            // copy_process entry (0x40179670) - trace fork
            if (cpu.pc_rd == 64'h0000000040179670) begin
                $display("[%0d] COPY_PROCESS: r2(caller)=%016x", cycle_count, cpu.rf[2]);
            end
            // dup_task_struct (arch_dup_task_struct at 0x40178bb8) - trace task alloc
            if (cpu.pc_rd == 64'h0000000040178bb8) begin
                $display("[%0d] ARCH_DUP_TASK: r26(dst)=%016x r25(src)=%016x r2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end
            // Dump task_struct cache properties once
            // Cache at VA 0x40802540 = PA 0x802540 (PAGE_OFFSET=0x40000000)
            if (cycle_count == 7000000 && mem_map_resolved) begin
                // Dump raw 64-bit words at the task_struct cache VA 0x40802540 PA 0x802540
                $display("[%0d] TASK_CACHE (PA=0x802540) raw dump:", cycle_count);
                $display("  +00: %016x  +08: %016x  +10: %016x  +18: %016x",
                         cpu.umem[64'h802540 >> 3], cpu.umem[64'h802548 >> 3],
                         cpu.umem[64'h802550 >> 3], cpu.umem[64'h802558 >> 3]);
                $display("  +20: %016x  +28: %016x  +30: %016x  +38: %016x",
                         cpu.umem[64'h802560 >> 3], cpu.umem[64'h802568 >> 3],
                         cpu.umem[64'h802570 >> 3], cpu.umem[64'h802578 >> 3]);
                $display("  +40: %016x  +48: %016x  +50: %016x  +58: %016x",
                         cpu.umem[64'h802580 >> 3], cpu.umem[64'h802588 >> 3],
                         cpu.umem[64'h802590 >> 3], cpu.umem[64'h802598 >> 3]);
                $display("  +60: %016x  +68: %016x  +70: %016x  +78: %016x",
                         cpu.umem[64'h8025a0 >> 3], cpu.umem[64'h8025a8 >> 3],
                         cpu.umem[64'h8025b0 >> 3], cpu.umem[64'h8025b8 >> 3]);
                // Decoded task_struct cache:
                // size(0x18h32)=0x960, obj_size(0x1ch32)=0x950, oo encodes order and objects count
                // For order-1 (2 pages=8192), objects = 8192/0x960 = 3, oo=0x30001
                $display("  Decoded: size=%0d obj_size=%0d offset=%0d",
                         cpu.umem[64'h802558 >> 3][63:32],
                         cpu.umem[64'h802558 >> 3][31:0],
                         cpu.umem[64'h802568 >> 3][63:32]);
                // Read oo field - need to figure out exact offset
                // Also dump kmalloc-512 similarly
                $display("[%0d] KMALLOC512_CACHE (PA=0x801600) raw dump:", cycle_count);
                $display("  +00: %016x  +08: %016x  +10: %016x  +18: %016x",
                         cpu.umem[64'h801600 >> 3], cpu.umem[64'h801608 >> 3],
                         cpu.umem[64'h801610 >> 3], cpu.umem[64'h801618 >> 3]);
                $display("  +20: %016x  +28: %016x  +30: %016x  +38: %016x",
                         cpu.umem[64'h801620 >> 3], cpu.umem[64'h801628 >> 3],
                         cpu.umem[64'h801630 >> 3], cpu.umem[64'h801638 >> 3]);
            end
            if (cpu.pc_rd == 64'h0000000040106908)  // paging_init
                $display("[%0d] PAGING_INIT: SP=%016x R2=%016x",
                         cycle_count, cpu.rf[30], cpu.rf[2]);

            // __next_mem_pfn_range loop trace (first 50 calls)
            if (cpu.pc_rd == 64'h000000004011b528 && next_memfn_count < 50) begin
                next_memfn_count <= next_memfn_count + 1;
                // R26 = &idx, R25 = nid, R24 = &start_pfn, R23 = &end_pfn
                $display("[%0d] NEXT_MEM_PFN[%0d]: R26(idx_ptr)=%016x R25(nid)=%016x SP=%016x R2(caller)=%016x",
                         cycle_count, next_memfn_count, cpu.rf[26], cpu.rf[25], cpu.rf[30], cpu.rf[2]);
            end
            // Trace the cmpb that checks cnt vs idx at 0x4011b550
            if (cpu.pc_rd == 64'h000000004011b550 && next_memfn_cmp_count < 50) begin
                next_memfn_cmp_count <= next_memfn_cmp_count + 1;
                // R31 = cnt, ret0 = idx (after sign-extend)
                $display("[%0d] MEMFN_CMP[%0d]: cnt(R31)=%016x idx(ret0)=%016x idx_ptr(R26)=%016x",
                         cycle_count, next_memfn_cmp_count, cpu.rf[31], cpu.rf[28], cpu.rf[26]);
            end
            // free_area_init idx check at 0x40114a5c
            if (cpu.pc_rd == 64'h000000004011b558 && next_memfn_cmp_count <= 50) begin
                // ret0 was just set to -1 (loop exhausted)
                $display("[%0d] MEMFN_EXHAUST: idx set to -1",
                         cycle_count);
            end

            // Debug: trace ADDL execution (DISABLED - too verbose)
            // if (cpu.addl_enable) begin
            //     $display("[%0d] ADDL: PC=%016x R1=%016x R29=%016x add_res=%016x rfwr=%b null=%b trap=%b",
            //              cycle_count, cpu.pc_rd, cpu.rf[1], cpu.rf[29], cpu.add_res,
            //              cpu.rf_add_t_ne_0_and_invinstr_trap_taken_and_invin_nullified_guarded_enable,
            //              cpu.in_nullified, cpu.instr_trap_taken);
            // end
            // Periodic state dump during DTLB handler loop
            if (cpu.pc_rd >= 64'h150000 && cpu.pc_rd < 64'h160000 && (cycle_count % 50000 == 0)) begin
                $display("[%0d] PERIODIC: PC=%016x PSW=%016x SP=%016x R1=%016x R29=%016x CR18=%016x",
                         cycle_count, cpu.pc_rd, cpu.psw, cpu.rf[30],
                         cpu.rf[1], cpu.rf[29], cpu.cr18_rd);
            end
            // Unwind loop debug: trace R22 (loop counter), R6, R7 (end), R28 (ret0), R5 (base)
            if (cpu.pc_rd == 64'h4016609c && (cycle_count % 100000 == 0)) begin
                $display("[%0d] UNWIND: PC=%016x R22=%016x R6=%016x R7=%016x R28(ret0)=%016x R5=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf[22], cpu.rf[6], cpu.rf[7], cpu.rf[28], cpu.rf[5]);
            end

            // PDC result buffer memory monitor (disabled for speed)
            // if (cpu.umem_write_enable && cpu.pc_rd[31:12] == 20'h0F000) begin
            //     $display("[%0d] FW_STORE: ...");
            // end

            // Trace execution in start_parisc FPU check area (0x10105c54-0x10105d10)
            if (cpu.pc_rd >= 64'h10105c54 && cpu.pc_rd <= 64'h10105d10 && start_parisc_trace_count < 200) begin
                start_parisc_trace_count <= start_parisc_trace_count + 1;
                $display("[%0d] START_PARISC: PC=%016x PSW=%016x R3=%016x R28=%016x R19=%016x SP=%016x instr=%08x",
                         cycle_count, cpu.pc_rd, cpu.psw,
                         cpu.rf[3], cpu.rf[28], cpu.rf[19], cpu.rf[30],
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32]);
            end

            // RFI instruction trace - near end of boot
            if ((cpu.rfi_enable || cpu.rfir_enable) && cycle_count > 97000000) begin
                $display("[%0d] RFI: PC=%016x CR17=%016x CR17_back=%016x CR18=%016x CR18_back=%016x CR22=%016x code_iasq=%016x code_iasq_wr=%016x sel_cr17=%0b sel_exc=%0b sel_ds=%0b",
                         cycle_count, cpu.pc_rd, cpu.cr17_rd, cpu.cr17_back_rd,
                         cpu.cr18_rd, cpu.cr18_back_rd, cpu.cr22_rd,
                         cpu.code_iasq, cpu.code_iasq_wr_mux,
                         cpu.select_cr17_rd_code_iasq_merged,
                         cpu.select_64_h0_code_iasq_merged,
                         cpu.select_branch_target_space_code_iasq_merged);
            end

            // Trace MTCTL to CR17 - show queue push details
            if (cpu.mtctl_enable && cpu.instr[25:21] == 5'd17 && cycle_count > 97000000) begin
                $display("[%0d] MTCTL_CR17: PC=%016x src_reg=%0d value=%016x cr17=%016x cr17_back=%016x cr17_wr=%016x cr17_back_wr=%016x mux_or_0=%0b",
                         cycle_count, cpu.pc_rd, cpu.instr[20:16],
                         (cpu.instr[20:16] == 5'd0) ? 64'h0 : cpu.rf[cpu.instr[20:16]],
                         cpu.cr17_rd, cpu.cr17_back_rd,
                         cpu.cr17_wr_mux, cpu.cr17_back_wr_mux,
                         cpu.cr17_wr_mux_or_0);
            end

            // Trace code_iasq changes
            if (cpu.code_iasq_wr_mux != cpu.code_iasq && cycle_count > 97000000) begin
                $display("[%0d] CODE_IASQ_CHANGE: PC=%016x old=%016x new=%016x sel_exc=%0b sel_ds=%0b sel_rfi=%0b",
                         cycle_count, cpu.pc_rd, cpu.code_iasq, cpu.code_iasq_wr_mux,
                         cpu.select_64_h0_code_iasq_merged,
                         cpu.select_branch_target_space_code_iasq_merged,
                         cpu.select_cr17_rd_code_iasq_merged);
            end

            // Trace ITLB miss exception
            if (cpu.exception_taken && cpu.itlb_miss && cycle_count > 97000000) begin
                $display("[%0d] ITLB_MISS: PC=%016x code_iasq=%016x cr17=%016x cr18=%016x",
                         cycle_count, cpu.pc_rd, cpu.code_iasq, cpu.cr17_rd, cpu.cr18_rd);
            end

            // panic() entry trace (64-bit: 0x4049ba00)
            if (cpu.pc_rd == 64'h000000004049ba00 && panic_trace_count < 5) begin
                panic_trace_count <= panic_trace_count + 1;
                $display("[%0d] PANIC_ENTRY: PC=%016x R26(msg)=%016x R2(caller)=%016x SP=%016x PSW=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf[26], cpu.rf[2], cpu.rf[30], cpu.psw);
                // Dump panic message string from memory (VA -> PA via BTLB: PA = VA - 0x40000000)
                begin
                    reg [63:0] msg_pa;
                    reg [63:0] word_data;
                    msg_pa = cpu.rf[26] - 64'h40000000;
                    $write("[%0d] PANIC_MSG: \"", cycle_count);
                    for (integer bi = 0; bi < 128; bi = bi + 1) begin
                        word_data = cpu.umem[(msg_pa + bi) >> 3];
                        // Extract byte from big-endian 64-bit word
                        case ((msg_pa + bi) & 7)
                            0: if (word_data[63:56] == 0) bi = 128; else $write("%c", word_data[63:56]);
                            1: if (word_data[55:48] == 0) bi = 128; else $write("%c", word_data[55:48]);
                            2: if (word_data[47:40] == 0) bi = 128; else $write("%c", word_data[47:40]);
                            3: if (word_data[39:32] == 0) bi = 128; else $write("%c", word_data[39:32]);
                            4: if (word_data[31:24] == 0) bi = 128; else $write("%c", word_data[31:24]);
                            5: if (word_data[23:16] == 0) bi = 128; else $write("%c", word_data[23:16]);
                            6: if (word_data[15:8]  == 0) bi = 128; else $write("%c", word_data[15:8]);
                            7: if (word_data[7:0]   == 0) bi = 128; else $write("%c", word_data[7:0]);
                        endcase
                    end
                    $display("\"");
                end
                // Dump caller function context
                $display("[%0d] PANIC_REGS: R23=%016x R24=%016x R25=%016x R3=%016x R4=%016x R5=%016x",
                         cycle_count, cpu.rf[23], cpu.rf[24], cpu.rf[25], cpu.rf[3], cpu.rf[4], cpu.rf[5]);
            end

            // vsnprintf entry trace (0x4048fcc8)
            // int vsnprintf(char *buf, size_t size, const char *fmt, va_list args)
            if (cpu.pc_rd == 64'h4048fcc8 && vsnprintf_trace_count < 10) begin
                vsnprintf_trace_count <= vsnprintf_trace_count + 1;
                $display("[%0d] VSNPRINTF: R26(buf)=%016x R25(size)=%016x R24(fmt)=%016x R23(args)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[23], cpu.rf[2]);
                // Dump format string (VA -> PA via BTLB: PA = VA - 0x40000000)
                begin
                    reg [63:0] fmt_pa;
                    reg [63:0] word_data;
                    fmt_pa = cpu.rf[24] - 64'h40000000;
                    $write("[%0d] FMT: \"", cycle_count);
                    for (integer fi = 0; fi < 128; fi = fi + 1) begin
                        word_data = cpu.umem[(fmt_pa + fi) >> 3];
                        case ((fmt_pa + fi) & 7)
                            0: if (word_data[63:56] == 0) fi = 128; else $write("%c", word_data[63:56]);
                            1: if (word_data[55:48] == 0) fi = 128; else $write("%c", word_data[55:48]);
                            2: if (word_data[47:40] == 0) fi = 128; else $write("%c", word_data[47:40]);
                            3: if (word_data[39:32] == 0) fi = 128; else $write("%c", word_data[39:32]);
                            4: if (word_data[31:24] == 0) fi = 128; else $write("%c", word_data[31:24]);
                            5: if (word_data[23:16] == 0) fi = 128; else $write("%c", word_data[23:16]);
                            6: if (word_data[15:8]  == 0) fi = 128; else $write("%c", word_data[15:8]);
                            7: if (word_data[7:0]   == 0) fi = 128; else $write("%c", word_data[7:0]);
                        endcase
                    end
                    $display("\"");
                end
            end

            // vprintk_store return trace (catches corrupted rp)
            if (cpu.pc_rd == 64'h10453990) begin
                $display("[%0d] VPRINTK_RET: bv rp=%016x SP=%016x R3=%016x",
                         cycle_count, cpu.rf[2], cpu.rf[30], cpu.rf[3]);
            end

            // widen_string entry trace (0x1063a1bc)
            if (cpu.pc_rd == 64'h1063a1bc) begin
                $display("[%0d] WIDEN_STR: R26(buf)=%016x R25(written)=%016x R24(end-buf)=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2]);
            end
            // widen_string after ldw -38(r3),r4 at 0x1063a1d4 (raw spec)
            if (cpu.pc_rd == 64'h1063a1d8) begin
                $display("[%0d] WIDEN_SPEC_RAW: R4(raw_spec)=%016x R3=%016x",
                         cycle_count, cpu.rf[4], cpu.rf[3]);
            end
            // widen_string after extrw,s at 0x1063a1dc (r4 = field_width extracted)
            if (cpu.pc_rd == 64'h1063a1e0) begin
                $display("[%0d] WIDEN_FW: R4(field_width)=%016x R25(written)=%016x R26(buf)=%016x",
                         cycle_count, cpu.rf[4], cpu.rf[25], cpu.rf[26]);
            end
            // widen_string memset call at 0x1063a208
            if (cpu.pc_rd == 64'h1063a208) begin
                $display("[%0d] WIDEN_MEMSET: R26(dst)=%016x R25(val)=%016x R24(len)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24]);
            end

            // vsnprintf STR handler at 0x1063e128 (after spec loaded into ret0/ret1)
            // At this point: ret0=spec0, ret1=spec1, r4=va_list-4, r10=fmt
            if (cpu.pc_rd == 64'h1063e128) begin
                $display("[%0d] VSN_STR: ret0(spec0)=%016x ret1(spec1)=%016x R4(va_list)=%016x R10(fmt)=%016x R5(buf)=%016x R6(end)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[29], cpu.rf[4], cpu.rf[10], cpu.rf[5], cpu.rf[6]);
            end

            // string() entry (0x1063a4d4) - shows caller, string ptr, end, buf
            if (cpu.pc_rd == 64'h1063a4d4) begin
                $display("[%0d] STR_ENTRY: R2(caller)=%016x R26(buf)=%016x R25(end)=%016x R24(str)=%016x",
                         cycle_count, cpu.rf[2], cpu.rf[26], cpu.rf[25], cpu.rf[24]);
            end

            // string() spec load at 0x1063a4ec (after ldw -38(r3)/ldw -34(r3))
            if (cpu.pc_rd == 64'h1063a4ec) begin
                $display("[%0d] STR_SPEC: ret0(spec0)=%016x ret1(spec1)=%016x R3=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[29], cpu.rf[3]);
            end

            // string_nocheck entry (0x1063a280) - shows who called it
            if (cpu.pc_rd == 64'h1063a280) begin
                $display("[%0d] SNC_ENTRY: R2(caller)=%016x R26(buf)=%016x R25(end)=%016x R24(str)=%016x",
                         cycle_count, cpu.rf[2], cpu.rf[26], cpu.rf[25], cpu.rf[24]);
            end

            // string_nocheck loading spec for widen_string (0x1063a2ac)
            if (cpu.pc_rd == 64'h1063a2b4) begin
                $display("[%0d] SNC_SPEC: R19(spec0)=%016x R20(spec1)=%016x R3=%016x",
                         cycle_count, cpu.rf[19], cpu.rf[20], cpu.rf[3]);
            end

            // check_pointer entry (0x1063a33c)
            // check_pointer(char **buf, char *end, const void *ptr, struct printf_spec spec)
            if (cpu.pc_rd == 64'h1063a33c) begin
                $display("[%0d] CHKPTR: R2(caller)=%016x R26(buf_ptr)=%016x R25(end)=%016x R24(ptr)=%016x",
                         cycle_count, cpu.rf[2], cpu.rf[26], cpu.rf[25], cpu.rf[24]);
            end

            // vsnprintf entry (0x1063de60) - show fmt, buf, size
            if (cpu.pc_rd == 64'h1063de60) begin
                $display("[%0d] VSNPRINTF: R26(buf)=%016x R25(size)=%016x R24(fmt)=%016x R23(args)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[23], cpu.rf[2]);
            end

            // pointer() entry (0x1063d9ac)
            if (cpu.pc_rd == 64'h1063d9ac) begin
                $display("[%0d] POINTER: R26(fmt)=%016x R25(buf)=%016x R24(end)=%016x R23(ptr)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[23], cpu.rf[2]);
            end

            // Format decode return trace - shows what type format_decode returns
            // At 0x1063df30: r19 = spec.type, r11 = ret value (format len), r10 = fmt
            if (cpu.pc_rd == 64'h1063df30 && cycle_count > 440000 && cycle_count < 445000) begin
                $display("[%0d] FMT_DECODE: type=%0d len=%0d fmt=%016x",
                         cycle_count, cpu.rf[19], cpu.rf[11], cpu.rf[10]);
            end

            // Escaped_string entry trace (0x1063ac9c)
            if (cpu.pc_rd == 64'h1063ac9c) begin
                $display("[%0d] ESCAPED_STR: R2(caller)=%016x R26(buf)=%016x R25(end)=%016x R24(addr)=%016x",
                         cycle_count, cpu.rf[2], cpu.rf[26], cpu.rf[25], cpu.rf[24]);
            end

            // Trace put_dec_helper4 function (0x10639650-0x10639770) to debug fault
            if (cpu.pc_rd >= 64'h10639650 && cpu.pc_rd <= 64'h10639770) begin
                $display("[%0d] PDEC: PC=%016x instr=%08x R19=%016x R20=%016x R21=%016x R22=%016x R25=%016x R28=%016x R29=%016x null=%0d",
                         cycle_count, cpu.pc_rd,
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.rf[19], cpu.rf[20], cpu.rf[21], cpu.rf[22],
                         cpu.rf[25], cpu.rf[28], cpu.rf[29],
                         cpu.in_nullified);
            end

            // handle_interruption entry trace (64-bit: 0x40157ef8)
            if (cpu.pc_rd == 64'h40157ef8) begin
                reg [63:0] hndl_regs_pa;
                reg [63:0] hndl_iaoq0_pa;
                reg [63:0] hndl_ior_pa;
                reg [63:0] hndl_iir_pa;
                reg [5:0]  hndl_code;
                handle_int_trace_count <= handle_int_trace_count + 1;
                total_trap_count <= total_trap_count + 1;
                hndl_code = cpu.rf[26][5:0];
                if (hndl_code < 32)
                    trap_code_count[hndl_code] <= trap_code_count[hndl_code] + 1;
                // Detailed trace for first 200 entries
                if (handle_int_trace_count < 200) begin
                    reg [63:0] pt_gr25_pa, pt_gr26_pa, pt_gr28_pa, pt_gr29_pa;
                    reg [63:0] pt_gr7_pa, pt_gr1_pa;
                    hndl_regs_pa = cpu.rf[25] - 64'h40000000;
                    hndl_iaoq0_pa = hndl_regs_pa + 64'h250;  // pt_regs->iaoq[0] (64-bit: offset 592)
                    hndl_ior_pa = hndl_regs_pa + 64'h2A0;     // pt_regs->ior (64-bit: offset 672)
                    hndl_iir_pa = hndl_regs_pa + 64'h290;     // pt_regs->iir (64-bit: offset 656)
                    // Register offsets: PT_GR1=8, PT_GR7=56, PT_GR25=200, PT_GR26=208, PT_GR28=224, PT_GR29=232
                    pt_gr1_pa  = hndl_regs_pa + 64'h8;
                    pt_gr7_pa  = hndl_regs_pa + 64'h38;
                    pt_gr25_pa = hndl_regs_pa + 64'hC8;
                    pt_gr26_pa = hndl_regs_pa + 64'hD0;
                    pt_gr28_pa = hndl_regs_pa + 64'hE0;
                    pt_gr29_pa = hndl_regs_pa + 64'hE8;
                    $display("[%0d] HANDLE_INT: code=%0d R25(regs)=%016x R2=%016x SP=%016x",
                             cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2], cpu.rf[30]);
                    $display("        fault_pc(iaoq0)=%016x ior(fault_addr)=%016x iir=%08x",
                             cpu.umem[hndl_iaoq0_pa[25:3]],
                             cpu.umem[hndl_ior_pa[25:3]],
                             hndl_iir_pa[2] ?
                                 cpu.umem[hndl_iir_pa[25:3]][31:0] :
                                 cpu.umem[hndl_iir_pa[25:3]][63:32]);
                    // Dump saved registers for debugging division/modulo bugs
                    $display("        saved: r1=%016x r7=%016x r25=%016x r26=%016x r28=%016x r29=%016x",
                             cpu.umem[pt_gr1_pa[25:3]],
                             cpu.umem[pt_gr7_pa[25:3]],
                             cpu.umem[pt_gr25_pa[25:3]],
                             cpu.umem[pt_gr26_pa[25:3]],
                             cpu.umem[pt_gr28_pa[25:3]],
                             cpu.umem[pt_gr29_pa[25:3]]);
                end
            end

            // __udivdi3 entry trace (0x4049d988)
            if (cpu.pc_rd == 64'h4049d988) begin
                $display("[%0d] UDIVDI3_ENTRY: r26(dividend)=%016x r25(divisor)=%016x r2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end
            // pcpu_dump_alloc_info entry trace (0x404a39a8)
            if (cpu.pc_rd == 64'h404a39a8) begin
                $display("[%0d] PCPU_DUMP_ENTRY: r26(lvl)=%016x r25(ai)=%016x r2(caller)=%016x r7=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2], cpu.rf[7]);
            end
            // pcpu_dump_alloc_info BVE at 0x404a3a84 (calls __udivdi3 for upa)
            if (cpu.pc_rd == 64'h404a3a84) begin
                $display("[%0d] PCPU_UPA_DIV: r26(arg1)=%016x r25(arg2)=%016x r1(target)=%016x r7=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[1], cpu.rf[7]);
            end
            // Instruction-level trace when PC is inside __udivdi3 (0x4049d988 to 0x4049e0d0)
            // or $$remoI millicode (0x4049e788 to 0x4049ea70)
            // or $$divoI helper (0x404b4d20 to 0x404b4f80)
            if ((cpu.pc_rd >= 64'h4049d988 && cpu.pc_rd < 64'h4049e0d0) ||
                (cpu.pc_rd >= 64'h4049e788 && cpu.pc_rd < 64'h4049ea70) ||
                (cpu.pc_rd >= 64'h404b4d20 && cpu.pc_rd < 64'h404b4f80)) begin
                $display("[%0d] UDIV: PC=%016x instr=%08x r1=%016x r19=%016x r20=%016x r21=%016x r22=%016x r25=%016x r26=%016x r28=%016x r29=%016x null=%0d PSW=%016x ds=%0d",
                         cycle_count, cpu.pc_rd,
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.rf[1],
                         cpu.rf[19], cpu.rf[20], cpu.rf[21], cpu.rf[22],
                         cpu.rf[25], cpu.rf[26], cpu.rf[28], cpu.rf[29],
                         cpu.in_nullified, cpu.psw, cpu.delay_slot_rd);
            end
            // 0x404a3c10: copy ret0,r26 (nr_units into arg1, right before modulo call)
            if (cpu.pc_rd == 64'h404a3c10) begin
                $display("[%0d] PCPU_MOD_CALL: r28(nr_units)=%016x r25(upa)=%016x r7(upa)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[25], cpu.rf[7]);
            end
            // 0x404a3c20: bve,l (r1),rp - the actual call to modulo function
            if (cpu.pc_rd == 64'h404a3c20) begin
                $display("[%0d] PCPU_MOD_BVE: r1(target)=%016x r26(arg1)=%016x r25(arg2)=%016x",
                         cycle_count, cpu.rf[1], cpu.rf[26], cpu.rf[25]);
            end
            // 0x404a3c28: cmpib,= 0,ret1 - after modulo return, check remainder
            if (cpu.pc_rd == 64'h404a3c28) begin
                $display("[%0d] PCPU_MOD_RET: r28(quotient)=%016x r29(remainder)=%016x r26=%016x r25=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[29], cpu.rf[26], cpu.rf[25]);
            end

            // parisc_terminate entry trace (64-bit: 0x4049aab8)
            // parisc_terminate(char *msg, struct pt_regs *regs, int code, unsigned long offset)
            if (cpu.pc_rd == 64'h4049aab8 && parisc_term_trace_count < 10) begin
                parisc_term_trace_count <= parisc_term_trace_count + 1;
                $display("[%0d] PARISC_TERM: R26(msg)=%016x R25(regs)=%016x R24(code)=%016x R23(offset)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[23], cpu.rf[2]);
                // Read faulting PC and IOR from pt_regs (64-bit offsets)
                begin
                    reg [63:0] term_regs_pa;
                    reg [63:0] term_msg_pa;
                    term_regs_pa = cpu.rf[25] - 64'h40000000;
                    // pt_regs->iaoq[0] at offset 0x250, ior at 0x2A0, iir at 0x290, isr at 0x298
                    $display("[%0d] PARISC_TERM: fault_pc=%016x ior=%016x iir=%016x isr=%016x",
                             cycle_count,
                             cpu.umem[(term_regs_pa + 64'h250) >> 3],
                             cpu.umem[(term_regs_pa + 64'h2A0) >> 3],
                             cpu.umem[(term_regs_pa + 64'h290) >> 3],
                             cpu.umem[(term_regs_pa + 64'h298) >> 3]);
                    // Print terminate message
                    term_msg_pa = cpu.rf[26] - 64'h40000000;
                    $write("[%0d] PARISC_TERM_MSG: \"", cycle_count);
                    for (integer bi = 0; bi < 128; bi = bi + 1) begin
                        reg [63:0] wd;
                        wd = cpu.umem[(term_msg_pa + bi) >> 3];
                        case ((term_msg_pa + bi) & 7)
                            0: if (wd[63:56] == 0) bi = 128; else $write("%c", wd[63:56]);
                            1: if (wd[55:48] == 0) bi = 128; else $write("%c", wd[55:48]);
                            2: if (wd[47:40] == 0) bi = 128; else $write("%c", wd[47:40]);
                            3: if (wd[39:32] == 0) bi = 128; else $write("%c", wd[39:32]);
                            4: if (wd[31:24] == 0) bi = 128; else $write("%c", wd[31:24]);
                            5: if (wd[23:16] == 0) bi = 128; else $write("%c", wd[23:16]);
                            6: if (wd[15:8]  == 0) bi = 128; else $write("%c", wd[15:8]);
                            7: if (wd[7:0]   == 0) bi = 128; else $write("%c", wd[7:0]);
                        endcase
                    end
                    $display("\"");
                end
            end

            // start_kernel entry trace (64-bit: 0x40101360)
            if (cpu.pc_rd == 64'h40101360 && start_kernel_trace_count < 5) begin
                start_kernel_trace_count <= start_kernel_trace_count + 1;
                $display("[%0d] START_KERNEL: PC=%016x PSW=%016x SP=%016x dp=%016x R2=%016x",
                         cycle_count, cpu.pc_rd, cpu.psw, cpu.rf[30], cpu.rf[27], cpu.rf[2]);
                post_start_kernel_trace <= 5000;
            end

            // Post-start_kernel instruction trace (DISABLED - too verbose)
            // if (post_start_kernel_trace > 0) begin
            //     post_start_kernel_trace <= post_start_kernel_trace - 1;
            //     $display("[%0d] SK: ...");
            // end

            // format_decode entry trace (64-bit: 0x4048a918)
            if (cpu.pc_rd == 64'h4048a918) begin
                $display("[%0d] FORMAT_DECODE: R26(fmt)=%016x R25(spec)=%016x R2(caller)=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2], cpu.rf[30]);
            end

            // vsnprintf padding loop trace: depd,z,* at 0x4048ffa4
            // Track first 10 entries into the padding loop
            if (cpu.pc_rd == 64'h4048ff90 && vsnprintf_pad_trace < 10) begin
                vsnprintf_pad_trace <= vsnprintf_pad_trace + 1;
                $display("[%0d] VSNPRINTF_PAD[%0d]: ret0(width)=%016x R5(str)=%016x R7(end)=%016x R19=%016x R3(frame)=%016x R2=%016x",
                         cycle_count, vsnprintf_pad_trace, cpu.rf[28], cpu.rf[5], cpu.rf[7], cpu.rf[19], cpu.rf[3], cpu.rf[2]);
            end

            // format_decode return: stb ret0,0(r6) at 0x40490960 sets type
            if (cpu.pc_rd == 64'h40490960) begin
                $display("[%0d] FD_SET_TYPE: ret0=%016x R6(spec)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[6]);
                $display("[%0d]   spec_mem[0:7]=%016x",
                         cycle_count, cpu.umem[(cpu.rf[6] - 64'h40000000) >> 3]);
            end

            // vsnprintf after format_decode returns: copy ret0,r24 at 0x40495be8
            if (cpu.pc_rd == 64'h40495be8) begin
                $display("[%0d] FD_RETURN: ret0=%016x R3=%016x R12(spec_ptr)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[3], cpu.rf[12]);
                // Print spec memory at r3+8 (PA = VA - 0x40000000)
                $display("[%0d]   spec_mem[0:7]=%016x",
                         cycle_count, cpu.umem[((cpu.rf[3] + 64'h8) - 64'h40000000) >> 3]);
            end

            // vsnprintf reads spec.type: ldb 8(r3),ret0 at 0x40495bf4
            if (cpu.pc_rd == 64'h40495bf4) begin
                $display("[%0d] READ_TYPE: R3=%016x ret0_before=%016x spec_mem=%016x null=%0d ds=%0d",
                         cycle_count, cpu.rf[3], cpu.rf[28],
                         cpu.umem[((cpu.rf[3] + 64'h8) - 64'h40000000) >> 3],
                         cpu.in_nullified, cpu.delay_slot_rd);
            end

            // cmpib after ldb: check ret0 was updated at 0x40495bf8
            if (cpu.pc_rd == 64'h40495bf8) begin
                $display("[%0d] CMPIB_CHECK: ret0_after_ldb=%016x (should be spec.type, not 0x1e)",
                         cycle_count, cpu.rf[28]);
            end

            // Jump table: ldw,s at 0x40495c08
            if (cpu.pc_rd == 64'h40495c08) begin
                $display("[%0d] JUMP_TBL: ret0=%016x r19=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[19]);
            end

            // Trace any instruction after ldb at 0x40495bfc (delay slot of cmpib)
            if (cpu.pc_rd == 64'h40495bfc) begin
                $display("[%0d] CMPIB_DS: ret0=%016x (delay slot, branch %s)",
                         cycle_count, cpu.rf[28], cpu.delay_slot_rd ? "TAKEN" : "NOT_TAKEN");
            end

            // vsnprintf entry trace (64-bit: 0x40495ae8) - DISABLED (too noisy)
            // if (cpu.pc_rd == 64'h40495ae8) begin
            //     $display("[%0d] VSNPRINTF: ...");
            // end

            // vsnprintf LDD spec for number(): ldd 8(r3),r23 at 0x40495f90
            if (cpu.pc_rd == 64'h40495f90) begin
                $display("[%0d] LDD_SPEC: R3=%016x spec_addr=%016x spec_mem=%016x",
                         cycle_count, cpu.rf[3], cpu.rf[3] + 64'h8,
                         cpu.umem[((cpu.rf[3] + 64'h8) - 64'h40000000) >> 3]);
            end

            // number() entry trace (64-bit: 0x4048faf8)
            if (cpu.pc_rd == 64'h4048faf8) begin
                $display("[%0d] NUMBER: R26(buf)=%016x R25(end)=%016x R24(num)=%016x R23(spec)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[23], cpu.rf[2]);
            end

            // number() padding loop: r23=ret0 set at 0x4048fca4
            if (cpu.pc_rd == 64'h4048fca4) begin
                $display("[%0d] NUMBER_PAD: R28(ret0/padcount)=%016x R5=%016x R7=%016x R8=%016x R19=%016x R20=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5], cpu.rf[7], cpu.rf[8], cpu.rf[19], cpu.rf[20]);
            end

            // _printk entry trace (64-bit: 0x404a2c10)
            if (cpu.pc_rd == 64'h404a2c10) begin
                $display("[%0d] PRINTK: R26(fmt)=%016x R25(arg1)=%016x R2(caller)=%016x dp=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2], cpu.rf[27]);
            end

            // Break handler entry trace (vector 9 at IVA+0x120)
            // Detect when code=9 (break) is passed to handle_interruption
            if (cpu.pc_rd == 64'h104076cc && cpu.rf[26] == 64'h9 && post_break_trace == 0) begin
                post_break_trace <= 200;
                $display("[%0d] BRK_HANDLER: code=9 CR18(now_pcoq)=%016x CR19(IIR)=%016x",
                         cycle_count, cpu.cr18_rd, cpu.cr19_rd);
                // Read saved fault PC from pt_regs->iaoq[0] at offset 0x1a8 from R25
                // R25 = regs ptr (virtual), PA = VA - 0x10000000
                // iaoq[0] at PA = (R25-0x10000000) + 0x1a8
                // iir at PA = (R25-0x10000000) + 0x1c8
                $display("[%0d] BRK_SAVED: regs_pa=%016x iaoq0=%08x iir=%08x",
                         cycle_count, cpu.rf[25] - 64'h10000000,
                         (cpu.rf[25] - 64'h10000000 + 64'h1a8) & 64'h4 ?
                             cpu.umem[(cpu.rf[25] - 64'h10000000 + 64'h1a8) >> 3][31:0] :
                             cpu.umem[(cpu.rf[25] - 64'h10000000 + 64'h1a8) >> 3][63:32],
                         (cpu.rf[25] - 64'h10000000 + 64'h1c8) & 64'h4 ?
                             cpu.umem[(cpu.rf[25] - 64'h10000000 + 64'h1c8) >> 3][31:0] :
                             cpu.umem[(cpu.rf[25] - 64'h10000000 + 64'h1c8) >> 3][63:32]);
            end
            if (post_break_trace > 0) begin
                post_break_trace <= post_break_trace - 1;
                $display("[%0d] BRK: PC=%016x instr=%08x R2=%016x R26=%016x",
                         cycle_count, cpu.pc_rd,
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.rf[2], cpu.rf[26]);
            end

            // workqueue_init_early entry trace (0x1010938c)
            if (cpu.pc_rd == 64'h1010938c) begin
                $display("[%0d] WQ_INIT_EARLY: PC=%016x R2=%016x R27(dp)=%016x SP=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf[2], cpu.rf[27], cpu.rf[30]);
            end

            // alloc_workqueue entry trace (0x1043a848)
            // R26=fmt, R25=flags, R24=max_active
            if (cpu.pc_rd == 64'h1043a848) begin
                $display("[%0d] ALLOC_WQ: R26(fmt)=%016x R25(flags)=%08x R24(max_act)=%08x R2(caller)=%016x R27(dp)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25][31:0], cpu.rf[24][31:0], cpu.rf[2], cpu.rf[27]);
            end

            // apply_workqueue_attrs_locked entry (0x104397dc)
            if (cpu.pc_rd == 64'h104397dc) begin
                $display("[%0d] APPLY_WQ_ATTRS: R26(wq)=%016x R25(attrs)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end

            // After apply_workqueue_attrs_locked returns (0x1043ac94)
            // ret0 has the return value; cmpib,<= 0,ret0 - if ret0>=0 => success
            if (cpu.pc_rd == 64'h1043ac94) begin
                $display("[%0d] APPLY_WQ_ATTRS_RET: ret0=%016x (%0d) R4(wq)=%016x R5=%016x",
                         cycle_count, cpu.rf[28], $signed(cpu.rf[28][31:0]), cpu.rf[4], cpu.rf[5]);
            end

            // apply_wqattrs_prepare entry (0x1043965c)
            if (cpu.pc_rd == 64'h1043965c) begin
                $display("[%0d] WQATTRS_PREPARE: R26(wq)=%016x R25(attrs)=%016x R24(cpumask)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2]);
            end

            // After kzalloc in apply_wqattrs_prepare (0x104396d8)
            // r5 = ctx from kzalloc, about to call alloc_workqueue_attrs
            if (cpu.pc_rd == 64'h104396d8) begin
                $display("[%0d] WQATTRS_CTX: ret0(ctx)=%016x (kzalloc result)",
                         cycle_count, cpu.rf[28]);
            end

            // After alloc_workqueue_attrs returns (0x104396e0)
            // ret0 = new_attrs, r5 = ctx
            if (cpu.pc_rd == 64'h104396e0) begin
                $display("[%0d] WQATTRS_ATTRS: ret0(new_attrs)=%016x r5(ctx)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5]);
            end

            // After alloc_unbound_pwq returns (0x1043972c)
            // ret0 = dfl_pwq
            if (cpu.pc_rd == 64'h1043972c) begin
                $display("[%0d] WQATTRS_DFLPWQ: ret0(dfl_pwq)=%016x r5(ctx)=%016x r4(new_attrs)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5], cpu.rf[4]);
            end

            // alloc_unbound_pwq entry (0x104391dc)
            if (cpu.pc_rd == 64'h104391dc) begin
                $display("[%0d] ALLOC_UNBOUND_PWQ: R26(wq)=%016x R25(attrs)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end

            // wq_online check at 0x104393b8 (ldb 3ac(r1),ret0)
            // After this, at 0x104393bc: cmpib,<> 0,ret0 => if wq_online != 0, create_worker
            if (cpu.pc_rd == 64'h104393bc) begin
                $display("[%0d] WQ_ONLINE_CHECK: ret0(wq_online)=%016x (expect 0 during init_early)",
                         cycle_count, cpu.rf[28]);
            end

            // create_worker entry (0x10435c70)
            if (cpu.pc_rd == 64'h10435c70) begin
                $display("[%0d] CREATE_WORKER: R26(pool)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[2]);
            end

            // worker_pool_assign_id return check (0x104393b0)
            if (cpu.pc_rd == 64'h104393b0) begin
                $display("[%0d] POOL_ASSIGN_ID_RET: ret0=%016x (%0d)",
                         cycle_count, cpu.rf[28], $signed(cpu.rf[28][31:0]));
            end

            // Pool allocation return check (0x10439360)
            if (cpu.pc_rd == 64'h10439360) begin
                $display("[%0d] POOL_ALLOC: ret0(pool)=%016x",
                         cycle_count, cpu.rf[28]);
            end

            // init_worker_pool entry (0x104390a0)
            if (cpu.pc_rd == 64'h104390a0) begin
                $display("[%0d] INIT_POOL_ENTRY: R26(pool)=%016x R2(caller)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[2]);
            end

            // init_worker_pool return check (0x10439370)
            if (cpu.pc_rd == 64'h10439370) begin
                $display("[%0d] INIT_POOL_RET: ret0=%016x (%0d)",
                         cycle_count, cpu.rf[28], $signed(cpu.rf[28][31:0]));
            end

            // Trace inside alloc_unbound_pwq: hash lookup hit path (0x104392ec - pool found)
            if (cpu.pc_rd == 64'h104392ec) begin
                $display("[%0d] POOL_FOUND: r4(pool)=%016x",
                         cycle_count, cpu.rf[4]);
            end

            // kmem_cache_alloc_node return for pwq (0x1043930c)
            if (cpu.pc_rd == 64'h1043930c) begin
                $display("[%0d] PWQ_CACHE_ALLOC: ret0(pwq)=%016x r4(pool)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[4]);
            end

            // put_unbound_pool (failure path at 0x104393fc)
            if (cpu.pc_rd == 64'h104393fc) begin
                $display("[%0d] PUT_UNBOUND_POOL: r4(pool)=%016x R2=%016x",
                         cycle_count, cpu.rf[4], cpu.rf[2]);
            end

            // per-CPU alloc_unbound_pwq return (0x104397b8 in for loop)
            if (cpu.pc_rd == 64'h104397b8) begin
                $display("[%0d] WQATTRS_CPU_PWQ: ret0(pwq)=%016x r5(ctx)=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[5]);
            end

            // alloc_workqueue error path - kthread_flush_worker(pwq_release_worker)
            // At 0x1043acc4: b,l kthread_flush_worker - R26 already loaded
            if (cpu.pc_rd == 64'h1043acc4) begin
                $display("[%0d] WQ_ERR_FLUSH: R26(pwq_release_worker)=%016x R4(wq)=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[4], cpu.rf[2]);
            end

            // kthread_flush_worker entry (0x1043e028)
            if (cpu.pc_rd == 64'h1043e028) begin
                $display("[%0d] KTHREAD_FLUSH_WORKER: R26(worker)=%016x R2(caller)=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[2], cpu.rf[30]);
            end

            // kthread_insert_work entry trace (0x1043db8c)
            if (cpu.pc_rd == 64'h1043db8c) begin
                $display("[%0d] KTHREAD_INSERT: R26(worker)=%016x R25(work)=%016x R24(pos)=%016x R2(caller)=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2], cpu.rf[30]);
            end

            // put_task_struct_rcu_user entry trace (0x1042212c)
            if (cpu.pc_rd == 64'h1042212c && put_task_trace_count < 20) begin
                put_task_trace_count <= put_task_trace_count + 1;
                $display("[%0d] PUT_TASK: PC=%016x R26(task)=%016x R4=%016x R2(caller)=%016x SP=%016x PSW=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf[26], cpu.rf[4], cpu.rf[2], cpu.rf[30], cpu.psw);
            end

            // release_task entry trace (0x104221a8)
            if (cpu.pc_rd == 64'h104221a8 && release_task_trace_count < 20) begin
                release_task_trace_count <= release_task_trace_count + 1;
                $display("[%0d] RELEASE_TASK: PC=%016x R26(task)=%016x R4=%016x R2(caller)=%016x SP=%016x PSW=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf[26], cpu.rf[4], cpu.rf[2], cpu.rf[30], cpu.psw);
            end

            // put_pid entry trace (0x1043af30)
            if (cpu.pc_rd == 64'h1043af30 && put_pid_trace_count < 20) begin
                put_pid_trace_count <= put_pid_trace_count + 1;
                $display("[%0d] PUT_PID: PC=%016x R26(pid)=%016x R4=%016x R2(caller)=%016x SP=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf[26], cpu.rf[4], cpu.rf[2], cpu.rf[30]);
            end

            // Trace at RFI return from break handler (0x10403248)
            if (cpu.pc_rd == 64'h10403248 && rfi_return_trace_count < 10) begin
                rfi_return_trace_count <= rfi_return_trace_count + 1;
                $display("[%0d] RFI_RETURN: PC=%016x CR18=%016x CR22=%016x R4=%016x R26=%016x R2=%016x",
                         cycle_count, cpu.pc_rd, cpu.cr18_rd, cpu.cr22_rd,
                         cpu.rf[4], cpu.rf[26], cpu.rf[2]);
            end

            // Post-RFI trace: trace 200 cycles after RFI to see register state
            if (cpu.pc_rd == 64'h10403248 && post_rfi_trace == 0) begin
                post_rfi_trace <= 200;
            end
            if (post_rfi_trace > 0) begin
                post_rfi_trace <= post_rfi_trace - 1;
                $display("[%0d] RFI_TRACE: PC=%016x PSW=%016x R2=%016x R4=%016x R5=%016x R26=%016x SP=%016x",
                         cycle_count, cpu.pc_rd, cpu.psw, cpu.rf[2], cpu.rf[4], cpu.rf[5], cpu.rf[26], cpu.rf[30]);
            end

            // __udelay trace: dump key registers when inside the loop
            // 0x10644470 = mfctl itmr,r19 (initial read, entry point)
            // 0x10644474 = mfctl itmr,ret0 (loop body)
            // 0x10644478 = sub ret0,r19,ret0 (elapsed)
            // 0x1064447c = cmpclr,<< ret0,ret1,r0
            if (cpu.pc_rd == 64'h10644470 && udelay_trace_count < 5) begin
                $display("[%0d] UDELAY_ENTRY: PC=%016x CR16/timer=%016x R19=%016x R28(ret0)=%016x R29(ret1/target)=%016x R2(rp)=%016x",
                         cycle_count, cpu.pc_rd, timer_counter, cpu.rf[19], cpu.rf[28], cpu.rf[29], cpu.rf[2]);
                udelay_trace_count <= udelay_trace_count + 1;
            end
            if (cpu.pc_rd == 64'h10644474 && udelay_trace_count >= 1 && udelay_trace_count < 20) begin
                udelay_trace_count <= udelay_trace_count + 1;
                $display("[%0d] UDELAY_LOOP: PC=%016x CR16/timer=%016x R19(initial)=%016x R28(ret0)=%016x R29(ret1/target)=%016x",
                         cycle_count, cpu.pc_rd, timer_counter, cpu.rf[19], cpu.rf[28], cpu.rf[29]);
            end
            if (cpu.pc_rd == 64'h1064447c && udelay_trace_count >= 1 && udelay_trace_count < 20) begin
                $display("[%0d] UDELAY_CMP: R28(elapsed)=%016x R29(target)=%016x cmp_result=%s",
                         cycle_count, cpu.rf[28], cpu.rf[29],
                         (cpu.rf[28] < cpu.rf[29]) ? "lt(loop)" : "ge(exit)");
            end

            // DEBUG: trace LDD in desc_read at VA 0x401ce428
            if (cpu.pc_rd == 64'h00000000401ce428 && desc_read_trace_count < 5) begin
                $display("[%0d] DESC_READ_LDD: PC=%016x r28=%016x umem_da_pa_rd=%016x ldcd_data=%016x ldd_short_en=%0d",
                         cycle_count, cpu.pc_rd, cpu.rf[28], cpu.umem_da_pa_rd, cpu.ldcd_data, cpu.ldd_short_enable);
                $display("  umem_da_pa_rd_addr_mux_adj=%016x umem[0xd6038]=%016x",
                         cpu.umem_da_pa_rd_addr_mux_adj, cpu.umem[32'hd6038]);
                desc_read_trace_count <= desc_read_trace_count + 1;
            end
            // Trace the next cycle (when r31 should be written)
            if (cpu.pc_rd == 64'h00000000401ce42c && desc_read_trace_count < 10) begin
                $display("[%0d] DESC_READ_POST_LDD: PC=%016x r31=%016x r28=%016x rf_write_data_mux=%026x",
                         cycle_count, cpu.pc_rd, cpu.rf[31], cpu.rf[28], cpu.rf_write_data_mux);
                desc_read_trace_count <= desc_read_trace_count + 1;
            end
            // Also trace the EXTRD at 0x401ce43c (state extraction)
            if (cpu.pc_rd == 64'h00000000401ce43c && desc_read_trace_count < 15) begin
                $display("[%0d] DESC_READ_EXTRD_STATE: PC=%016x r31=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf[31]);
                desc_read_trace_count <= desc_read_trace_count + 1;
            end

            // Memory watchpoint: detect writes to PA 0x00406c18 (contains pdtlb instruction)
            // Watch for the 64-bit word at umem[0x80D83] changing
            if (cpu.umem[32'h80D83] != 64'h001a582007205200 && cycle_count > 100) begin
                if (!mem_watch_fired) begin
                    $display("[%0d] MEM_CORRUPT: PA=00406c18 word=%016x (expected 001a582007205200) PC=%016x PSW=%016x",
                             cycle_count, cpu.umem[32'h80D83], cpu.pc_rd, cpu.psw);
                    mem_watch_fired <= 1;
                end
            end

            // Memory watchpoint: detect writes to PA 0x000EC040 (compound_head of page struct at 0x400EC038)
            // umem word index = 0x000EC040 >> 3 = 0x1D808
            if (cpu.umem[26'h1D808] != prev_compound_head && compound_watch_count < 100) begin
                compound_watch_count <= compound_watch_count + 1;
                $display("[%0d] COMPOUND_HEAD_WATCH: PA=000EC040 old=%016x new=%016x PC=%016x PSW=%016x",
                         cycle_count, prev_compound_head, cpu.umem[26'h1D808], cpu.pc_rd, cpu.psw);
                $display("[%0d] COMPOUND_HEAD_WATCH: R2=%016x R3=%016x R6=%016x R26=%016x ret0=%016x SP=%016x",
                         cycle_count, cpu.rf[2], cpu.rf[3], cpu.rf[6], cpu.rf[26], cpu.rf[28], cpu.rf[30]);
                // Also dump mem_map value (at PA 0x0072DE28, umem word index 0xE5BC5)
                // and saved_command_line pointer (at PA 0x005D2108, umem word index 0xBA421)
                $display("[%0d] COMPOUND_HEAD_WATCH: mem_map(PA 0072DE28)=%016x saved_cmd(PA 005D2108)=%016x",
                         cycle_count, cpu.umem[26'hE5BC5], cpu.umem[26'hBA421]);
            end
            prev_compound_head <= cpu.umem[26'h1D808];

            // Monitor mem_map variable (PA 0x0072DE28, umem[0xE5BC5])
            if (cpu.umem[26'hE5BC5] != prev_mem_map) begin
                $display("[%0d] MEM_MAP_WRITE: old=%016x new=%016x PC=%016x R2=%016x R26=%016x",
                         cycle_count, prev_mem_map, cpu.umem[26'hE5BC5], cpu.pc_rd, cpu.rf[2], cpu.rf[26]);
            end
            prev_mem_map <= cpu.umem[26'hE5BC5];

            // Monitor saved_command_line pointer (PA 0x005D2108, umem[0xBA421])
            if (cpu.umem[26'hBA421] != prev_saved_cmd) begin
                $display("[%0d] SAVED_CMD_WRITE: old=%016x new=%016x PC=%016x R2=%016x R26=%016x",
                         cycle_count, prev_saved_cmd, cpu.umem[26'hBA421], cpu.pc_rd, cpu.rf[2], cpu.rf[26]);
            end
            prev_saved_cmd <= cpu.umem[26'hBA421];

            // Trace make_alloc_exact virt_to_page computation
            // PC=0x402687e8: ldd 640(r1),r19 — loads DLT entry pointer
            if (cpu.pc_rd == 64'h00000000402687e8) begin
                $display("[%0d] VIRT2PAGE_TRACE: PC=402687e8 R1=%016x DP(R27)=%016x",
                         cycle_count, cpu.rf[1], cpu.rf[27]);
            end
            // PC=0x402687ec: ldd 0(r19),r31 — loads mem_map value from DLT
            if (cpu.pc_rd == 64'h00000000402687ec) begin
                $display("[%0d] VIRT2PAGE_TRACE: PC=402687ec R19=%016x (DLT entry addr)",
                         cycle_count, cpu.rf[19]);
            end
            // PC=0x402687f0: shladd,l ret0,3,r31,r31 — r31=pfn*56+mem_map
            if (cpu.pc_rd == 64'h00000000402687f0) begin
                $display("[%0d] VIRT2PAGE_TRACE: PC=402687f0 RET0=%016x R31=%016x (pfn*7, mem_map_value)",
                         cycle_count, cpu.rf[28], cpu.rf[31]);
            end
            // PC=0x402687f4: ldd 8(r31),ret0 — load compound_head from computed page
            if (cpu.pc_rd == 64'h00000000402687f4) begin
                $display("[%0d] VIRT2PAGE_TRACE: PC=402687f4 R31=%016x (page_struct_ptr=pfn*56+mem_map)",
                         cycle_count, cpu.rf[31]);
            end
            // Also trace the crash point in __free_pages_ok
            // PC=0x4026855c: ldd 0(r26),ret0 — deref head page (CRASH)
            if (cpu.pc_rd == 64'h000000004026855c) begin
                $display("[%0d] FREE_PAGES_CRASH: PC=4026855c R26=%016x R6=%016x RET0=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[6], cpu.rf[28], cpu.rf[2]);
            end

            // Periodic progress report
            if ((cycle_count % 100000 == 0 && cycle_count > 0) ||
                (cycle_count >= 1000000 && cycle_count % 5000000 == 0)) begin
                $display("[%0d] PROGRESS: PC=%016x PSW=%016x SP=%016x R27(dp)=%016x CR14=%016x psw_c_total=%0d",
                         cycle_count, cpu.pc_rd, cpu.psw, cpu.rf[30], cpu.rf[27], cpu.cr14_rd, psw_c_total);
                $display("        BTLB[0]: valid=%0d type_i=%0d va=%016x mask=%016x pa=%016x",
                         cpu.btlb_valid[0], cpu.btlb_type_i[0],
                         cpu.btlb_va_base[0], cpu.btlb_page_mask[0], cpu.btlb_pa_base[0]);
                $display("        uart_writes=%0d firmware_hits=%0d",
                         uart_write_count, firmware_hit_count);
                $display("        EIEM=%016x EIRR=%016x itmr_armed=%0b itmr_compare=%016x timer=%016x",
                         cpu.cr15_rd, eirr_reg, itmr_armed, itmr_compare, timer_counter);
                $display("        code_iasq=%016x btlb_space[0]=%016x itlb_miss=%0d btlb_i_hit=%0d itlb_hit=%0d",
                         cpu.code_iasq_rd, cpu.btlb_space[0], cpu.itlb_miss, cpu.btlb_i_hit, cpu.itlb_hit);
                $display("        pc_pa=%016x exception_taken=%0d select_trap_target_pc_merged=%0d",
                         cpu.pc_pa, cpu.exception_taken, cpu.select_trap_target_pc_merged);
                $display("        delay_slot=%0d in_nullified=%0d pdtlb_enable=%0d pdtlb_no_gated_cond=%0d",
                         cpu.delay_slot_rd, cpu.in_nullified, cpu.pdtlb_enable, cpu.pdtlb_no_gated_cond);
                $display("        pc_wr=%016x select_pc_add_4=%0d select_branch_rd=%0d select_b_target=%0d",
                         cpu.pc_wr, cpu.select_pc_add_4_pc_merged, cpu.select_branch_target_rd_pc_merged, cpu.select_b_target_pc_merged);
                $display("        cmpib_false_geu_en=%0d cmpib_false_geu_no_gated=%0d instr=%08x",
                         cpu.cmpib_false_geu_enable, cpu.cmpib_false_geu_no_gated_cond, cpu.instr);
                // Show fetched instruction word at pc_pa
                $display("        instr_at_pc_pa=%08x (word at mem[%08x]) pc_pa_adj=%016x",
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.pc_pa[25:0],
                         {cpu.pc_pa[25:3], 3'b000});
                // Trap code distribution
                if (total_trap_count > 0) begin
                    $display("        TRAPS total=%0d code1(HPMC)=%0d code2(prot)=%0d code3(privop)=%0d code5(align)=%0d",
                             total_trap_count, trap_code_count[1], trap_code_count[2], trap_code_count[3], trap_code_count[5]);
                    $display("        code6(ITLB)=%0d code7(ipmask)=%0d code8(iprot)=%0d code9(break)=%0d code10(privregs)=%0d",
                             trap_code_count[6], trap_code_count[7], trap_code_count[8], trap_code_count[9], trap_code_count[10]);
                    $display("        code14(assist)=%0d code15(DTLB)=%0d code17(NA-pg)=%0d code18(NA-prot)=%0d code20(DMIR)=%0d",
                             trap_code_count[14], trap_code_count[15], trap_code_count[17], trap_code_count[18], trap_code_count[20]);
                    $display("        code22(DMHD)=%0d code23(ext)=%0d code25(TKN-br)=%0d code26(DMLB)=%0d",
                             trap_code_count[22], trap_code_count[23], trap_code_count[25], trap_code_count[26]);
                end
                $fflush();
            end

            // D-BTLB match diagnostic: fires when stb_short data trap is taken
            if (cpu.stb_short_data_trap_taken && dtlb_diag_count < 10) begin
                dtlb_diag_count <= dtlb_diag_count + 1;
                $display("[%0d] DBTLB_DIAG: PC=%016x eff_addr=%016x dspace=%016x PSW=%016x",
                         cycle_count, cpu.pc_rd, cpu.stb_short_eff_addr, cpu.dspace, cpu.psw);
                $display("  btlb_d_hit=%0d dtlb_hit=%0d dtlb_miss=%0d",
                         cpu.stb_short_btlb_d_hit, cpu.dtlb_hit, cpu.stb_short_dtlb_miss);
                $display("  btlb[0]: valid=%0d type_d=%0d va=%016x mask=%016x pa=%016x space=%016x",
                         cpu.btlb_valid[0], cpu.btlb_type_d[0],
                         cpu.btlb_va_base[0], cpu.btlb_page_mask[0], cpu.btlb_pa_base[0], cpu.btlb_space[0]);
                $display("  dbm_0=%0d masked_addr=%016x dspace_eq_sp0=%0d",
                         cpu.stb_short_dbm_0, cpu.stb_short_dbp_masked_addr_0, cpu.dspace_eq_btlb_space_0_rd);
                $display("  psw_D=%0d psw_W=%0d instr=%08x std_short_en=%0d stb_short_en=%0d",
                         cpu.psw[1], cpu.psw[27],
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.std_short_enable, cpu.stb_short_enable);
            end

            // Targeted diagnostic at the faulting store instruction
            if (cpu.pc_rd == 64'h4015266c && cpu.psw[1] && dtlb_diag_count < 20) begin
                dtlb_diag_count <= dtlb_diag_count + 1;
                $display("[%0d] FAULT_PC_DIAG: PC=%016x PSW=%016x pc_pa=%016x",
                         cycle_count, cpu.pc_rd, cpu.psw, cpu.pc_pa);
                $display("  instr=%08x std_short_en=%0d stb_short_en=%0d any_gated=%0d",
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.std_short_enable, cpu.stb_short_enable, cpu.std_short_any_gated_cond);
                $display("  data_trap_taken=%0d eff_addr=%016x dspace=%016x btlb_d_hit=%0d dtlb_miss=%0d",
                         cpu.stb_short_data_trap_taken, cpu.stb_short_eff_addr, cpu.dspace,
                         cpu.stb_short_btlb_d_hit, cpu.stb_short_dtlb_miss);
                $display("  R1=%016x R29(ret1)=%016x addr_calc=%016x",
                         cpu.rf[1], cpu.rf[29], cpu.rf[29] + 64'h8);
                $display("  btlb[0]: valid=%0d type_d=%0d va=%016x mask=%016x space=%016x",
                         cpu.btlb_valid[0], cpu.btlb_type_d[0],
                         cpu.btlb_va_base[0], cpu.btlb_page_mask[0], cpu.btlb_space[0]);
                $display("  psw_D=%0d psw_W=%0d in_null=%0d instr_trap=%0d delay=%0d",
                         cpu.psw[1], cpu.psw[27], cpu.in_nullified, cpu.instr_trap_taken, cpu.delay_slot_rd);
            end

            // Exception trace - DISABLED (too noisy during TLB misses)
            // if (cpu.exception_taken) begin ... end
            // Post-exception PC trace - DISABLED
            // if (post_exc_trace > 0) begin ... end

            // sized_strscpy entry trace (function at 0x10638f7c)
            if (cpu.pc_rd == 64'h10638f7c) begin
                $display("[%0d] STRSCPY_ENTRY: R2(ret)=%016x R24(count)=%016x R25(src)=%016x R26(dst)=%016x",
                         cycle_count, cpu.rf[2], cpu.rf[24], cpu.rf[25], cpu.rf[26]);
                post_strscpy_trace <= 30;
            end
            if (post_strscpy_trace > 0) begin
                post_strscpy_trace <= post_strscpy_trace - 1;
                $display("[%0d] STRSCPY: PC=%016x instr=%08x R24=%016x R25=%016x R26=%016x R28=%016x null=%0d",
                         cycle_count, cpu.pc_rd,
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.rf[24], cpu.rf[25], cpu.rf[26], cpu.rf[28],
                         cpu.in_nullified);
            end

            // parisc_get_cpu_type trace (function at 0x10106434)
            if (cpu.pc_rd == 64'h10106434) begin
                $display("[%0d] GET_CPU_TYPE_ENTRY: R26(hversion)=%016x R2(ret)=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[2]);
                post_cputype_trace <= 80;
            end
            if (post_cputype_trace > 0) begin
                post_cputype_trace <= post_cputype_trace - 1;
                $display("[%0d] CPUTYPE: PC=%016x instr=%08x R1=%016x R19=%016x R26=%016x R28=%016x null=%0d",
                         cycle_count, cpu.pc_rd,
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32],
                         cpu.rf[1], cpu.rf[19], cpu.rf[26], cpu.rf[28],
                         cpu.in_nullified);
            end

            // Data trap monitor (first 50 occurrences with full details)
            if (cpu.stb_data_trap_taken && dtlb_trap_count < 50) begin
                dtlb_trap_count <= dtlb_trap_count + 1;
                $display("[%0d] DATA_TRAP: PC=%016x eff_addr=%016x dspace=%016x PSW=%016x instr=%08x",
                         cycle_count, cpu.pc_rd,
                         cpu.fldd_data_trap_taken ? cpu.fldd_eff_addr_mux : cpu.cr21_rd,
                         cpu.cr20_rd, cpu.psw,
                         cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0]
                                      : cpu.umem[cpu.pc_pa[25:3]][63:32]);
                $display("        dtlb_hit=%0d btlb_d_hit=%0d fldd_hit=%0d fldd_dbm0=%0d dtlb_next=%0d sr0=%016x",
                         cpu.dtlb_hit, cpu.fldd_btlb_d_hit_mux, cpu.fldd_data_trap_taken, cpu.fldd_dbm_0_mux, cpu.dtlb_next_rd, cpu.sr0_rd);
                $display("        BTLB0: valid=%0d type_d=%0d va=%016x mask=%016x space=%016x",
                         cpu.btlb_valid[0], cpu.btlb_type_d[0],
                         cpu.btlb_va_base[0], cpu.btlb_page_mask[0], cpu.btlb_space[0]);
            end

            // IDTLBT trace: when PC=0x00151d10 (idtlbt r16,r17 in dbit_trap_20w)
            if (cpu.pc_rd == 64'h00151d10 && dbit_trace_count < 20) begin
                $display("[%0d] DBIT_IDTLBT: r16=%016x r17=%016x CR20(ISR)=%016x CR21(IOR)=%016x dtlb_next=%0d null=%0d trap=%0d",
                         cycle_count, cpu.rf[16], cpu.rf[17], cpu.cr20_rd, cpu.cr21_rd,
                         cpu.dtlb_next_rd, cpu.in_nullified, cpu.instr_trap_taken);
                $display("  prot_bit60=%0d prot_bit56=%0d vpn_from_cr21=%013x",
                         cpu.rf[17][60], cpu.rf[17][56], cpu.cr21_rd[63:12]);
                dbit_trace_count <= dbit_trace_count + 1;
            end

            // Faulting store trace: when PC=0x4015166c (std r1,8(ret1) in intr_save2)
            if (cpu.pc_rd == 64'h4015166c && dbit_trace_count < 20 && dbit_trace_count > 0) begin
                $display("[%0d] FAULT_STORE: r1=%016x ret1(r29)=%016x eff_addr=%016x PSW=%016x",
                         cycle_count, cpu.rf[1], cpu.rf[29], cpu.rf[29] + 64'h8, cpu.psw);
                $display("  dtlb_hit=%0d dirty_trap=%0d store_prot=%0d null=%0d trap=%0d",
                         cpu.dtlb_hit, cpu.dirty_trap, cpu.store_prot_viol,
                         cpu.in_nullified, cpu.instr_trap_taken);
                $display("  dtlb_prot_result=%016x prot[60]=%0d prot[56]=%0d ppn=%013x",
                         cpu.dtlb_prot_result, cpu.dtlb_prot_result[60], cpu.dtlb_prot_result[56],
                         cpu.dtlb_ppn_result);
                // Dump ALL DTLB entries
                for (integer kk = 0; kk < 16; kk = kk + 1) begin
                    $display("  DTLB[%0d]: valid=%0d vpn=%013x ppn=%013x space=%016x prot=%016x",
                             kk, cpu.dtlb_valid[kk], cpu.dtlb_vpn[kk], cpu.dtlb_ppn[kk], cpu.dtlb_space[kk], cpu.dtlb_prot[kk]);
                end
                dbit_trace_count <= dbit_trace_count + 1;
            end

            // Store at 0x4015266c trace: std r1,8(ret1) - the faulting instruction
            if (cpu.pc_rd == 64'h4015266c && handle_int_trace_count < 100) begin
                $display("[%0d] FAULT_STD: r1=%016x ret1(r29)=%016x addr=%016x PSW=%016x null=%0d trap=%0d",
                         cycle_count, cpu.rf[1], cpu.rf[29], cpu.rf[29] + 64'h8, cpu.psw,
                         cpu.in_nullified, cpu.instr_trap_taken);
                // Dump all valid DTLB entries
                for (integer kk = 0; kk < 16; kk = kk + 1) begin
                    if (cpu.dtlb_valid[kk])
                        $display("  DTLB[%0d]: vpn=%013x ppn=%013x space=%016x",
                                 kk, cpu.dtlb_vpn[kk], cpu.dtlb_ppn[kk], cpu.dtlb_space[kk]);
                end
            end

            // DTLB entry change monitor (detect both new entries AND replacements)
            for (integer jj = 0; jj < 16; jj = jj + 1) begin
                if (cpu.dtlb_valid[jj] && (!last_dtlb_valid[jj] || cpu.dtlb_vpn[jj] != last_dtlb_vpn[jj])) begin
                    $display("[%0d] DTLB_CHANGE[%0d]: vpn=%013x ppn=%013x space=%016x prot=%016x",
                             cycle_count, jj,
                             cpu.dtlb_vpn[jj], cpu.dtlb_ppn[jj],
                             cpu.dtlb_space[jj], cpu.dtlb_prot[jj]);
                end
                last_dtlb_vpn[jj] <= cpu.dtlb_vpn[jj];
                last_dtlb_valid[jj] <= cpu.dtlb_valid[jj];
            end

            // Short trace after PSW.C goes high (DISABLED - too verbose)
            // if (cpu.psw[18] && !last_psw[18] && psw_c_total < 10) begin
            //     post_c_trace <= 200;
            // end
            // if (post_c_trace > 0) begin
            //     post_c_trace <= post_c_trace - 1;
            //     $display("[%0d] TRACE: ...");
            // end

            // Stuck-at detector (earlier trigger for debugging: 500 cycles)
            if (cpu.pc_rd == last_pc && cycle_count > 100) begin
                if (stuck_counter < 32'd1002) stuck_counter <= stuck_counter + 1;
                // Per-cycle trace for first 10 stuck cycles
                if (stuck_counter >= 32'd5 && stuck_counter < 32'd15) begin
                    $display("[%0d] STUCK_TRACE: PC=%016x pc_pa=%016x PSW=%016x delay_slot=%0d null=%0d trap=%0d exc=%0d psw_N=%0d",
                             cycle_count, cpu.pc_rd, cpu.pc_pa, cpu.psw,
                             cpu.delay_slot_rd, cpu.in_nullified, cpu.instr_trap_taken, cpu.exception_taken, cpu.psw[21]);
                end
                if (stuck_counter == 32'd500) begin
                    $display("[%0d] STUCK_AT: PC=%016x PSW=%016x R2=%016x SP=%016x",
                             cycle_count, cpu.pc_rd, cpu.psw, cpu.rf[2], cpu.rf[30]);
                    $display("        CR14=%016x CR18=%016x CR22=%016x",
                             cpu.cr14_rd, cpu.cr18_rd, cpu.cr22_rd);
                    $display("        in_nullified=%0d instr_trap_taken=%0d psw_C=%0d psw_D=%0d psw_N=%0d",
                             cpu.in_nullified, cpu.instr_trap_taken, cpu.psw[18], cpu.psw[1], cpu.psw[21]);
                    $display("        BTLB[0]: valid=%0d type_i=%0d type_d=%0d va=%016x mask=%016x pa=%016x",
                             cpu.btlb_valid[0], cpu.btlb_type_i[0], cpu.btlb_type_d[0],
                             cpu.btlb_va_base[0], cpu.btlb_page_mask[0], cpu.btlb_pa_base[0]);
                    $display("        R3=%016x R4=%016x R19=%016x R28=%016x",
                             cpu.rf[3], cpu.rf[4], cpu.rf[19], cpu.rf[28]);
                    $display("        R20=%016x R25=%016x SAR=%016x R10=%016x R14=%016x R22=%016x",
                             cpu.rf[20], cpu.rf[25], {58'h0, cpu.sar_rd}, cpu.rf[10], cpu.rf[14], cpu.rf[22]);
                    $display("        sub_enable=%0d select_1_ds=%0d ds_wr_mux=%0d branch_target=%016x",
                             cpu.sub_enable, cpu.select_1_delay_slot_merged,
                             cpu.delay_slot_wr_mux, cpu.branch_target_rd);
                    $display("        in_delay_slot=%0d in_delay_slot_eq_1=%0d instr_rd=%08x delay_slot_wr=%0d",
                             cpu.in_delay_slot, cpu.in_delay_slot_eq_1,
                             cpu.pc_pa[2] ? cpu.umem[cpu.pc_pa[25:3]][31:0] : cpu.umem[cpu.pc_pa[25:3]][63:32],
                             cpu.delay_slot_wr);
                    $fflush();
                end
            end else begin
                stuck_counter <= 0;
            end

            // Periodic PC sampling (every 1M cycles)
            if (cycle_count > 0 && cycle_count % 1000000 == 0) begin
                $display("[%0d] SAMPLE: PC=%016x PSW=%016x R2=%016x SP=%016x CR18=%016x",
                         cycle_count, cpu.pc_rd, cpu.psw, cpu.rf[2], cpu.rf[30], cpu.cr18_rd);
            end

            // === Debug EFAULT in copy_to_user during create_elf_tables ===
            // Stack setup traces (always on during execve window)
            // setup_arg_pages entry: R26=bprm, R25=stack_top, R24=exec_stack
            if (cpu.pc_rd == 64'h000000004029df68) begin
                $display("[%0d] SETUP_ARG_PAGES: bprm(R26)=%016x stack_top(R25)=%016x exec_stack(R24)=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[24], cpu.rf[2]);
            end
            // relocate_vma_down entry: R26=vma, R25=shift
            if (cpu.pc_rd == 64'h0000000040250500) begin
                $display("[%0d] RELOCATE_VMA_DOWN: vma(R26)=%016x shift(R25)=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end
            // expand_stack_locked entry: R26=vma, R25=address
            if (cpu.pc_rd == 64'h000000004024ebc8) begin
                $display("[%0d] EXPAND_STACK_LOCKED: vma(R26)=%016x addr(R25)=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end
            // randomize_stack_top entry: R26=stack_top
            if (cpu.pc_rd == 64'h000000004022b388) begin
                $display("[%0d] RANDOMIZE_STACK_TOP: stack_top(R26)=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[2]);
            end
            // Trace handle_interruption/page_fault/fixup during execve (always on)
            // handle_interruption entry: trap code in R26, regs in R25
            if (cpu.pc_rd == 64'h0000000040156ef8 && cpu.rf[26] == 15) begin
                $display("[%0d] HANDLE_INT: code(R26)=%0d CR20(ISR)=%016x CR21(IOR)=%016x SR0=%016x SR2=%016x SR3=%016x PSW=%016x CR25=%016x",
                         cycle_count, cpu.rf[26], cpu.cr20_rd, cpu.cr21_rd, cpu.sr0_rd, cpu.sr2_rd, cpu.sr3_rd, cpu.psw, cpu.cr25_rd);
            end
            // fixup_exception entry
            if (cpu.pc_rd == 64'h0000000040153a38) begin
                $display("[%0d] FIXUP_EXCEPTION: regs(R26)=%016x CR20(ISR)=%016x CR21(IOR)=%016x",
                         cycle_count, cpu.rf[26], cpu.cr20_rd, cpu.cr21_rd);
            end
            // expand_upwards entry (0x4024e818): R26=vma, R25=address
            if (cpu.pc_rd == 64'h000000004024e818) begin
                $display("[%0d] EXPAND_UPWARDS: vma(R26)=%016x addr(R25)=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[2]);
            end
            // expand_upwards return (0x4024ea00 = error path, 0x4024eb74+ = success)
            // The ret0 is set at 0x4024ea00 (ldi -c,r6 = -ENOMEM) or earlier default -EFAULT
            // Trace expand_stack return: at expand_stack_locked+0x3c = 0x4024ec04
            if (cpu.pc_rd == 64'h000000004024ec04) begin
                $display("[%0d] EXPAND_STACK_RET: ret0(R28)=%016x R2=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[2]);
            end
            // setup_arg_pages return value check in load_elf_binary at 0x4030a0fc
            if (cpu.pc_rd == 64'h000000004030a0fc) begin
                $display("[%0d] SETUP_ARG_RET: ret0(R28)=%016x R2=%016x",
                         cycle_count, cpu.rf[28], cpu.rf[2]);
            end
            // create_elf_tables (in load_elf_binary) - trace R28 transitions to -14
            if (cpu.rf[28] == 64'hfffffffffffffff2 && prev_r28_exec != 64'hfffffffffffffff2) begin
                $display("[%0d] EFAULT_SET: PC=%016x R28=%016x R26=%016x R25=%016x R2=%016x SP=%016x",
                         cycle_count, cpu.pc_rd, cpu.rf[28], cpu.rf[26], cpu.rf[25], cpu.rf[2], cpu.rf[30]);
            end
            prev_r28_exec <= cpu.rf[28];
            // === Execve debug traces (PC-triggered, not cycle-range) ===
            // run_init_process entry
            if (cpu.pc_rd == 64'h0000000040498dd0) begin
                $display("[%0d] RUN_INIT: entry R26=%016x SP=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[30], cpu.rf[2]);
            end
            // try_to_run_init_process entry
            if (cpu.pc_rd == 64'h0000000040498f68) begin
                $display("[%0d] TRY_INIT: entry R26=%016x SP=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[30], cpu.rf[2]);
            end
            // bprm_execve entry
            if (cpu.pc_rd == 64'h000000004029ec78) begin
                $display("[%0d] BPRM_EXECVE: entry R26=%016x R25=%016x SP=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[30], cpu.rf[2]);
            end
            // do_execveat_common entry
            if (cpu.pc_rd == 64'h00000000402a0378) begin
                $display("[%0d] DO_EXECVEAT: entry R26=%016x R25=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[30]);
            end
            // load_elf_binary entry (two addresses)
            if (cpu.pc_rd == 64'h0000000040309b20 || cpu.pc_rd == 64'h000000004030cab8) begin
                $display("[%0d] LOAD_ELF: entry R26=%016x SP=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[30], cpu.rf[2]);
            end
            // setup_arg_pages
            if (cpu.pc_rd == 64'h000000004029df68) begin
                $display("[%0d] SETUP_ARG: entry R26=%016x R25=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[30]);
            end
            // begin_new_exec
            if (cpu.pc_rd == 64'h00000000402a0aa8) begin
                $display("[%0d] BEGIN_NEW_EXEC: entry R26=%016x SP=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[30], cpu.rf[2]);
            end
            // copy_strings_kernel
            if (cpu.pc_rd == 64'h000000004029f5e0) begin
                $display("[%0d] COPY_STRINGS: entry R26=%016x R25=%016x SP=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[25], cpu.rf[30]);
            end
            // finalize_exec
            if (cpu.pc_rd == 64'h000000004029ddb8) begin
                $display("[%0d] FINALIZE_EXEC: entry R26=%016x SP=%016x R2=%016x",
                         cycle_count, cpu.rf[26], cpu.rf[30], cpu.rf[2]);
            end

            // Timeout
            if (cycle_count >= max_cycles) begin
                $display("");
                $display("=== Simulation Timeout (%0d cycles) ===", max_cycles);
                $display("Final PC: 0x%016x PSW: 0x%016x", cpu.pc_rd, cpu.psw);
                $display("CR14: 0x%016x CR18: 0x%016x CR22: 0x%016x",
                         cpu.cr14_rd, cpu.cr18_rd, cpu.cr22_rd);
                $display("Regs: R1=%016x R2=%016x R26=%016x R28=%016x SP=%016x",
                         cpu.rf[1], cpu.rf[2], cpu.rf[26], cpu.rf[28], cpu.rf[30]);
                for (i = 0; i < 8; i = i + 1)
                    $display("BTLB[%0d]: valid=%0d type_i=%0d type_d=%0d va=%016x mask=%016x pa=%016x space=%016x",
                             i, cpu.btlb_valid[i], cpu.btlb_type_i[i], cpu.btlb_type_d[i],
                             cpu.btlb_va_base[i], cpu.btlb_page_mask[i], cpu.btlb_pa_base[i],
                             cpu.btlb_space[i]);
                // Dump kernel log buffer (__log_buf at PA 0x70b408)
                $display("");
                $display("=== Kernel Log Buffer (PA 0x70b408) ===");
                begin
                    integer log_i;
                    reg [63:0] log_word;
                    reg [7:0] log_byte;
                    for (log_i = 0; log_i < 16384; log_i = log_i + 1) begin
                        log_word = cpu.umem[(32'h70b408 >> 3) + (log_i >> 3)];
                        case (log_i[2:0])
                            3'd0: log_byte = log_word[63:56];
                            3'd1: log_byte = log_word[55:48];
                            3'd2: log_byte = log_word[47:40];
                            3'd3: log_byte = log_word[39:32];
                            3'd4: log_byte = log_word[31:24];
                            3'd5: log_byte = log_word[23:16];
                            3'd6: log_byte = log_word[15:8];
                            3'd7: log_byte = log_word[7:0];
                        endcase
                        if (log_byte >= 8'h20 && log_byte < 8'h7f)
                            $write("%c", log_byte);
                        else if (log_byte == 8'h0a)
                            $write("\n");
                        else if (log_byte == 8'h00)
                            ; // skip nulls
                        else
                            $write(".");
                    end
                    $display("");
                    $display("=== End Kernel Log Buffer ===");
                end
                $finish;
            end
        end
    end

    // =========================================================================
    // Boot Image Loading
    // =========================================================================
    integer boot_file, fdt_file, initrd_file;
    integer bytes_read;
    reg [7:0] byte_data;
    integer i, j;
    string boot_path, fdt_path, initrd_path, firmware_path;
    integer word_count, fdt_word_count, initrd_word_count;

    initial begin
        initialized           = 0;
        reset                 = 1;
        reset_counter         = 10;
        cycle_count           = 0;
        timer_irq_pending_tb  = 0;
        ext_irq_lines_tb      = 0;
        eirr_reg              = 0;

        // Get cycle limit from plusargs (default 200M)
        if (!$value$plusargs("cycles=%d", max_cycles))
            max_cycles = 2000000;

        // Get entry point from plusargs
        if (!$value$plusargs("entry=%h", entry_point))
            entry_point = {32'h0, BOOT_STUB_ADDR};

        // Get boot image path
        if (!$value$plusargs("boot=%s", boot_path))
            boot_path = "boot.bin";

        // Get FDT path
        if (!$value$plusargs("fdt=%s", fdt_path))
            fdt_path = "hppa20_isacomp.dtb";

        // Get initrd path (optional)
        if (!$value$plusargs("initrd=%s", initrd_path))
            initrd_path = "";

        // Get firmware path
        if (!$value$plusargs("firmware=%s", firmware_path))
            firmware_path = "firmware.bin";

        $display("===========================================");
        $display("HPPA (PA-RISC 2.0) Linux Boot Simulation");
        $display("===========================================");
        $display("Boot image: %s", boot_path);
        $display("FDT:        %s", fdt_path);
        $display("Entry:      0x%016x", entry_point);
        $display("===========================================");

        // =====================================================================
        // Load boot image into CPU unified memory (64-bit words, big-endian)
        // =====================================================================
        boot_file = $fopen(boot_path, "rb");
        if (boot_file == 0) begin
            $display("ERROR: Cannot open boot image: %s", boot_path);
            $finish;
        end

        word_count = 0;
        while (!$feof(boot_file)) begin
            // Upper 32-bit half [63:32]: bytes 0-3 big-endian
            for (j = 7; j >= 4; j = j - 1) begin
                bytes_read = $fread(byte_data, boot_file);
                if (bytes_read == 1)
                    cpu.umem[word_count][j*8 +: 8] = byte_data;
            end
            // Lower 32-bit half [31:0]: bytes 4-7 big-endian
            for (j = 3; j >= 0; j = j - 1) begin
                bytes_read = $fread(byte_data, boot_file);
                if (bytes_read == 1)
                    cpu.umem[word_count][j*8 +: 8] = byte_data;
            end
            word_count = word_count + 1;
        end
        $fclose(boot_file);
        $display("Loaded boot image: %0d 64-bit words (%0d KB)",
                 word_count, (word_count * 8) / 1024);

        // Load FDT (device tree blob)
        fdt_file = $fopen(fdt_path, "rb");
        if (fdt_file == 0) begin
            $display("WARNING: Cannot open FDT: %s (continuing without FDT)", fdt_path);
        end else begin
            fdt_word_count = FDT_ADDR >> 3;
            while (!$feof(fdt_file)) begin
                for (j = 7; j >= 4; j = j - 1) begin
                    bytes_read = $fread(byte_data, fdt_file);
                    if (bytes_read == 1)
                        cpu.umem[fdt_word_count][j*8 +: 8] = byte_data;
                end
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, fdt_file);
                    if (bytes_read == 1)
                        cpu.umem[fdt_word_count][j*8 +: 8] = byte_data;
                end
                fdt_word_count = fdt_word_count + 1;
            end
            $fclose(fdt_file);
            $display("Loaded FDT: %0d words at 0x%08x",
                     fdt_word_count - (FDT_ADDR >> 3), FDT_ADDR);
            $display("FDT magic: 0x%08x (expect 0xd00dfeed)",
                     cpu.umem[FDT_ADDR >> 3][63:32]);
        end

        // Load initrd if specified
        if (initrd_path != "") begin
            initrd_file = $fopen(initrd_path, "rb");
            if (initrd_file == 0) begin
                $display("ERROR: Cannot open initrd: %s", initrd_path);
                $finish;
            end
            initrd_word_count = INITRD_BASE >> 3;
            while (!$feof(initrd_file)) begin
                for (j = 7; j >= 4; j = j - 1) begin
                    bytes_read = $fread(byte_data, initrd_file);
                    if (bytes_read == 1)
                        cpu.umem[initrd_word_count][j*8 +: 8] = byte_data;
                end
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, initrd_file);
                    if (bytes_read == 1)
                        cpu.umem[initrd_word_count][j*8 +: 8] = byte_data;
                end
                initrd_word_count = initrd_word_count + 1;
            end
            $fclose(initrd_file);
            $display("Loaded initrd: %0d words at 0x%08x",
                     initrd_word_count - (INITRD_BASE >> 3), INITRD_BASE);
        end

        // =====================================================================
        // Load firmware (PDC/IODC) into ROM area at 0x0F000000
        // =====================================================================
        begin
            integer fw_file, fw_word_count;
            fw_file = $fopen(firmware_path, "rb");
            if (fw_file == 0) begin
                $display("ERROR: Cannot open firmware: %s", firmware_path);
                $finish;
            end
            fw_word_count = PDC_STUB_ADDR >> 3;
            while (!$feof(fw_file)) begin
                for (j = 7; j >= 4; j = j - 1) begin
                    bytes_read = $fread(byte_data, fw_file);
                    if (bytes_read == 1)
                        cpu.umem[fw_word_count][j*8 +: 8] = byte_data;
                end
                for (j = 3; j >= 0; j = j - 1) begin
                    bytes_read = $fread(byte_data, fw_file);
                    if (bytes_read == 1)
                        cpu.umem[fw_word_count][j*8 +: 8] = byte_data;
                end
                fw_word_count = fw_word_count + 1;
            end
            $fclose(fw_file);
            $display("Loaded firmware: %0d words at 0x%08x",
                     fw_word_count - (PDC_STUB_ADDR >> 3), PDC_STUB_ADDR);
        end

        // =====================================================================
        // Page Zero dynamic fields
        // =====================================================================
        if (initrd_path != "") begin
            write_mem32(32'h394, INITRD_BASE);
            write_mem32(32'h398, INITRD_BASE +
                        (initrd_word_count - (INITRD_BASE >> 3)) * 8);
        end

        // =====================================================================
        // Simulation speedup: NOP out vsnprintf padding loop branches.
        // The kernel's vsnprintf uses fixed-point arithmetic for field_width
        // padding. When field_width=-1 (the default for %c etc.), the 24-bit
        // negative value becomes positive in 64-bit unsigned, causing the
        // padding loop to run ~16.7M iterations. This is bounded and correct
        // behavior on real hardware (takes ~30ms at 500MHz), but in simulation
        // it takes hours. NOP-ing the branches skips all padding loops
        // (cosmetic-only impact on kernel printk formatting).
        //
        // vsnprintf+0x2e4: b,l,n 4049003c (right-pad loop 1) at VA 0x4048ffac
        // vsnprintf+0x34c: b,l,n 40490054 (right-pad loop 2) at VA 0x40490014
        // =====================================================================
        // PA = VA - 0x40000000. PA-RISC NOP = or r0,r0,r0 = 0x08000240
        // DISABLED: addresses are kernel-build-dependent and break after rebuild
        // cpu.umem[32'h91FF5][31:0] = 32'h08000240;
        // $display("Patched vsnprintf padding loop 1 at PA 0x0048ffac (NOP)");
        // cpu.umem[32'h92002][31:0] = 32'h08000240;
        // $display("Patched vsnprintf padding loop 2 at PA 0x00490014 (NOP)");

        // Display memory layout
        $display("-------------------------------------------");
        $display("Memory Layout:");
        $display("  0x%08x - Page Zero", PAGE_ZERO);
        $display("  0x%08x - FDT", FDT_ADDR);
        $display("  0x%08x - Boot stub (entry)", entry_point[31:0]);
        $display("  0x%08x - PDC firmware (ROM)", PDC_STUB_ADDR);
        $display("  0x%08x - IODC firmware (ROM)", IODC_STUB_ADDR);
        $display("  0x%08x - Kernel load address", KERNEL_LOAD);
        if (initrd_path != "")
            $display("  0x%08x - Initrd", INITRD_BASE);
        $display("  0x%08x - UART", UART_BASE);
        $display("  0x%08x - RAM end", MEMORY_BASE + MEMORY_SIZE - 1);
        $display("-------------------------------------------");

        // Verify boot stub entry
        $display("Boot stub entry:");
        $display("  [0x%08x] = 0x%08x", entry_point[31:0], read_mem32(entry_point[31:0]));
        $display("  [0x%08x] = 0x%08x", entry_point[31:0] + 32'd4, read_mem32(entry_point[31:0] + 32'd4));
        $display("Firmware at PDC entry (0x%08x):", PDC_STUB_ADDR);
        $display("  [0x%08x] = 0x%08x %08x", PDC_STUB_ADDR,
                 cpu.umem[PDC_STUB_ADDR >> 3][63:32], cpu.umem[PDC_STUB_ADDR >> 3][31:0]);
    end

    // =========================================================================
    // Waveform Dumping
    // =========================================================================
    initial begin
        if ($test$plusargs("trace")) begin
            $dumpfile("hppa20_boot.vcd");
            $dumpvars(0, hppa20_boot_tb);
        end
    end

endmodule
