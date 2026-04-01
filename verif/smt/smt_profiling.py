"""
Performance profiling and instrumentation for SMT verification.

Provides tools to measure and analyze verification performance:
- Timing of each verification phase
- SMT formula statistics
- Memory usage tracking
- Bottleneck identification
- Performance report generation
"""

import time
import functools
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from collections import defaultdict
import sys


@dataclass
class PhaseMetrics:
    """Metrics for a single verification phase."""
    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    memory_delta: int = 0  # bytes
    metadata: Dict[str, Any] = field(default_factory=dict)

    def elapsed(self) -> float:
        """Get elapsed time for this phase."""
        if self.end_time > 0:
            return self.duration
        elif self.start_time > 0:
            return time.time() - self.start_time
        return 0.0

    def percentage_of(self, total: float) -> float:
        """Calculate what percentage this phase is of total time."""
        if total == 0:
            return 0.0
        return (self.duration / total) * 100.0


class VerificationProfiler:
    """Profiles SMT verification performance."""

    def __init__(self):
        self.phases: Dict[str, PhaseMetrics] = {}
        self.current_phase: Optional[str] = None
        self.total_start_time: float = 0.0
        self.total_end_time: float = 0.0

        # Statistics
        self.formula_stats: Dict[str, Any] = {}
        self.solver_stats: Dict[str, Any] = {}

    def start_total(self):
        """Start timing the entire verification process."""
        self.total_start_time = time.time()

    def end_total(self):
        """End timing the entire verification process."""
        self.total_end_time = time.time()

    def total_duration(self) -> float:
        """Get total verification duration."""
        if self.total_end_time > 0:
            return self.total_end_time - self.total_start_time
        elif self.total_start_time > 0:
            return time.time() - self.total_start_time
        return 0.0

    def start_phase(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        """Start timing a phase."""
        if self.current_phase:
            # End the current phase automatically
            self.end_phase(self.current_phase)

        phase = PhaseMetrics(name=name, metadata=metadata or {})
        phase.start_time = time.time()
        self.phases[name] = phase
        self.current_phase = name

    def end_phase(self, name: str):
        """End timing a phase."""
        if name not in self.phases:
            return

        phase = self.phases[name]
        phase.end_time = time.time()
        phase.duration = phase.end_time - phase.start_time

        if self.current_phase == name:
            self.current_phase = None

    def record_formula_stats(self, num_variables: int, num_constraints: int,
                            formula_size: int, formula_type: str = "QF_ABV"):
        """Record statistics about the generated SMT formula."""
        self.formula_stats = {
            'variables': num_variables,
            'constraints': num_constraints,
            'size_bytes': formula_size,
            'logic': formula_type
        }

    def record_solver_stats(self, solver_name: str, result: str,
                           solver_time: float, peak_memory: Optional[int] = None):
        """Record statistics about solver execution."""
        self.solver_stats = {
            'solver': solver_name,
            'result': result,
            'time': solver_time,
            'peak_memory_mb': peak_memory // (1024 * 1024) if peak_memory else None
        }

    def identify_bottleneck(self) -> str:
        """Identify the slowest phase."""
        if not self.phases:
            return "No phases recorded"

        slowest = max(self.phases.values(), key=lambda p: p.duration)
        total = self.total_duration()
        percentage = slowest.percentage_of(total)

        return f"{slowest.name} ({slowest.duration:.2f}s, {percentage:.1f}% of total)"

    def generate_report(self, colorize: bool = True) -> str:
        """Generate a comprehensive performance report."""
        if colorize:
            BOLD = '\033[1m'
            BLUE = '\033[94m'
            GREEN = '\033[92m'
            YELLOW = '\033[93m'
            RESET = '\033[0m'
        else:
            BOLD = BLUE = GREEN = YELLOW = RESET = ''

        lines = []
        lines.append(f"\n{BOLD}{BLUE}SMT Verification Performance Report{RESET}")
        lines.append("=" * 50)
        lines.append("")

        # Overall timing
        total = self.total_duration()
        lines.append(f"{BOLD}Overall:{RESET}")
        lines.append(f"  Total Time:  {total:.3f}s")
        lines.append("")

        # Phase breakdown
        if self.phases:
            lines.append(f"{BOLD}Phase Breakdown:{RESET}")

            # Sort by duration (descending)
            sorted_phases = sorted(self.phases.values(), key=lambda p: p.duration, reverse=True)

            for phase in sorted_phases:
                pct = phase.percentage_of(total)
                bar_length = int(pct / 2)  # Scale to 50 chars max
                bar = '█' * bar_length

                # Color code based on percentage
                if pct > 50:
                    color = YELLOW  # Bottleneck
                else:
                    color = GREEN

                lines.append(f"  {phase.name:20s}: {phase.duration:6.3f}s ({color}{pct:5.1f}%{RESET}) {bar}")

            lines.append("  " + "─" * 48)
            lines.append(f"  {'Total':20s}: {total:6.3f}s (100.0%)")
            lines.append("")

        # Formula statistics
        if self.formula_stats:
            lines.append(f"{BOLD}SMT Formula Statistics:{RESET}")
            lines.append(f"  Variables:    {self.formula_stats.get('variables', 0):,}")
            lines.append(f"  Constraints:  {self.formula_stats.get('constraints', 0):,}")
            lines.append(f"  Formula Size: {self.formula_stats.get('size_bytes', 0):,} bytes ({self.formula_stats.get('size_bytes', 0) / 1024:.1f} KB)")
            lines.append(f"  Logic:        {self.formula_stats.get('logic', 'unknown')}")
            lines.append("")

        # Solver statistics
        if self.solver_stats:
            lines.append(f"{BOLD}Solver Statistics:{RESET}")
            lines.append(f"  Solver:       {self.solver_stats.get('solver', 'unknown')}")
            lines.append(f"  Result:       {self.solver_stats.get('result', 'unknown')}")
            lines.append(f"  Solver Time:  {self.solver_stats.get('time', 0):.3f}s")
            if self.solver_stats.get('peak_memory_mb'):
                lines.append(f"  Peak Memory:  {self.solver_stats['peak_memory_mb']} MB")
            lines.append("")

        # Bottleneck analysis
        lines.append(f"{BOLD}Bottleneck Analysis:{RESET}")
        lines.append(f"  Primary bottleneck: {self.identify_bottleneck()}")

        # Recommendations
        if self.solver_stats.get('time', 0) / total > 0.5:
            lines.append(f"\n{BOLD}{YELLOW}Recommendation:{RESET}")
            lines.append(f"  Solver time dominates ({self.solver_stats.get('time', 0) / total * 100:.1f}% of total)")
            lines.append(f"  Consider:")
            lines.append(f"    - Incremental solving for multiple queries")
            lines.append(f"    - Constraint simplification")
            lines.append(f"    - Trying alternative solvers (CVC5, Bitwuzla)")

        lines.append("")
        return "\n".join(lines)

    def export_csv(self, filepath: str):
        """Export performance data to CSV for analysis."""
        import csv

        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow(['Phase', 'Duration (s)', 'Percentage'])

            # Data
            total = self.total_duration()
            for phase in sorted(self.phases.values(), key=lambda p: p.duration, reverse=True):
                writer.writerow([
                    phase.name,
                    f"{phase.duration:.6f}",
                    f"{phase.percentage_of(total):.2f}"
                ])

            # Total
            writer.writerow(['TOTAL', f"{total:.6f}", "100.00"])


class ProfilerContext:
    """Context manager for automatic phase profiling."""

    def __init__(self, profiler: VerificationProfiler, phase_name: str,
                 metadata: Optional[Dict[str, Any]] = None):
        self.profiler = profiler
        self.phase_name = phase_name
        self.metadata = metadata

    def __enter__(self):
        self.profiler.start_phase(self.phase_name, self.metadata)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.profiler.end_phase(self.phase_name)
        return False  # Don't suppress exceptions


def profile_phase(phase_name: str):
    """
    Decorator to automatically profile a function as a phase.

    Usage:
        @profile_phase("Graph Loading")
        def load_graph(path):
            # ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Try to find profiler in args/kwargs or use global
            profiler = kwargs.get('profiler')
            if profiler is None and args:
                # Check if first arg has a profiler attribute
                if hasattr(args[0], 'profiler'):
                    profiler = args[0].profiler

            if profiler and isinstance(profiler, VerificationProfiler):
                with ProfilerContext(profiler, phase_name):
                    return func(*args, **kwargs)
            else:
                # No profiler, just call function normally
                return func(*args, **kwargs)

        return wrapper
    return decorator


# Global profiler instance (optional, for convenience)
_global_profiler: Optional[VerificationProfiler] = None


def get_global_profiler() -> VerificationProfiler:
    """Get or create the global profiler instance."""
    global _global_profiler
    if _global_profiler is None:
        _global_profiler = VerificationProfiler()
    return _global_profiler


def reset_global_profiler():
    """Reset the global profiler."""
    global _global_profiler
    _global_profiler = VerificationProfiler()
