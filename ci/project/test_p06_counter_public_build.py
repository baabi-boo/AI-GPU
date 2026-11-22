# SPDX-License-Identifier: Apache-2.0
"""Host-only build-record tests; dry runs and synthetic objects are not native evidence."""

import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile
import unittest
from unittest import mock

import p06_checked_execute as checked
import p06_counter_public_build as public
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]


def configured_fixture():
    compiler = shutil.which("g++")
    with tempfile.TemporaryDirectory(prefix="counter-public-records-") as directory:
        temporary = Path(directory)
        build, tools = temporary / "checked", temporary / "tools"
        build.mkdir()
        tools.mkdir()
        env = dict(os.environ, CCACHE_DISABLE="1", OBJCACHE="", MAKEFLAGS="-j2", THREADS="1")
        run = lambda argv, cwd=build: run_host_command(argv, cwd=cwd, env=env, timeout=90)
        run([str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
             "--osversion=ubuntu/focal", "--tooldir=" + str(tools)])
        unit = build / "sim/simx"
        common = [shutil.which("make"), "--no-print-directory", "-j2", "THREADS=1", "PERF=1",
                  "PROFILE=p02-tfr", "CONFIGS=-DSIMX_CHECKED_COUNTERS=1", "CXX=" + compiler]
        binary = unit / "checked_counters_test"
        first = run([*common, "-n", "-f", "checked_counters.mk", str(binary)], unit)
        fragment = "../../tests/unittest/checked_counters/public.mk"
        run([*common, "-f", fragment, str(build / checked.STAMP),
             *(str(build / name) for name in public.STAMPS)], unit)
        model_words = checked.compile_flags((build / checked.STAMP).read_text(), checked=True,
                                             source=ROOT, build=build)
        stamps = {kind: (build / name).read_text() for kind, name in zip(public.KINDS, public.STAMPS)}
        first_commands = "\n".join(line for line in first.splitlines() if line.startswith(compiler + " "))
        files = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*") if path.is_file()}
        contents = {name: (ROOT / name).read_bytes() for name in checked.DIAGNOSTIC_CONTENTS}
        model = checked.parse_build_records(first_commands, model_words, source=ROOT, build=build,
            binary=binary, compiler=compiler, source_files=files, source_contents=contents,
            generated_contents={checked.GENERATED_TCU: contents[checked.TCU_ORIGINAL] + b"\n" + contents[checked.TCU_FOOTER]})
        paths = model.pop("object_paths")
        # These identities exercise retained-data validation without claiming compilation.
        model["object_identities"] = [{"path": path, "resolved_path": path, "sha256": "a" * 64,
                                       "size_bytes": 1} for path in paths]
        reused = [path for path in paths if not path.endswith("/tests/checked_counters_test.o")]
        second = run([*common, "-n", "-f", fragment,
                      *(option for path in reused for option in ("-o", path)), "checked-public"], unit)
        commands = "\n".join(line for line in second.replace("\\\n", " ").splitlines()
                             if line.startswith(compiler + " ")) + "\n"
        return {"text": commands, "raw_text": second, "model_stamp_words": model_words, "stamps": stamps,
                "source": ROOT, "build": build, "compiler": compiler, "source_files": files,
                "model_records": model}


@unittest.skipUnless(shutil.which("g++") and shutil.which("make"), "host compiler and Make are required")
class PublicBuildRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = configured_fixture()

    def setUp(self):
        self.data = copy.deepcopy(self.fixture)

    def parse(self, data=None):
        selected = dict(self.data if data is None else data)
        selected.pop("raw_text")
        return public.parse_build_records(**selected)

    def reject(self):
        with self.assertRaises(ValueError):
            self.parse()

    def alter_command(self, predicate, transform):
        lines = self.data["text"].splitlines()
        index = next(index for index, line in enumerate(lines) if predicate(line))
        lines[index] = transform(lines[index])
        self.data["text"] = "\n".join(lines) + "\n"

    def test_actual_configured_make_records(self):
        result = self.parse()
        self.assertEqual(result["translation_units"], 19)
        self.assertEqual(result["link_count"], 4)
        self.assertEqual(len(result["object_paths"]), 19)
        self.assertEqual(len(result["reused_model_object_identities"]), 44)
        self.assertEqual(len(result["wrapped_processor_symbols"]), 5)
        self.assertEqual(len(result["compile_records"]), 19)
        self.assertFalse(self.data["build"].exists())

    def test_actual_multiline_make_records(self):
        self.data["text"] = self.data["raw_text"]
        self.assertEqual(self.parse()["link_count"], 4)

    def test_pure_parser_never_reads_producer_paths(self):
        with mock.patch.object(Path, "resolve", side_effect=AssertionError("path resolution")), \
             mock.patch.object(Path, "read_bytes", side_effect=AssertionError("file read")), \
             mock.patch.object(Path, "read_text", side_effect=AssertionError("file read")), \
             mock.patch.object(checked.native, "file_identity", side_effect=AssertionError("object hashing")):
            self.assertEqual(self.parse()["translation_units"], 19)

    def test_requires_checked_model_stamp(self):
        self.data["model_stamp_words"].remove("-DSIMX_CHECKED_COUNTERS=1")
        self.reject()

    def test_rejects_unknown_model_hardware_macro(self):
        self.data["model_stamp_words"].append("-DVX_CFG_NEW_COUNTER_SHORTCUT=1")
        self.reject()

    def test_rejects_unknown_macro_even_when_every_runtime_record_changes(self):
        extra = " -DVX_CFG_NEW_COUNTER_SHORTCUT=1"
        for kind in public.KINDS:
            self.data["stamps"][kind] = self.data["stamps"][kind].rstrip() + extra + "\n"
        self.data["text"] = self.data["text"].replace(" -c ", extra + " -c ")
        self.reject()

    def test_rejects_altered_derived_macro(self):
        for kind in public.KINDS:
            self.data["stamps"][kind] = self.data["stamps"][kind].replace("-DVX_CFG_LMEM_SIZE=16384", "-DVX_CFG_LMEM_SIZE=32768")
        self.reject()

    def test_rejects_repeated_guard(self):
        self.data["stamps"]["runtime"] = self.data["stamps"]["runtime"].replace(
            "-DSIMX_CHECKED_COUNTERS=1", "-DSIMX_CHECKED_COUNTERS=1 -DSIMX_CHECKED_COUNTERS=1")
        self.reject()

    def test_rejects_macro_order_change(self):
        self.data["stamps"]["runtime"] = self.data["stamps"]["runtime"].replace(
            "-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64", "-DVX_CFG_XLEN_64 -DVX_CFG_XLEN=64", 1)
        self.reject()

    def test_rejects_changed_include_order(self):
        source = str(self.data["source"])
        self.data["stamps"]["runtime"] = self.data["stamps"]["runtime"].replace(
            "-I" + source + "/sw/runtime/include -I" + source + "/sw/kernel/include",
            "-I" + source + "/sw/kernel/include -I" + source + "/sw/runtime/include")
        self.reject()

    def test_rejects_optimization_or_access_override(self):
        for flag in ("-O0", "-fno-access-control", "-Wno-error"):
            with self.subTest(flag=flag):
                self.data = copy.deepcopy(self.fixture)
                self.alter_command(lambda line: " -c " in line, lambda line: line.replace(" -c ", " " + flag + " -c "))
                self.reject()

    def test_rejects_mixed_guard_translation_unit(self):
        self.alter_command(lambda line: " -c " in line and "/obj/runtime/" in line,
                           lambda line: line.replace("-DSIMX_CHECKED_COUNTERS=1", ""))
        self.reject()

    def test_rejects_wrong_source_for_object(self):
        self.data["text"] = self.data["text"].replace("/sw/runtime/common/queue.cpp", "/sw/runtime/common/event.cpp")
        self.reject()

    def test_rejects_source_path_alias(self):
        self.data["text"] = self.data["text"].replace("/sw/runtime/common/queue.cpp", "/sw/runtime/common/./queue.cpp")
        self.reject()

    def test_rejects_missing_new_compile(self):
        self.alter_command(lambda line: " -c " in line, lambda _: "")
        self.reject()

    def test_rejects_repeated_new_compile(self):
        self.alter_command(lambda line: " -c " in line, lambda line: line + "\n" + line)
        self.reject()

    def test_rejects_unrecognized_compiler(self):
        self.alter_command(lambda line: " -c " in line, lambda line: "/unexpected/compiler" + line[len(self.data["compiler"]):])
        self.reject()

    def test_short_commands_fail_as_contract_errors(self):
        for suffix in (" -o", " -c -o /missing/object.o"):
            with self.subTest(suffix=suffix):
                self.data["text"] = self.data["compiler"] + suffix + "\n"
                self.reject()

    def test_rejects_omitted_model_object(self):
        item = self.data["model_records"]["object_identities"][0]["path"]
        self.alter_command(lambda line: " -c " not in line and "-soname,libchecked-simx.so" in line,
                           lambda line: line.replace(" " + item + " ", " "))
        self.reject()

    def test_rejects_model_link_replaced_with_boundary_main(self):
        item = self.data["model_records"]["object_identities"][0]["path"]
        replacement = str(self.data["build"] / "sim/simx/obj/tests/checked_counters_test.o")
        self.alter_command(lambda line: "-soname,libchecked-simx.so" in line, lambda line: line.replace(item, replacement))
        self.reject()

    def test_rejects_runtime_object_omission(self):
        self.alter_command(lambda line: "-soname,libvortex.so" in line,
                           lambda line: rejoin_without(line, "/obj/runtime/common/perf.o"))
        self.reject()

    def test_rejects_each_missing_wrap(self):
        for symbol in public.WRAPS:
            with self.subTest(symbol=symbol):
                self.data = copy.deepcopy(self.fixture)
                self.data["text"] = self.data["text"].replace("-Wl,--wrap=" + symbol, "")
                self.reject()

    def test_rejects_wrap_at_final_executable_only(self):
        token = "-Wl,--wrap=" + public.WRAPS[0]
        self.data["text"] = self.data["text"].replace(token, "")
        self.alter_command(lambda line: line.endswith("/checked_public_test"),
                           lambda line: line.replace(" -o ", " " + token + " -o "))
        self.reject()

    def test_rejects_foreign_library(self):
        self.data["text"] = self.data["text"].replace("-lchecked-simx", "-lchecked-simx -lfake-processor")
        self.reject()

    def test_rejects_original_backend_model_library(self):
        self.data["text"] = self.data["text"].replace("-lchecked-simx", "-lsimx")
        self.reject()

    def test_rejects_source_snapshot_omission(self):
        self.data["source_files"].remove("sw/runtime/common/perf.cpp")
        self.reject()

    def test_source_inventory_type_fails_as_contract_error(self):
        self.data["source_files"] = None
        self.reject()

    def test_rejects_missing_header_snapshot(self):
        self.data["source_files"].remove("tests/regression/ai_bench_common/counters.h")
        self.reject()

    def test_rejects_prior_model_counts_and_provenance(self):
        for field, replacement in (("translation_units", True), ("link_count", 2),
                                    ("included_production_sources", {}), ("generated_production_sources", {})):
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.fixture)
                self.data["model_records"][field] = replacement
                self.reject()

    def test_rejects_prior_object_identity_mutations(self):
        for field, value in (("size_bytes", True), ("size_bytes", 0), ("sha256", "not-a-digest"),
                             ("resolved_path", "/somewhere/else.o")):
            with self.subTest(field=field, value=value):
                self.data = copy.deepcopy(self.fixture)
                self.data["model_records"]["object_identities"][0][field] = value
                self.reject()

    def test_rejects_duplicate_prior_object(self):
        objects = self.data["model_records"]["object_identities"]
        objects[0] = dict(objects[1])
        self.reject()

    def test_rejects_foreign_link_output(self):
        self.data["text"] = self.data["text"].replace(" -o " + str(self.data["build"] / public.ARTIFACTS[3]),
                                                     " -o /foreign/checked_public_test")
        self.reject()

    def test_rejects_shell_expansion_and_unquoted_origin(self):
        for target in ("-Wl,-rpath,$ORIGIN", "-Wl,-rpath,'${ORIGIN}'", "-Wl,-rpath,'$ORIGIN';true"):
            with self.subTest(target=target):
                self.data = copy.deepcopy(self.fixture)
                self.data["text"] = self.data["text"].replace("-Wl,-rpath,'$ORIGIN'", target, 1)
                self.reject()

    def test_rejects_control_bytes_and_unbounded_log(self):
        for text in (self.fixture["text"] + "\r", " " * (records_limit() + 1)):
            with self.subTest(size=len(text)):
                self.data["text"] = text
                self.reject()

    def test_live_identity_hashing_and_drift(self):
        with tempfile.TemporaryDirectory(prefix="public-object-fixture-") as directory:
            build = Path(directory) / "checked"
            data = relocate_build(self.fixture, build)
            parsed = self.parse(data)
            all_paths = [item["path"] for item in data["model_records"]["object_identities"]] + parsed["object_paths"]
            for index, path in enumerate(all_paths):
                destination = Path(path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"synthetic host parser object " + str(index).encode())
            data["model_records"]["object_identities"] = [checked.native.file_identity(item["path"])
                for item in data["model_records"]["object_identities"]]
            arguments = dict(data)
            arguments.pop("raw_text")
            result = public.validate_build(**arguments)
            self.assertEqual(len(result["object_identities"]), 19)
            self.assertNotIn("object_paths", result)
            Path(result["reused_model_object_identities"][0]["path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "reused model object changed"):
                public.validate_build(**arguments)


def records_limit():
    return 1024 * 1024


def rejoin_without(line, suffix):
    token = next(word for word in shlex.split(line) if word.endswith(suffix))
    return line.replace(" " + token + " ", " ")


def relocate_build(fixture, build):
    old = str(fixture["build"])
    data = {key: value for key, value in fixture.items() if key not in ("source_files", "source", "build")}
    data = json.loads(json.dumps(data).replace(old, str(build)))
    data.update(source_files=set(fixture["source_files"]), source=fixture["source"], build=build)
    return data


if __name__ == "__main__":
    unittest.main()
