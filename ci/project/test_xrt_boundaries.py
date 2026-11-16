# Licensed under the Apache License, Version 2.0.
"""Independent XRT argument, environment, path and reference-log boundaries."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import xrt_baseline as baseline
import xrt_inventory
from xrt_test_support import FIXTURE_CONFIGS, VendorFixture, write_file, write_json


REFERENCE_LINES = (
    "open device connection", "data type: integer", "number of points: 16",
    "buffer size: 64 bytes", "upload source buffer0", "upload source buffer1",
    "launch kernel", "download destination buffer", "wait for completion",
    "verify result", "cleanup", "PASSED!",
)
LOG_LIMIT = 16 * 1024**2


class BoundaryFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-xrt-boundary-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.fixture = VendorFixture(self.base / "fixture")
        self.bundle = self.base / "bundle.json"
        write_json(self.bundle, {"synthetic_fixture": True})
        for target in ("subprocess.Popen", "os.system"):
            patcher = mock.patch(target, side_effect=AssertionError("unexpected process execution"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def args(self, **changes):
        result = argparse.Namespace(
            mode="plan", source=self.fixture.source, build_dir=self.fixture.build,
            tool_dir=self.fixture.tools, manifest=self.fixture.manifest_path,
            bundle_manifest=self.bundle, output=self.fixture.output,
            jobs=2, timeout_seconds=30, min_free_gib=0.001,
            max_log_mib=16, max_rss_gib=1,
        )
        for key, value in changes.items():
            setattr(result, key, value)
        return result

    def paths(self):
        return baseline.resolve_paths(self.args())

    def write_log(self, lines=REFERENCE_LINES, prefix="", suffix=""):
        path = self.base / "smoke.log"
        write_file(path, prefix + "\n".join(lines) + "\n" + suffix)
        return path


class EnvironmentBoundaryTests(BoundaryFixture):
    def test_inherited_injection_and_configuration_overrides_are_removed(self):
        excluded = (
            "MAKEFILES", "MFLAGS", "GNUMAKEFLAGS", "MAKEOVERRIDES", "SHELL",
            "BASH_ENV", "ENV", "CDPATH", "IFS", "PYTHONPATH", "PYTHONHOME",
            "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONPYCACHEPREFIX", "LD_PRELOAD",
            "LD_AUDIT", "LD_LIBRARY_PATH", "LIBRARY_PATH", "CPATH", "C_INCLUDE_PATH",
            "CPLUS_INCLUDE_PATH", "CC", "CXX", "AR", "AS", "CFLAGS", "CXXFLAGS",
            "LDFLAGS", "XLEN", "XRTSIM", "VORTEX_DRIVER", "XCL_EMULATION_MODE",
            "XCLBIN_PATH", "EMCONFIG_PATH", "XRT_INI_PATH", "XRT_DEVICE_INDEX",
            "AWS_SECRET_ACCESS_KEY", "API_TOKEN",
        )
        inherited = {key: "UNTRUSTED-" + key for key in excluded}
        inherited.update({key: "UNTRUSTED-" + key for key in (
            "MAKEFLAGS", "CONFIGS", "TARGET", "THREADS", "JOBS", "IMPL_MAX_THREADS",
            "CMAKE_BUILD_PARALLEL_LEVEL", "CCACHE_DISABLE", "OBJCACHE", "TMPDIR",
            "LANG", "LC_ALL", "TZ", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE",
            "XILINX_VITIS", "XILINX_VIVADO", "XILINX_XRT",
        )})
        original = copy.deepcopy(inherited)
        paths = self.paths()
        for jobs in (1, 2):
            with self.subTest(jobs=jobs):
                cleaned = baseline.clean_environment(self.fixture.manifest, paths, jobs, inherited)
                for key in excluded:
                    self.assertNotIn(key, cleaned)
                self.assertEqual(cleaned["MAKEFLAGS"], "-j" + str(jobs))
                for key in ("THREADS", "JOBS", "IMPL_MAX_THREADS", "CMAKE_BUILD_PARALLEL_LEVEL"):
                    self.assertEqual(cleaned[key], str(jobs))
                self.assertEqual(cleaned["CONFIGS"].split(), FIXTURE_CONFIGS)
                self.assertEqual(cleaned["TARGET"], "hw_emu")
                self.assertEqual(cleaned["CCACHE_DISABLE"], "1")
                self.assertEqual(cleaned["OBJCACHE"], "")
                self.assertEqual(cleaned["TMPDIR"], str(self.fixture.output / "tmp"))
                self.assertEqual(cleaned["XILINX_VITIS"], str(self.fixture.vitis))
                self.assertEqual(cleaned["XILINX_VIVADO"], str(self.fixture.vivado))
                self.assertEqual(cleaned["XILINX_XRT"], str(self.fixture.xrt))
                self.assertEqual((cleaned["LANG"], cleaned["LC_ALL"], cleaned["TZ"]),
                                 ("C", "C", "UTC"))
                self.assertEqual(cleaned["PYTHONUTF8"], "1")
                self.assertEqual(cleaned["PYTHONDONTWRITEBYTECODE"], "1")
                self.assertNotIn("UNTRUSTED-", json.dumps(cleaned))
        self.assertEqual(inherited, original)

    def test_only_path_home_and_license_values_are_inherited(self):
        inherited = {"PATH": str(self.base / "host-bin"), "HOME": str(self.base / "home"),
                     "XILINXD_LICENSE_FILE": "PRIVATE-XILINX-LICENSE",
                     "LM_LICENSE_FILE": "PRIVATE-LM-LICENSE", "PRIVATE_TOKEN": "SECRET"}
        cleaned = baseline.clean_environment(self.fixture.manifest, self.paths(), environ=inherited)
        for key in ("PATH", "HOME", "XILINXD_LICENSE_FILE", "LM_LICENSE_FILE"):
            self.assertEqual(cleaned[key], inherited[key])
        self.assertNotIn("PRIVATE_TOKEN", cleaned)

    def test_missing_optional_environment_uses_default_path_without_tmpdir(self):
        cleaned = baseline.clean_environment(self.fixture.manifest,
                                             dict(self.paths(), output=None), environ={})
        self.assertEqual(cleaned["PATH"], os.defpath)
        for key in ("HOME", "XILINXD_LICENSE_FILE", "LM_LICENSE_FILE", "TMPDIR"):
            self.assertNotIn(key, cleaned)

    def test_environment_rejects_unbounded_or_coerced_job_counts(self):
        for jobs in (0, -1, 3, 100, True, False, 1.0, "1", None):
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                baseline.clean_environment(self.fixture.manifest, self.paths(), jobs, {})

    def test_make_commands_explicitly_select_vendor_target_and_frozen_configuration(self):
        for jobs in (1, 2):
            with self.subTest(jobs=jobs):
                commands = baseline.commands_for(self.paths(), jobs)
                self.assertEqual([item["id"] for item in commands], [
                    "configure", "kernel-library", "runtime-stub", "application",
                    "vendor-runtime", "smoke",
                ])
                for command in commands[1:-1]:
                    argv = command["argv"]
                    self.assertEqual(argv[0], "make")
                    self.assertEqual(argv.count("TARGET=hw_emu"), 1)
                    self.assertIn("CONFIGS=" + " ".join(FIXTURE_CONFIGS), argv)
                    self.assertIn("-j" + str(jobs), argv)
                    self.assertIn("JOBS=" + str(jobs), argv)
                    self.assertIn("IMPL_MAX_THREADS=" + str(jobs), argv)
                    self.assertNotIn("XRTSIM", " ".join(argv))
                self.assertIn("--xlen=64", commands[0]["argv"])
                self.assertEqual(commands[-1]["argv"],
                                 [str(self.fixture.build / "tests/regression/demo/demo"), "-n1"])

    def test_probe_and_plan_reports_do_not_disclose_inherited_secrets(self):
        inherited = {
            "PATH": str(self.base / "PRIVATE-HOST-PATH"),
            "HOME": str(self.base / "PRIVATE-HOME"),
            "XILINXD_LICENSE_FILE": "PRIVATE-LICENSE-ENDPOINT",
            "LM_LICENSE_FILE": "PRIVATE-SECOND-LICENSE", "API_TOKEN": "PRIVATE-API-TOKEN",
            "MAKEFLAGS": "PRIVATE-MAKE-INJECTION", "PYTHONPATH": "PRIVATE-PYTHON-INJECTION",
            "LD_PRELOAD": "PRIVATE-LOADER-INJECTION", "CONFIGS": "PRIVATE-CONFIG-INJECTION",
        }
        for mode in ("probe", "plan"):
            argv = [mode]
            if mode == "plan":
                argv += ["--source", str(self.fixture.source),
                         "--build-dir", str(self.fixture.build), "--tool-dir", str(self.fixture.tools),
                         "--manifest", str(self.fixture.manifest_path),
                         "--bundle-manifest", str(self.bundle), "--output", str(self.fixture.output),
                         "--min-free-gib", "0.001"]
            stream = io.StringIO()
            with self.subTest(mode=mode), mock.patch.dict(os.environ, inherited, clear=True), \
                    mock.patch.object(xrt_inventory, "collect_source",
                                      return_value=copy.deepcopy(self.fixture.source_record)), \
                    redirect_stdout(stream):
                code = baseline.main(argv)
            report = json.loads(stream.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(report["outcome"], "blocked")
            self.assertIs(report["phase_complete"], False)
            self.assertEqual(report["acceptance"], "not_evaluated")
            for value in inherited.values():
                self.assertNotIn(value, stream.getvalue())
            self.assertFalse(self.fixture.output.exists())
            self.assertEqual(list(self.fixture.build.iterdir()), [])


class PathBoundaryTests(BoundaryFixture):
    def test_plan_accepts_existing_empty_or_fresh_build_without_creating_output(self):
        for build in (self.fixture.build, self.base / "fresh-build"):
            with self.subTest(build=build):
                paths = baseline.resolve_paths(self.args(build_dir=build, output=None))
                self.assertEqual(paths["build"], build)
                self.assertIsNone(paths["output"])
                self.assertFalse(self.fixture.output.exists())
        self.assertFalse((self.base / "fresh-build").exists())

    def test_all_required_paths_must_be_supplied(self):
        for name in ("build_dir", "tool_dir", "manifest"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                baseline.resolve_paths(self.args(**{name: None}))
        with self.assertRaisesRegex(ValueError, "run requires --output"):
            baseline.resolve_paths(self.args(mode="run", output=None))

    def test_source_must_be_an_existing_directory(self):
        for source in (self.fixture.manifest_path, self.base / "missing-source"):
            with self.subTest(source=source), self.assertRaises((OSError, ValueError)):
                baseline.resolve_paths(self.args(source=source))

    def test_source_build_and_tools_reject_equal_and_nested_roots(self):
        roots = {"source": self.fixture.source, "build_dir": self.fixture.build,
                 "tool_dir": self.fixture.tools}
        for left, right in (("source", "build_dir"), ("source", "tool_dir"),
                            ("build_dir", "tool_dir")):
            for target, parent in ((left, right), (right, left)):
                for nested in (False, True):
                    path = roots[parent]
                    if nested:
                        path = path / (target + "-nested")
                        path.mkdir(exist_ok=True)
                    with self.subTest(target=target, parent=parent, nested=nested), \
                            self.assertRaisesRegex(ValueError, "roots must not overlap"):
                        baseline.resolve_paths(self.args(**{target: path}))

    def test_common_name_prefixes_are_not_path_overlap(self):
        source = self.fixture.source
        paths = baseline.resolve_paths(self.args(build_dir=source.with_name("source-build"),
                                                tool_dir=source.with_name("source-tools"),
                                                output=source.with_name("source-output")))
        self.assertEqual(paths["source"], source)

    def test_build_rejects_nonempty_directory_file_and_missing_parent(self):
        nonempty = self.base / "nonempty"
        write_file(nonempty / ".hidden-input", "do not overwrite")
        file_path = self.base / "build-file"
        write_file(file_path, "do not overwrite")
        for build in (nonempty, file_path, self.base / "missing-parent/build"):
            with self.subTest(build=build), self.assertRaisesRegex(ValueError, "build must be"):
                baseline.resolve_paths(self.args(build_dir=build))
        self.assertEqual(file_path.read_text(), "do not overwrite")
        self.assertEqual((nonempty / ".hidden-input").read_text(), "do not overwrite")

    def test_output_rejects_existing_directories_files_and_missing_parent(self):
        empty = self.base / "empty-output"
        empty.mkdir()
        nonempty = self.base / "nonempty-output"
        write_file(nonempty / "retained.log", "keep this")
        file_path = self.base / "output-file"
        write_file(file_path, "keep this too")
        for output in (empty, nonempty, file_path, self.base / "missing-parent/output"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "output must be fresh"):
                baseline.resolve_paths(self.args(output=output))
        self.assertEqual((nonempty / "retained.log").read_text(), "keep this")
        self.assertEqual(file_path.read_text(), "keep this too")

    def test_output_must_not_be_inside_source_build_or_tools(self):
        for root in (self.fixture.source, self.fixture.build, self.fixture.tools):
            with self.subTest(root=root), self.assertRaisesRegex(ValueError, "output must not overlap"):
                baseline.resolve_paths(self.args(output=root / "new-output"))
            self.assertFalse((root / "new-output").exists())

    def test_symlinks_are_rejected_at_each_root_and_input_file(self):
        values = {"source": self.fixture.source, "build_dir": self.fixture.build,
                  "tool_dir": self.fixture.tools, "manifest": self.fixture.manifest_path,
                  "bundle_manifest": self.bundle, "output": self.fixture.output}
        for key, target in values.items():
            link = self.base / (key + "-link")
            link.symlink_to(target, target_is_directory=key not in ("manifest", "bundle_manifest"))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "symlinks"):
                baseline.resolve_paths(self.args(**{key: link}))

    def test_parent_symlink_is_rejected_for_fresh_paths(self):
        link = self.base / "parent-link"
        link.symlink_to(self.fixture.base, target_is_directory=True)
        for key in ("build_dir", "output"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "symlinks"):
                baseline.resolve_paths(self.args(**{key: link / "fresh"}))

    def test_shell_sensitive_or_whitespace_paths_are_rejected(self):
        for name in ("space name", "tab\tname", "line\nname", "$(command)", "`command`",
                     "semicolon;name", "quote'name", "name&tail", "name|tail"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                baseline.resolve_paths(self.args(output=self.base / name))

    def test_build_and_output_cannot_overlap_frozen_files_or_vendor_roots(self):
        data = self.fixture.manifest
        protected = [Path(data["platform"]["file"]["path"]), self.fixture.receipt_path,
                     Path(data["qualification_review"]["path"]), self.fixture.manifest_path,
                     self.bundle]
        protected += [Path(record["path"]) for record in data["vendor"]["files"].values()]
        protected += [Path(record["path"]) for record in data["artifacts"].values()]
        protected += [self.fixture.vitis, self.fixture.vivado, self.fixture.xrt]
        original = self.paths()
        for protected_path in protected:
            for target in ("build", "output"):
                for location in (protected_path, protected_path.parent, protected_path / "generated"):
                    paths = dict(original, **{target: location})
                    with self.subTest(target=target, location=location), \
                            self.assertRaisesRegex(ValueError, "overlaps a frozen input"):
                        baseline._validate_outputs(paths, data)
        baseline._validate_outputs(original, data)


class BudgetBoundaryTests(unittest.TestCase):
    def args(self, **changes):
        values = dict(jobs=2, timeout_seconds=30, min_free_gib=1, max_log_mib=16, max_rss_gib=1)
        values.update(changes)
        return argparse.Namespace(**values)

    def test_one_and_two_jobs_and_exact_byte_budget_conversions(self):
        for jobs in (1, 2):
            with self.subTest(jobs=jobs):
                self.assertEqual(baseline._budget(self.args(
                    jobs=jobs, timeout_seconds=1.5, min_free_gib=0.5,
                    max_log_mib=0.5, max_rss_gib=0.25)), {
                        "jobs": jobs, "timeout_seconds": 1.5,
                        "min_free_bytes": 512 * 1024**2, "max_log_bytes": 512 * 1024,
                        "max_rss_bytes": 256 * 1024**2,
                    })

    def test_positive_fractional_timeout_is_supported(self):
        self.assertEqual(baseline._budget(self.args(timeout_seconds=0.5))["timeout_seconds"], 0.5)

    def test_job_count_rejects_out_of_range_and_type_coercions(self):
        for jobs in (0, -1, 3, 2**63, True, False, 1.0, "1", None):
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                baseline._budget(self.args(jobs=jobs))

    def test_budgets_reject_nonpositive_nonfinite_non_numeric_and_huge_values(self):
        for key in ("timeout_seconds", "min_free_gib", "max_log_mib", "max_rss_gib"):
            for value in (0, -1, float("nan"), float("inf"), -float("inf"),
                          True, False, "1", None, [], 10**400, 1e308):
                with self.subTest(key=key, value_type=type(value), value=str(value)[:40]), \
                        self.assertRaises(ValueError):
                    baseline._budget(self.args(**{key: value}))

    def test_byte_budgets_cannot_round_to_zero(self):
        for key, scale in (("min_free_gib", 1024**3), ("max_log_mib", 1024**2),
                           ("max_rss_gib", 1024**3)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                baseline._budget(self.args(**{key: 0.5 / scale}))
            self.assertEqual(baseline._budget(self.args(**{key: 1 / scale}))[
                {"min_free_gib": "min_free_bytes", "max_log_mib": "max_log_bytes",
                 "max_rss_gib": "max_rss_bytes"}[key]], 1)

    def test_selected_log_budget_cannot_exceed_reference_parser_limit(self):
        self.assertEqual(baseline._budget(self.args(max_log_mib=16))["max_log_bytes"], LOG_LIMIT)
        for value in (16 + 1 / 1024**2, 17, 32):
            with self.subTest(value=value), self.assertRaises(ValueError):
                baseline._budget(self.args(max_log_mib=value))

    def test_positive_parser_handles_finite_numbers_and_rejects_overflow(self):
        for text, expected in (("0.25", 0.25), ("1", 1), ("2e1", 20)):
            self.assertEqual(baseline._positive(text), expected)
        for value in ("0", "-1", "nan", "inf", "-inf", "1e9999", "text", None, 10**400):
            with self.subTest(value=str(value)[:40]), self.assertRaises(argparse.ArgumentTypeError):
                baseline._positive(value)

    def test_cli_rejects_invalid_jobs_and_nonfinite_resource_options(self):
        parser = baseline.argument_parser()
        for key, values in (("jobs", ("0", "3", "1.0")),
                            ("timeout-seconds", ("0", "nan", "inf", "1e9999")),
                            ("min-free-gib", ("0", "nan", "inf")),
                            ("max-log-mib", ("0", "nan", "inf")),
                            ("max-rss-gib", ("0", "nan", "inf"))):
            for value in values:
                with self.subTest(key=key, value=value), redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as error:
                    parser.parse_args(["plan", "--" + key + "=" + value])
                self.assertEqual(error.exception.code, 2)


class ReferenceBoundaryTests(BoundaryFixture):
    def test_complete_ordered_integer_reference_accepts_benign_vendor_noise(self):
        path = self.write_log(prefix="Vendor emulator initialization\n", suffix="Elapsed time: 1 ms\n")
        self.assertTrue(baseline.reference_passed(path))

    def test_every_reference_milestone_is_required(self):
        for index, marker in enumerate(REFERENCE_LINES):
            with self.subTest(marker=marker):
                lines = list(REFERENCE_LINES)
                lines.pop(index)
                self.assertFalse(baseline.reference_passed(self.write_log(lines)))

    def test_duplicate_milestones_and_two_complete_runs_are_rejected(self):
        for marker in REFERENCE_LINES:
            with self.subTest(marker=marker):
                self.assertFalse(baseline.reference_passed(self.write_log(suffix=marker + "\n")))
        self.assertFalse(baseline.reference_passed(self.write_log(REFERENCE_LINES * 2)))

    def test_each_adjacent_order_inversion_is_rejected(self):
        for index in range(len(REFERENCE_LINES) - 1):
            lines = list(REFERENCE_LINES)
            lines[index], lines[index + 1] = lines[index + 1], lines[index]
            with self.subTest(index=index):
                self.assertFalse(baseline.reference_passed(self.write_log(lines)))

    def test_markers_must_be_whole_exact_lines(self):
        for replacement in ("PASSED! extra", "prefix PASSED!", " PASSED!", "PASSED! ", "passed!"):
            with self.subTest(replacement=replacement):
                self.assertFalse(baseline.reference_passed(self.write_log(
                    REFERENCE_LINES[:-1] + (replacement,))))

    def test_float_other_point_count_or_other_buffer_size_is_rejected(self):
        for index, replacement in ((1, "data type: float"), (2, "number of points: 1"),
                                   (2, "number of points: 16.0"), (2, "number of points: 64"),
                                   (3, "buffer size: 256 bytes")):
            lines = list(REFERENCE_LINES)
            lines[index] = replacement
            with self.subTest(replacement=replacement):
                self.assertFalse(baseline.reference_passed(self.write_log(lines)))

    def test_contradictory_configuration_lines_cannot_accompany_success(self):
        for contradictory in ("data type: float", "number of points: 64", "buffer size: 256 bytes"):
            for position in ("prefix", "suffix"):
                with self.subTest(contradictory=contradictory, position=position):
                    self.assertFalse(baseline.reference_passed(self.write_log(
                        **{position: contradictory + "\n"})))

    def test_failure_diagnostics_override_complete_success_markers(self):
        for failure in ("FAILED", "failure", "ERROR", "error: device launch", "Found 1 errors!",
                        "Found 16 errors!", "XRT exception: device unavailable"):
            for position in ("prefix", "suffix"):
                with self.subTest(failure=failure, position=position):
                    self.assertFalse(baseline.reference_passed(self.write_log(
                        **{position: failure + "\n"})))

    def test_zero_error_count_does_not_invent_a_failure(self):
        self.assertTrue(baseline.reference_passed(self.write_log(suffix="Found 0 errors!\n")))

    def test_log_at_size_limit_is_read_completely_and_one_extra_byte_is_rejected(self):
        path = self.base / "bounded.log"
        markers = ("\n" + "\n".join(REFERENCE_LINES) + "\n").encode()
        with path.open("wb") as stream:
            stream.write(b"x" * (LOG_LIMIT - len(markers)))
            stream.write(markers)
        self.assertEqual(path.stat().st_size, LOG_LIMIT)
        self.assertTrue(baseline.reference_passed(path))
        with path.open("ab") as stream:
            stream.write(b"x")
        with self.assertRaises(ValueError):
            baseline.reference_passed(path)

    def test_missing_nonregular_and_symlink_logs_are_rejected(self):
        original = self.write_log()
        link = self.base / "log-link"
        link.symlink_to(original)
        for path in (self.base / "missing", self.base, link):
            with self.subTest(path=path), self.assertRaises((OSError, ValueError)):
                baseline.reference_passed(path)


if __name__ == "__main__":
    unittest.main()
