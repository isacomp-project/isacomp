"""
Floating-point intrinsic function definitions for isacomp.

This module defines FP intrinsic functions that can be used in ISA specifications.
Each intrinsic maps to a specific FP operation that will be implemented as a
hardware module in the generated Verilog.

Rounding Mode:
    Intrinsics with has_rounding_mode=True REQUIRE a rounding mode parameter.
    The rounding mode must be passed as the LAST argument in canonical IEEE 754
    encoding (matching fpnew/RISC-V):
        000 = RNE (Round to Nearest, ties to Even)
        001 = RTZ (Round toward Zero)
        010 = RDN (Round toward -Infinity)
        011 = RUP (Round toward +Infinity)
        100 = RMM (Round to Nearest, ties to Max Magnitude)

    ISAs with different encodings (OpenPOWER, MIPS) must map their native
    encoding to canonical form before passing to intrinsics.

    Example:
        // RISC-V (encoding matches canonical):
        result = fp_add(a, b, rm);

        // OpenPOWER (must map FPSCR[RN] to canonical):
        var rm_canonical[2:0] = {1'b0, fpscr[1], fpscr[1] ^ fpscr[0]};
        result = fp_add(a, b, rm_canonical);
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class FPIntrinsic:
    """Definition of an FP intrinsic function.

    Attributes:
        name: Intrinsic function name
        num_operands: Number of data operands (excluding rounding mode)
        result_type: Type of result ('fp', 'fp64', 'int', 'int64', 'bool')
        description: Human-readable description
        has_rounding_mode: If True, rounding mode is REQUIRED as last argument
        has_exceptions: If True, operation can raise FP exceptions
        latency: Pipeline latency in cycles
        pipelined: If True, operation is pipelined; if False, multi-cycle
    """
    name: str
    num_operands: int
    result_type: str  # 'fp', 'int', 'bool'
    description: str
    has_rounding_mode: bool = True
    has_exceptions: bool = True
    latency: int = 3  # Default latency in cycles
    pipelined: bool = True

    @property
    def total_args(self) -> int:
        """Total number of arguments including rounding mode if required."""
        return self.num_operands + (1 if self.has_rounding_mode else 0)


# FP intrinsic function definitions
FP_INTRINSICS: Dict[str, FPIntrinsic] = {
    # Arithmetic operations
    'fp_add': FPIntrinsic('fp_add', 2, 'fp', 'Floating-point addition', latency=3),
    'fp_sub': FPIntrinsic('fp_sub', 2, 'fp', 'Floating-point subtraction', latency=3),
    'fp_mul': FPIntrinsic('fp_mul', 2, 'fp', 'Floating-point multiplication', latency=4),
    'fp_div': FPIntrinsic('fp_div', 2, 'fp', 'Floating-point division', latency=15, pipelined=False),
    'fp_sqrt': FPIntrinsic('fp_sqrt', 1, 'fp', 'Floating-point square root', latency=15, pipelined=False),

    # Fused multiply-add operations
    'fp_fmadd': FPIntrinsic('fp_fmadd', 3, 'fp', 'Fused multiply-add: (a*b)+c', latency=4),
    'fp_fmsub': FPIntrinsic('fp_fmsub', 3, 'fp', 'Fused multiply-sub: (a*b)-c', latency=4),
    'fp_fnmadd': FPIntrinsic('fp_fnmadd', 3, 'fp', 'Fused neg-multiply-add: -(a*b)+c', latency=4),
    'fp_fnmsub': FPIntrinsic('fp_fnmsub', 3, 'fp', 'Fused neg-multiply-sub: -(a*b)-c', latency=4),

    # Sign manipulation (no rounding, no exceptions, combinational)
    'fp_sgnj': FPIntrinsic('fp_sgnj', 2, 'fp', 'Sign injection', has_rounding_mode=False, has_exceptions=False, latency=0),
    'fp_sgnjn': FPIntrinsic('fp_sgnjn', 2, 'fp', 'Negated sign injection', has_rounding_mode=False, has_exceptions=False, latency=0),
    'fp_sgnjx': FPIntrinsic('fp_sgnjx', 2, 'fp', 'XOR sign injection', has_rounding_mode=False, has_exceptions=False, latency=0),

    # Min/Max (IEEE 754-2019 semantics)
    'fp_min': FPIntrinsic('fp_min', 2, 'fp', 'Minimum', has_rounding_mode=False, latency=1),
    'fp_max': FPIntrinsic('fp_max', 2, 'fp', 'Maximum', has_rounding_mode=False, latency=1),

    # Comparisons (return boolean)
    'fp_eq': FPIntrinsic('fp_eq', 2, 'bool', 'Equal', has_rounding_mode=False, latency=1),
    'fp_lt': FPIntrinsic('fp_lt', 2, 'bool', 'Less than', has_rounding_mode=False, latency=1),
    'fp_le': FPIntrinsic('fp_le', 2, 'bool', 'Less or equal', has_rounding_mode=False, latency=1),

    # Classification (return integer encoding)
    'fp_class': FPIntrinsic('fp_class', 1, 'int', 'Classify FP value', has_rounding_mode=False, has_exceptions=False, latency=0),

    # Conversions (32-bit integer)
    'fp_cvt_w_s': FPIntrinsic('fp_cvt_w_s', 1, 'int', 'FP32 to signed int32', latency=2),
    'fp_cvt_wu_s': FPIntrinsic('fp_cvt_wu_s', 1, 'int', 'FP32 to unsigned int32', latency=2),
    'fp_cvt_s_w': FPIntrinsic('fp_cvt_s_w', 1, 'fp', 'Signed int32 to FP32', latency=2),
    'fp_cvt_s_wu': FPIntrinsic('fp_cvt_s_wu', 1, 'fp', 'Unsigned int32 to FP32', latency=2),

    # Conversions (64-bit integer) - RV64F specific
    'fp_cvt_l_s': FPIntrinsic('fp_cvt_l_s', 1, 'int64', 'FP32 to signed int64', latency=2),
    'fp_cvt_lu_s': FPIntrinsic('fp_cvt_lu_s', 1, 'int64', 'FP32 to unsigned int64', latency=2),
    'fp_cvt_s_l': FPIntrinsic('fp_cvt_s_l', 1, 'fp', 'Signed int64 to FP32', latency=2),
    'fp_cvt_s_lu': FPIntrinsic('fp_cvt_s_lu', 1, 'fp', 'Unsigned int64 to FP32', latency=2),

    # ========================================
    # D Extension (Double-Precision) Intrinsics
    # ========================================

    # Arithmetic operations (double precision)
    'fp_add_d': FPIntrinsic('fp_add_d', 2, 'fp64', 'Double-precision addition', latency=3),
    'fp_sub_d': FPIntrinsic('fp_sub_d', 2, 'fp64', 'Double-precision subtraction', latency=3),
    'fp_mul_d': FPIntrinsic('fp_mul_d', 2, 'fp64', 'Double-precision multiplication', latency=4),
    'fp_div_d': FPIntrinsic('fp_div_d', 2, 'fp64', 'Double-precision division', latency=25, pipelined=False),
    'fp_sqrt_d': FPIntrinsic('fp_sqrt_d', 1, 'fp64', 'Double-precision square root', latency=25, pipelined=False),

    # Fused multiply-add operations (double precision)
    'fp_fmadd_d': FPIntrinsic('fp_fmadd_d', 3, 'fp64', 'Double FMA: (a*b)+c', latency=4),
    'fp_fmsub_d': FPIntrinsic('fp_fmsub_d', 3, 'fp64', 'Double FMS: (a*b)-c', latency=4),
    'fp_fnmadd_d': FPIntrinsic('fp_fnmadd_d', 3, 'fp64', 'Double FNMA: -(a*b)+c', latency=4),
    'fp_fnmsub_d': FPIntrinsic('fp_fnmsub_d', 3, 'fp64', 'Double FNMS: -(a*b)-c', latency=4),

    # Min/Max (double precision)
    'fp_min_d': FPIntrinsic('fp_min_d', 2, 'fp64', 'Double minimum', has_rounding_mode=False, latency=1),
    'fp_max_d': FPIntrinsic('fp_max_d', 2, 'fp64', 'Double maximum', has_rounding_mode=False, latency=1),

    # Comparisons (double precision)
    'fp_eq_d': FPIntrinsic('fp_eq_d', 2, 'bool', 'Double equal', has_rounding_mode=False, latency=1),
    'fp_lt_d': FPIntrinsic('fp_lt_d', 2, 'bool', 'Double less than', has_rounding_mode=False, latency=1),
    'fp_le_d': FPIntrinsic('fp_le_d', 2, 'bool', 'Double less or equal', has_rounding_mode=False, latency=1),

    # Classification (double precision)
    'fp_class_d': FPIntrinsic('fp_class_d', 1, 'int', 'Classify double value', has_rounding_mode=False, has_exceptions=False, latency=0),

    # Conversions (double <-> 32-bit integer)
    'fp_cvt_w_d': FPIntrinsic('fp_cvt_w_d', 1, 'int', 'FP64 to signed int32', latency=2),
    'fp_cvt_wu_d': FPIntrinsic('fp_cvt_wu_d', 1, 'int', 'FP64 to unsigned int32', latency=2),
    'fp_cvt_d_w': FPIntrinsic('fp_cvt_d_w', 1, 'fp64', 'Signed int32 to FP64', latency=2),
    'fp_cvt_d_wu': FPIntrinsic('fp_cvt_d_wu', 1, 'fp64', 'Unsigned int32 to FP64', latency=2),

    # Conversions (double <-> 64-bit integer) - RV64D specific
    'fp_cvt_l_d': FPIntrinsic('fp_cvt_l_d', 1, 'int64', 'FP64 to signed int64', latency=2),
    'fp_cvt_lu_d': FPIntrinsic('fp_cvt_lu_d', 1, 'int64', 'FP64 to unsigned int64', latency=2),
    'fp_cvt_d_l': FPIntrinsic('fp_cvt_d_l', 1, 'fp64', 'Signed int64 to FP64', latency=2),
    'fp_cvt_d_lu': FPIntrinsic('fp_cvt_d_lu', 1, 'fp64', 'Unsigned int64 to FP64', latency=2),

    # Conversions (single <-> double)
    'fp_cvt_s_d': FPIntrinsic('fp_cvt_s_d', 1, 'fp', 'FP64 to FP32', latency=2),
    'fp_cvt_d_s': FPIntrinsic('fp_cvt_d_s', 1, 'fp64', 'FP32 to FP64', latency=2),
}


def get_fp_intrinsic(name: str) -> Optional[FPIntrinsic]:
    """Get the intrinsic definition for a given function name."""
    return FP_INTRINSICS.get(name)


def is_fp_intrinsic(name: str) -> bool:
    """Check if a function name is a known FP intrinsic."""
    return name in FP_INTRINSICS


def get_fp_intrinsic_operand_count(name: str) -> int:
    """Get the number of operands for an FP intrinsic."""
    intrinsic = FP_INTRINSICS.get(name)
    return intrinsic.num_operands if intrinsic else 0


# Rounding mode constants (matching RISC-V fcsr.frm encoding)
ROUNDING_MODES = {
    'RNE': 0b000,  # Round to Nearest, ties to Even
    'RTZ': 0b001,  # Round toward Zero
    'RDN': 0b010,  # Round Down (toward -infinity)
    'RUP': 0b011,  # Round Up (toward +infinity)
    'RMM': 0b100,  # Round to Nearest, ties to Max Magnitude
    'DYN': 0b111,  # Dynamic (use fcsr.frm)
}


# Exception flag bit positions (matching RISC-V fflags)
EXCEPTION_FLAGS = {
    'NX': 0,  # Inexact
    'UF': 1,  # Underflow
    'OF': 2,  # Overflow
    'DZ': 3,  # Divide by Zero
    'NV': 4,  # Invalid Operation
}


# IEEE 754 FP format constants
FP_FORMATS = {
    'fp16': {
        'total_bits': 16,
        'sign_bit': 15,
        'exponent_bits': 5,
        'exponent_high': 14,
        'exponent_low': 10,
        'mantissa_bits': 10,
        'mantissa_high': 9,
        'mantissa_low': 0,
        'exponent_bias': 15,
    },
    'fp32': {
        'total_bits': 32,
        'sign_bit': 31,
        'exponent_bits': 8,
        'exponent_high': 30,
        'exponent_low': 23,
        'mantissa_bits': 23,
        'mantissa_high': 22,
        'mantissa_low': 0,
        'exponent_bias': 127,
    },
    'fp64': {
        'total_bits': 64,
        'sign_bit': 63,
        'exponent_bits': 11,
        'exponent_high': 62,
        'exponent_low': 52,
        'mantissa_bits': 52,
        'mantissa_high': 51,
        'mantissa_low': 0,
        'exponent_bias': 1023,
    },
    'fp128': {
        'total_bits': 128,
        'sign_bit': 127,
        'exponent_bits': 15,
        'exponent_high': 126,
        'exponent_low': 112,
        'mantissa_bits': 112,
        'mantissa_high': 111,
        'mantissa_low': 0,
        'exponent_bias': 16383,
    },
}

# Alias for backwards compatibility
FP32_FORMAT = FP_FORMATS['fp32']


# Packed result types: value + 5-bit exception flags
# Layout: [N+4:N] = flags {NV, DZ, OF, UF, NX}, [N-1:0] = IEEE value
FP_RESULT_TYPES = {
    'fp16_res': {'value_bits': 16, 'flag_bits': 5, 'total_bits': 21, 'format': 'fp16'},
    'fp32_res': {'value_bits': 32, 'flag_bits': 5, 'total_bits': 37, 'format': 'fp32'},
    'fp64_res': {'value_bits': 64, 'flag_bits': 5, 'total_bits': 69, 'format': 'fp64'},
    'fp128_res': {'value_bits': 128, 'flag_bits': 5, 'total_bits': 133, 'format': 'fp128'},
    'fpcmp_res': {'value_bits': 1, 'flag_bits': 5, 'total_bits': 6, 'format': 'bool'},
    'int32_res': {'value_bits': 32, 'flag_bits': 5, 'total_bits': 37, 'format': 'int32'},
    'int64_res': {'value_bits': 64, 'flag_bits': 5, 'total_bits': 69, 'format': 'int64'},
}


def get_fp_result_type(fp_format: str) -> dict:
    """Get the packed result type info for an FP format.

    Args:
        fp_format: FP format ('fp16', 'fp32', 'fp64', 'fp128')

    Returns:
        Dictionary with value_bits, flag_bits, total_bits, and bit ranges
    """
    if fp_format not in FP_FORMATS:
        raise ValueError(f"Unknown FP format: {fp_format}")

    format_bits = FP_FORMATS[fp_format]['total_bits']
    return {
        'value_bits': format_bits,
        'flag_bits': 5,
        'total_bits': format_bits + 5,
        'value_range': (format_bits - 1, 0),
        'flags_range': (format_bits + 4, format_bits),
        'format': fp_format,
    }


def get_intrinsic_result_type(intrinsic_name: str, fp_format: str = 'fp32') -> dict:
    """Get the result type info for an FP intrinsic.

    Args:
        intrinsic_name: Name of the FP intrinsic
        fp_format: FP format for the operation (default 'fp32')

    Returns:
        Dictionary with result type info including packed width
    """
    intrinsic = FP_INTRINSICS.get(intrinsic_name)
    if not intrinsic:
        raise ValueError(f"Unknown FP intrinsic: {intrinsic_name}")

    # Operations that don't produce exception flags
    if not intrinsic.has_exceptions:
        if intrinsic.result_type == 'fp':
            return {
                'value_bits': FP_FORMATS[fp_format]['total_bits'],
                'flag_bits': 0,
                'total_bits': FP_FORMATS[fp_format]['total_bits'],
                'has_flags': False,
                'result_type': 'fp',
                'format': fp_format,
            }
        elif intrinsic.result_type == 'fp64':
            # Explicit 64-bit FP result (D extension)
            return {
                'value_bits': 64,
                'flag_bits': 0,
                'total_bits': 64,
                'has_flags': False,
                'result_type': 'fp64',
                'format': 'fp64',
            }
        elif intrinsic.result_type == 'int':
            return {
                'value_bits': 32,  # Classification returns 32-bit integer
                'flag_bits': 0,
                'total_bits': 32,
                'has_flags': False,
                'result_type': 'int',
                'format': 'int32',
            }

    # Operations that produce exception flags
    if intrinsic.result_type == 'fp':
        # FP result: packed FP value + flags
        format_bits = FP_FORMATS[fp_format]['total_bits']
        return {
            'value_bits': format_bits,
            'flag_bits': 5,
            'total_bits': format_bits + 5,
            'value_range': (format_bits - 1, 0),
            'flags_range': (format_bits + 4, format_bits),
            'has_flags': True,
            'result_type': 'fp',
            'format': fp_format,
        }

    elif intrinsic.result_type == 'fp64':
        # Explicit 64-bit FP result with flags (D extension): 64 + 5 = 69 bits
        return {
            'value_bits': 64,
            'flag_bits': 5,
            'total_bits': 69,
            'value_range': (63, 0),
            'flags_range': (68, 64),
            'has_flags': True,
            'result_type': 'fp64',
            'format': 'fp64',
        }

    elif intrinsic.result_type == 'bool':
        # Comparison result: 1-bit boolean + 5-bit flags = 6 bits
        return {
            'value_bits': 1,
            'flag_bits': 5,
            'total_bits': 6,
            'value_range': (0, 0),
            'flags_range': (5, 1),
            'has_flags': True,
            'result_type': 'bool',
            'format': 'bool',
        }

    elif intrinsic.result_type == 'int':
        # Conversion to 32-bit integer: 32-bit result + 5-bit flags = 37 bits
        return {
            'value_bits': 32,
            'flag_bits': 5,
            'total_bits': 37,
            'value_range': (31, 0),
            'flags_range': (36, 32),
            'has_flags': True,
            'result_type': 'int',
            'format': 'int32',
        }

    elif intrinsic.result_type == 'int64':
        # Conversion to 64-bit integer: 64-bit result + 5-bit flags = 69 bits
        return {
            'value_bits': 64,
            'flag_bits': 5,
            'total_bits': 69,
            'value_range': (63, 0),
            'flags_range': (68, 64),
            'has_flags': True,
            'result_type': 'int64',
            'format': 'int64',
        }

    raise ValueError(f"Unknown result type: {intrinsic.result_type}")


def make_fp_operation_node_data(intrinsic_name: str, operand_count: int,
                                 rounding_mode: str = 'DYN',
                                 fp_format: str = 'fp32') -> Dict:
    """Create node data dictionary for an FP operation node.

    Args:
        intrinsic_name: Name of the FP intrinsic (e.g., 'fp_add')
        operand_count: Number of operands for this call
        rounding_mode: Rounding mode ('RNE', 'RTZ', 'RDN', 'RUP', 'RMM', 'DYN')
        fp_format: FP format ('fp16', 'fp32', 'fp64', 'fp128')

    Returns:
        Dictionary with node data for an FP operation node
    """
    intrinsic = FP_INTRINSICS.get(intrinsic_name)
    if not intrinsic:
        raise ValueError(f"Unknown FP intrinsic: {intrinsic_name}")

    # Get result type info (including packed width)
    result_info = get_intrinsic_result_type(intrinsic_name, fp_format)

    return {
        'type': 'fp_operation',
        'fp_intrinsic': intrinsic_name,
        'num_operands': operand_count,
        'result_type': intrinsic.result_type,
        'has_rounding_mode': intrinsic.has_rounding_mode,
        'has_exceptions': intrinsic.has_exceptions,
        'rounding_mode': rounding_mode,
        'latency': intrinsic.latency,
        'pipelined': intrinsic.pipelined,
        'fp_format': fp_format,
        'bit_width': result_info['total_bits'],  # Full packed width
        'value_bits': result_info['value_bits'],
        'flag_bits': result_info.get('flag_bits', 0),
        'has_flags': result_info.get('has_flags', False),
        'value_range': result_info.get('value_range'),
        'flags_range': result_info.get('flags_range'),
    }
