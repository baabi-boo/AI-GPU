# SPDX-License-Identifier: Apache-2.0
"""Real GNU fixtures and malformed retained-byte controls for dependency joins."""

import copy
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import p06_dependency_binary as binary


def descriptor(name, body):
    return {"name": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def member(name, body, *, date="0", uid="0", gid="0", mode="644", size=None):
    fields = ((name, 16), (date, 12), (uid, 6), (gid, 6), (mode, 8),
              (str(len(body)) if size is None else size, 10))
    header = "".join(value.ljust(width) for value, width in fields).encode("ascii") + b"`\n"
    return header + body + (b"\n" if len(body) % 2 else b"")


def archive(*members):
    return b"!<arch>\n" + b"".join(members)


def map_text(rows, loads):
    prefix = (binary.ARCHIVE_HEADING + "\n\n" + "\n".join(rows) + "\n\n") if rows else ""
    contributions = []
    for row in rows:
        match = binary._SELECTION.fullmatch(row)
        if match:
            path, name, _ = match.groups()
            contributions.append(" .text 0x00000010 0x10 " + path + "(" + name + ")")
    return (prefix + binary.MAP_HEADING + "\n\n" + "\n".join("LOAD " + item for item in loads)
            + "\n" + "\n".join(contributions) + "\n")


class DependencyArchiveTests(unittest.TestCase):
    def test_ordinary_archive_preserves_order_and_odd_payload(self):
        data = archive(member("first.o/", b"abc"), member("second.o/", b"de"))
        expected = [descriptor("first.o", b"abc"), descriptor("second.o", b"de")]
        result = binary.validate_archive(data, expected)
        self.assertEqual(result["members"], expected)
        self.assertEqual(result["size_bytes"], len(data))
        self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(result["symbol_count"], 0)
        self.assertFalse(result["has_long_names"])

    def test_fresh_different_object_cannot_be_admitted_by_rehashing_archive(self):
        expected = [descriptor("same.o", b"original-object")]
        replacement = archive(member("same.o/", b"different-real-bytes"))
        self.assertEqual(binary.parse_archive(replacement)["members"][0]["name"], "same.o")
        with self.assertRaisesRegex(ValueError, "ordered object identities"):
            binary.validate_archive(replacement, expected)

    def test_missing_extra_and_reordered_members_fail_exact_join(self):
        expected = [descriptor("first.o", b"a"), descriptor("second.o", b"b")]
        for data in (archive(member("first.o/", b"a")),
                     archive(member("second.o/", b"b"), member("first.o/", b"a")),
                     archive(member("first.o/", b"a"), member("second.o/", b"b"), member("extra.o/", b"c"))):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "ordered object identities"):
                binary.validate_archive(data, expected)

    def test_thin_magic_wrong_type_empty_and_truncated_archives_reject(self):
        for data in (b"!<thin>\n", b"not-archive", b"!<arch>\n", archive(member("a.o/", b"ab"))[:-1],
                     bytearray(archive(member("a.o/", b"ab"))), archive(member("a.o/", b""))):
            with self.subTest(data=data), self.assertRaises(ValueError):
                binary.parse_archive(data)

    def test_unsafe_duplicate_and_unsupported_member_names_reject(self):
        for name in ("../a.o/", "/tmp/a.o/", "dir/a.o/", ".hidden.o/", "a b.o/", "a.o", "#1/5", "/bogus"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                binary.parse_archive(archive(member(name, b"a")))
        with self.assertRaisesRegex(ValueError, "duplicate object"):
            binary.parse_archive(archive(member("a.o/", b"a"), member("a.o/", b"b")))

    def test_numeric_header_fields_are_strict(self):
        for kwargs in ({"date": "-1"}, {"date": "01"}, {"uid": "x"}, {"gid": " 1"},
                       {"mode": "888"}, {"size": "-1"}, {"size": "01"}, {"size": "1x"},
                       {"uid": ""}, {"size": "9999999999"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                binary.parse_archive(archive(member("a.o/", b"a", **kwargs)))

    def test_header_and_padding_are_exact(self):
        data = bytearray(archive(member("a.o/", b"a")))
        data[66:68] = b"xx"
        with self.assertRaisesRegex(ValueError, "terminator"):
            binary.parse_archive(bytes(data))
        for data in (archive(member("a.o/", b"a"))[:-1], archive(member("a.o/", b"a"))[:-1] + b"x"):
            with self.assertRaisesRegex(ValueError, "padding"):
                binary.parse_archive(data)
        with self.assertRaisesRegex(ValueError, "header is truncated"):
            binary.parse_archive(archive(member("a.o/", b"aa")) + b"x")

    def test_long_name_table_offsets_and_padding(self):
        name = "longfilename12345.o"
        table = (name + "/\n\n").encode("ascii")
        data = archive(member("//", table, date="", uid="", gid="", mode=""), member("/0", b"object"))
        result = binary.validate_archive(data, [descriptor(name, b"object")])
        self.assertTrue(result["has_long_names"])
        for offset in ("/1", "/999", "/00"):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                binary.parse_archive(archive(member("//", table), member(offset, b"object")))

    def test_long_table_extra_duplicate_traversal_and_late_table_reject(self):
        for table in (b"../escape.o/\n", b"repeated.o/\nrepeated.o/\n", b"no-terminator",
                      b"first.o/\nsecond.o/\n", b"bad\x00name.o/\n"):
            with self.subTest(table=table), self.assertRaises(ValueError):
                binary.parse_archive(archive(member("//", table), member("/0", b"object")))
        with self.assertRaisesRegex(ValueError, "out of order"):
            binary.parse_archive(archive(member("a.o/", b"object"), member("//", b"longfilename12345.o/\n\n")))

    def test_long_and_short_aliases_cannot_duplicate_member(self):
        table = b"same.o/\n"
        with self.assertRaisesRegex(ValueError, "duplicate object"):
            binary.parse_archive(archive(member("//", table), member("/0", b"x"), member("same.o/", b"y")))

    def test_symbol_offsets_must_identify_actual_member_headers(self):
        symbol = (1).to_bytes(4, "big") + (80).to_bytes(4, "big") + b"sym\0"
        data = archive(member("/", symbol), member("a.o/", b"xx"))
        result = binary.parse_archive(data)
        self.assertEqual(result["symbol_count"], 1)
        for changed in ((1).to_bytes(4, "big") + (8).to_bytes(4, "big") + b"sym\0",
                        (1).to_bytes(4, "big") + (81).to_bytes(4, "big") + b"sym\0",
                        (1).to_bytes(4, "big") + (80).to_bytes(4, "big") + b"symx",
                        (1000000).to_bytes(4, "big")):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                binary.parse_archive(archive(member("/", changed), member("a.o/", b"xx")))

    def test_symbol_table_order_and_duplicate_metadata_reject(self):
        empty = (0).to_bytes(4, "big")
        for data in (archive(member("/", empty), member("/", empty), member("a.o/", b"xx")),
                     archive(member("a.o/", b"xx"), member("/", empty)),
                     archive(member("//", b"longfilename12345.o/\n\n"), member("/", empty), member("/0", b"xx"))):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "symbol table is duplicate or out of order"):
                binary.parse_archive(data)

    def test_64_bit_gnu_symbol_table(self):
        symbol = (1).to_bytes(8, "big") + (88).to_bytes(8, "big") + b"sym\0"
        self.assertEqual(binary.parse_archive(archive(member("/SYM64/", symbol), member("a.o/", b"xx")))["symbol_count"], 1)

    def test_expected_member_schema_and_bounds(self):
        data = archive(member("a.o/", b"x"))
        valid = descriptor("a.o", b"x")
        for rows in ([], (valid,), [dict(valid, extra=True)], [dict(valid, size_bytes=True)],
                     [dict(valid, sha256="A" * 64)], [valid, valid]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                binary.validate_archive(data, rows)
        with mock.patch.object(binary.contract, "MAX_FILE_BYTES", 16), self.assertRaisesRegex(ValueError, "bounded immutable"):
            binary.parse_archive(data)
        with mock.patch.object(binary, "MAX_MEMBERS", 1), self.assertRaisesRegex(ValueError, "member bound"):
            binary.parse_archive(archive(member("a.o/", b"x"), member("b.o/", b"y")))


class DependencyLinkMapTests(unittest.TestCase):
    def setUp(self):
        self.cwd = "/build/ramulator"
        self.path = "/build/ramulator/libselected.a"
        self.expected = {self.path: [descriptor("first.o", b"first"), descriptor("second.o", b"second")]}
        self.rows = ["libselected.a(first.o)      first-user.o (symbol_one)",
                     "./libselected.a(second.o)", "   libselected.a(first.o) (name::method(int))"]
        self.text = map_text(self.rows, ["main.o", self.path, "/system/libdynamic.so"])

    def test_selected_members_bind_hashes_and_relative_paths(self):
        result = binary.validate_link_map(self.text, cwd=self.cwd, archives=self.expected,
                                          required_loads=["/system/libdynamic.so"])
        self.assertEqual([row["name"] for row in result["selected_members"]], ["first.o", "second.o"])
        self.assertEqual(result["selected_members"][0]["sha256"], self.expected[self.path][0]["sha256"])
        self.assertEqual(result["selected_members"][1]["reference_file"], self.path)
        self.assertEqual(result["selected_members"][1]["reference_member"], "first.o")
        self.assertEqual(result["selected_members"][1]["symbol"], "name::method(int)")
        self.assertEqual(result["loads"][0], self.cwd + "/main.o")

    def test_load_only_cannot_establish_archive_consumption(self):
        text = map_text([], [self.path])
        with self.assertRaisesRegex(ValueError, "required archive-member evidence"):
            binary.validate_link_map(text, cwd=self.cwd, archives=self.expected)

    def test_dynamic_only_link_with_exact_required_load(self):
        text = map_text([], ["bridge.o", "/native/libramulator.so"])
        result = binary.validate_link_map(text, cwd=self.cwd, archives={},
                                          required_loads=["/native/libramulator.so"])
        self.assertEqual(result["selected_members"], [])
        with self.assertRaisesRegex(ValueError, "required LOAD"):
            binary.validate_link_map(text, cwd=self.cwd, archives={},
                                     required_loads=["/substitute/libramulator.so"])

    def test_unknown_archive_and_member_are_rejected(self):
        for text, reason in ((self.text.replace("libselected.a", "libselected.a.other.a"), "unadmitted archive"),
                             (self.text.replace("first.o)", "unknown.o)"), "unadmitted archive member")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                binary.validate_link_map(text, cwd=self.cwd, archives=self.expected)

    def test_external_static_inputs_require_explicit_verified_member_inventory(self):
        rows = [*self.rows, "/system/libgcc.a(extra.o) user.o (helper)"]
        text = map_text(rows, [self.path, "/system/libgcc.a"])
        with self.assertRaisesRegex(ValueError, "unadmitted archive"):
            binary.validate_link_map(text, cwd=self.cwd, archives=self.expected)
        known = {**self.expected, "/system/libgcc.a": [descriptor("extra.o", b"toolchain-object")]}
        result = binary.validate_link_map(text, cwd=self.cwd, archives=known, required_archives=[self.path])
        self.assertEqual(len(result["selected_members"]), 3)

    def test_missing_duplicate_and_confusing_loads_reject(self):
        for loads in ([self.path + ".substitution"], [self.path, self.path], ["prefix" + self.path]):
            with self.subTest(loads=loads), self.assertRaisesRegex(ValueError, "required LOAD"):
                binary.validate_link_map(map_text(self.rows, loads), cwd=self.cwd, archives=self.expected)

    def test_duplicate_resolved_member_selection_rejects(self):
        rows = [self.rows[0], "./libselected.a(first.o) other.o (another)"]
        with self.assertRaisesRegex(ValueError, "repeats an archive member"):
            binary.parse_link_map(map_text(rows, [self.path]), cwd=self.cwd)

    def test_archive_selection_omission_cannot_hide_input_section_member(self):
        for text in (self.text.replace(binary.ARCHIVE_HEADING + "\n\n", ""),
                     self.text.replace(self.rows[0] + "\n", ""),
                     self.text.replace(self.rows[1] + "\n" + self.rows[2] + "\n", "")):
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                binary.parse_link_map(text, cwd=self.cwd)
        hidden = map_text([], ["/native/libramulator.so"]) + " .text 0x10 0x10 hidden.a(x.o)\n"
        with self.assertRaisesRegex(ValueError, "input-section members"):
            binary.validate_link_map(hidden, cwd=self.cwd, archives={},
                                     required_loads=["/native/libramulator.so"])

    def test_fabricated_selection_without_input_section_evidence_rejects(self):
        text = self.text.replace(" .text 0x00000010 0x10 libselected.a(first.o)\n", "")
        with self.assertRaisesRegex(ValueError, "input-section members"):
            binary.parse_link_map(text, cwd=self.cwd)

    def test_malformed_selected_rows_and_unsupported_whole_archive_reject(self):
        for rows in (["libselected.a(first.o)"], ["libselected.a(first.o) (--whole-archive)"],
                     ["libselected.a(first.o) user.o symbol"], ["libselected.a(../escape.o) user.o (s)"],
                     ["   libselected.a(first.o) user.o (s)"], ["echo libselected.a(first.o) user.o (s)"]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                binary.parse_link_map(map_text(rows, [self.path]), cwd=self.cwd)

    def test_section_control_and_line_bounds_reject(self):
        for text in (self.text[:-1], self.text.replace("symbol_one", "symbol\x00one"),
                     self.text.replace("symbol_one", "symbol\rname"), self.text.replace("symbol_one", "نام"),
                     self.text + binary.MAP_HEADING + "\n", "noise\n" + self.text,
                     "LOAD " + self.path + "\n" + self.text,
                     self.text.replace("LOAD " + self.path, "LOAD\t" + self.path)):
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                binary.parse_link_map(text, cwd=self.cwd)
        with mock.patch.object(binary, "MAX_MAP_LINE_BYTES", 10), self.assertRaisesRegex(ValueError, "line bounds"):
            binary.parse_link_map(self.text, cwd=self.cwd)

    def test_path_traversal_is_lexical_and_cannot_escape_root(self):
        text = map_text(["../dependency/lib.a(x.o) ../source/main.o (x)"], ["../dependency/lib.a"])
        result = binary.parse_link_map(text, cwd="/build/current")
        self.assertEqual(result["selected_members"][0]["archive"], "/build/dependency/lib.a")
        self.assertEqual(result["selected_members"][0]["reference_file"], "/build/source/main.o")
        for path in ("//double/a.a", "../../../../escape.a", "$(command).a", "/with space.a"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                binary.parse_link_map(map_text([path + "(x.o) user.o (x)"], [path]), cwd="/build")

    def test_caller_expectations_have_exact_types_and_canonical_paths(self):
        for kwargs in ({"archives": {self.cwd + "/../libselected.a": self.expected[self.path]}},
                       {"archives": self.expected, "required_archives": [self.path, self.path]},
                       {"archives": self.expected, "required_archives": ["/absent.a"]},
                       {"archives": self.expected, "required_loads": [self.path, self.path]},
                       {"archives": self.expected, "required_loads": [True]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                binary.validate_link_map(self.text, cwd=self.cwd, **kwargs)
        for cwd in ("relative", "/build/../build", "/build//path", "/build/./path", True):
            with self.subTest(cwd=cwd), self.assertRaises(ValueError):
                binary.parse_link_map(self.text, cwd=cwd)

    def test_readers_never_open_paths_execute_or_extract(self):
        data = archive(member("first.o/", b"first"), member("second.o/", b"second"))
        with mock.patch("builtins.open", side_effect=AssertionError("unexpected file read")), \
                mock.patch.object(Path, "open", side_effect=AssertionError("unexpected path read")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("unexpected execution")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("unexpected execution")):
            binary.validate_archive(data, copy.deepcopy(self.expected[self.path]))
            binary.validate_link_map(self.text, cwd=self.cwd, archives=self.expected)


class DependencyRealGNUFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-dependency-binary-")
        cls.root = Path(cls.temporary.name)
        cls.gcc, cls.ar = shutil.which("gcc"), shutil.which("ar")
        if cls.gcc is None or cls.ar is None:
            raise RuntimeError("GNU C compiler and archiver are required for dependency binary controls")

        def run(*args):
            return subprocess.run(list(map(str, args)), cwd=cls.root, check=True, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

        cls.run_command = staticmethod(run)
        sources = {
            "first.c": "int second(void); int first(void) { return second() + 1; }\n",
            "long_filename_for_dependency_archive.c": "int second(void) { return 41; }\n",
            "unused.c": "int unused(void) { return 9; }\n",
            "main.c": "int first(void); int main(void) { return first() != 42; }\n",
            "dynamic.c": "int dynamic_dependency(void) { return 3; }\n",
            "bridge.c": "int dynamic_dependency(void); int bridge(void) { return dynamic_dependency(); }\n",
        }
        for name, source in sources.items():
            (cls.root / name).write_text(source)
            run(cls.gcc, "-fPIC", "-c", cls.root / name, "-o", cls.root / (name + ".o"))
        names = ["first.c.o", "long_filename_for_dependency_archive.c.o", "unused.c.o"]
        cls.members = [descriptor(name, (cls.root / name).read_bytes()) for name in names]
        cls.archive_path = str(cls.root / "libdependency.a")
        run(cls.ar, "crs", cls.archive_path, *[cls.root / name for name in names])
        run(cls.gcc, cls.root / "main.c.o", cls.archive_path,
            "-Wl,-Map," + str(cls.root / "main.map"), "-o", cls.root / "main")
        run(cls.root / "main")
        run(cls.gcc, "-shared", cls.root / "dynamic.c.o", "-o", cls.root / "libdynamic.so")
        run(cls.gcc, "-shared", cls.root / "bridge.c.o", "-L" + str(cls.root), "-ldynamic",
            "-Wl,-Map," + str(cls.root / "bridge.map"), "-o", cls.root / "bridge.so")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_actual_gnu_archive_matches_every_compiler_output(self):
        result = binary.validate_archive((self.root / "libdependency.a").read_bytes(), self.members)
        self.assertEqual(result["symbol_count"], 3)
        self.assertTrue(result["has_long_names"])

    def test_actual_gnu_map_identifies_consumed_subset(self):
        result = binary.validate_link_map((self.root / "main.map").read_text(), cwd=str(self.root),
                                          archives={self.archive_path: self.members})
        self.assertEqual([row["name"] for row in result["selected_members"]],
                         ["first.c.o", "long_filename_for_dependency_archive.c.o"])
        self.assertNotIn("unused.c.o", [row["name"] for row in result["selected_members"]])

    def test_actual_shared_link_binds_exact_dynamic_load(self):
        result = binary.validate_link_map((self.root / "bridge.map").read_text(), cwd=str(self.root),
                                          archives={}, required_loads=[str(self.root / "libdynamic.so")])
        self.assertEqual(result["selected_members"], [])

    def test_real_object_substitution_rejects_after_valid_rearchive(self):
        changed = self.root / "different"
        changed.mkdir()
        target = changed / self.members[0]["name"]
        target.write_bytes((self.root / "unused.c.o").read_bytes())
        self.run_command(self.ar, "crs", changed / "replacement.a", target,
                         self.root / self.members[1]["name"], self.root / self.members[2]["name"])
        replacement = (changed / "replacement.a").read_bytes()
        self.assertEqual([row["name"] for row in binary.parse_archive(replacement)["members"]],
                         [row["name"] for row in self.members])
        with self.assertRaisesRegex(ValueError, "ordered object identities"):
            binary.validate_archive(replacement, self.members)


if __name__ == "__main__":
    unittest.main()
