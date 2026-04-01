# Associative Memory (CAM) Support in ISA Language

This document describes the syntax and semantics for content-addressable memory
(CAM) structures in the .isa language, used for TLBs, caches, and other
associative lookup structures.

## Motivation

Software-managed TLBs (MIPS, SH4, Alpha) and architectural caches require
associative lookups that are tedious to express with standard arrays. The
current approach requires manually unrolling parallel comparators and priority
encoders, resulting in hundreds of lines of repetitive code.

The CAM syntax provides a declarative way to express these structures.

## Syntax

### Declaration

```isa
isa_state cam name[tag_width]@[way_bits][set_bits];
```

Components:
- `cam` - modifier indicating content-addressable memory
- `name` - identifier for the CAM
- `[tag_width]` - bit range for the tag (compared during lookup)
- `@[way_bits]` - number of ways (entries searched in parallel)
  - Empty `@[]` means 1 way (direct-mapped)
- `[set_bits]` - number of sets (indexed, not searched)
  - Empty `[]` means 1 set (fully associative)

### Examples

```isa
// Fully associative TLB: 32 entries, 19-bit VPN2 tag
isa_state cam tlb_vpn2[18:0]@[4:0][];

// 4-way set-associative cache: 64 sets, 20-bit tag
isa_state cam cache_tags[19:0]@[1:0][5:0];

// Direct-mapped cache: 64 entries, 20-bit tag
isa_state cam cache_tags[19:0]@[][5:0];
```

### Lookup

```isa
// Returns bitmask of matching entries
var matches[31:0];
matches = tlb_vpn2@[search_vpn2];

// For set-associative, provide set index
var way_matches[3:0];
way_matches = cache_tags@[tag][set_idx];
```

### Builtins

```isa
// ctz - count trailing zeros (find first match)
var idx[5:0];
idx = ctz(matches);  // Returns 0..31 for match, 32 for no match

// clz - count leading zeros
var leading[5:0];
leading = clz(value);
```

## MIPS32 TLB Example

### Before (manual unrolling, ~200+ lines)

```isa
// TLB array - 32 entries
isa_state tlb_hi[31:0][4:0];
isa_state tlb_lo0[31:0][4:0];
isa_state tlb_lo1[31:0][4:0];

// Match signals for each entry
var tlb_match_0[0:0]; var tlb_match_1[0:0]; ... var tlb_match_31[0:0];

// Extract and compare each entry
tlb_match_0 = (tlb_hi[0][31:13] == pc_vpn2) & ...;
tlb_match_1 = (tlb_hi[1][31:13] == pc_vpn2) & ...;
// ... 30 more lines

// Priority mux tree (~50+ lines)
mux_lo_01 = tlb_match_0 ? sel_lo_0 : sel_lo_1;
// ... many more mux stages
```

### After (CAM syntax, ~20 lines)

```isa
// TLB arrays using CAM for VPN2 lookup
isa_state cam tlb_vpn2[18:0]@[4:0][];  // VPN2 tags, 32 entries
isa_state tlb_asid[7:0][4:0];           // ASID per entry
isa_state tlb_global[0:0][4:0];         // Global bit per entry
isa_state tlb_lo0[31:0][4:0];           // EntryLo0
isa_state tlb_lo1[31:0][4:0];           // EntryLo1

// Lookup
var vpn2_matches[31:0];
vpn2_matches = tlb_vpn2@[pc_vpn2];

// Apply ASID/Global filtering (still needs per-entry logic for now)
// Future: could add filter expression to CAM lookup

// Get first match
var tlb_hit[0:0];
var tlb_idx[4:0];
tlb_hit = |vpn2_matches;
tlb_idx = ctz(vpn2_matches);

// Read matched entry
var matched_lo[31:0];
matched_lo = pc_odd_page ? tlb_lo1[tlb_idx] : tlb_lo0[tlb_idx];
```

## Generated Hardware

### CAM Lookup

For `cam@[key]` with N ways, generates:
- N parallel comparators: `match[i] = (cam[i] == key)`
- Concatenation: `result = {match[N-1], ..., match[0]}`

### ctz Builtin

Generates priority encoder chain:
```verilog
assign result = operand[0] ? 6'd0 :
                operand[1] ? 6'd1 :
                ...
                operand[31] ? 6'd31 :
                6'd32;  // No match
```

## Future Extensions

1. **Filter expressions**: Allow custom match conditions
   ```isa
   matches = tlb@[vpn2] where (global[i] | (asid[i] == current_asid));
   ```

2. **Multi-match detection**: Return additional flag for multiple matches
   ```isa
   var multi_hit[0:0];
   multi_hit = matches & (matches - 1);  // Already possible
   ```

3. **Indexed write**: Dynamic index for CAM writes
   ```isa
   tlb_vpn2[idx] = new_vpn2;  // Currently requires unrolling
   ```
