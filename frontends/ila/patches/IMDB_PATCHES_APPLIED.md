# IMDb Model Patches Applied

This document records the patches applied to the IMDb git submodules to enable
full ILA model export.

## Patches Applied

All patches from `frontends/ila/imdb_complete_fix.patch` have been applied to
the following submodules:

### 1. ILA_Pico (frontends/ila/models/ILA_Pico)

**File**: `RISC-V-Spec/src/riscvIla.cc`
- Added `model.SetValid(BoolConst(true));` at the beginning of `addInstructions()`
- Line 122-125

**File**: `RISC-V-Spec/include/riscvIla.hpp`
- Added public getter method: `Ila& getModel() { return model; }`
- Line 73-74

**File**: `RISC-V-Spec/export_full_model.cc` (NEW)
- Created export program to generate full model JSON

### 2. ILA_Piccolo (frontends/ila/models/ILA_Piccolo)

**File**: `src/riscvIla.cc`
- Added `model.SetValid(BoolConst(true));` at the beginning of `addInstructions()`
- Line 122-125

### 3. ILA_Rocket (frontends/ila/models/ILA_Rocket)

**File**: `src/riscvIla.cc`
- Added `model.SetValid(BoolConst(true));` at the beginning of `addInstructions()`
- Line 121-124

## Why These Patches Are Needed

The SetValid() method was added to ILAng after these models were created. JSON
serialization now requires a valid expression to be set on the ILA model.
Without this patch, JSON export fails with a NULL pointer error.

## Build and Export Instructions

After applying patches, to export the Pico model:

```bash
cd frontends/ila/models/ILA_Pico/RISC-V-Spec

# Compile export program
g++ -std=c++17 \
  -I./include \
  -I<ISACOMP_ROOT>/frontends/ila/ILAng/include \
  -o export_full \
  export_full_model.cc src/riscvIla.cc src/helpers.cc \
  -L<ISACOMP_ROOT>/frontends/ila/ILAng/build/src \
  -Wl,-rpath,<ISACOMP_ROOT>/frontends/ila/ILAng/build/src \
  -lilang -lz3 -lpthread

# Export to JSON
./export_full /path/to/output.json
```

## Results

Successfully exported:
- **pico_full.json**: 194KB, 37 instructions, 34 states, 3877 AST nodes
- Parsed to ResourceGraph: 3915 nodes, 8091 edges

## Note

These changes are **NOT committed** to the submodule repositories. They exist
only in the local working directory. The submodules remain pointing to their
original upstream commits. If you update the submodules, you'll need to
reapply these patches.
