# SPDX-License-Identifier: Apache-2.0
"""Governance workflow trust and shell boundaries using synthetic executables."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from governance_workflow_test_support import assert_strict_governance_step
from test_p05_ci_workflow import children, fields, path_filters, scalars, script, steps


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/project-governance.yml"
INSTALL = "Install pinned governance CMake"
PREPARE = "Prepare checked governance invocation environment"
RUN = "Test governance tooling"
UPLOAD = "Retain complete governance packet"
CMAKE_REQUIREMENT = (
    "cmake==3.22.6 --hash=sha256:"
    "a2357c510e37db7df156c31ab43857b4583e3a2ece8220747e8a007aea50aa45"
)
PACKET_PREFIX = "${{ runner.temp }}/project-governance"
PACKET_PATHS = (
    PACKET_PREFIX + "/logs",
    PACKET_PREFIX + "/environment/environment.json",
    PACKET_PREFIX + "/run",
)
STAGE_NAMES = (
    None, "Prepare governance evidence directory", "Verify system Python 3.12",
    "Inspect governance prerequisites", "Validate project structure and evidence",
    "Check published baseline packet consistency", INSTALL, PREPARE, RUN, UPLOAD,
)
PATH_FILTERS = {
    ".github/workflows/project-governance.yml", ".github/workflows/p05-python.yml",
    ".github/workflows/p05-torch.yml", ".github/workflows/p06-baseline.yml",
    ".github/workflows/p06-workspace.yml", ".github/workflows/p06-warm-workspace.yml",
    ".github/workflows/p06-checked-counters.yml", ".github/workflows/p06-managed-preflight.yml",
    ".github/workflows/p06-native-lifetime.yml", ".github/workflows/p06-dependency-provenance.yml",
    ".github/workflows/p06-managed-preflight-replay.yml", ".github/ISSUE_TEMPLATE/**",
    ".github/pull_request_template.md", "ci/project/**", "ci/gen_config.py", "python/**",
    "setup.py", "pyproject.toml", "MANIFEST.in", "sw/runtime/ai/**", "sw/runtime/common/**",
    "sw/runtime/include/**", "sw/common/ai_matmul*.h", "sw/kernel/ai/**",
    "tests/regression/ai_matmul/**", "tests/regression/ai_mlp/**",
    "tests/regression/ai_bench_common/**", "tests/regression/ai_bench_matmul/**",
    "tests/regression/ai_bench_mlp/**", "tests/regression/ai_workspace/**",
    "tests/regression/ai_warm_workspace/**", "tests/regression/ai_counter_preflight/**",
    "tests/runtime/**", "tests/unittest/checked_counters/**", "tests/unittest/pending_reads/**",
    "sim/common/perf_counter.h", "sim/simx/**", "docs/project/**",
    "docs/designs/tiny_mlp_fixture_v1.md", "docs/designs/mlp_execution_records_v1.md",
    "docs/designs/tensor_numerics_v1.md", "docs/designs/python_binding_v1.md",
    "docs/designs/torch_custom_ops_v1.md", "docs/designs/torch_archive_replay_v1.md",
    "docs/designs/native_benchmark_v1.md", "docs/designs/native_baseline_analysis_v1.md",
    "docs/designs/serial_matmul_workspace_v1.md", "docs/designs/warm_workspace_benchmark_v1.md",
    "docs/designs/managed_counter_preflight_v1.md", "docs/designs/managed_counter_lifetime_v1.md",
    "docs/designs/complete_counter_qualification_v1.md", "docs/designs/qualified_warm_workspace_v1.md",
    "docs/designs/dependency_provenance_v1.md", "docs/designs/managed_counter_preflight_replay_v1.md",
    "docs/designs/simx_checked_counters_v1.md", "docs/index.md",
    "docs/assets/img/vortex_framework_stack.svg", "profiles/**", "README.md", "ROADMAP.md",
    "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "LICENSE", "VERSION",
    "VX_config.toml", "VX_types.toml", ".gitmodules",
}


def one(case, sequence, key, value):
    matches = [step for step in sequence if step.get(key, (None,))[0] == value]
    case.assertEqual(len(matches), 1, (key, value))
    return matches[0]


def assert_envelope(case, source):
    parsed = fields(source.splitlines(), 0)
    case.assertEqual(set(parsed), {"name", "on", "permissions", "concurrency", "jobs"})
    events = children(parsed, "on", 2)
    case.assertEqual(set(events), {"push", "pull_request", "workflow_dispatch"})
    case.assertEqual(events["workflow_dispatch"], ("", []))
    for event in ("push", "pull_request"):
        case.assertEqual(set(children(events, event, 4)), {"paths"})
    case.assertEqual(scalars(children(parsed, "permissions", 2)), {"contents": "read"})
    case.assertEqual(scalars(children(parsed, "concurrency", 2)), {
        "group": "project-governance-${{ github.event_name }}-${{ github.ref }}",
        "cancel-in-progress": "true",
    })
    jobs = children(parsed, "jobs", 2)
    case.assertEqual(set(jobs), {"governance"})
    job = children(jobs, "governance", 4)
    case.assertEqual(set(job), {"runs-on", "timeout-minutes", "env", "steps"})
    case.assertEqual(job["runs-on"], ("ubuntu-24.04", []))
    case.assertEqual(job["timeout-minutes"], ("90", []))
    case.assertEqual(scalars(children(job, "env", 6)), {
        "PYTHONDONTWRITEBYTECODE": "'1'", "GOVERNANCE_ROOT": PACKET_PREFIX,
    })
    case.assertNotRegex(source, r"secrets\s*[.\[]|pull_request_target|workflow_run|"
                        r"self-hosted|write-all|id-token\s*:|continue-on-error\s*:")
    return events, steps(job)


def assert_stages(case, sequence):
    case.assertEqual(tuple(step.get("name", (None,))[0] for step in sequence), STAGE_NAMES)
    case.assertEqual([step["uses"][0] for step in sequence if "uses" in step], [
        "actions/checkout@v4", "actions/upload-artifact@v4",
    ])
    checkout = one(case, sequence, "uses", "actions/checkout@v4")
    case.assertEqual(set(checkout), {"uses", "with"})
    case.assertEqual(scalars(children(checkout, "with", 10)), {
        "fetch-depth": "1", "submodules": "false", "lfs": "false", "persist-credentials": "false",
    })
    for step in sequence[1:-1]:
        expected = {"name", "run", "timeout-minutes"} if step["name"][0] == INSTALL else {"name", "run"}
        case.assertEqual(set(step), expected)
    for filename, name in (("governance_env.py", PREPARE), ("governance_run.py", RUN)):
        invocations = [step for step in sequence if "run" in step and filename in script(step)]
        case.assertEqual(invocations, [one(case, sequence, "name", name)])
        case.assertEqual(script(invocations[0]).count(filename), 1)


def assert_cmake_install(case, step):
    case.assertEqual(set(step), {"name", "timeout-minutes", "run"})
    case.assertEqual(step["timeout-minutes"], ("5", []))
    lines = script(step).replace("\\\n", " ").splitlines()
    case.assertEqual(len(lines), 9)
    case.assertEqual(lines[:4], [
        "set -euo pipefail",
        "cat > \"$GOVERNANCE_ROOT/logs/cmake-requirements.txt\" <<'REQUIREMENTS'",
        CMAKE_REQUIREMENT, "REQUIREMENTS",
    ])
    case.assertEqual(shlex.split(lines[4], posix=False), [
        "python3", "-m", "pip", "--isolated", "--disable-pip-version-check", "install",
        "--index-url", "https://pypi.org/simple", "--no-cache-dir", "--no-deps", "--no-compile",
        "--only-binary=:all:", "--require-hashes", "--target", '"$GOVERNANCE_ROOT/cmake-package"',
        "--requirement", '"$GOVERNANCE_ROOT/logs/cmake-requirements.txt"',
        "2>&1", "|", "tee", '"$GOVERNANCE_ROOT/logs/cmake-install.log"',
    ])
    case.assertEqual(lines[5:], [
        'cmake="$GOVERNANCE_ROOT/cmake-package/cmake/data/bin/cmake"',
        'test -x "$cmake"',
        '"$cmake" --version 2>&1 | tee "$GOVERNANCE_ROOT/logs/cmake-version.log"',
        'test "$(head -n 1 "$GOVERNANCE_ROOT/logs/cmake-version.log")" = \'cmake version 3.22.6\'',
    ])


def assert_environment_prepare(case, step):
    case.assertEqual(set(step), {"name", "run"})
    lines = script(step).replace("\\\n", " ").splitlines()
    case.assertEqual(len(lines), 2)
    case.assertEqual(lines[0], "set -euo pipefail")
    case.assertEqual(shlex.split(lines[1], posix=False), [
        "python3", "ci/project/governance_env.py", "--output-dir", '"$GOVERNANCE_ROOT/environment"',
        "--cmake", '"$GOVERNANCE_ROOT/cmake-package/cmake/data/bin/cmake"',
        "2>&1", "|", "tee", '"$GOVERNANCE_ROOT/logs/environment.log"',
    ])


def assert_artifact(case, step):
    case.assertEqual(set(step), {"name", "if", "uses", "with"})
    case.assertEqual(step["if"], ("always()", []))
    case.assertEqual(step["uses"], ("actions/upload-artifact@v4", []))
    options = children(step, "with", 10)
    case.assertEqual(set(options), {
        "name", "path", "if-no-files-found", "retention-days", "compression-level", "include-hidden-files",
    })
    case.assertEqual(scalars({key: value for key, value in options.items() if key != "path"}), {
        "name": "project-governance-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
        "if-no-files-found": "error", "retention-days": "30", "compression-level": "6",
        "include-hidden-files": "true",
    })
    case.assertEqual(options["path"], ("|", ["            " + path for path in PACKET_PATHS]))


def assert_workflow(case, source):
    events, sequence = assert_envelope(case, source)
    assert_stages(case, sequence)
    for event in ("push", "pull_request"):
        case.assertEqual(path_filters(events, event), PATH_FILTERS)
    assert_cmake_install(case, one(case, sequence, "name", INSTALL))
    assert_environment_prepare(case, one(case, sequence, "name", PREPARE))
    assert_strict_governance_step(case, one(case, sequence, "name", RUN))
    assert_artifact(case, sequence[-1])


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!" + sys.executable + "\n" + body, encoding="utf-8")
    path.chmod(0o700)


def checked_environment(root):
    return {
        "PATH": str(root / "environment/venv/bin") + ":/usr/bin:/bin",
        "HOME": str(root / "environment/home"), "TMPDIR": str(root / "environment/tmp"),
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
        "MAKEFLAGS": "-j2", "CMAKE_BUILD_PARALLEL_LEVEL": "2", "THREADS": "1",
    }


class GovernanceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        parsed = fields(cls.source.splitlines(), 0)
        cls.events = children(parsed, "on", 2)
        cls.sequence = steps(children(children(parsed, "jobs", 2), "governance", 4))

    def named(self, name):
        return one(self, self.sequence, "name", name)

    def packet_directory(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-workflow-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "runner temp" / "project-governance"
        (root / "logs").mkdir(parents=True)
        return root

    def shell(self, name, root, env=None):
        environment = {"PATH": str(root / "bin") + os.pathsep + os.defpath,
                       "GOVERNANCE_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
        environment.update(env or {})
        return subprocess.run(["bash", "-e", "-c", script(self.named(name))],
                              cwd=ROOT, env=environment, capture_output=True, text=True, timeout=10)

    def test_workflow_keeps_read_only_fork_trust_and_bounded_hosted_execution(self):
        assert_envelope(self, self.source)
        assert_stages(self, self.sequence)

    def test_trigger_path_filters_remain_exactly_unchanged(self):
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                self.assertEqual(path_filters(self.events, event), PATH_FILTERS)

    def test_cmake_wheel_digest_is_pinned_and_native_version_is_required(self):
        assert_cmake_install(self, self.named(INSTALL))

    def test_checked_environment_precedes_the_single_unconditional_strict_run(self):
        assert_stages(self, self.sequence)
        assert_environment_prepare(self, self.named(PREPARE))
        assert_strict_governance_step(self, self.named(RUN))

    def test_always_artifact_retains_complete_run_and_logs_without_tool_payloads(self):
        self.assertIs(self.sequence[-1], self.named(UPLOAD))
        assert_artifact(self, self.sequence[-1])

    def test_security_and_retention_mutations_are_rejected(self):
        mutations = (
            ("changed wheel", CMAKE_REQUIREMENT, CMAKE_REQUIREMENT.replace("a2357c", "b2357c")),
            ("floating version", "cmake==3.22.6", "cmake>=3.22.6"),
            ("unhashed install", "--require-hashes", ""),
            ("ambient pip config", "--isolated", ""),
            ("dependency resolution", "--no-deps", ""),
            ("source package", "--only-binary=:all:", ""),
            ("pip cache", "--no-cache-dir", ""),
            ("package launcher", 'cmake="$GOVERNANCE_ROOT/cmake-package/cmake/data/bin/cmake"',
             'cmake="$GOVERNANCE_ROOT/cmake-package/bin/cmake"'),
            ("wrong native version", "= 'cmake version 3.22.6'", "= 'cmake version 3.26.0'"),
            ("suppressed install", 'tee "$GOVERNANCE_ROOT/logs/cmake-install.log"',
             'tee "$GOVERNANCE_ROOT/logs/cmake-install.log" || true'),
            ("conditional environment", "- name: " + PREPARE, "- name: " + PREPARE + "\n        if: success()"),
            ("ambient suite environment", "/usr/bin/env -i", "/usr/bin/env"),
            ("secret forwarded", "LANG=C LC_ALL=C", "TOKEN=${{ secrets.TOKEN }} LANG=C LC_ALL=C"),
            ("success-only artifact", "if: always()", "if: success()"),
            ("incomplete run packet", PACKET_PREFIX + "/run\n", PACKET_PREFIX + "/run/summary.json\n"),
            ("missing logs", "            " + PACKET_PREFIX + "/logs\n", ""),
            ("tool payload upload", PACKET_PREFIX + "/run\n", PACKET_PREFIX + "/\n"),
            ("missing artifact allowed", "if-no-files-found: error", "if-no-files-found: warn"),
            ("hidden evidence omitted", "include-hidden-files: true", "include-hidden-files: false"),
            ("fork target trigger", "  pull_request:\n", "  pull_request_target:\n"),
            ("write permission", "contents: read", "contents: write"),
            ("self-hosted execution", "runs-on: ubuntu-24.04", "runs-on: self-hosted"),
            ("job failure ignored", "    timeout-minutes: 90", "    timeout-minutes: 90\n    continue-on-error: true"),
            ("narrow test trigger", "'ci/project/**'", "'ci/project/governance_run.py'"),
        )
        assert_workflow(self, self.source)
        for label, old, new in mutations:
            with self.subTest(mutation=label):
                self.assertIn(old, self.source)
                with self.assertRaises(AssertionError):
                    assert_workflow(self, self.source.replace(old, new, 1))

    def test_missing_repeated_and_reordered_environment_or_run_are_rejected(self):
        for name in (PREPARE, RUN):
            index = self.sequence.index(self.named(name))
            for change in ("missing", "repeated", "reordered"):
                with self.subTest(step=name, change=change):
                    altered = deepcopy(self.sequence)
                    if change == "missing":
                        del altered[index]
                    elif change == "repeated":
                        altered.insert(index, deepcopy(altered[index]))
                    else:
                        altered[index - 1], altered[index] = altered[index], altered[index - 1]
                    with self.assertRaises(AssertionError):
                        assert_stages(self, altered)

    def test_install_shell_retains_logs_and_rejects_pip_native_and_version_failures(self):
        cases = (
            ("pass", 0, 0, "cmake version 3.22.6", 0),
            ("pip failure", 7, 0, "cmake version 3.22.6", 7),
            ("native failure", 0, 9, "cmake version 3.22.6", 9),
            ("wrong version", 0, 0, "cmake version 3.26.0", 1),
            ("missing binary", 0, 0, None, 1),
        )
        for label, pip_status, native_status, version, expected in cases:
            with self.subTest(case=label):
                root = self.packet_directory()
                native_marker = root / "native-invocations.jsonl"
                native_body = (
                    "from pathlib import Path\nimport sys\n"
                    + "with Path(" + repr(str(native_marker)) + ").open('a') as target:\n"
                    + "    target.write(repr(sys.argv[1:]) + '\\n')\n"
                    + "print(" + repr(version) + ", flush=True)\n"
                    + "raise SystemExit(" + str(native_status) + ")\n"
                )
                native = root / "cmake-package/cmake/data/bin/cmake"
                provision = (
                    "import json, os, sys\nfrom pathlib import Path\n"
                    + "root = Path(os.environ['GOVERNANCE_ROOT'])\n"
                    + "with (root / 'install-invocations.jsonl').open('a') as target:\n"
                    + "    target.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    + "print('synthetic-install-stdout', flush=True)\n"
                    + "print('synthetic-install-stderr', file=sys.stderr, flush=True)\n"
                )
                if version is not None:
                    provision += (
                        "native = Path(" + repr(str(native)) + ")\n"
                        + "native.parent.mkdir(parents=True)\n"
                        + "native.write_text(" + repr("#!" + sys.executable + "\n" + native_body) + ")\n"
                        + "native.chmod(0o700)\n"
                    )
                provision += "raise SystemExit(" + str(pip_status) + ")\n"
                executable(root / "bin/python3", provision)
                result = self.shell(INSTALL, root)
                self.assertEqual(result.returncode, expected, result.stderr)
                calls = (root / "install-invocations.jsonl").read_text().splitlines()
                self.assertEqual(len(calls), 1)
                self.assertEqual(json.loads(calls[0]), [
                    "-m", "pip", "--isolated", "--disable-pip-version-check", "install",
                    "--index-url", "https://pypi.org/simple", "--no-cache-dir", "--no-deps", "--no-compile",
                    "--only-binary=:all:", "--require-hashes", "--target", str(root / "cmake-package"),
                    "--requirement", str(root / "logs/cmake-requirements.txt"),
                ])
                self.assertEqual((root / "logs/cmake-requirements.txt").read_text(), CMAKE_REQUIREMENT + "\n")
                self.assertEqual((root / "logs/cmake-install.log").read_text(),
                                 "synthetic-install-stdout\nsynthetic-install-stderr\n")
                if pip_status == 0 and version is not None:
                    self.assertEqual(native_marker.read_text().splitlines(), ["['--version']"])
                    self.assertEqual((root / "logs/cmake-version.log").read_text(), version + "\n")
                else:
                    self.assertFalse(native_marker.exists())
                    self.assertFalse((root / "logs/cmake-version.log").exists())

    def test_environment_helper_shell_invokes_once_and_propagates_failure_with_both_streams(self):
        for status in (0, 7):
            with self.subTest(status=status):
                root = self.packet_directory()
                executable(root / "bin/python3", (
                    "import json, os, sys\nfrom pathlib import Path\n"
                    + "with (Path(os.environ['GOVERNANCE_ROOT']) / 'environment-calls.jsonl').open('a') as target:\n"
                    + "    target.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    + "print('synthetic-environment-stdout', flush=True)\n"
                    + "print('synthetic-environment-stderr', file=sys.stderr, flush=True)\n"
                    + "raise SystemExit(" + str(status) + ")\n"
                ))
                result = self.shell(PREPARE, root)
                self.assertEqual(result.returncode, status, result.stderr)
                calls = (root / "environment-calls.jsonl").read_text().splitlines()
                self.assertEqual(len(calls), 1)
                self.assertEqual(json.loads(calls[0]), [
                    "ci/project/governance_env.py", "--output-dir", str(root / "environment"),
                    "--cmake", str(root / "cmake-package/cmake/data/bin/cmake"),
                ])
                self.assertEqual((root / "logs/environment.log").read_text(),
                                 "synthetic-environment-stdout\nsynthetic-environment-stderr\n")

    def test_actual_suite_shell_clears_ambient_state_and_retains_failed_packet(self):
        for status in (0, 7):
            with self.subTest(status=status):
                root = self.packet_directory()
                executable(root / "bin/env", "raise SystemExit(98)\n")
                executable(root / "environment/venv/bin/python", (
                    "import json, os, sys\nfrom pathlib import Path\n"
                    + "root = Path(" + repr(str(root)) + ")\n"
                    + "with (root / 'suite-calls.jsonl').open('a') as target:\n"
                    + "    target.write(json.dumps({'args': sys.argv[1:], 'environment': dict(os.environ)}) + '\\n')\n"
                    + "output = Path(sys.argv[sys.argv.index('--output-dir') + 1])\n"
                    + "output.mkdir()\n"
                    + "for name in ('started.json', 'summary.json', 'discovered.json', 'events.jsonl', 'unittest.log', '.failure-state'):\n"
                    + "    (output / name).write_text('synthetic retained result\\n')\n"
                    + "print('synthetic-suite-stdout', flush=True)\n"
                    + "print('synthetic-suite-stderr', file=sys.stderr, flush=True)\n"
                    + "raise SystemExit(" + str(status) + ")\n"
                ))
                (root / "environment/environment.json").write_text('{}\n')
                (root / "cmake-package").mkdir()
                (root / "cmake-package/unselected-wheel.whl").write_text("synthetic package payload\n")
                result = self.shell(RUN, root, {
                    "GITHUB_TOKEN": "synthetic-secret", "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
                    "PYTHONHOME": str(root / "invalid-python-home"), "PYTHONPATH": str(root / "ambient-modules"),
                    "VIRTUAL_ENV": "/ambient/venv", "CC": "/ambient/compiler", "CXX": "/ambient/compiler",
                    "CMAKE_PREFIX_PATH": "/ambient/prefix", "MAKEFLAGS": "-j999", "THREADS": "999",
                    "HOME": "/ambient/home", "TMPDIR": "/ambient/tmp", "LANG": "ambient-locale",
                })
                self.assertEqual(result.returncode, status, result.stderr)
                calls = (root / "suite-calls.jsonl").read_text().splitlines()
                self.assertEqual(len(calls), 1)
                observed = json.loads(calls[0])
                self.assertEqual(observed["environment"], checked_environment(root))
                self.assertEqual(observed["args"], [
                    "ci/project/governance_run.py", "--output-dir", str(root / "run"),
                    "--environment-receipt", str(root / "environment/environment.json"),
                ])
                self.assertEqual((root / "logs/governance.log").read_text(),
                                 "synthetic-suite-stdout\nsynthetic-suite-stderr\n")
                upload = self.named(UPLOAD)
                assert_artifact(self, upload)
                selected = set()
                for line in children(upload, "with", 10)["path"][1]:
                    path = Path(line.strip().replace(PACKET_PREFIX, str(root)))
                    selected.update(member.relative_to(root).as_posix()
                                    for member in (path.rglob("*") if path.is_dir() else [path])
                                    if member.is_file())
                self.assertEqual(selected, {
                    "logs/governance.log", "environment/environment.json", "run/started.json",
                    "run/summary.json", "run/discovered.json", "run/events.jsonl", "run/unittest.log",
                    "run/.failure-state",
                })


if __name__ == "__main__":
    unittest.main()
