// CVFPU Wrapper for isacomp
// Wraps the OpenHW Group's cvfpu (fpnew) with a simplified interface
// for use in isacomp-generated single-cycle processors.
//
// This wrapper supports both RV32F and RV64F configurations.
// - RV32F: 32-bit width, INT32 only
// - RV64F: 64-bit width, INT32 and INT64

module cvfpu_wrapper #(
    parameter WIDTH = 32,  // 32 for RV32F, 64 for RV64F/D
    parameter FP_FORMAT = 0  // 0=FP32, 1=FP64 (D extension)
) (
    input  logic                clk_i,
    input  logic                rst_ni,

    // Operands (up to 3 for fused multiply-add)
    input  logic [WIDTH-1:0]    operand_a_i,
    input  logic [WIDTH-1:0]    operand_b_i,
    input  logic [WIDTH-1:0]    operand_c_i,

    // Operation select (encoded as fpnew_pkg::operation_e)
    input  logic [3:0]          op_i,
    input  logic                op_mod_i,       // Operation modifier

    // Rounding mode (RISC-V encoding)
    input  logic [2:0]          rnd_mode_i,

    // Integer format select for conversions
    input  logic [1:0]          int_fmt_i,      // 0=INT8, 1=INT16, 2=INT32, 3=INT64

    // FP format select for F2F conversions (optional, default to FP_FORMAT)
    input  logic [2:0]          src_fmt_i,      // Source FP format (for F2F)
    input  logic [2:0]          dst_fmt_i,      // Destination FP format (for F2F)

    // Control
    input  logic                valid_i,
    output logic                ready_o,

    // Result
    output logic [WIDTH-1:0]    result_o,
    output logic [4:0]          status_o,       // IEEE exception flags {NV, DZ, OF, UF, NX}
    output logic                valid_o
);

    // Import the fpnew package
    import fpnew_pkg::*;

    // Configure FPU features based on WIDTH and FP_FORMAT
    // RV32F: FP32 only, INT32 only
    // RV64F: FP32 only, INT32 and INT64
    // RV32D/RV64D: FP32+FP64, INT32 and INT64
    // Note: IntFmtMask uses ascending bit order [0:3] where bit 0=INT8, 1=INT16, 2=INT32, 3=INT64
    // In Verilog literal 4'bABCD: A=bit[0]=INT8, B=bit[1]=INT16, C=bit[2]=INT32, D=bit[3]=INT64
    localparam fpu_features_t FPU_FEATURES = '{
        Width:         WIDTH,
        EnableVectors: 1'b0,
        EnableNanBox:  1'b1,
        FpFmtMask:     (WIDTH == 64 || FP_FORMAT == 1) ? 5'b11000 : 5'b10000,  // FP32+FP64 for D ext or 64-bit
        IntFmtMask:    (WIDTH == 64 || FP_FORMAT == 1) ? 4'b1111 : 4'b0010  // Enable all INT formats for D ext or 64-bit
    };

    // Determine actual FP format to use based on FP_FORMAT parameter
    localparam fp_format_e FP_FMT = (FP_FORMAT == 1) ? FP64 : FP32;

    // No pipeline registers for single-cycle operation
    localparam fpu_implementation_t FPU_IMPLEMENTATION = '{
        PipeRegs:   '{default: 0},
        UnitTypes:  '{'{default: PARALLEL},  // ADDMUL
                      '{default: MERGED},    // DIVSQRT
                      '{default: PARALLEL},  // NONCOMP
                      '{default: MERGED}},   // CONV
        PipeConfig: BEFORE
    };

    // Pack operands for fpnew_top (expects array)
    logic [2:0][WIDTH-1:0] operands;
    assign operands[0] = operand_a_i;
    assign operands[1] = operand_b_i;
    assign operands[2] = operand_c_i;

    // Map rounding mode
    roundmode_e rnd_mode;
    assign rnd_mode = roundmode_e'(rnd_mode_i);

    // Map operation
    operation_e op;
    assign op = operation_e'(op_i);

    // Map integer format
    int_format_e int_fmt;
    assign int_fmt = int_format_e'(int_fmt_i);

    // Internal signals
    logic in_ready;
    logic out_valid;
    logic busy;
    status_t fpu_status;

    // Instantiate fpnew_top
    fpnew_top #(
        .Features       ( FPU_FEATURES       ),
        .Implementation ( FPU_IMPLEMENTATION ),
        .DivSqrtSel     ( (WIDTH == 64 || FP_FORMAT == 1) ? PULP : TH32 ),  // PULP for D ext or 64-bit, TH32 for FP32-only
        .TagType        ( logic              ),
        .TrueSIMDClass  ( 0                  ),
        .EnableSIMDMask ( 0                  )
    ) i_fpnew (
        .clk_i          ( clk_i              ),
        .rst_ni         ( rst_ni             ),
        .operands_i     ( operands           ),
        .rnd_mode_i     ( rnd_mode           ),
        .op_i           ( op                 ),
        .op_mod_i       ( op_mod_i           ),
        .src_fmt_i      ( fp_format_e'(src_fmt_i) ),  // Source format from input
        .dst_fmt_i      ( fp_format_e'(dst_fmt_i) ),  // Destination format from input
        .int_fmt_i      ( int_fmt            ),  // Integer format from input
        .vectorial_op_i ( 1'b0               ),  // No vector ops
        .tag_i          ( 1'b0               ),
        .simd_mask_i    ( 1'b1               ),
        .in_valid_i     ( valid_i            ),
        .in_ready_o     ( in_ready           ),
        .flush_i        ( 1'b0               ),
        .result_o       ( result_o           ),
        .status_o       ( fpu_status         ),
        .tag_o          ( /* unused */       ),
        .out_valid_o    ( out_valid          ),
        .out_ready_i    ( 1'b1               ),  // Always ready to accept result
        .busy_o         ( busy               ),
        .early_valid_o  ( /* unused */       )
    );

    // Output mappings
    assign ready_o = in_ready;
    assign valid_o = out_valid;
    assign status_o = {fpu_status.NV, fpu_status.DZ, fpu_status.OF, fpu_status.UF, fpu_status.NX};

endmodule


// Convenience wrapper with operation-specific interface
// This provides a simpler interface for common FP operations
// Supports both RV32F (WIDTH=32) and RV64F (WIDTH=64) with F and D extensions
module cvfpu_simple #(
    parameter WIDTH = 32,  // 32 for RV32F, 64 for RV64F/D
    parameter FP_FORMAT = 0,  // 0=FP32 (F extension), 1=FP64 (D extension) - destination format
    parameter SRC_FP_FORMAT = FP_FORMAT  // Source format (for F2F conversions, may differ from FP_FORMAT)
) (
    input  logic              clk_i,
    input  logic              rst_ni,

    // Operands - FP operands use lower 32 bits, integer conversions use full width
    input  logic [WIDTH-1:0]  a_i,
    input  logic [WIDTH-1:0]  b_i,
    input  logic [WIDTH-1:0]  c_i,       // For fused multiply-add

    // Operation select (isacomp encoding)
    // 0=ADD, 1=SUB, 2=MUL, 3=DIV, 4=SQRT
    // 5=FMADD, 6=FMSUB, 7=FNMADD, 8=FNMSUB
    // 9=SGNJ, 10=SGNJN, 11=SGNJX
    // 12=MIN, 13=MAX
    // 14=EQ, 15=LT, 16=LE
    // 17=CLASS
    // 18=CVT_W_S, 19=CVT_WU_S, 20=CVT_S_W, 21=CVT_S_WU (32-bit int)
    // 22=CVT_L_S, 23=CVT_LU_S, 24=CVT_S_L, 25=CVT_S_LU (64-bit int, RV64F only)
    input  logic [4:0]        op_select_i,

    // Rounding mode
    input  logic [2:0]        rnd_mode_i,

    // Control
    input  logic              valid_i,
    output logic              ready_o,

    // Result
    output logic [WIDTH-1:0]  result_o,
    output logic [4:0]        status_o,
    output logic              valid_o
);

    import fpnew_pkg::*;

    // Map isacomp operation to fpnew operation and modifier
    logic [3:0] fpnew_op;
    logic       op_mod;
    logic [1:0] int_fmt;  // Integer format: 2=INT32, 3=INT64

    always_comb begin
        // Default
        fpnew_op = ADD;
        op_mod = 1'b0;
        int_fmt = 2'b10;  // INT32 by default

        case (op_select_i)
            5'd0:  begin fpnew_op = ADD;      op_mod = 1'b0; end  // ADD
            5'd1:  begin fpnew_op = ADD;      op_mod = 1'b1; end  // SUB (ADD with mod)
            5'd2:  begin fpnew_op = MUL;      op_mod = 1'b0; end  // MUL
            5'd3:  begin fpnew_op = DIV;      op_mod = 1'b0; end  // DIV
            5'd4:  begin fpnew_op = SQRT;     op_mod = 1'b0; end  // SQRT
            5'd5:  begin fpnew_op = FMADD;    op_mod = 1'b0; end  // FMADD: (a*b)+c
            5'd6:  begin fpnew_op = FMADD;    op_mod = 1'b1; end  // FMSUB: (a*b)-c
            5'd7:  begin fpnew_op = FNMSUB;   op_mod = 1'b1; end  // FNMADD: -(a*b)-c
            5'd8:  begin fpnew_op = FNMSUB;   op_mod = 1'b0; end  // FNMSUB: -(a*b)+c
            5'd9:  begin fpnew_op = SGNJ;     op_mod = 1'b0; end  // SGNJ
            5'd10: begin fpnew_op = SGNJ;     op_mod = 1'b1; end  // SGNJN
            5'd11: begin fpnew_op = SGNJ;     op_mod = 1'b0; end  // SGNJX (need different encoding)
            5'd12: begin fpnew_op = MINMAX;   op_mod = 1'b0; end  // MIN
            5'd13: begin fpnew_op = MINMAX;   op_mod = 1'b1; end  // MAX
            5'd14: begin fpnew_op = CMP;      op_mod = 1'b0; end  // EQ
            5'd15: begin fpnew_op = CMP;      op_mod = 1'b0; end  // LT (different encoding in rnd_mode)
            5'd16: begin fpnew_op = CMP;      op_mod = 1'b0; end  // LE
            5'd17: begin fpnew_op = CLASSIFY; op_mod = 1'b0; end  // CLASS
            // 32-bit integer conversions
            5'd18: begin fpnew_op = F2I;      op_mod = 1'b0; int_fmt = 2'b10; end  // CVT.W.S (signed int32)
            5'd19: begin fpnew_op = F2I;      op_mod = 1'b1; int_fmt = 2'b10; end  // CVT.WU.S (unsigned int32)
            5'd20: begin fpnew_op = I2F;      op_mod = 1'b0; int_fmt = 2'b10; end  // CVT.S.W (signed int32)
            5'd21: begin fpnew_op = I2F;      op_mod = 1'b1; int_fmt = 2'b10; end  // CVT.S.WU (unsigned int32)
            // 64-bit integer conversions (RV64F only)
            5'd22: begin fpnew_op = F2I;      op_mod = 1'b0; int_fmt = 2'b11; end  // CVT.L.S (signed int64)
            5'd23: begin fpnew_op = F2I;      op_mod = 1'b1; int_fmt = 2'b11; end  // CVT.LU.S (unsigned int64)
            5'd24: begin fpnew_op = I2F;      op_mod = 1'b0; int_fmt = 2'b11; end  // CVT.S.L (signed int64)
            5'd25: begin fpnew_op = I2F;      op_mod = 1'b1; int_fmt = 2'b11; end  // CVT.S.LU (unsigned int64)
            // FP-to-FP format conversions (D extension)
            5'd26: begin fpnew_op = F2F;      op_mod = 1'b0; end  // CVT.S.D (FP64 to FP32)
            5'd27: begin fpnew_op = F2F;      op_mod = 1'b0; end  // CVT.D.S (FP32 to FP64)
            default: begin fpnew_op = ADD;    op_mod = 1'b0; end
        endcase
    end

    // For comparisons, the specific comparison type is encoded in the rounding mode field
    // FEQ: rm=010, FLT: rm=001, FLE: rm=000
    // For MINMAX, the operation type is also encoded in the rounding mode field
    // MIN: rm=RNE(0), MAX: rm=RTZ(1)
    logic [2:0] effective_rnd_mode;
    always_comb begin
        effective_rnd_mode = rnd_mode_i;
        case (op_select_i)
            5'd12: effective_rnd_mode = 3'b000;  // MIN (RNE)
            5'd13: effective_rnd_mode = 3'b001;  // MAX (RTZ)
            5'd14: effective_rnd_mode = 3'b010;  // EQ
            5'd15: effective_rnd_mode = 3'b001;  // LT
            5'd16: effective_rnd_mode = 3'b000;  // LE
            default: effective_rnd_mode = rnd_mode_i;
        endcase
    end

    // For SGNJX, we need to pass info differently - use operand manipulation
    // SGNJX: result sign = sign(a) XOR sign(b)
    // In fpnew, SGNJ with op_mod=0 copies sign from b
    //           SGNJ with op_mod=1 copies negated sign from b
    // For XOR, we pre-XOR the signs: if sign(a)=1, negate b's sign
    logic [WIDTH-1:0] b_for_sgnj;
    generate
        if (FP_FORMAT == 1) begin : gen_fp64_sgnj
            // FP64: sign bit at position 63 (WIDTH must be 64)
            assign b_for_sgnj = (op_select_i == 5'd11) ? (a_i[63] ? {~b_i[63], b_i[62:0]} : b_i) : b_i;
        end else if (WIDTH == 64) begin : gen_fp32_nanbox_sgnj
            // FP32 NaN-boxed in 64-bit: sign bit at position 31, preserve upper bits
            assign b_for_sgnj = (op_select_i == 5'd11) ? (a_i[31] ? {b_i[63:32], ~b_i[31], b_i[30:0]} : b_i) : b_i;
        end else begin : gen_fp32_sgnj
            // FP32: sign bit at position 31, WIDTH=32
            assign b_for_sgnj = (op_select_i == 5'd11) ? (a_i[31] ? {~b_i[31], b_i[30:0]} : b_i) : b_i;
        end
    endgenerate

    // Operand reordering for fpnew FMA-based operations
    // fpnew computes: operands[0] * operands[1] + operands[2]
    // For ADD/SUB: operands[0] is replaced with 1.0, so result = 1.0 * operands[1] + operands[2]
    // Therefore for ADD(a,b) = a + b, we need: operands[1] = a, operands[2] = b
    // For MUL: operands[2] is replaced with 0, so result = operands[0] * operands[1] + 0
    // For FMADD(a,b,c) = a*b + c, operands are used as-is
    logic [WIDTH-1:0] operand_a_mapped;
    logic [WIDTH-1:0] operand_b_mapped;
    logic [WIDTH-1:0] operand_c_mapped;

    // Constant for 1.0 in appropriate FP format, padded to WIDTH
    // FP32 1.0 = 0x3f800000, FP64 1.0 = 0x3ff0000000000000
    // For FP32 on 64-bit width, NaN-box with 0xffffffff in upper bits
    localparam logic [WIDTH-1:0] ONE_F = (FP_FORMAT == 1) ? 64'h3ff0_0000_0000_0000 :
                                         (WIDTH == 64) ? 64'hffffffff_3f800000 : 32'h3f800000;
    localparam logic [WIDTH-1:0] ZERO  = '0;

    always_comb begin
        case (op_select_i)
            5'd0, 5'd1: begin  // ADD, SUB: need a in operands[1], b in operands[2]
                operand_a_mapped = ONE_F;             // Will be overwritten to 1.0 anyway
                operand_b_mapped = a_i;               // First addend
                operand_c_mapped = b_for_sgnj;        // Second addend
            end
            5'd2: begin  // MUL: a * b, operands[0]=a, operands[1]=b, operands[2] ignored
                operand_a_mapped = a_i;
                operand_b_mapped = b_for_sgnj;
                operand_c_mapped = ZERO;
            end
            5'd3, 5'd4: begin  // DIV, SQRT: a / b or sqrt(a)
                operand_a_mapped = a_i;
                operand_b_mapped = b_for_sgnj;
                operand_c_mapped = ZERO;
            end
            5'd5, 5'd6, 5'd7, 5'd8: begin  // FMADD, FMSUB, FNMADD, FNMSUB: a*b+c
                operand_a_mapped = a_i;
                operand_b_mapped = b_for_sgnj;
                operand_c_mapped = c_i;
            end
            default: begin
                operand_a_mapped = a_i;
                operand_b_mapped = b_for_sgnj;
                operand_c_mapped = c_i;
            end
        endcase
    end

    // Determine source and destination FP formats
    // For most operations, src=dst=FP_FORMAT
    // For F2F conversions, use SRC_FP_FORMAT for source and FP_FORMAT for destination
    logic [2:0] src_fp_fmt;
    logic [2:0] dst_fp_fmt;
    always_comb begin
        // Default: both formats are FP_FORMAT (0=FP32, 1=FP64)
        src_fp_fmt = FP_FORMAT[0] ? 3'd1 : 3'd0;  // 0=FP32, 1=FP64
        dst_fp_fmt = FP_FORMAT[0] ? 3'd1 : 3'd0;

        // For F2F operations, use SRC_FP_FORMAT for source
        if (op_select_i == 5'd26 || op_select_i == 5'd27) begin
            src_fp_fmt = SRC_FP_FORMAT[0] ? 3'd1 : 3'd0;
        end
    end

    // Instantiate the main wrapper
    cvfpu_wrapper #(
        .WIDTH     ( WIDTH     ),
        .FP_FORMAT ( FP_FORMAT )
    ) i_cvfpu (
        .clk_i       ( clk_i              ),
        .rst_ni      ( rst_ni             ),
        .operand_a_i ( operand_a_mapped   ),
        .operand_b_i ( operand_b_mapped   ),
        .operand_c_i ( operand_c_mapped   ),
        .op_i        ( fpnew_op           ),
        .op_mod_i    ( op_mod             ),
        .rnd_mode_i  ( effective_rnd_mode ),
        .int_fmt_i   ( int_fmt            ),
        .src_fmt_i   ( src_fp_fmt         ),
        .dst_fmt_i   ( dst_fp_fmt         ),
        .valid_i     ( valid_i            ),
        .ready_o     ( ready_o            ),
        .result_o    ( result_o           ),
        .status_o    ( status_o           ),
        .valid_o     ( valid_o            )
    );

endmodule
