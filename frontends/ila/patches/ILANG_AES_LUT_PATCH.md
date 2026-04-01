# ILAng AES S-box LUT Optimization Patch

## Summary
This patch modifies ILAng's AES-128 implementation to use memory-based lookup tables (LUTs) instead of nested if-then-else operations for S-box lookups, resulting in a 99% reduction in expression count and graph size.

## Results
| Metric | Before (nested ITE) | After (LUT) | Reduction |
|--------|---------------------|-------------|-----------|
| JSON Size | 3.02 MB | 0.03 MB | 99.2% |
| AST Expressions | 61,657 | 459 | 99.3% |
| Graph Nodes | 61,658 | 460 | 99.3% |
| Graph Edges | 77,088 | 708 | 99.1% |

## Patch for `ILA_AES/src/aes_128.cc`

### Original Code (256 nested ITEs per S-box lookup):
```cpp
ExprRef AES_128::s_table_read(const ExprRef& idx) {
  assert(idx.bit_width() == 8);

  ExprRef ret = BvConst(S_table[0], 8);
  for (int i = 1; i < 256; i++) {
    ret = Ite(idx == i, BvConst(S_table[i], 8), ret);
  }
  return ret;
}

ExprRef AES_128::xs_table_read(const ExprRef& idx) {
  assert(idx.bit_width() == 8);

  ExprRef ret = BvConst(xS_table[0], 8);
  for (int i = 1; i < 256; i++) {
    ret = Ite(idx == i, BvConst(xS_table[i], 8), ret);
  }
  return ret;
}
```

### Optimized Code (MemConst + Load):
```cpp
// Helper to create S-box LUT
static ExprRef create_s_lut() {
  std::map<unsigned long, unsigned long> s_vals;
  for (unsigned long i = 0; i < 256; i++) {
    s_vals[i] = S_table[i];
  }
  return MemConst(0, s_vals, 8, 8);  // 8-bit addr, 8-bit data, default 0
}

// Helper to create inverse S-box LUT
static ExprRef create_xs_lut() {
  std::map<unsigned long, unsigned long> xs_vals;
  for (unsigned long i = 0; i < 256; i++) {
    xs_vals[i] = xS_table[i];
  }
  return MemConst(0, xs_vals, 8, 8);
}

// ACTUAL LUT: Just a memory load!
ExprRef AES_128::s_table_read(const ExprRef& idx) {
  assert(idx.bit_width() == 8);
  static ExprRef s_lut = create_s_lut();  // Created once on first call
  return Load(s_lut, idx);  // Single Load operation!
}

// ACTUAL LUT: Just a memory load!
ExprRef AES_128::xs_table_read(const ExprRef& idx) {
  assert(idx.bit_width() == 8);
  static ExprRef xs_lut = create_xs_lut();  // Created once on first call
  return Load(xs_lut, idx);  // Single Load operation!
}
```

## How to Apply

1. Clone ILAng and ILA_AES repositories:
```bash
cd frontends/ila
git clone https://github.com/PrincetonUniversity/ILAng.git
git clone https://github.com/yuex1994/ILA_AES.git imdb/ILA_AES
```

2. Build ILAng:
```bash
cd ILAng
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

3. Apply the patch to `imdb/ILA_AES/src/aes_128.cc`:
   - Replace the `s_table_read()` and `xs_table_read()` functions with the optimized versions above
   - Add the helper functions `create_s_lut()` and `create_xs_lut()`

4. Export the optimized model:
```bash
cd ../imdb/ILA_AES

# Create export script
cat > export_aes.cc << 'EOF'
#include <aes_ila.h>
#include <aes_128.h>
#include <ilang/ilang++.h>
#include <iostream>

using namespace ilang;

int main() {
  SetUnsignedComparison(true);

  AES aes_ila_model;
  if (ExportIlaPortable(aes_ila_model.model, "aes_full.json")) {
    std::cout << "✓ AES full model exported\n";
  }

  AES_128 aes128;
  if (ExportIlaPortable(aes128.model, "aes128_function.json")) {
    std::cout << "✓ AES-128 function model exported\n";
  }

  return 0;
}
EOF

# Compile and run
g++ -std=c++17 -I include -I ../../ILAng/include -L ../../ILAng/build/src \
    export_aes.cc src/aes_128.cc src/aes_ila.cc src/aes_child.cc src/aes_util.cc \
    -lilang -lz3 -o export_aes

LD_LIBRARY_PATH=../../ILAng/build/src:$LD_LIBRARY_PATH ./export_aes
```

5. The generated JSONs will be:
   - `aes128_function.json` (~27 KB, 459 expressions)
   - `aes_full.json` (~44 KB)

## Inspiration

This optimization was inspired by [OWL (ucsbarchlab/owl)](https://github.com/ucsbarchlab/owl), which uses PyRTL's RomBlock for S-box lookups:

```python
# OWL's approach
self.sbox = pyrtl.RomBlock(bitwidth=8, addrwidth=8, romdata=self._sbox_data)
subbed = [self.sbox[byte] for byte in partition_wire(in_vector, 8)]
```

## Reference Files

See the example implementation in isacomp:
- `frontends/ila/aes_128_with_lut_example.cc` - Full optimized AES source
- `frontends/ila/test_data/aes128_function_lut.json` - Generated optimized JSON (27 KB)
- `frontends/ila/test_data/aes_full_lut.json` - Full AES model with LUTs (44 KB)

## Testing

Parse and compare the optimized model:
```python
import sys
sys.path.insert(0, '/path/to/isacomp')
from frontends.ila.ila_parser_real import RealILAParser
import json

parser = RealILAParser()
with open('aes128_function.json') as f:
    graph = parser.parse_json(json.load(f))

print(f"Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}")
# Expected: Nodes: 460, Edges: 708 (vs original 61,658 nodes, 77,088 edges)
```
