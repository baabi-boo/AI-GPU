"""Source-only contract for hosted RTL gate compilation resource limits."""

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class RtlGateResourcesTests(unittest.TestCase):
    def test_only_long_cycle_gate_cells_get_reduced_compile_parallelism(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        tests_job = workflow.split("\n  tests:\n", 1)[1].split("\n  complete:\n", 1)[0]
        cell_step = tests_job.split("      - name: Run cell\n", 1)[1].split(
            "      - uses: actions/upload-artifact@v4\n", 1
        )[0]
        self.assertIn(
            'if [[ "${{ matrix.category }}" == "model_parity" || '
            '"${{ matrix.category }}" == "perf_gate" ]]; then',
            cell_step,
        )
        self.assertIn("export THREADS=2", cell_step)
        self.assertLess(cell_step.index("export THREADS=2"),
                        cell_step.index("VX_XLEN=${{ matrix.xlen }} python3 -m pytest"))
        self.assertNotIn("--update-baselines", cell_step)

    def test_verilator_compile_workers_are_driven_by_threads_variable(self):
        makefile = (ROOT / "sim/rtlsim/Makefile").read_text()
        self.assertIn("THREADS ?=", makefile)
        self.assertIn("VL_FLAGS += -j $(THREADS)", makefile)
        self.assertIn("--build $(VL_FLAGS)", makefile)


if __name__ == "__main__":
    unittest.main()
