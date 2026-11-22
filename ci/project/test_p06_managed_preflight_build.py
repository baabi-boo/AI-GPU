# SPDX-License-Identifier: Apache-2.0
"""Independent generated-stamp and Make-dry-run tests; no native model executes."""

import copy
import hashlib
from pathlib import Path
import re
import shlex
import tempfile
import unittest

import p06_managed_preflight_build as records
from p06_managed_preflight_build_fixture import generate, ROOT, ROLES


def mutate_role(stamps, outer, inner, change):
    result = list(stamps)
    lines = result[outer].splitlines()
    lines[inner] = change(lines[inner])
    result[outer] = "\n".join(lines) + "\n"
    return tuple(result)


class ManagedPreflightBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-managed-records-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.generated = generate(Path(cls.temporary.name))

    def setUp(self):
        self.data = copy.deepcopy(self.generated["formats"]["fp16"])

    def stamps(self, data=None):
        data = data or self.data
        return records.validate_records(*data["stamps"], fmt=data["fmt"], source=data["source"],
                                        build=data["build"], jobs=2)

    def commands(self, data=None):
        data = data or self.data
        return records.validate_build_commands(data["text"], *data["stamps"][:2], data["backend_linker"],
            **{key: data[key] for key in ("source", "build", "compiler", "make", "fmt", "source_files")})

    def reject_stamps(self):
        with self.assertRaises(ValueError):
            self.stamps()

    def reject_commands(self):
        with self.assertRaises(ValueError):
            self.commands()

    def change_command(self, predicate, change):
        lines = self.data["text"].splitlines()
        index = next(index for index, line in enumerate(lines) if predicate(line))
        lines[index] = change(lines[index])
        self.data["text"] = "\n".join(lines) + "\n"

    def test_real_generated_records_both_formats(self):
        for fmt, data in self.generated["formats"].items():
            with self.subTest(fmt=fmt):
                parsed = self.stamps(data)
                self.assertEqual([row["role"] for row in parsed], [role for _, _, role in ROLES])
                for row, (outer, inner, _) in zip(parsed, ROLES):
                    original = data["stamps"][outer].splitlines()[inner]
                    self.assertEqual(row["original_record"], original)
                    self.assertEqual(row["sha256"], hashlib.sha256(original.encode()).hexdigest())
                    self.assertIn("-DSIMX_CHECKED_COUNTERS=1", row["macro_flags"])
                    self.assertEqual(row["configuration"]["SIMX_CHECKED_COUNTERS"], "1")
                self.assertFalse(self.generated["guard_marker"].exists())

    def test_original_effective_headers_both_formats(self):
        for fmt, data in self.generated["formats"].items():
            for role, text in data["headers"].items():
                with self.subTest(fmt=fmt, role=role):
                    self.assertEqual(records.validate_effective_header(text, data["expected_headers"][role],
                                                                      role=role), data["expected_headers"][role])

    def test_actual_make_dry_run_contains_exact_production_route(self):
        for fmt, data in self.generated["formats"].items():
            with self.subTest(fmt=fmt):
                parsed = self.commands(data)
                self.assertEqual(parsed["model_translation_units"], 43)
                self.assertEqual(parsed["backend_translation_units"], 4)
                self.assertEqual(parsed["link_count"], 2)
                self.assertFalse(parsed["qualified"])
                self.assertFalse(parsed["dependency_compilation_provenance_verified"])
                self.assertFalse(parsed["diagnostic_object_substitutions"])

    def test_guards_reject_missing_disabled_duplicate_and_worker_override(self):
        for outer, inner, role in ROLES:
            for replacement in ("", "-DSIMX_CHECKED_COUNTERS=0", "-DSIMX_CHECKED_COUNTERS=2",
                                "-DSIMX_CHECKED_COUNTERS=1 -DSIMX_CHECKED_COUNTERS=1",
                                "-DSIMX_CHECKED_COUNTERS=1 -DSIMX_MT=2",
                                "-DSIMX_CHECKED_COUNTERS=1 -DSIMX_FUNCTIONAL=1",
                                "-DSIMX_CHECKED_COUNTERS=1 -DSIMX_TEST_LIMIT=7",
                                "-DSIMX_CHECKED_COUNTERS=1 -USIMX_CHECKED_COUNTERS"):
                with self.subTest(role=role, replacement=replacement):
                    self.data = copy.deepcopy(self.generated["formats"]["fp16"])
                    self.data["stamps"] = mutate_role(self.data["stamps"], outer, inner,
                        lambda text: text.replace("-DSIMX_CHECKED_COUNTERS=1", replacement))
                    self.reject_stamps()

    def test_forwarded_guard_is_not_a_direct_guard(self):
        for outer, inner, role in ROLES:
            for forwarded in ("-Wp,-DSIMX_CHECKED_COUNTERS=1", "-Xpreprocessor -DSIMX_CHECKED_COUNTERS=1"):
                with self.subTest(role=role, forwarded=forwarded):
                    self.data["stamps"] = mutate_role(self.generated["formats"]["fp16"]["stamps"], outer, inner,
                        lambda text: text.replace("-DSIMX_CHECKED_COUNTERS=1", forwarded))
                    self.reject_stamps()

    def test_host_include_is_required_and_ordered(self):
        expected = "-I" + str(ROOT / "sw/runtime/common")
        for change in (lambda text: text.replace(expected, ""),
                       lambda text: text.replace(expected, expected + " " + expected),
                       lambda text: expected + " " + text.replace(expected, ""),
                       lambda text: text.replace(expected, "-I/tmp/foreign-runtime")):
            self.data["stamps"] = mutate_role(self.generated["formats"]["fp16"]["stamps"], 2, 1, change)
            self.reject_stamps()

    def test_host_link_rejects_missing_extra_and_reordered_dependencies(self):
        for change in (lambda line: line.replace("-Wl,--wrap=vx_device_mpm_query", ""),
                       lambda line: line.replace(" -lvortex-simx", ""),
                       lambda line: line + " -ldl",
                       lambda line: line.replace("-lvortex -lvortex-simx", "-lvortex-simx -lvortex"),
                       lambda line: line + " /tmp/access_tcu.o"):
            self.data["stamps"] = mutate_role(self.generated["formats"]["fp16"]["stamps"], 2, 2, change)
            self.reject_stamps()

    def test_stamp_inventory_cannot_merge_or_omit_roles(self):
        baseline = self.data["stamps"]
        for changed in ((baseline[0] + baseline[1], baseline[1], baseline[2]),
                        (baseline[0], baseline[1], "\n".join(baseline[2].splitlines()[:2])),
                        ("", baseline[1], baseline[2])):
            self.data["stamps"] = changed
            self.reject_stamps()

    def test_wrong_format_and_build_budget_reject(self):
        for fmt, jobs in (("fp32", 2), ("bf16", 2), ("fp16", 0), ("fp16", 3), ("fp16", True)):
            with self.subTest(fmt=fmt, jobs=jobs), self.assertRaises(ValueError):
                records.validate_records(*self.data["stamps"], fmt=fmt, source=ROOT,
                                         build=self.data["build"], jobs=jobs)

    def test_paths_are_absolute_canonical_and_disjoint(self):
        for source, build in ((ROOT, ROOT), (ROOT, ROOT / "build"),
                              ("relative", self.data["build"]),
                              (str(ROOT) + "/../foreign", self.data["build"]),
                              (ROOT, str(self.data["build"]) + "/../other")):
            with self.subTest(source=source, build=build), self.assertRaises(ValueError):
                records.validate_records(*self.data["stamps"], fmt="fp16", source=source, build=build, jobs=2)

    def test_header_requires_one_direct_checked_definition(self):
        original = self.data["headers"]["backend_cpp"]
        for replacement in ("", "#define SIMX_CHECKED_COUNTERS 0", "#define SIMX_CHECKED_COUNTERS (1)",
                            "#define SIMX_CHECKED_COUNTERS 1\n#define SIMX_CHECKED_COUNTERS 1",
                            "#define SIMX_CHECKED_COUNTERS(x) 1"):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                records.validate_effective_header(original.replace("#define SIMX_CHECKED_COUNTERS 1", replacement),
                    self.data["expected_headers"]["backend_cpp"], role="backend_cpp")

    def test_header_rejects_unapproved_simulator_or_profile_changes(self):
        original = self.data["headers"]["backend_cpp"]
        for suffix in ("#define SIMX_MT 2", "#define SIMX_FUNCTIONAL 1", "#define SIMX_TINY_LIMIT 3",
                       "#define VX_CFG_NUM_CORES 2"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                records.validate_effective_header(original + "\n" + suffix + "\n",
                    self.data["expected_headers"]["backend_cpp"], role="backend_cpp")

    def test_header_expected_guard_cannot_be_omitted_or_disabled(self):
        for value in (None, "0", 1):
            expected = dict(self.data["expected_headers"]["host"])
            if value is None:
                del expected["SIMX_CHECKED_COUNTERS"]
            else:
                expected["SIMX_CHECKED_COUNTERS"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                records.validate_effective_header(self.data["headers"]["host"], expected, role="host")

    def test_backend_stamp_preserves_literal_origin_under_injected_environment(self):
        original = self.data["backend_linker"]
        self.assertIn("-Wl,-rpath,'$ORIGIN'", original)
        self.assertNotIn("must-not-expand", original)
        parsed = records.validate_backend_linker(original, build=self.data["build"])
        self.assertIn("-Wl,-rpath,$ORIGIN", parsed["arguments"])
        for changed in (original.replace("'$ORIGIN'", "$ORIGIN"),
                        original.replace("'$ORIGIN'", "/tmp/foreign"),
                        original + original):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                records.validate_backend_linker(changed, build=self.data["build"])

    def test_missing_compile_is_not_a_fresh_build(self):
        lines = self.data["text"].splitlines()
        self.data["text"] = "\n".join(lines[1:]) + "\n"
        self.reject_commands()

    def test_duplicate_compile_rejects(self):
        self.data["text"] += self.data["text"].splitlines()[0] + "\n"
        self.reject_commands()

    def test_foreign_diagnostic_source_substitution_rejects(self):
        self.change_command(lambda line: " -c " in line and "/sim/simx/socket.cpp" in line,
            lambda line: line.replace(str(ROOT / "sim/simx/socket.cpp"),
                                      str(ROOT / "tests/unittest/checked_counters/access_socket.cpp")))
        self.reject_commands()

    def test_changed_object_mapping_rejects(self):
        self.change_command(lambda line: " -c " in line,
                            lambda line: line.rsplit(" -o ", 1)[0] + " -o /tmp/foreign.o")
        self.reject_commands()

    def test_changed_dependency_output_rejects(self):
        self.change_command(lambda line: " -c " in line,
                            lambda line: re.sub(r"(?<=-MF )\S+", "/tmp/foreign.d", line))
        self.reject_commands()

    def test_changed_compile_guard_rejects(self):
        self.change_command(lambda line: " -c " in line,
                            lambda line: line.replace("-DSIMX_CHECKED_COUNTERS=1", "-DSIMX_CHECKED_COUNTERS=0"))
        self.reject_commands()

    def test_foreign_compiler_even_with_same_sources_rejects(self):
        self.change_command(lambda line: " -c " in line,
                            lambda line: "/tmp/other-compiler" + line[len(self.data["compiler"]):])
        self.reject_commands()

    def test_missing_model_object_in_link_rejects(self):
        def change(line):
            tokens = shlex.split(line)
            tokens.remove(next(word for word in tokens if word.endswith(".o")))
            return " ".join(tokens)
        self.change_command(lambda line: line.endswith("/libsimx.so"), change)
        self.reject_commands()

    def test_extra_diagnostic_object_in_model_link_rejects(self):
        self.change_command(lambda line: line.endswith("/libsimx.so"),
                            lambda line: line.replace(" -shared ", " /tmp/access_tcu.o -shared "))
        self.reject_commands()

    def test_duplicate_object_in_model_link_rejects(self):
        def change(line):
            item = next(word for word in shlex.split(line) if word.endswith(".o"))
            return line.replace(" -shared ", " " + item + " -shared ")
        self.change_command(lambda line: line.endswith("/libsimx.so"), change)
        self.reject_commands()

    def test_missing_or_duplicate_backend_link_rejects(self):
        baseline = self.data["text"]
        line = next(line for line in baseline.splitlines() if line.endswith("/libvortex-simx.so"))
        for changed in (baseline.replace(line + "\n", ""), baseline + line + "\n"):
            self.data["text"] = changed
            self.reject_commands()

    def test_missing_or_duplicate_model_link_rejects(self):
        baseline = self.data["text"]
        line = next(line for line in baseline.splitlines() if line.endswith("/libsimx.so"))
        for changed in (baseline.replace(line + "\n", ""), baseline + line + "\n"):
            self.data["text"] = changed
            self.reject_commands()

    def test_missing_or_foreign_backend_hook_rejects(self):
        original = self.data["text"]
        path = str(ROOT / "tests/regression/ai_counter_preflight/hooks.cpp")
        for replacement in ("", str(ROOT / "tests/unittest/checked_counters/public_hooks.cpp")):
            self.data["text"] = original.replace(path, replacement)
            self.reject_commands()

    def test_backend_without_required_wrap_rejects(self):
        self.data["text"] = self.data["text"].replace("-Wl,--wrap=_ZN6vortex9ProcessorD1Ev", "")
        self.reject_commands()

    def test_backend_unquoted_origin_rejects(self):
        self.data["text"] = self.data["text"].replace("'$ORIGIN'", "$ORIGIN")
        self.reject_commands()

    def test_origin_quote_exception_cannot_admit_shell_injection(self):
        for inserted in ("-Wl,-rpath,'$ORIGIN';touch /tmp/foreign",
                         "-Wl,-rpath,'$ORIGIN'$(id)",
                         "-Wl,-rpath,'$ORIGIN'`id`",
                         "-Wl,-rpath,'$ORIGIN'|true"):
            with self.subTest(inserted=inserted):
                self.data = copy.deepcopy(self.generated["formats"]["fp16"])
                self.data["text"] = self.data["text"].replace("-Wl,-rpath,'$ORIGIN'", inserted)
                self.reject_commands()
                with self.assertRaises(ValueError):
                    records.validate_backend_linker(self.data["backend_linker"].replace(
                        "-Wl,-rpath,'$ORIGIN'", inserted), build=self.data["build"])

    def test_model_dependency_substitution_rejects(self):
        self.data["text"] = self.data["text"].replace("-lramulator-vortex", "-lforeign")
        self.reject_commands()

    def test_extra_unrecognized_source_command_rejects(self):
        self.data["text"] += "foreign-tool /tmp/seed.cpp /tmp/seed.o\n"
        self.reject_commands()

    def test_critical_source_inventory_omission_rejects(self):
        for omitted in ("sim/common/perf_counter.h", "tests/regression/ai_warm_workspace/main.cpp",
                        "tests/regression/ai_counter_preflight/hooks.h", "sim/simx/socket.cpp"):
            with self.subTest(omitted=omitted):
                self.data["source_files"] = self.generated["formats"]["fp16"]["source_files"] - {omitted}
                self.reject_commands()

    def test_build_records_do_not_open_recorded_producer_paths(self):
        from unittest import mock
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("producer file opened")), \
             mock.patch.object(Path, "read_text", side_effect=AssertionError("producer file opened")):
            self.commands()


if __name__ == "__main__":
    unittest.main()
