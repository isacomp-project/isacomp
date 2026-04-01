"""
Multi-solver support for SMT verification.

Tries multiple SMT solvers automatically and picks the best one:
- Z3 (command-line or Python API)
- CVC5 (Python API)
- Bitwuzla (if available)

Features:
- Automatic fallback on timeout or failure
- Solver performance tracking
- Detailed reporting of which solver was used
"""

from typing import Tuple, Optional, List
import subprocess
import tempfile
import os
import time
from dataclasses import dataclass


@dataclass
class SolverResult:
    """Result from an SMT solver."""
    solver_name: str
    result: str  # 'sat', 'unsat', 'unknown', 'timeout', 'error'
    time_seconds: float
    output: str
    error: Optional[str] = None


class MultiSolverVerifier:
    """
    Tries multiple SMT solvers and picks the best result.

    Priority order:
    1. Z3 command-line (fastest for most problems)
    2. Z3 Python API (if CLI fails)
    3. CVC5 Python API (alternative solver)
    4. Bitwuzla (if available)
    """

    def __init__(self, timeout_per_solver: int = 30):
        """
        Initialize multi-solver verifier.

        Args:
            timeout_per_solver: Timeout in seconds for each solver attempt
        """
        self.timeout = timeout_per_solver
        self.solver_stats = []  # Track which solvers worked

        # Detect available solvers
        self.available_solvers = self._detect_solvers()

    def _detect_solvers(self) -> List[str]:
        """Detect which solvers are available."""
        available = []

        # Check for Z3 command-line
        try:
            result = subprocess.run(
                ['z3', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                available.append('z3-cli')
        except:
            pass

        # Check for Z3 Python API
        try:
            import z3
            available.append('z3-python')
        except ImportError:
            pass

        # Check for CVC5 Python API
        try:
            import cvc5
            available.append('cvc5-python')
        except ImportError:
            pass

        # Check for Bitwuzla
        try:
            result = subprocess.run(
                ['bitwuzla', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                available.append('bitwuzla-cli')
        except:
            pass

        return available

    def _try_z3_cli(self, formula: str) -> SolverResult:
        """Try Z3 command-line solver."""
        start_time = time.time()

        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.smt2', delete=False) as f:
                f.write(formula)
                temp_file = f.name

            result = subprocess.run(
                ['z3', '-smt2', temp_file],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            elapsed = time.time() - start_time
            os.unlink(temp_file)

            output = result.stdout.strip()

            # Parse result
            if 'unsat' in output.lower():
                return SolverResult('z3-cli', 'unsat', elapsed, output)
            elif 'sat' in output.lower() and 'unsat' not in output.lower():
                return SolverResult('z3-cli', 'sat', elapsed, output)
            else:
                return SolverResult('z3-cli', 'unknown', elapsed, output)

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            if os.path.exists(temp_file):
                os.unlink(temp_file)
            return SolverResult('z3-cli', 'timeout', elapsed, '', f'Timeout after {self.timeout}s')

        except Exception as e:
            elapsed = time.time() - start_time
            return SolverResult('z3-cli', 'error', elapsed, '', str(e))

    def _try_z3_python(self, formula: str) -> SolverResult:
        """Try Z3 Python API."""
        start_time = time.time()

        try:
            import z3

            # Parse SMT-LIB2 formula
            solver = z3.Solver()
            solver.set('timeout', self.timeout * 1000)  # milliseconds

            # Parse the formula
            solver.from_string(formula)

            # Check satisfiability
            result = solver.check()
            elapsed = time.time() - start_time

            if result == z3.unsat:
                return SolverResult('z3-python', 'unsat', elapsed, 'unsat')
            elif result == z3.sat:
                model = solver.model()
                model_str = str(model)
                return SolverResult('z3-python', 'sat', elapsed, f'sat\n{model_str}')
            else:
                return SolverResult('z3-python', 'unknown', elapsed, 'unknown')

        except Exception as e:
            elapsed = time.time() - start_time
            return SolverResult('z3-python', 'error', elapsed, '', str(e))

    def _try_cvc5_python(self, formula: str) -> SolverResult:
        """Try CVC5 Python API."""
        start_time = time.time()

        try:
            import cvc5
            from cvc5 import Kind

            solver = cvc5.Solver()
            solver.setOption("produce-models", "true")
            solver.setLogic("QF_ABV")

            # Set timeout (in milliseconds)
            solver.setOption("tlimit-per", str(self.timeout * 1000))

            # Parse SMT-LIB2 input
            # CVC5 Python API is different - we need to parse the formula
            # For now, use the command parser if available
            try:
                solver.checkSatAssuming([])  # This won't work, placeholder

                # Since CVC5 Python API doesn't have easy SMT-LIB2 parsing,
                # we'll return an error for now
                elapsed = time.time() - start_time
                return SolverResult('cvc5-python', 'error', elapsed, '',
                                   'CVC5 Python API requires formula construction, SMT-LIB2 parsing not trivial')

            except Exception as e:
                elapsed = time.time() - start_time
                return SolverResult('cvc5-python', 'error', elapsed, '', str(e))

        except ImportError:
            elapsed = time.time() - start_time
            return SolverResult('cvc5-python', 'error', elapsed, '', 'CVC5 not available')
        except Exception as e:
            elapsed = time.time() - start_time
            return SolverResult('cvc5-python', 'error', elapsed, '', str(e))

    def verify(self, formula: str, preferred_solver: Optional[str] = None) -> Tuple[bool, str, str]:
        """
        Verify an SMT formula using available solvers.

        Tries solvers in order until one succeeds or all fail/timeout.

        Args:
            formula: SMT-LIB2 formula string
            preferred_solver: Try this solver first if specified

        Returns:
            (is_equivalent, details, solver_used)
            - is_equivalent: True if unsat (no counterexample found)
            - details: Solver output or error message
            - solver_used: Name of solver that produced the result
        """
        if not self.available_solvers:
            return False, "No SMT solvers available. Please install z3-solver.", "none"

        # Determine solver order
        solver_order = list(self.available_solvers)
        if preferred_solver and preferred_solver in solver_order:
            solver_order.remove(preferred_solver)
            solver_order.insert(0, preferred_solver)

        # Try each solver
        results = []
        for solver_name in solver_order:
            print(f"  Trying {solver_name}...", end=' ', flush=True)

            if solver_name == 'z3-cli':
                result = self._try_z3_cli(formula)
            elif solver_name == 'z3-python':
                result = self._try_z3_python(formula)
            elif solver_name == 'cvc5-python':
                result = self._try_cvc5_python(formula)
            else:
                continue

            results.append(result)

            # Check if we got a definitive answer
            if result.result in ['sat', 'unsat']:
                print(f"{result.result} ({result.time_seconds:.2f}s)")
                self.solver_stats.append(result)

                # For equivalence checking:
                # - unsat means no counterexample → graphs are equivalent
                # - sat means counterexample found → graphs are NOT equivalent
                is_equivalent = (result.result == 'unsat')
                return is_equivalent, result.output, result.solver_name

            elif result.result == 'timeout':
                print(f"timeout ({result.time_seconds:.1f}s)")
            elif result.result == 'error':
                print(f"error: {result.error}")
            else:
                print(f"unknown")

        # All solvers failed
        failure_summary = "\n".join(
            f"  {r.solver_name}: {r.result}" +
            (f" ({r.error})" if r.error else "")
            for r in results
        )

        return False, f"All solvers failed or timed out:\n{failure_summary}", "none"

    def get_stats_summary(self) -> str:
        """Get summary of solver performance."""
        if not self.solver_stats:
            return "No solver statistics available"

        lines = []
        lines.append("\nSolver Performance Summary:")
        lines.append("-" * 50)

        for result in self.solver_stats:
            lines.append(f"  {result.solver_name:15s}: {result.result:8s} in {result.time_seconds:.3f}s")

        # Average times by solver
        from collections import defaultdict
        solver_times = defaultdict(list)
        for result in self.solver_stats:
            solver_times[result.solver_name].append(result.time_seconds)

        if solver_times:
            lines.append("\nAverage Times:")
            for solver, times in solver_times.items():
                avg_time = sum(times) / len(times)
                lines.append(f"  {solver:15s}: {avg_time:.3f}s (n={len(times)})")

        return "\n".join(lines)


def verify_with_multi_solver(formula: str, timeout: int = 30) -> Tuple[bool, str]:
    """
    Convenience function to verify with automatic solver selection.

    Args:
        formula: SMT-LIB2 formula
        timeout: Timeout per solver in seconds

    Returns:
        (is_equivalent, details): Tuple of verification result
    """
    verifier = MultiSolverVerifier(timeout_per_solver=timeout)
    is_equiv, details, solver_used = verifier.verify(formula)

    # Add solver info to details
    details_with_solver = f"[Solver: {solver_used}]\n{details}"

    return is_equiv, details_with_solver
