# SPDX-License-Identifier: Apache-2.0
"""Static hosted-workflow contracts; these checks do not execute qualification."""

from pathlib import Path
import re
import shlex
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p05-python.yml"
P04_WORKFLOW = ROOT / ".github/workflows/p04-model.yml"


def fields(lines, indent):
    result = {}
    active = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        depth = len(line) - len(line.lstrip(" "))
        if depth == indent:
            match = re.fullmatch(" " * indent + r"([A-Za-z][A-Za-z0-9_-]*):(.*)", line)
            if match is None or match[1] in result:
                raise AssertionError("expected a unique plain mapping field: " + line)
            active = match[1]
            result[active] = (match[2].strip(), [])
        elif depth > indent and active is not None:
            result[active][1].append(line)
        else:
            raise AssertionError("unexpected workflow indentation: " + line)
    return result


def children(mapping, name, indent):
    value, lines = mapping[name]
    if value:
        raise AssertionError("expected a block mapping: " + name)
    return fields(lines, indent)


def scalars(mapping):
    if any(lines for _, lines in mapping.values()):
        raise AssertionError("expected only scalar fields")
    return {name: value for name, (value, _) in mapping.items()}


def workflow(path):
    raw = path.read_bytes()
    if len(raw) > 64 * 1024 or b"\t" in raw:
        raise AssertionError("workflow exceeds the bounded plain-indentation contract")
    return fields(raw.decode("utf-8").splitlines(), 0)


def steps(job):
    blocks = []
    for line in job["steps"][1]:
        if line.startswith("      - "):
            blocks.append(["        " + line[8:]])
        elif blocks:
            blocks[-1].append(line)
        else:
            raise AssertionError("expected a plain step sequence")
    return [fields(block, 8) for block in blocks]


def script(step):
    value, lines = step["run"]
    if value == "|":
        return "\n".join(line[10:] for line in lines)
    if lines:
        raise AssertionError("unexpected multiline shell scalar")
    return value


def command(step):
    return shlex.split(script(step).replace("\\\n", " ").splitlines()[0])


def path_filters(events, event):
    body = children(events, event, 4)
    paths = body["paths"]
    if paths[0]:
        raise AssertionError("expected an explicit positive path list")
    result = []
    for line in paths[1]:
        match = re.fullmatch(r"      - '([A-Za-z0-9_./*\-]+)'", line)
        if match is None or match[1] in result:
            raise AssertionError("unsupported or duplicate path filter: " + line)
        result.append(match[1])
    if not result:
        raise AssertionError("empty path filters")
    return set(result)


class InstalledPythonWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.p04 = workflow(P04_WORKFLOW)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "qualification", 4)
        cls.steps = steps(cls.job)
        cls.p04_steps = steps(children(children(cls.p04, "jobs", 2), "qualification", 4))

    def one(self, key, value, sequence=None):
        sequence = self.steps if sequence is None else sequence
        found = [step for step in sequence if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def test_push_and_pull_request_cover_python_and_native_p04_inputs(self):
        events = children(self.workflow, "on", 2)
        self.assertEqual(set(events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(events["workflow_dispatch"], ("", []))
        self.assertEqual(children(events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(set(children(events, "push", 4)), {"branches", "paths"})
        self.assertEqual(set(children(events, "pull_request", 4)), {"paths"})
        additional = {
            ".github/workflows/p05-python.yml", "python/**", "setup.py", "pyproject.toml",
            "MANIFEST.in", "LICENSE", "ci/project/**", "tests/regression/ai_matmul/**",
            "tests/regression/sgemm_tcu/**", "tests/runtime/**",
        }
        p04_events = children(self.p04, "on", 2)
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                required = path_filters(p04_events, event) | additional
                self.assertLessEqual(required, path_filters(events, event))
        self.assertEqual(path_filters(events, "push"), path_filters(events, "pull_request"))

    def test_only_two_simx_formats_run_with_bounded_parallelism(self):
        self.assertEqual(set(self.jobs), {"qualification"})
        self.assertEqual(set(self.job), {
            "name", "runs-on", "timeout-minutes", "strategy", "defaults", "env", "steps",
        })
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        strategy = children(self.job, "strategy", 6)
        self.assertEqual(set(strategy), {"fail-fast", "max-parallel", "matrix"})
        self.assertEqual(strategy["fail-fast"], ("false", []))
        self.assertEqual(strategy["max-parallel"], ("2", []))
        self.assertEqual(scalars(children(strategy, "matrix", 8)), {"format": "[fp16, bf16]"})
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "P05_BACKEND": "simx", "P05_FORMAT": "${{ matrix.format }}",
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'2'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        defaults = children(self.job, "defaults", 6)
        self.assertEqual(set(defaults), {"run"})
        self.assertEqual(scalars(children(defaults, "run", 8)), {"shell": "bash"})

    def test_read_only_checkout_and_complete_evidence_survive_failures(self):
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p05-python-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "false",
        })
        checkout = self.one("uses", "actions/checkout@v4")
        self.assertEqual(scalars(children(checkout, "with", 10)), {
            "fetch-depth": "1", "submodules": "recursive", "persist-credentials": "false",
        })
        identity = script(self.one("name", "Initialize retained job identity"))
        for token in ("'job.json'", "'workflow.yml'", "'GITHUB_SHA'", "'GITHUB_RUN_ID'",
                      "'GITHUB_RUN_ATTEMPT'", "'P05_BACKEND'", "'P05_FORMAT'",
                      "native_execution='not_run'", "python_execution='not_run'",
                      "acceptance_claimed=False", "workflow_sha256=hashlib.sha256(workflow).hexdigest()"):
            self.assertIn(token, identity)
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p05-simx-${{ matrix.format }}-${{ github.sha }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p05-python/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true",
        })

    def test_exact_python_build_pins_precede_the_clean_native_runner(self):
        setup = self.one("uses", "actions/setup-python@v5")
        self.assertEqual(scalars(children(setup, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false",
        })
        provision = self.one("name", "Provision pinned Python build tools")
        pins = ["setuptools==84.2.1", "wheel==0.48.0", "packaging==26.3"]
        self.assertEqual(tomllib.loads((ROOT / "pyproject.toml").read_text())["build-system"]["requires"], pins)
        self.assertEqual(command(provision), [
            "python3", "-I", "-m", "pip", "--isolated", "install",
            "--disable-pip-version-check", "--no-cache-dir", "--only-binary=:all:", "--no-deps",
            *pins, "2>&1", "|", "tee", "$P05_ROOT/evidence/python-provision.log",
        ])
        probe = script(provision)
        for token in ("'python-provision.json'", "importlib.metadata.version(name)",
                      "data['python_version'] != [3, 12, 14]", "data['implementation'] != 'CPython'",
                      "data['platform'] != 'linux'", "data['build_requirements'] != expected",
                      "raise SystemExit("):
            self.assertIn(token, probe)
        order = [
            self.one("uses", "actions/checkout@v4"),
            self.one("name", "Initialize retained job identity"), setup, provision,
            self.one("name", "Verify clean source and relocate restored tools"),
            self.one("name", "Execute unchanged native model reference"),
            self.one("name", "Execute installed Python variant against native results"),
            self.one("uses", "actions/upload-artifact@v4"),
        ]
        self.assertEqual([self.steps.index(step) for step in order],
                         sorted(self.steps.index(step) for step in order))

    def test_native_caches_reuse_the_exact_restore_only_p04_identity(self):
        actions = [step["uses"][0] for step in self.steps if "uses" in step]
        self.assertEqual(actions, ["actions/checkout@v4", "actions/setup-python@v5",
                                   "actions/cache/restore@v4", "actions/cache/restore@v4",
                                   "actions/upload-artifact@v4"])
        for identifier in ("toolchain", "dependencies"):
            with self.subTest(identifier=identifier):
                self.assertEqual(self.one("id", identifier), self.one("id", identifier, self.p04_steps))
        pins = script(self.one("id", "pins")).replace("P05_", "P04_")
        self.assertEqual(pins, script(self.one("id", "pins", self.p04_steps)))
        installer = self.one("name", "Install baseline host dependencies")
        self.assertEqual(installer, self.one("name", "Install baseline host dependencies", self.p04_steps))
        self.assertLess(self.steps.index(self.one("id", "pins")), self.steps.index(self.one("id", "toolchain")))
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step), r"toolchain_install|(?:curl|wget)\s|make\s.*third_party|git clone")

    def test_preparation_and_execution_fail_closed_with_retained_raw_logs(self):
        prepare = self.one("name", "Verify clean source and relocate restored tools")
        p04_prepare = self.one("name", "Verify clean source and relocate restored tools", self.p04_steps)
        self.assertEqual({name.replace("P05_", "P04_"): value for name, value in
                          scalars(children(prepare, "env", 10)).items()},
                         scalars(children(p04_prepare, "env", 10)))
        self.assertEqual(command(prepare), [
            "python3", "ci/project/p04_ci_prepare.py", "--source-dir", "$PWD",
            "--workspace-dir", "$P05_ROOT", "--expected-revision", "$GITHUB_SHA",
            "--toolchain-id", "$P05_TOOLCHAIN_ID", "--toolchain-cache-key", "$P05_TOOLCHAIN_CACHE",
            "--third-party-cache-key", "$P05_DEPENDENCY_CACHE", "--expected-third-party-key", "$P05_DEPENDENCY_KEY",
            "--backend", "$P05_BACKEND", "--format", "$P05_FORMAT",
            "2>&1", "|", "tee", "$P05_ROOT/evidence/preparation.log",
        ])
        native = self.one("name", "Execute unchanged native model reference")
        self.assertEqual(command(native), [
            "python3", "ci/project/p04_execute.py", "run", "--source-dir", "$PWD",
            "--tools-dir", "$P05_ROOT/tools", "--work-dir", "$P05_ROOT/native-work",
            "--output", "$P05_ROOT/evidence/native-model", "--backend", "simx",
            "--format", "$P05_FORMAT", "--iterations", "2", "--jobs", "2",
            "--timeout-seconds", "1800", "--run-timeout-seconds", "180",
            "2>&1", "|", "tee", "$P05_ROOT/evidence/native-execution.log",
        ])
        execute = self.one("name", "Execute installed Python variant against native results")
        self.assertEqual(command(execute), [
            "python3", "ci/project/p05_execute.py", "run", "--source-dir", "$PWD",
            "--tools-dir", "$P05_ROOT/tools", "--work-dir", "$P05_ROOT/work",
            "--output", "$P05_ROOT/evidence/python",
            "--native-build", "$P05_ROOT/native-work/simx-$P05_FORMAT",
            "--native-output", "$P05_ROOT/evidence/native-model",
            "--format", "$P05_FORMAT", "--jobs", "2",
            "--timeout-seconds", "1800", "--run-timeout-seconds", "180",
            "2>&1", "|", "tee", "$P05_ROOT/evidence/execution.log",
        ])
        guarded = {"Install baseline host dependencies", "Retain preparation and installed Python execution packet"}
        self.assertEqual(len(self.steps), 12)
        for step in self.steps:
            self.assertNotIn("continue-on-error", step)
            self.assertNotIn("shell", step)
            if step.get("name", (None,))[0] not in guarded:
                self.assertNotIn("if", step)
        self.assertEqual(set(prepare), {"name", "env", "run"})
        self.assertEqual(set(native), {"name", "run"})
        self.assertEqual(set(execute), {"name", "run"})
        self.assertEqual(len(script(prepare).replace("\\\n", " ").splitlines()), 1)
        self.assertEqual(len(script(native).replace("\\\n", " ").splitlines()), 1)
        self.assertEqual(len(script(execute).replace("\\\n", " ").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
