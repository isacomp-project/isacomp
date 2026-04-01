"""
Generic pipeline configuration for RISC-V processors.

This module defines pipeline stage configurations that can be used
to create 3, 4, or 5-stage pipelines. The configuration includes:
- Stage names and ordering
- Which cuts to make for each configuration
- Stage mapping for hazard resolution
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from enum import Enum


class PipelineStage(Enum):
    """Standard pipeline stages for RISC-V processors."""
    FETCH = "Fetch"
    DECODE = "Decode"
    EXECUTE = "Execute"
    MEMORY = "Memory"
    WRITEBACK = "Writeback"


@dataclass
class PipelineCut:
    """Defines a pipeline cut (boundary between stages)."""
    name: str  # Name of the stage AFTER the cut (registers hold value entering this stage)
    description: str
    stage_index: int  # 0-indexed position in the pipeline

    def __str__(self):
        return f"Cut -> {self.name} (stage {self.stage_index})"


@dataclass
class PipelineConfig:
    """
    Configuration for a pipelined processor.

    Attributes:
        num_stages: Total number of pipeline stages (3, 4, or 5)
        stage_names: Ordered list of stage names
        cuts: List of PipelineCut definitions
        register_read_stage: Stage where register file is read (usually Decode)
        register_write_stage: Stage where register file is written (last stage)
        memory_stage: Stage where memory access happens
        branch_resolution_stage: Stage where branches are resolved
    """
    num_stages: int
    stage_names: List[str]
    cuts: List[PipelineCut]
    register_read_stage: str
    register_write_stage: str
    memory_stage: str
    branch_resolution_stage: str
    prefix: str = "PIPE"

    def get_stage_index(self, stage_name: str) -> int:
        """Get the index of a stage by name."""
        try:
            return self.stage_names.index(stage_name)
        except ValueError:
            raise ValueError(f"Stage '{stage_name}' not found in pipeline config")

    def get_stage_name(self, index: int) -> str:
        """Get the name of a stage by index."""
        if 0 <= index < len(self.stage_names):
            return self.stage_names[index]
        raise IndexError(f"Stage index {index} out of range")

    def get_cut_for_stage(self, stage_name: str) -> Optional[PipelineCut]:
        """Get the cut that creates the given stage."""
        for cut in self.cuts:
            if cut.name == stage_name:
                return cut
        return None

    def get_validity_signal_id(self, stage_name: str) -> str:
        """Get the validity signal node ID for a stage."""
        return f"{self.prefix}_{stage_name}_valid_{self.prefix}"

    def get_stall_controller_id(self, stage_name: str) -> str:
        """Get the stall controller node ID for a stage."""
        return f"{self.prefix}_{stage_name}_stall_ctrl"

    def is_valid_stage(self, stage_name: str) -> bool:
        """Check if a stage name is valid for this configuration."""
        return stage_name in self.stage_names

    def get_stages_before(self, stage_name: str) -> List[str]:
        """Get all stages before the given stage."""
        idx = self.get_stage_index(stage_name)
        return self.stage_names[:idx]

    def get_stages_after(self, stage_name: str) -> List[str]:
        """Get all stages after the given stage."""
        idx = self.get_stage_index(stage_name)
        return self.stage_names[idx + 1:]

    def get_hazard_stages(self) -> List[str]:
        """Get stages that can cause data hazards (between RF read and write)."""
        read_idx = self.get_stage_index(self.register_read_stage)
        write_idx = self.get_stage_index(self.register_write_stage)
        return self.stage_names[read_idx:write_idx + 1]

    def __str__(self):
        stages = " -> ".join(self.stage_names)
        return f"Pipeline({self.num_stages}-stage): {stages}"


def create_5_stage_config() -> PipelineConfig:
    """
    Create a classic 5-stage RISC-V pipeline configuration (FDXMW).

    Stages:
    - Fetch: Instruction fetch from imem
    - Decode: Instruction decode, register file read
    - Execute: ALU operations, branch resolution
    - Memory: Data memory access
    - Writeback: Register file write
    """
    return PipelineConfig(
        num_stages=5,
        stage_names=["Fetch", "Decode", "Execute", "Memory", "Writeback"],
        cuts=[
            PipelineCut("Decode", "F/D boundary - instruction fetch complete", 1),
            PipelineCut("Execute", "D/X boundary - decode complete", 2),
            PipelineCut("Memory", "X/M boundary - execute complete", 3),
            PipelineCut("Writeback", "M/W boundary - memory access complete", 4),
        ],
        register_read_stage="Decode",
        register_write_stage="Writeback",
        memory_stage="Memory",
        branch_resolution_stage="Execute",
    )


def create_4_stage_config() -> PipelineConfig:
    """
    Create a 4-stage RISC-V pipeline configuration (FDXW).

    This combines Memory and Writeback into a single stage.
    Memory operations complete in Execute stage for address calculation,
    and Memory/Writeback stage handles data access and register write.

    Stages:
    - Fetch: Instruction fetch from imem
    - Decode: Instruction decode, register file read
    - Execute: ALU operations, branch resolution, address calculation
    - MemoryWriteback: Data memory access and register file write
    """
    return PipelineConfig(
        num_stages=4,
        stage_names=["Fetch", "Decode", "Execute", "MemoryWriteback"],
        cuts=[
            PipelineCut("Decode", "F/D boundary - instruction fetch complete", 1),
            PipelineCut("Execute", "D/X boundary - decode complete", 2),
            PipelineCut("MemoryWriteback", "X/MW boundary - execute complete", 3),
        ],
        register_read_stage="Decode",
        register_write_stage="MemoryWriteback",
        memory_stage="MemoryWriteback",
        branch_resolution_stage="Execute",
    )


def create_3_stage_config() -> PipelineConfig:
    """
    Create a 3-stage RISC-V pipeline configuration (FDX).

    This combines Execute, Memory and Writeback into a single stage.
    This results in simpler hazard logic but lower throughput.

    Stages:
    - Fetch: Instruction fetch from imem
    - Decode: Instruction decode, register file read
    - ExecuteMemoryWriteback: ALU, memory access, and register write
    """
    return PipelineConfig(
        num_stages=3,
        stage_names=["Fetch", "Decode", "ExecuteMemoryWriteback"],
        cuts=[
            PipelineCut("Decode", "F/D boundary - instruction fetch complete", 1),
            PipelineCut("ExecuteMemoryWriteback", "D/XMW boundary - decode complete", 2),
        ],
        register_read_stage="Decode",
        register_write_stage="ExecuteMemoryWriteback",
        memory_stage="ExecuteMemoryWriteback",
        branch_resolution_stage="ExecuteMemoryWriteback",
    )


def create_2_stage_config() -> PipelineConfig:
    """
    Create a 2-stage RISC-V pipeline configuration (FD/XMW).

    This combines Fetch and Decode into a single stage, and
    Execute, Memory and Writeback into another single stage.
    This is the simplest pipelined configuration.

    Stages:
    - FetchDecode: Instruction fetch, decode, and register file read
    - ExecuteMemoryWriteback: ALU, memory access, and register write

    The cut happens AFTER register file reads but BEFORE ALU operations.
    """
    return PipelineConfig(
        num_stages=2,
        stage_names=["FetchDecode", "ExecuteMemoryWriteback"],
        cuts=[
            PipelineCut("ExecuteMemoryWriteback", "FD/XMW boundary - decode complete", 1),
        ],
        register_read_stage="FetchDecode",
        register_write_stage="ExecuteMemoryWriteback",
        memory_stage="ExecuteMemoryWriteback",
        branch_resolution_stage="ExecuteMemoryWriteback",
    )


def get_pipeline_config(num_stages: int) -> PipelineConfig:
    """
    Get a pipeline configuration for the specified number of stages.

    Args:
        num_stages: Number of pipeline stages (2, 3, 4, or 5)

    Returns:
        PipelineConfig for the requested pipeline depth

    Raises:
        ValueError: If num_stages is not 2, 3, 4, or 5
    """
    if num_stages == 5:
        return create_5_stage_config()
    elif num_stages == 4:
        return create_4_stage_config()
    elif num_stages == 3:
        return create_3_stage_config()
    elif num_stages == 2:
        return create_2_stage_config()
    else:
        raise ValueError(f"Unsupported number of stages: {num_stages}. Supported: 2, 3, 4, or 5")


class PipelineStageMapper:
    """
    Maps between different pipeline configurations.

    This is useful when the optimization algorithms need to work with
    different stage naming schemes.
    """

    # Canonical stage names that optimization algorithms understand
    CANONICAL_STAGES = ["Fetch", "Decode", "Execute", "Memory", "Writeback"]

    def __init__(self, config: PipelineConfig):
        self.config = config
        self._build_mappings()

    def _build_mappings(self):
        """Build mappings from canonical to actual stage names."""
        self._canonical_to_actual = {}
        self._actual_to_canonical = {}

        if self.config.num_stages == 5:
            # Direct 1:1 mapping
            for stage in self.CANONICAL_STAGES:
                self._canonical_to_actual[stage] = stage
                self._actual_to_canonical[stage] = stage

        elif self.config.num_stages == 4:
            # Memory and Writeback merged into MemoryWriteback
            self._canonical_to_actual = {
                "Fetch": "Fetch",
                "Decode": "Decode",
                "Execute": "Execute",
                "Memory": "MemoryWriteback",
                "Writeback": "MemoryWriteback",
            }
            self._actual_to_canonical = {
                "Fetch": "Fetch",
                "Decode": "Decode",
                "Execute": "Execute",
                "MemoryWriteback": "Writeback",  # Use later stage as canonical
            }

        elif self.config.num_stages == 3:
            # Execute, Memory, Writeback merged into ExecuteMemoryWriteback
            self._canonical_to_actual = {
                "Fetch": "Fetch",
                "Decode": "Decode",
                "Execute": "ExecuteMemoryWriteback",
                "Memory": "ExecuteMemoryWriteback",
                "Writeback": "ExecuteMemoryWriteback",
            }
            self._actual_to_canonical = {
                "Fetch": "Fetch",
                "Decode": "Decode",
                "ExecuteMemoryWriteback": "Writeback",  # Use later stage as canonical
            }

        elif self.config.num_stages == 2:
            # Fetch and Decode merged into FetchDecode
            # Execute, Memory, Writeback merged into ExecuteMemoryWriteback
            self._canonical_to_actual = {
                "Fetch": "FetchDecode",
                "Decode": "FetchDecode",
                "Execute": "ExecuteMemoryWriteback",
                "Memory": "ExecuteMemoryWriteback",
                "Writeback": "ExecuteMemoryWriteback",
            }
            self._actual_to_canonical = {
                "FetchDecode": "Decode",  # Use later stage as canonical
                "ExecuteMemoryWriteback": "Writeback",
            }

    def canonical_to_actual(self, canonical_stage: str) -> str:
        """Map a canonical stage name to the actual stage name in this config."""
        return self._canonical_to_actual.get(canonical_stage, canonical_stage)

    def actual_to_canonical(self, actual_stage: str) -> str:
        """Map an actual stage name to the canonical stage name."""
        return self._actual_to_canonical.get(actual_stage, actual_stage)

    def get_pipeline_register_prefix(self, canonical_stage: str) -> str:
        """Get the pipeline register prefix for a canonical stage."""
        actual_stage = self.canonical_to_actual(canonical_stage)
        return f"{self.config.prefix}_{actual_stage}_"

    def is_stage_combined(self, canonical_stage: str) -> bool:
        """Check if a canonical stage is combined with others in this config."""
        if self.config.num_stages == 5:
            return False
        actual = self.canonical_to_actual(canonical_stage)
        # Count how many canonical stages map to this actual stage
        count = sum(1 for c in self.CANONICAL_STAGES
                   if self._canonical_to_actual.get(c) == actual)
        return count > 1


# Helper function to parse stage name from pipeline register ID
def parse_stage_from_register_id(register_id: str, prefix: str = "PIPE") -> Optional[str]:
    """
    Extract the stage name from a pipeline register ID.

    Examples:
        PIPE_Execute_add_res_PIPE -> Execute
        PIPE_Memory_PIPE_Execute_rd_PIPE_PIPE -> Memory
        PIPE_Writeback_valid_PIPE -> Writeback

    Args:
        register_id: Pipeline register node ID
        prefix: Pipeline prefix (default: PIPE)

    Returns:
        Stage name, or None if not a valid pipeline register ID
    """
    if not register_id.startswith(f"{prefix}_") or not register_id.endswith(f"_{prefix}"):
        return None

    # Remove prefix and suffix
    middle = register_id[len(prefix) + 1:]  # Skip "PIPE_"

    # Find the stage name (first component after PIPE_)
    # Stage name is everything up to the first underscore that isn't part of the stage name
    parts = middle.split('_')
    if parts:
        return parts[0]
    return None


def count_pipeline_depth(register_id: str, prefix: str = "PIPE") -> int:
    """
    Count the pipeline depth of a register ID by counting _PIPE suffixes.

    Examples:
        PIPE_Execute_rd_PIPE -> 1 (stage 2)
        PIPE_Memory_PIPE_Execute_rd_PIPE_PIPE -> 2 (stage 3)
        PIPE_Writeback_PIPE_Memory_PIPE_Execute_rd_PIPE_PIPE_PIPE -> 3 (stage 4)

    Args:
        register_id: Pipeline register node ID
        prefix: Pipeline prefix (default: PIPE)

    Returns:
        Number of _PIPE suffixes (pipeline depth)
    """
    # Count trailing _PIPE suffixes
    suffix = f"_{prefix}"
    depth = 0
    temp = register_id
    while temp.endswith(suffix):
        depth += 1
        temp = temp[:-len(suffix)]
    return depth


if __name__ == "__main__":
    # Test configurations
    print("Pipeline Configurations Test")
    print("=" * 60)

    for num_stages in [3, 4, 5]:
        config = get_pipeline_config(num_stages)
        print(f"\n{config}")
        print(f"  Stages: {config.stage_names}")
        print(f"  Cuts: {[str(c) for c in config.cuts]}")
        print(f"  RF read: {config.register_read_stage}")
        print(f"  RF write: {config.register_write_stage}")
        print(f"  Memory: {config.memory_stage}")
        print(f"  Branch resolution: {config.branch_resolution_stage}")

        mapper = PipelineStageMapper(config)
        print(f"  Stage mappings:")
        for canonical in PipelineStageMapper.CANONICAL_STAGES:
            actual = mapper.canonical_to_actual(canonical)
            combined = "(combined)" if mapper.is_stage_combined(canonical) else ""
            print(f"    {canonical} -> {actual} {combined}")
