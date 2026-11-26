# SPDX-License-Identifier: Apache-2.0
"""Offline stdlib unit tests for ci/project/export_clean_rtl_handoff.py."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import export_clean_rtl_handoff as exporter

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_minimal_clean_repo(root: Path) -> None:
    (root / "hw/rtl").mkdir(parents=True, exist_ok=True)
    (root / "hw/asic/sram").mkdir(parents=True, exist_ok=True)
    (root / "hw/asic/phys/__pycache__").mkdir(parents=True, exist_ok=True)
    (root / "hw/dv/sva").mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "third_party/ramulator").mkdir(parents=True, exist_ok=True)
    (root / "build64").mkdir(parents=True, exist_ok=True)
    (root / ".git").mkdir(parents=True, exist_ok=True)

    apache_sv = (
        "// Copyright (c) 2026 AI-GPU Project\n"
        "// Licensed under the Apache License, Version 2.0\n"
        "module top (input logic clk);\nendmodule\n"
    )
    (root / "hw/rtl/top.sv").write_text(apache_sv, encoding="utf-8")
    (root / "hw/rtl/.DS_Store").write_bytes(b"\x00\x00\x00\x01")
    (root / "hw/asic/sram/VX_sram_1rw.sv").write_text(apache_sv, encoding="utf-8")
    (root / "hw/asic/phys/__pycache__/cached.pyc").write_bytes(b"pycdata")
    (root / "hw/dv/sva/VX_axi4_sva.sv").write_text(apache_sv, encoding="utf-8")
    (root / "hw/asic/sram/sram_macro_manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "profiles": {
                "aigpu-b1-tile": {
                    "sram_arrays": [
                        {
                            "array_id": "l2_data",
                            "port_type": "1rw",
                            "depth": 2048,
                            "width": 512,
                            "total_instances": 2,
                            "physical_cut": "4x 2048x128b_wm1",
                            "total_kib": 256.0,
                            "total_mib": 0.25,
                        }
                    ],
                    "totals": {
                        "total_logical_arrays": 2,
                        "total_bits": 2097152,
                        "total_bytes": 262144,
                        "total_kib": 256.0,
                        "total_mib": 0.25,
                    },
                }
            },
        }),
        encoding="utf-8",
    )
    (root / "profiles/aigpu-b1.json").write_text('{"name":"aigpu-b1"}\n', encoding="utf-8")
    (root / "profiles/aigpu-b1-tile.json").write_text('{"name":"aigpu-b1-tile"}\n', encoding="utf-8")
    (root / "VX_config.toml").write_text("[platform]\nVX_CFG_NUM_CORES = 1\n", encoding="utf-8")
    (root / "VX_types.toml").write_text("[globals]\nVX_CSR_ADDR_BITS = 12\n", encoding="utf-8")
    (root / "LICENSE").write_text("Apache License\nVersion 2.0, January 2004\n", encoding="utf-8")

    # Synthetic proprietary/excluded trees outside clean export scope
    (root / "third_party/ramulator/micron_ddr4.sv").write_text(
        "// MICRON TECHNOLOGY, INC. - CONFIDENTIAL AND PROPRIETARY INFORMATION\n",
        encoding="utf-8",
    )
    (root / "build64/stale.xclbin").write_bytes(b"XCLBIN")


class CleanRtlHandoffExporterTests(unittest.TestCase):
    def test_real_repo_dry_run_audit_passes_with_zero_violations(self):
        stdout_buf = io.StringIO()
        with redirect_stdout(stdout_buf):
            rc = exporter.main(["--dry-run", "--json"])
        self.assertEqual(rc, 0)
        manifest = json.loads(stdout_buf.getvalue())

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["package_id"], "aigpu_b1_clean_rtl_handoff")
        self.assertEqual(manifest["evidence_level"], "source_present")
        self.assertIs(manifest["foundry_signoff"], False)
        self.assertIs(manifest["silicon_measured"], False)
        self.assertIs(manifest["clean_ip_verified"], True)
        self.assertEqual(manifest["summary"]["violation_count"], 0)
        self.assertEqual(manifest["violations"], [])

        exported_paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("LICENSE", exported_paths)
        self.assertIn("VX_config.toml", exported_paths)
        self.assertIn("VX_types.toml", exported_paths)
        self.assertIn("profiles/aigpu-b1.json", exported_paths)
        self.assertIn("profiles/aigpu-b1-tile.json", exported_paths)
        self.assertIn("hw/asic/sram/sram_macro_manifest.json", exported_paths)
        self.assertIn("hw/asic/constraints/aigpu_b1.sdc", exported_paths)
        self.assertIn("hw/asic/power/aigpu_b1.upf", exported_paths)

        # Verify caches and forbidden trees are excluded
        for p in exported_paths:
            self.assertNotIn("__pycache__", p)
            self.assertNotIn(".DS_Store", p)
            self.assertFalse(p.startswith("third_party/"))
            self.assertFalse(p.startswith("build"))
            self.assertFalse(p.startswith(".git/"))
            self.assertFalse(p.endswith((".xci", ".dcp", ".bit", ".xclbin")))

        # Verify SRAM macro summary consistency
        sram_profiles = manifest["sram_macro_summary"]["profiles"]
        self.assertEqual(sram_profiles["aigpu-b1-tile"]["total_logical_arrays"], 131)
        self.assertEqual(sram_profiles["aigpu-b1-tile"]["total_physical_macro_cuts"], 218)
        self.assertEqual(sram_profiles["aigpu-b1"]["total_logical_arrays"], 8256)
        self.assertEqual(sram_profiles["aigpu-b1"]["total_physical_macro_cuts"], 22784)
        self.assertGreater(manifest["summary"]["rtl_lines"], 90000)

    def test_tarball_export_and_sha256_verification_and_determinism(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tar1 = tmp / "handoff_1.tar.gz"
            tar2 = tmp / "handoff_2.tar.gz"
            manifest_out = tmp / "standalone_manifest.json"

            buf1 = io.StringIO()
            with redirect_stdout(buf1):
                rc1 = exporter.main([
                    "--repo-root", str(REPO_ROOT),
                    "--output", str(tar1),
                    "--manifest-out", str(manifest_out),
                    "--json",
                ])
            self.assertEqual(rc1, 0)
            self.assertTrue(tar1.is_file())
            self.assertTrue(manifest_out.is_file())

            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                rc2 = exporter.main([
                    "--repo-root", str(REPO_ROOT),
                    "--output", str(tar2),
                    "--json",
                ])
            self.assertEqual(rc2, 0)

            # Bit-for-bit deterministic tarball & manifest across runs
            self.assertEqual(tar1.read_bytes(), tar2.read_bytes())

            cli_manifest = json.loads(buf1.getvalue())
            standalone_manifest = json.loads(manifest_out.read_text(encoding="utf-8"))
            self.assertNotIn("archive_output", standalone_manifest)

            # Verify every file inside the .tar.gz against manifest SHA-256
            with tarfile.open(tar1, "r:gz") as tf:
                members = {m.name: m for m in tf.getmembers() if m.isfile()}
                manifest_member_name = f"{exporter.DEFAULT_ARCHIVE_PREFIX}/handoff_manifest.json"
                self.assertIn(manifest_member_name, members)
                inner_manifest = json.loads(
                    tf.extractfile(members[manifest_member_name]).read().decode("utf-8")
                )
                self.assertEqual(inner_manifest, standalone_manifest)
                self.assertIs(inner_manifest["foundry_signoff"], False)
                self.assertIs(inner_manifest["silicon_measured"], False)
                self.assertIs(inner_manifest["clean_ip_verified"], True)

                for entry in inner_manifest["files"]:
                    arc_name = f"{exporter.DEFAULT_ARCHIVE_PREFIX}/{entry['path']}"
                    self.assertIn(arc_name, members)
                    payload = tf.extractfile(members[arc_name]).read()
                    self.assertEqual(len(payload), entry["bytes"])
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])

            self.assertEqual(
                cli_manifest["archive_output"]["sha256"],
                hashlib.sha256(tar1.read_bytes()).hexdigest(),
            )

    def test_synthetic_clean_repo_excludes_caches_and_third_party(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            _make_minimal_clean_repo(repo)
            tar_path = Path(tmpdir) / "out.tar.gz"

            out = io.StringIO()
            with redirect_stdout(out):
                rc = exporter.main(["--repo-root", str(repo), "--output", str(tar_path), "--json"])
            self.assertEqual(rc, 0)
            manifest = json.loads(out.getvalue())
            self.assertEqual(manifest["summary"]["excluded_cache_count"], 2)
            paths = {e["path"] for e in manifest["files"]}
            self.assertNotIn("hw/rtl/.DS_Store", paths)
            self.assertNotIn("hw/asic/phys/__pycache__/cached.pyc", paths)
            self.assertNotIn("third_party/ramulator/micron_ddr4.sv", paths)
            self.assertNotIn("build64/stale.xclbin", paths)

    def test_negative_forbidden_files_fail_audit_and_block_export(self):
        forbidden_cases = [
            ("hw/rtl/micron_ddr4.sv", "// Apache-2.0\nmodule micron_ddr4; endmodule\n", "forbidden_path_token"),
            ("hw/rtl/ramulator_stub.cpp", "// Apache-2.0\nint ramulator_init() { return 0; }\n", "forbidden_path_token"),
            ("hw/asic/kernel.xclbin", b"\x00\x01XCLBIN", "forbidden_extension"),
            ("hw/rtl/vendor_ip.xci", "<xml/>", "forbidden_extension"),
            (
                "hw/rtl/encrypted_core.sv",
                "// Licensed under the Apache License, Version 2.0\n`pragma protect begin_protected\n",
                "forbidden_content:ieee_1735_protect",
            ),
            (
                "hw/rtl/proprietary_block.sv",
                "// CONFIDENTIAL AND PROPRIETARY - DO NOT DISTRIBUTE\nmodule p; endmodule\n",
                "forbidden_content:restricted_proprietary_banner",
            ),
        ]
        for rel_path, content, expected_rule in forbidden_cases:
            with self.subTest(rel_path=rel_path):
                with tempfile.TemporaryDirectory() as tmpdir:
                    repo = Path(tmpdir) / "repo"
                    _make_minimal_clean_repo(repo)
                    target = repo / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(content, bytes):
                        target.write_bytes(content)
                    else:
                        target.write_text(content, encoding="utf-8")

                    tar_path = Path(tmpdir) / "blocked.tar.gz"
                    out = io.StringIO()
                    err = io.StringIO()
                    with redirect_stdout(out), redirect_stderr(err):
                        rc = exporter.main([
                            "--repo-root", str(repo),
                            "--output", str(tar_path),
                            "--json",
                        ])
                    self.assertEqual(rc, 1)
                    self.assertFalse(tar_path.exists())
                    manifest = json.loads(out.getvalue())
                    self.assertIs(manifest["clean_ip_verified"], False)
                    self.assertIs(manifest["foundry_signoff"], False)
                    self.assertIs(manifest["silicon_measured"], False)
                    rules = {v["rule"] for v in manifest["violations"]}
                    self.assertIn(expected_rule, rules)

    def test_negative_forced_third_party_extra_scan_path_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            _make_minimal_clean_repo(repo)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = exporter.main([
                    "--repo-root", str(repo),
                    "--dry-run",
                    "--json",
                    "--extra-scan-path", "third_party/ramulator/micron_ddr4.sv",
                ])
            self.assertEqual(rc, 1)
            manifest = json.loads(out.getvalue())
            self.assertIs(manifest["clean_ip_verified"], False)
            rules = {v["rule"] for v in manifest["violations"]}
            self.assertIn("forbidden_path_token", rules)
            self.assertIn("forbidden_content:micron_vendor", rules)

    def test_missing_output_without_dry_run_exits_with_code_2(self):
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                exporter.main([])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
