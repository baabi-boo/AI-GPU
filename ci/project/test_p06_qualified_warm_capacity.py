# SPDX-License-Identifier: Apache-2.0
"""Small synthetic memory hierarchies and bounded read-only filesystem checks."""

from contextlib import redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_capacity as capacity


GIB = 1024**3
MOUNTINFO = b"31 24 0:27 /private /memory\\040space rw - cgroup2 cgroup rw\n"


class Fixture:
    def __init__(self):
        self.proc = "/proc/" + str(os.getpid())
        self.calls = []
        self.counts = {}
        self.files = {
            "/proc/meminfo": b"MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n",
            self.proc + "/cgroup": b"0::/private/parent/leaf\n",
            self.proc + "/mountinfo": MOUNTINFO,
        }
        self.directories = ("/memory space/parent/leaf", "/memory space/parent", "/memory space")
        for directory in self.directories:
            self.files[directory + "/cgroup.type"] = b"domain\n"
            self.files[directory + "/memory.max"] = b"max\n"
            self.files[directory + "/memory.current"] = b"0\n"
            self.files[directory + "/memory.high"] = b"max\n"

    def scalar(self, level, name, value):
        self.files[self.directories[level] + "/" + name] = str(value).encode() + b"\n"

    def root_layout(self, *, process_at_root=False):
        self.files[self.proc + "/cgroup"] = (b"0::/\n" if process_at_root
                                              else b"0::/parent/leaf\n")
        self.files[self.proc + "/mountinfo"] = MOUNTINFO.replace(b"/private", b"/")
        for name in (*capacity.SCALARS, "memory.high"):
            self.files[self.directories[-1] + "/" + name] = OSError(errno.ENOENT, "absent")
        self.files[self.directories[-1] + "/cgroup.controllers"] = b"cpu io memory pids\n"
        return self

    def read(self, path, maximum, mount):
        self.calls.append((path, maximum, mount))
        count = self.counts.get(path, 0)
        self.counts[path] = count + 1
        value = self.files.get(path, OSError("private path must not reach report"))
        if isinstance(value, list):
            value = value[min(count, len(value) - 1)]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, capacity.ReadResult):
            return value
        return capacity.ReadResult(value[:maximum + 1], (27, sum(path.encode())))

    def observe(self):
        return capacity.observe_capacity(self.read, clock=lambda: 0)


class ParserTests(unittest.TestCase):
    def test_scalar_grammar_and_memavailable(self):
        self.assertEqual(capacity.parse_scalar(b"0\n"), 0)
        self.assertEqual(capacity.parse_scalar(str(2**64 - 1).encode()), 2**64 - 1)
        self.assertEqual(capacity.parse_scalar(b"max\n", allow_max=True), "max")
        for body in (b"max", b"-1", b"+1", b"1.0", b"1 2", b" 1", b"1\n\n",
                     b"1\r\n", b"1\x00", b"\xff", str(2**64).encode(), b"9" * 4097):
            with self.subTest(body=body[:32]), self.assertRaises(capacity.ObservationError):
                capacity.parse_scalar(body)
        self.assertEqual(capacity.parse_memavailable(b"MemAvailable:\t4096 kB\n"), 4194304)
        for body in (b"MemFree: 7 kB\n", b"MemAvailable: 1 kB\nMemAvailable: 2 kB\n",
                     b"MemAvailable: -1 kB\n", b"MemAvailable: 1 MB\n"):
            with self.subTest(body=body), self.assertRaises(capacity.ObservationError):
                capacity.parse_memavailable(body)

    def test_unsupported_membership_never_becomes_root(self):
        self.assertEqual(capacity.parse_membership(b"0::/\n"), "/")
        for body in (b"", b"0::/\n0::/\n", b"1:memory:/job\n", b"0::/\n1:cpu:/\n",
                     b"0::/../job\n", b"0::/a//b\n", b"0::/a/\n", b"0::/a (deleted)\n",
                     b"0::/a\\012b\n", b"0::relative\n"):
            with self.subTest(body=body), self.assertRaises(capacity.ObservationError):
                capacity.parse_membership(body)

    def test_controller_grammar_does_not_guess_availability(self):
        self.assertEqual(capacity.parse_controllers(b"cpu io memory pids\n"),
                         ("cpu", "io", "memory", "pids"))
        self.assertEqual(capacity.parse_controllers(b"\n"), ())
        for body in (b"memory memory\n", b"memory  cpu\n", b" memory\n", b"memory \n",
                     b"memory\tcpu\n", b"memory\r\n", b"memory\n\n", b"Memory\n",
                     b"memory\x00", b"\xff", b"m" * 4097):
            with self.subTest(body=body[:32]), self.assertRaises(capacity.ObservationError):
                capacity.parse_controllers(body)

    def test_escaped_mount_and_component_mapping(self):
        mounts = capacity.parse_mountinfo(
            b"31 24 0:27 /tenant\\040root /memory\\040space\\134name rw shared:1 - cgroup2 cgroup rw\n")
        mount, ancestors = capacity.map_visible_ancestors("/tenant root/job", mounts)
        self.assertEqual(mount.point, "/memory space\\name")
        self.assertEqual(ancestors, ("/memory space\\name/job", "/memory space\\name"))
        with self.assertRaisesRegex(capacity.ObservationError, "missing_or_ambiguous"):
            capacity.map_visible_ancestors("/tenant roots/job", mounts)
        for bad in (MOUNTINFO + MOUNTINFO, MOUNTINFO.replace(b"\\040", b"\\099"),
                    MOUNTINFO.replace(b"/private", b"/private/../other")):
            with self.subTest(bad=bad), self.assertRaises(capacity.ObservationError):
                capacity.parse_mountinfo(bad)

    def test_ambiguous_mounts_v1_and_overlays_are_unknown(self):
        extra_mounts = (
            b"32 24 0:27 /private /second rw - cgroup2 cgroup rw\n",
            b"32 24 0:28 / /legacy rw - cgroup cgroup rw\n",
            b"32 31 0:27 / /memory\\040space/parent rw - cgroup2 cgroup rw\n",
            b"32 31 0:28 / /memory\\040space/parent/leaf/memory.max ro - tmpfs tmpfs ro\n",
            b"32 31 0:28 / /memory\\040space/cgroup.controllers ro - tmpfs tmpfs ro\n",
        )
        for extra in extra_mounts:
            with self.subTest(extra=extra), self.assertRaises(capacity.ObservationError):
                capacity.map_visible_ancestors("/private/parent/leaf", capacity.parse_mountinfo(MOUNTINFO + extra))


class ObservationTests(unittest.TestCase):
    def assert_unknown_effective(self, report):
        self.assertEqual(report["effective_capacity_status"], "unknown")
        self.assertEqual(report["full_ancestry_status"], "unknown")
        self.assertIsNone(report["ancestry_complete"])
        self.assertIsNone(report["effective_headroom_bytes"])
        self.assertEqual(report["native_execution"], "not_run")
        for name in capacity.FALSE_CLAIMS:
            self.assertIs(report[name], False, name)
        encoded = json.dumps(report, allow_nan=False)
        self.assertLess(len(encoded.encode()), capacity.MAX_JSON_BYTES)
        self.assertNotIn("private", encoded)
        self.assertNotIn("memory space", encoded)

    def test_parent_usage_controls_margin_and_threshold_equality(self):
        for delta in (-1, 0, 1):
            with self.subTest(delta=delta):
                fixture = Fixture()
                fixture.scalar(0, "memory.current", GIB)
                fixture.scalar(1, "memory.max", 9 * GIB + delta)
                fixture.scalar(1, "memory.current", 5 * GIB)
                report = fixture.observe()
                self.assertEqual(report["visible_limit_bytes"], 9 * GIB + delta)
                self.assertEqual(report["visible_headroom_bytes"], 4 * GIB + delta)
                self.assertEqual(report["known_memory_shortfall"], delta < 0)
                self.assertTrue(report["observation_complete"])
                self.assert_unknown_effective(report)

    def test_leaf_limit_and_usage_above_limit_clamp_to_zero(self):
        fixture = Fixture()
        fixture.scalar(0, "memory.max", GIB)
        fixture.scalar(0, "memory.current", GIB + 1)
        fixture.scalar(2, "memory.max", 16 * GIB)
        report = fixture.observe()
        self.assertEqual(report["visible_headroom_bytes"], 0)
        self.assertTrue(report["known_memory_shortfall"])
        self.assertEqual(report["status"], "blocked")

    def test_all_max_and_namespace_root_never_establish_unlimited(self):
        fixture = Fixture()
        report = fixture.observe()
        self.assertTrue(report["observation_complete"])
        self.assertIsNone(report["visible_headroom_bytes"])
        self.assertIsNone(report["visible_limit_bytes"])
        self.assert_unknown_effective(report)
        fixture.files[fixture.proc + "/cgroup"] = b"0::/\n"
        fixture.files[fixture.proc + "/mountinfo"] = MOUNTINFO.replace(b"/private", b"/")
        report = fixture.observe()
        self.assertTrue(report["membership"]["namespace_relative_root"])
        self.assert_unknown_effective(report)

    def test_missing_ancestor_preserves_independent_shortfall(self):
        fixture = Fixture()
        fixture.scalar(0, "memory.max", 2 * GIB)
        del fixture.files[fixture.directories[2] + "/memory.max"]
        report = fixture.observe()
        self.assertFalse(report["observation_complete"])
        self.assertTrue(report["known_memory_shortfall"])
        self.assertEqual(report["visible_headroom_bytes"], 2 * GIB)
        self.assert_unknown_effective(report)

    def test_supported_visible_root_absence_is_complete_without_capacity_claim(self):
        for process_at_root in (False, True):
            with self.subTest(process_at_root=process_at_root):
                fixture = Fixture().root_layout(process_at_root=process_at_root)
                report = fixture.observe()
                self.assertTrue(report["observation_complete"])
                self.assertTrue(report["topology_stable"])
                self.assertFalse(report["known_memory_shortfall"])
                self.assertEqual(report["visible_root_observation"]["status"],
                                 "supported_nonroot_interfaces_absent")
                self.assertEqual(report["visible_root_observation"]["memory_controller_samples"],
                                 [True, True])
                self.assertTrue(report["ancestors"][-1]["supported_root_interfaces_absent"])
                self.assertIsNone(report["visible_headroom_bytes"])
                self.assertIsNone(report["visible_limit_bytes"])
                self.assertIsNone(report["limits_stable"])
                for name in (*capacity.SCALARS, "memory.high", "cgroup.controllers"):
                    self.assertEqual(fixture.counts[fixture.directories[-1] + "/" + name], 2)
                self.assert_unknown_effective(report)

    def test_visible_root_requires_exact_stable_supported_interfaces(self):
        for change in ("controller_missing", "controller_denied", "controller_malformed",
                       "controller_disabled", "controller_changed", "controller_identity",
                       "namespace_type", "namespace_subtree", "scalar_denied", "scalar_malformed",
                       "scalar_appeared", "high_appeared", "high_denied"):
            with self.subTest(change=change):
                fixture = Fixture().root_layout()
                root = fixture.directories[-1]
                controllers = root + "/cgroup.controllers"
                if change == "controller_missing":
                    fixture.files[controllers] = OSError(errno.ENOENT, "absent")
                elif change == "controller_denied":
                    fixture.files[controllers] = OSError(errno.EACCES, "denied")
                elif change == "controller_malformed":
                    fixture.files[controllers] = b"memory memory\n"
                elif change == "controller_disabled":
                    fixture.files[controllers] = b"cpu io pids\n"
                elif change == "controller_changed":
                    fixture.files[controllers] = [b"memory\n", b"cpu memory\n"]
                elif change == "controller_identity":
                    fixture.files[controllers] = [capacity.ReadResult(b"memory\n", (27, 1)),
                                                  capacity.ReadResult(b"memory\n", (27, 2))]
                elif change == "namespace_type":
                    fixture.files[root + "/cgroup.type"] = b"domain\n"
                elif change == "namespace_subtree":
                    fixture.files[fixture.proc + "/cgroup"] = b"0::/private/parent/leaf\n"
                    fixture.files[fixture.proc + "/mountinfo"] = MOUNTINFO
                elif change == "scalar_denied":
                    fixture.files[root + "/memory.max"] = OSError(errno.EACCES, "denied")
                elif change == "scalar_malformed":
                    fixture.files[root + "/memory.max"] = b"not-a-number\n"
                elif change == "scalar_appeared":
                    fixture.files[root + "/memory.max"] = [OSError(errno.ENOENT, "absent"), b"max\n"]
                elif change == "high_appeared":
                    fixture.files[root + "/memory.high"] = [OSError(errno.ENOENT, "absent"), b"max\n"]
                else:
                    fixture.files[root + "/memory.high"] = [OSError(errno.ENOENT, "absent"),
                                                            OSError(errno.EACCES, "denied")]
                report = fixture.observe()
                self.assertFalse(report["observation_complete"])
                self.assertEqual(report["visible_root_observation"]["status"], "unknown")
                self.assert_unknown_effective(report)

    def test_supported_root_preserves_parent_and_host_shortfall_rejection(self):
        for margin in (4 * GIB - 1, 4 * GIB):
            with self.subTest(margin=margin):
                fixture = Fixture().root_layout()
                fixture.scalar(1, "memory.max", 9 * GIB)
                fixture.scalar(1, "memory.current", 9 * GIB - margin)
                report = fixture.observe()
                self.assertTrue(report["observation_complete"])
                self.assertEqual(report["visible_headroom_bytes"], margin)
                self.assertEqual(report["known_memory_shortfall"], margin < 4 * GIB)
                self.assert_unknown_effective(report)
        fixture = Fixture().root_layout(process_at_root=True)
        fixture.files["/proc/meminfo"] = b"MemAvailable: 2097152 kB\n"
        report = fixture.observe()
        self.assertTrue(report["observation_complete"])
        self.assertTrue(report["known_memory_shortfall"])
        self.assertEqual(report["status"], "blocked")
        self.assert_unknown_effective(report)

    def test_host_shortfall_survives_missing_mount_and_scalar_errors(self):
        fixture = Fixture()
        fixture.files["/proc/meminfo"] = b"MemAvailable: 1 kB\n"
        fixture.files[fixture.proc + "/mountinfo"] = b"31 24 0:27 / /plain rw - tmpfs tmpfs rw\n"
        report = fixture.observe()
        self.assertEqual(report["host_available_bytes"], 1024)
        self.assertTrue(report["known_memory_shortfall"])
        self.assertFalse(report["observation_complete"])
        self.assert_unknown_effective(report)

    def test_increasing_usage_uses_larger_usage_without_changing_topology(self):
        fixture = Fixture()
        fixture.scalar(1, "memory.max", 8 * GIB)
        fixture.files[fixture.directories[1] + "/memory.current"] = [b"0\n", str(5 * GIB).encode()]
        report = fixture.observe()
        self.assertEqual(report["visible_headroom_bytes"], 3 * GIB)
        self.assertTrue(report["topology_stable"])
        self.assertTrue(report["limits_stable"])
        self.assertTrue(report["known_memory_shortfall"])

    def test_migration_remount_limit_and_identity_changes_are_incomplete(self):
        for change in ("membership", "mount", "limit", "identity", "deleted"):
            with self.subTest(change=change):
                fixture = Fixture()
                if change == "membership":
                    path = fixture.proc + "/cgroup"
                    fixture.files[path] = [fixture.files[path], b"0::/private/other\n"]
                elif change == "mount":
                    path = fixture.proc + "/mountinfo"
                    fixture.files[path] = [MOUNTINFO, MOUNTINFO.replace(b"31 ", b"41 ", 1)]
                elif change == "limit":
                    fixture.files[fixture.directories[0] + "/memory.max"] = [b"max\n", b"0\n"]
                elif change == "identity":
                    fixture.files[fixture.directories[0] + "/memory.current"] = [
                        capacity.ReadResult(b"0\n", (27, 1)), capacity.ReadResult(b"0\n", (27, 2))]
                else:
                    fixture.files[fixture.directories[0] + "/memory.max"] = [b"max\n", OSError("gone")]
                report = fixture.observe()
                self.assertFalse(report["observation_complete"])
                self.assertFalse(report["known_memory_shortfall"])
                self.assertEqual(report["visible_capacity_status"], "unknown")
                self.assert_unknown_effective(report)

    def test_throttle_swap_and_threaded_domains_do_not_supply_hard_capacity(self):
        fixture = Fixture()
        fixture.scalar(0, "memory.high", 0)
        fixture.files[fixture.directories[0] + "/memory.swap.max"] = b"0\n"
        report = fixture.observe()
        self.assertFalse(report["known_memory_shortfall"])
        self.assertEqual(report["ancestors"][0]["memory_high"], 0)
        self.assertFalse(any("swap" in path for path, _, _ in fixture.calls))
        fixture.files[fixture.directories[0] + "/cgroup.type"] = b"threaded\n"
        self.assertFalse(fixture.observe()["observation_complete"])

    def test_byte_read_depth_and_time_budgets_stop_with_bounded_unknown(self):
        for setting, value, reason in (("MAX_TOTAL_BYTES", 40, "byte_budget_exhausted"),
                                      ("MAX_FILE_READS", 2, "file_read_budget_exhausted"),
                                      ("MAX_ANCESTORS", 2, "ancestor_depth_limit"),
                                      ("MAX_PATH_DEPTH", 2, "path_depth_limit")):
            with self.subTest(setting=setting), mock.patch.object(capacity, setting, value):
                report = Fixture().observe()
                self.assertIn(reason, json.dumps(report))
                self.assertFalse(report["observation_complete"])
                self.assertLessEqual(report["observation_bounds"]["bytes_read"], capacity.MAX_TOTAL_BYTES)
        fixture = Fixture()
        with mock.patch.object(capacity, "MAX_SECONDS", 1):
            report = capacity.observe_capacity(fixture.read, clock=iter((0, 2)).__next__)
        self.assertEqual(report["observation_bounds"]["exhausted"], "time_budget_exhausted")
        self.assertEqual(fixture.calls, [])

    def test_cli_emits_bounded_json_and_has_no_override_flags(self):
        fixture = Fixture()
        output = io.StringIO()
        report = fixture.observe()
        with mock.patch.object(capacity, "observe_capacity", return_value=report), redirect_stdout(output):
            self.assertEqual(capacity.main([]), 1)
        self.assert_unknown_effective(json.loads(output.getvalue()))
        with mock.patch.object(capacity, "observe_capacity") as observe, \
                mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            capacity.main(["--allow-unknown"])
        observe.assert_not_called()


class FilesystemReaderTests(unittest.TestCase):
    def test_regular_read_and_rejection_of_symlinks_fifo_and_oversize(self):
        with tempfile.TemporaryDirectory(prefix="p06-capacity-") as temporary:
            root = Path(temporary).resolve()
            regular = root / "memory.max"
            regular.write_bytes(b"123\n")
            (root / "link").symlink_to(regular)
            (root / "directory-link").symlink_to(root, target_is_directory=True)
            os.mkfifo(root / "fifo")
            reader = capacity._Reader(None, lambda: 0)
            self.assertEqual(reader.read(str(regular), 10).body, b"123\n")
            for path, size in ((root / "link", 10), (root / "directory-link/memory.max", 10),
                               (root / "fifo", 10), (regular, 2)):
                with self.subTest(path=path), self.assertRaises(capacity.ObservationError):
                    reader.read(str(path), size)
            self.assertEqual(regular.read_bytes(), b"123\n")
            info = regular.stat()
            wrong_mount = capacity.Mount(1, (os.major(info.st_dev), os.minor(info.st_dev) + 1),
                                         "/", str(root), "cgroup2")
            with self.assertRaisesRegex(capacity.ObservationError, "crossed_mount_device"):
                reader.read(str(regular), 10, wrong_mount)

    def test_os_read_call_budget(self):
        with tempfile.TemporaryDirectory(prefix="p06-capacity-") as temporary:
            path = Path(temporary) / "value"
            path.write_bytes(b"1")
            with mock.patch.object(capacity, "MAX_READ_CALLS", 0):
                reader = capacity._Reader(None, lambda: 0)
                with self.assertRaisesRegex(capacity.ObservationError, "read_call_budget_exhausted"):
                    reader.read(str(path), 10)

    def test_bytes_from_failed_reads_still_consume_the_aggregate_budget(self):
        with tempfile.TemporaryDirectory(prefix="p06-capacity-") as temporary:
            path = Path(temporary) / "value"
            path.write_bytes(b"x")
            with mock.patch.object(capacity, "MAX_TOTAL_BYTES", 8), \
                    mock.patch.object(capacity.os, "read", side_effect=(
                        b"1234", OSError(errno.EIO, "late read failure"), b"5678")):
                reader = capacity._Reader(None, lambda: 0)
                with self.assertRaisesRegex(capacity.ObservationError, "unreadable_or_unsafe_file"):
                    reader.read(str(path), 10)
                self.assertEqual(reader.total_bytes, 4)
                with self.assertRaisesRegex(capacity.ObservationError, "byte_budget_exhausted"):
                    reader.read(str(path), 10)
                self.assertEqual(reader.total_bytes, 8)


if __name__ == "__main__":
    unittest.main()
