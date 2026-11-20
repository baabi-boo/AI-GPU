# SPDX-License-Identifier: Apache-2.0
"""Compile and independently decode every adapted tiny-model input and reference."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p04_fixture_adapter as adapter
import p04_model_contract as contract
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]


class TinyMlpFixtureAdapterTests(unittest.TestCase):
    def copied_source(self):
        temporary = tempfile.TemporaryDirectory(prefix="p04-adapter-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "source"
        root.mkdir()
        for name in (*contract.ARTIFACT_PATHS, contract.MANIFEST_PATH, adapter.HEADER_PATH):
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        return root

    def snapshot(self, root):
        return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in root.rglob("*") if path.is_file()}

    def cli(self, root, *arguments):
        return subprocess.run(
            [sys.executable, str(ROOT / "ci/project/p04_fixture_adapter.py"),
             "--root", str(root), *arguments],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True, text=True, timeout=20,
        )

    def test_checked_in_header_is_deterministic_and_check_is_read_only(self):
        root = self.copied_source()
        before = self.snapshot(root)
        self.assertEqual(adapter.render_header(root), adapter.render_header(root))
        self.assertEqual(adapter.render_header(root).encode(), (root / adapter.HEADER_PATH).read_bytes())
        result = self.cli(root, "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no native execution", result.stdout)
        self.assertEqual(self.snapshot(root), before)

    def test_loaded_inputs_and_references_are_independent_owned_copies(self):
        fixture = json.loads((ROOT / contract.FIXTURE_PATH).read_text())
        cases = adapter.load_cases()
        self.assertEqual(len(cases), 10)
        for case, original in zip(cases, fixture["cases"]):
            self.assertEqual({key: case[key] for key in original}, original)
            weights = fixture["weights"]["formats"][case["format"]]
            self.assertEqual(case["w1_words"], weights["w1_words"])
            self.assertEqual(case["w2_words"], weights["w2_words"])
        original = deepcopy(cases)
        cases[0]["input_words"][0] = "ffffffff"
        cases[0]["hidden_words"][0] = "ffffffff"
        cases[0]["w1_words"][0] = "ffffffff"
        self.assertEqual(cases[1:], original[1:])
        self.assertEqual(cases[0]["bridge_words"], original[0]["bridge_words"])
        self.assertEqual(adapter.load_cases(), original)

    def test_changed_reference_is_rejected_even_with_updated_fixture_hash(self):
        root = self.copied_source()
        path = root / contract.FIXTURE_PATH
        fixture = json.loads(path.read_text())
        fixture["cases"][0]["hidden_words"][0] = "c0000000"
        path.write_text(json.dumps(fixture, indent=2) + "\n")
        manifest_path = root / contract.MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text())
        for item in manifest["artifacts"]:
            if item["path"] == contract.FIXTURE_PATH:
                item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        before = self.snapshot(root)
        with self.assertRaises(contract.ContractError):
            adapter.load_cases(root)
        with self.assertRaises(contract.ContractError):
            adapter.render_header(root)
        self.assertEqual(self.snapshot(root), before)

    def test_fixture_replaced_after_validation_is_rejected(self):
        root = self.copied_source()
        validate = contract.validate

        def replace_after_validation(source):
            result = validate(source)
            path = source / contract.FIXTURE_PATH
            path.write_bytes(path.read_bytes() + b" ")
            return result

        with mock.patch.object(contract, "validate", side_effect=replace_after_validation):
            with self.assertRaisesRegex(contract.ContractError, "changed after contract validation"):
                adapter.load_cases(root)

    def test_check_rejects_missing_or_corrupted_header_without_repair(self):
        root = self.copied_source()
        path = root / adapter.HEADER_PATH
        original = path.read_bytes()
        for replacement in (None, original.replace(b"0xbf800000u", b"0xc0000000u", 1)):
            with self.subTest(missing=replacement is None):
                if replacement is None:
                    path.unlink()
                else:
                    path.write_bytes(replacement)
                before = self.snapshot(root)
                result = self.cli(root, "--check")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.snapshot(root), before)

    def test_explicit_regeneration_preserves_all_frozen_inputs(self):
        root = self.copied_source()
        path = root / adapter.HEADER_PATH
        path.write_text("invalid header\n")
        before = self.snapshot(root)
        result = self.cli(root, "--write-header")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.snapshot(root)
        self.assertEqual({key: value for key, value in after.items() if key != adapter.HEADER_PATH},
                         {key: value for key, value in before.items() if key != adapter.HEADER_PATH})
        self.assertEqual(path.read_bytes(), (ROOT / adapter.HEADER_PATH).read_bytes())

    def test_compiled_header_round_trips_every_original_word(self):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "fixture adapter tests require a C++17 compiler")
        temporary = tempfile.TemporaryDirectory(prefix="p04-adapter-cxx-", dir=ROOT.parent)
        self.addCleanup(temporary.cleanup)
        work = Path(temporary.name)
        source = work / "roundtrip.cpp"
        source.write_text(r'''#include "p04_fixtures.h"
#include <cstdio>
#include <type_traits>

static_assert(!std::is_same_v<p04::NativeInputs, p04::ExpectedOutputs>);
static_assert(std::is_const_v<std::remove_reference_t<decltype((p04::kFixtures[0]))>>);
static_assert(p04::kCaseCount == 10);
static_assert(p04::find_case("missing") == nullptr);
static_assert(p04::find_case("fp16-seeded_dense") == &p04::kFixtures[0]);

template <size_t N>
void dump(const char* name, const std::array<uint32_t, N>& words) {
  std::printf("%s %zu", name, words.size());
  for (uint32_t word : words) {
    std::printf(" %08x", word);
  }
  std::printf("\n");
}

int main() {
  std::printf("MODEL %s %s %s\n", p04::kModelId, p04::kFixtureId, p04::kFixtureSha256);
  for (const auto& fixture : p04::kFixtures) {
    if (p04::find_case(fixture.id) != &fixture) {
      return 1;
    }
    std::printf("CASE %s %s\n", fixture.id, fixture.format);
    dump("input", fixture.inputs.input_words);
    dump("w1", fixture.inputs.w1_words);
    dump("w2", fixture.inputs.w2_words);
    dump("hidden", fixture.expected.hidden_words);
    dump("bridge", fixture.expected.bridge_words);
    dump("output", fixture.expected.output_words);
  }
}
''')
        header = ROOT / adapter.HEADER_PATH
        identity = hashlib.sha256(header.read_bytes()).hexdigest()
        environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                       "TMPDIR": str(work), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
        binary = work / "roundtrip"
        run_host_command([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                          "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                          "-I", str(header.parent), str(source), "-o", str(binary)],
                         cwd=work, env=environment, timeout=45)
        output = run_host_command([str(binary)], cwd=work, env=environment, timeout=10)
        fixture_bytes = (ROOT / contract.FIXTURE_PATH).read_bytes()
        fixture = json.loads(fixture_bytes)
        lines = iter(output.splitlines())
        self.assertEqual(next(lines).split(), ["MODEL", fixture["model_id"], fixture["fixture_id"],
                                               hashlib.sha256(fixture_bytes).hexdigest()])
        for case in fixture["cases"]:
            self.assertEqual(next(lines).split(), ["CASE", case["id"], case["format"]])
            weights = fixture["weights"]["formats"][case["format"]]
            for name in ("input", "w1", "w2", "hidden", "bridge", "output"):
                words = (weights if name in ("w1", "w2") else case)[name + "_words"]
                self.assertEqual(next(lines).split(), [name, str(len(words)), *words])
        self.assertEqual(list(lines), [])
        self.assertEqual(hashlib.sha256(header.read_bytes()).hexdigest(), identity)
