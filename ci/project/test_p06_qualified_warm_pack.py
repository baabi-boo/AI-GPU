# SPDX-License-Identifier: Apache-2.0
"""Synthetic, data-only PRIVATE packaging checks; no native run or download."""

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_qualified_warm_pack as pack


class PrivatePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-private-pack-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.workspace = self.root / "workspace"
        self.evidence = self.workspace / "evidence"
        self.evidence.mkdir(parents=True)
        self.output = self.root / "output"
        self.extra = self.root / "acquisition"
        self.extra.mkdir()
        (self.extra / "raw.log").write_bytes(b"private acquisition output\x00\xff\n")
        self.make_success()

    def put(self, name, body):
        path = self.evidence / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def write_json(self, name, document):
        return self.put(name, (json.dumps(document, sort_keys=True) + "\n").encode())

    def descriptor(self, name):
        body = (self.evidence / name).read_bytes()
        return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}

    def make_success(self):
        command = {"process_started": True, "cleanup_complete": True,
                   "outcome": "pass", "exit_code": 0}
        documents = {"preparation": "dependency-preparation.json",
                     "dependency-build": "dependency-build/report.json",
                     "qualified-warm": "qualified-warm/report.json"}
        for name, relative in documents.items():
            self.write_json(relative, {"state": "finished", "outcome": "pass", "reason": None,
                                       "failures": [], "commands": [dict(command)]})
        self.put("dependency-build/payloads/.retention.lock", b"")
        self.put("dependency-build/opaque/output.bin", bytes(range(256)))
        self.put("qualified-warm/.retention.lock", b"")
        self.put("qualified-warm/opaque/native.bin", b"\x00Micron confidential/proprietary\xff\x00")
        self.put("qualified-warm/logs/unfavorable-diagnostic.log", b"an opaque unfavorable observation\n")
        self.put("top-level.raw.log", b"raw whole-attempt output\x00\xff\n")
        selected_sources = []
        for relative in pack.runner.SOURCE_FILES:
            body = ("# Inert packaging fixture: " + relative
                    + "\nraise RuntimeError('retained code must never run')\n").encode()
            source = self.source / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(body)
            source_name = pack.runner.SOURCE_ROOT + "/" + relative
            self.put(source_name, body)
            selected_sources.append(dict(self.descriptor(source_name), path=relative))
        stages = []
        for name in pack.runner.STAGE_NAMES:
            log = pack.runner.LOG_ROOT + "/" + name + ".log"
            self.put(log, (name + " unabridged log\n").encode())
            stages.append(dict(command, id=name, finished_at="2026-11-24T00:00:00Z",
                               log=log, raw_log=self.descriptor(log)))
        self.run = {"schema_version": 1, "contract_id": pack.runner.CONTRACT_ID, "state": "finished",
            "source_dir": str(self.source), "workspace_dir": str(self.workspace), "outcome": "pass",
            "orchestration_passed": True, "reason": None, "failures": [], "stages": stages,
            "source_stable": True, "selected_sources_stable": True, "inputs_stable": True,
            "selected_sources_before": selected_sources, "selected_sources_after": selected_sources,
            "reports": {name: self.descriptor(relative) for name, relative in documents.items()},
            "dependency_receipt_sha256": self.descriptor(documents["dependency-build"])["sha256"],
            "qualified_warm_report_sha256": self.descriptor(documents["qualified-warm"])["sha256"]}
        self.write_json(pack.runner.RECEIPT_PATH, self.run)

    def arguments(self, **updates):
        return dict(source_dir=self.source, workspace_dir=self.workspace, output_dir=self.output,
                    writers_finished=True, extra_roots={"acquisition": self.extra}, **updates)

    def success(self):
        return pack.package_success(**self.arguments())

    def partial(self):
        return pack.package_partial(**self.arguments())

    def failure_receipt(self):
        value = json.loads((self.output / pack.FAILURE_NAME).read_bytes())
        self.assertFalse(value["packaging_passed"])
        self.assertFalse(value["complete_replay_original_created"])
        self.assertTrue(value["partial_attempt"])
        self.assertEqual(value["classification"], "PRIVATE")
        return value

    def tree_bytes(self):
        return {path.relative_to(self.evidence).as_posix(): path.read_bytes()
                for path in self.evidence.rglob("*") if path.is_file()}

    def test_success_is_exact_two_roots_with_hidden_locks_and_opaque_bytes(self):
        originals = self.tree_bytes()
        receipt = self.success()
        self.assertEqual(self.tree_bytes(), originals)
        self.assertEqual(receipt["classification"], "PRIVATE")
        self.assertFalse(receipt["partial_attempt"])
        self.assertTrue(receipt["source_identities_stable"])
        with zipfile.ZipFile(self.output / pack.ORIGINAL_NAME) as archive:
            expected = {name: body for name, body in originals.items()
                        if name.split("/")[0] in pack.ROOTS}
            self.assertEqual(archive.namelist(), sorted(expected))
            self.assertEqual({name.split("/")[0] for name in archive.namelist()}, set(pack.ROOTS))
            self.assertEqual({name: archive.read(name) for name in archive.namelist()}, expected)
            self.assertNotIn(pack.RECEIPT_NAME, archive.namelist())
            self.assertTrue(all(stat.S_ISREG(item.external_attr >> 16) for item in archive.infolist()))
        for artifact in receipt["archives"]:
            body = (self.output / artifact["filename"]).read_bytes()
            self.assertEqual(artifact["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(artifact["size_bytes"], len(body))
            self.assertEqual(artifact["member_count"], len(artifact["members"]))
            self.assertTrue(artifact["zip_crc_verified"])
            self.assertTrue(all(row["source_identity"]["links"] == 1 for row in artifact["members"]))
        self.assertEqual(json.loads((self.output / pack.RECEIPT_NAME).read_bytes()), receipt)

    def test_envelope_preserves_full_raw_supervision_and_explicit_extra_evidence(self):
        originals = self.tree_bytes()
        self.success()
        with zipfile.ZipFile(self.output / pack.ENVELOPE_NAME) as archive:
            expected = {"evidence/" + name: body for name, body in originals.items()
                        if name.split("/")[0] not in pack.ROOTS}
            expected["additional-evidence/acquisition/raw.log"] = (self.extra / "raw.log").read_bytes()
            self.assertEqual({name: archive.read(name) for name in archive.namelist()}, expected)
            self.assertEqual(archive.read("evidence/" + pack.runner.RECEIPT_PATH),
                             originals[pack.runner.RECEIPT_PATH])

    def test_outputs_are_private_even_with_permissive_umask(self):
        previous = os.umask(0)
        try:
            self.success()
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in self.output.iterdir()))

    def test_requires_explicit_writers_finished_assertion(self):
        arguments = self.arguments()
        arguments["writers_finished"] = False
        with self.assertRaisesRegex(ValueError, "stop and wait"):
            pack.package_success(**arguments)
        self.assertFalse(self.output.exists())

    def test_refuses_existing_output_without_overwriting_any_bytes(self):
        self.success()
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        with self.assertRaises(FileExistsError):
            self.success()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_refuses_output_under_workspace_source_or_extra_root(self):
        for root in (self.workspace, self.source, self.extra):
            with self.subTest(root=root.name):
                arguments = self.arguments()
                arguments["output_dir"] = root / "out"
                with self.assertRaisesRegex(ValueError, "overlap"):
                    pack.package_success(**arguments)
                self.assertFalse((root / "out").exists())

    def test_refuses_overlapping_or_unsafe_extra_roots(self):
        for roots in ({"same": self.evidence}, {"all": self.workspace},
                      {"../escape": self.extra}, {"C:drive": self.extra},
                      {"bad\\name": self.extra}, {"a": self.extra, "b": self.extra}):
            with self.subTest(labels=list(roots)):
                arguments = self.arguments()
                arguments["extra_roots"] = roots
                with self.assertRaises(ValueError):
                    pack.package_success(**arguments)
                self.assertFalse(self.output.exists())

    def test_refuses_symlink_ancestor_and_traversal_output(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for output in (alias / "output", str(self.root) + "/../unsafe", str(self.root) + "//unsafe"):
            with self.subTest(output=str(output)):
                arguments = self.arguments()
                arguments["output_dir"] = output
                with self.assertRaises((OSError, ValueError)):
                    pack.package_success(**arguments)
        self.assertFalse(self.output.exists())

    def test_refuses_symlink_file_or_directory(self):
        for name, target in (("link", self.extra / "raw.log"), ("directory", self.extra)):
            with self.subTest(name=name):
                path = self.evidence / "qualified-warm" / name
                path.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "links and special"):
                    self.success()
                self.failure_receipt()
                path.unlink()
                self.output = self.root / (name + "-next")

    def test_refuses_hardlinks_and_special_fifo(self):
        linked = self.evidence / "qualified-warm/hardlink"
        os.link(self.extra / "raw.log", linked)
        with self.assertRaisesRegex(ValueError, "single-link|links and special"):
            self.success()
        self.failure_receipt()
        linked.unlink()
        self.output = self.root / "fifo-output"
        fifo = self.evidence / "qualified-warm/fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "links and special"):
            self.success()
        self.failure_receipt()

    def test_refuses_nonportable_member_names(self):
        self.put("qualified-warm/back\\slash", b"opaque")
        with self.assertRaises(ValueError):
            self.success()
        self.failure_receipt()

    def test_success_rejects_unfinished_report(self):
        self.run["state"] = "running"
        self.write_json(pack.runner.RECEIPT_PATH, self.run)
        with self.assertRaisesRegex(ValueError, "finished reports"):
            self.success()
        self.failure_receipt()
        self.assertFalse((self.output / pack.ORIGINAL_NAME).exists())

    def test_success_rejects_failed_cleanup_and_malformed_started_boolean(self):
        for change in ({"cleanup_complete": False}, {"process_started": 1}):
            with self.subTest(change=change):
                self.make_success()
                self.run["stages"][0].update(change)
                self.write_json(pack.runner.RECEIPT_PATH, self.run)
                with self.assertRaisesRegex(ValueError, "finished reports"):
                    self.success()
                self.failure_receipt()
                self.output = self.root / ("next-" + next(iter(change)))

    def test_success_rejects_missing_or_tampered_full_orchestration_evidence(self):
        cases = (pack.runner.LOG_ROOT + "/qualified-warm.log",
                 pack.runner.SOURCE_ROOT + "/" + pack.runner.SOURCE_FILES[0], "dependency-build/report.json")
        for index, name in enumerate(cases):
            with self.subTest(name=name):
                self.make_success()
                (self.evidence / name).write_bytes(b"changed\n")
                with self.assertRaises(ValueError):
                    self.success()
                self.failure_receipt()
                self.output = self.root / ("tamper-output-" + str(index))

    def test_success_requires_exact_ordered_helper_population(self):
        source_name = pack.runner.SOURCE_ROOT + "/ci/project/selected.py"
        self.put(source_name, b"arbitrary inert helper\n")
        arbitrary = dict(self.descriptor(source_name), path="ci/project/selected.py")
        selected = self.run["selected_sources_before"]
        cases = {"arbitrary-only": [arbitrary], "duplicate-only": [arbitrary, arbitrary],
                 "missing": selected[:-1], "extra": selected + [arbitrary],
                 "duplicate": selected[:-1] + [selected[0]], "reordered": selected[::-1]}
        for name, descriptors in cases.items():
            with self.subTest(name=name):
                self.run["selected_sources_before"] = descriptors
                self.run["selected_sources_after"] = descriptors
                self.write_json(pack.runner.RECEIPT_PATH, self.run)
                with self.assertRaisesRegex(ValueError, "helper population"):
                    self.success()
                self.assertEqual(self.failure_receipt()["stage"], "writer-observations")
                self.assertFalse(any(self.output.glob("*.zip")))
                self.assertFalse((self.output / pack.RECEIPT_NAME).exists())
                self.output = self.root / (name + "-next")

    def test_success_rejects_malformed_helper_descriptors_and_changed_after_inventory(self):
        selected = self.run["selected_sources_before"]
        first = selected[0]
        invalid = (None, [], {}, dict(first, path=None), dict(first, path="../escape"),
                   dict(first, sha256="0" * 64), dict(first, size_bytes=str(first["size_bytes"])),
                   dict(first, size_bytes=float(first["size_bytes"])), dict(first, unexpected=True))
        for index, descriptor in enumerate(invalid):
            with self.subTest(index=index):
                self.run["selected_sources_before"] = [descriptor] + selected[1:]
                self.run["selected_sources_after"] = [descriptor] + selected[1:]
                self.write_json(pack.runner.RECEIPT_PATH, self.run)
                with self.assertRaises(ValueError):
                    self.success()
                self.failure_receipt()
                self.assertFalse(any(self.output.glob("*.zip")))
                self.output = self.root / ("malformed-next-" + str(index))
        self.run["selected_sources_before"] = selected
        for index, after in enumerate((None, selected[:-1], selected[::-1],
                [dict(first, size_bytes=float(first["size_bytes"]))] + selected[1:])):
            with self.subTest(after=index):
                self.run["selected_sources_after"] = after
                self.write_json(pack.runner.RECEIPT_PATH, self.run)
                with self.assertRaises(ValueError):
                    self.success()
                self.failure_receipt()
                self.output = self.root / ("changed-after-next-" + str(index))

    def test_partial_preserves_incomplete_helper_population_without_complete_claim(self):
        import shutil
        shutil.rmtree(self.evidence / pack.runner.SOURCE_ROOT)
        source_name = pack.runner.SOURCE_ROOT + "/ci/project/selected.py"
        self.put(source_name, b"arbitrary inert helper\n")
        descriptor = dict(self.descriptor(source_name), path="ci/project/selected.py")
        self.run["selected_sources_before"] = [descriptor, descriptor]
        self.run["selected_sources_after"] = [descriptor, descriptor]
        self.write_json(pack.runner.RECEIPT_PATH, self.run)
        originals = self.tree_bytes()
        receipt = self.partial()
        self.assertTrue(receipt["partial_attempt"])
        self.assertFalse(receipt["complete_replay_original_created"])
        self.assertFalse(receipt["writer_observations"]["finished_cleanup_records_verified"])
        with zipfile.ZipFile(self.output / pack.PARTIAL_NAME) as archive:
            self.assertEqual({name: archive.read(name) for name in archive.namelist()
                              if name.startswith("partial-attempt/evidence/")},
                             {"partial-attempt/evidence/" + name: body for name, body in originals.items()})

    def test_partial_preserves_missing_native_root_without_fabrication(self):
        import shutil
        shutil.rmtree(self.evidence / "qualified-warm")
        self.run.update(state="finished", outcome="fail", orchestration_passed=False)
        self.write_json(pack.runner.RECEIPT_PATH, self.run)
        receipt = self.partial()
        self.assertTrue(receipt["partial_attempt"])
        self.assertFalse(receipt["complete_replay_original_created"])
        self.assertFalse((self.evidence / "qualified-warm").exists())
        self.assertFalse((self.output / pack.ORIGINAL_NAME).exists())
        with zipfile.ZipFile(self.output / pack.PARTIAL_NAME) as archive:
            self.assertTrue(all(name.startswith("partial-attempt/") for name in archive.namelist()))
            self.assertFalse(any("/qualified-warm/" in name for name in archive.namelist()))
            self.assertIn("partial-attempt/evidence/dependency-build/payloads/.retention.lock", archive.namelist())
        self.assertIn({"report": "qualified-warm/report.json", "observation": "missing"},
                      receipt["writer_observations"]["unresolved"])

    def test_partial_keeps_malformed_unfinished_and_failed_cleanup_records_verbatim(self):
        malformed = b'{"state":"running","state":"finished"}\xff'
        self.put("qualified-warm/report.json", malformed)
        self.run["state"] = "running"
        self.run["stages"][0]["cleanup_complete"] = False
        self.write_json(pack.runner.RECEIPT_PATH, self.run)
        receipt = self.partial()
        observations = {row["observation"] for row in receipt["writer_observations"]["unresolved"]}
        self.assertTrue({"malformed", "unfinished", "cleanup-unresolved"} <= observations)
        with zipfile.ZipFile(self.output / pack.PARTIAL_NAME) as archive:
            self.assertEqual(archive.read("partial-attempt/evidence/qualified-warm/report.json"), malformed)
        self.assertTrue(all(receipt[field] is False for field in pack.runner.qualification.FALSE_CLAIMS))

    def test_partial_can_preserve_explicit_acquisition_before_workspace_exists(self):
        arguments = self.arguments()
        arguments["workspace_dir"] = self.root / "never-created-workspace"
        receipt = pack.package_partial(**arguments)
        self.assertEqual(receipt["missing_selected_roots"], ["evidence"])
        self.assertFalse(arguments["workspace_dir"].exists())
        with zipfile.ZipFile(self.output / pack.PARTIAL_NAME) as archive:
            self.assertEqual(archive.namelist(), ["partial-attempt/additional-evidence/acquisition/raw.log"])

    def test_missing_extra_evidence_rejects_success_but_is_recorded_in_partial(self):
        arguments = self.arguments()
        arguments["extra_roots"] = {"missing": self.root / "missing"}
        with self.assertRaisesRegex(ValueError, "missing a selected"):
            pack.package_success(**arguments)
        self.failure_receipt()
        arguments["output_dir"] = self.root / "partial-next"
        receipt = pack.package_partial(**arguments)
        self.assertEqual(receipt["missing_selected_roots"], ["additional-evidence/missing"])

    def test_source_mutation_during_copy_rejects_and_keeps_partial_bytes(self):
        original = pack._write_zip

        def mutate(path, members):
            self.put("qualified-warm/opaque/native.bin", b"mutated")
            return original(path, members)

        with mock.patch.object(pack, "_write_zip", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "source identity changed"):
                self.success()
        self.failure_receipt()
        self.assertTrue(list(self.output.glob("incomplete-*.zip")))
        self.assertFalse((self.output / pack.RECEIPT_NAME).exists())

    def test_final_inventory_detects_new_member_and_identical_byte_replacement(self):
        original = pack._verify_zip
        for mutation in ("add", "replace"):
            with self.subTest(mutation=mutation):
                def change_after_verify(path, members, final_name):
                    result = original(path, members, final_name)
                    if final_name == pack.ENVELOPE_NAME:
                        if mutation == "add":
                            self.put("qualified-warm/late-side-output", b"new")
                        else:
                            selected = self.evidence / "qualified-warm/opaque/native.bin"
                            body = selected.read_bytes()
                            selected.unlink()
                            selected.write_bytes(body)
                    return result

                with mock.patch.object(pack, "_verify_zip", side_effect=change_after_verify):
                    with self.assertRaisesRegex(ValueError, "identities or bytes changed"):
                        self.success()
                self.failure_receipt()
                self.output = self.root / (mutation + "-next")

    def test_zip_reread_detects_member_byte_corruption(self):
        original = pack._write_zip

        def corrupt(path, members):
            original(path, members)
            if path.name.endswith(pack.ORIGINAL_NAME):
                with zipfile.ZipFile(path) as archive:
                    entries = [(item, archive.read(item)) for item in archive.infolist()]
                with zipfile.ZipFile(path, "w") as archive:
                    for index, (item, body) in enumerate(entries):
                        archive.writestr(item, b"corrupt" if index == 0 else body)

        with mock.patch.object(pack, "_write_zip", side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, "ZIP member differs"):
                self.success()
        self.failure_receipt()

    def test_zip_reread_rejects_duplicate_and_traversal_members(self):
        import warnings
        original = pack._write_zip
        for mutation in ("duplicate", "traversal"):
            with self.subTest(mutation=mutation):
                def corrupt(path, members):
                    original(path, members)
                    if path.name.endswith(pack.ORIGINAL_NAME):
                        with warnings.catch_warnings(), zipfile.ZipFile(path, "a") as archive:
                            warnings.simplefilter("ignore", UserWarning)
                            archive.writestr(next(iter(members)) if mutation == "duplicate" else "../escape", b"extra")

                with mock.patch.object(pack, "_write_zip", side_effect=corrupt):
                    with self.assertRaises(ValueError):
                        self.success()
                self.failure_receipt()
                self.output = self.root / (mutation + "-next")

    def test_enforces_existing_member_expanded_entry_and_compressed_bounds(self):
        for name, bound in (("MAX_MEMBER_BYTES", 32), ("MAX_EXPANDED_BYTES", 32),
                            ("MAX_MEMBERS", 3), ("MAX_ARCHIVE_BYTES", 200),
                            ("MAX_DIRECTORY_BYTES", 32)):
            with self.subTest(bound=name):
                with mock.patch.object(pack, name, bound):
                    with self.assertRaises(ValueError):
                        self.success()
                self.failure_receipt()
                if name == "MAX_ARCHIVE_BYTES":
                    self.assertTrue(all(path.stat().st_size <= bound for path in self.output.glob("*.zip")))
                self.output = self.root / name.lower()

    def test_interrupt_preserves_partial_bytes_and_failure_receipt(self):
        original = pack._read_file

        def interrupt(path, **kwargs):
            if kwargs.get("destination") is not None:
                kwargs["destination"].write(b"already-copied")
                raise KeyboardInterrupt()
            return original(path, **kwargs)

        with mock.patch.object(pack, "_read_file", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.success()
        failure = self.failure_receipt()
        self.assertEqual(failure["error_type"], "KeyboardInterrupt")
        partial = list(self.output.glob("incomplete-*.zip"))
        self.assertEqual(len(partial), 1)
        self.assertGreater(partial[0].stat().st_size, 0)
        self.assertFalse((self.output / pack.ORIGINAL_NAME).exists())

    def test_publication_does_not_overwrite_collision_and_relabels_other_created_zip(self):
        original = pack._publish

        for name in (pack.ENVELOPE_NAME, pack.RECEIPT_NAME):
            with self.subTest(name=name):
                def collision(source, target):
                    if target.name == name:
                        target.write_bytes(b"pre-existing racer")
                    return original(source, target)

                with mock.patch.object(pack, "_publish", side_effect=collision):
                    with self.assertRaises(FileExistsError):
                        self.success()
                self.failure_receipt()
                self.assertEqual((self.output / name).read_bytes(), b"pre-existing racer")
                self.assertTrue((self.output / ("incomplete-" + pack.ORIGINAL_NAME)).exists())
                self.assertFalse((self.output / pack.ORIGINAL_NAME).exists())
                self.output = self.root / (name + "-next")

    def test_publication_interruption_withdraws_final_receipt_and_keeps_owned_bytes(self):
        original = Path.unlink
        originals = self.tree_bytes()
        for name in (pack.ORIGINAL_NAME, pack.RECEIPT_NAME):
            for after_unlink in (False, True):
                with self.subTest(name=name, after_unlink=after_unlink):
                    interrupted = False
                    temporary = self.output / ("incomplete-" + name)

                    def interrupt(path, *args, **kwargs):
                        nonlocal interrupted
                        if path == temporary and not interrupted:
                            interrupted = True
                            if after_unlink:
                                original(path, *args, **kwargs)
                            raise KeyboardInterrupt()
                        return original(path, *args, **kwargs)

                    with mock.patch.object(Path, "unlink", interrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            self.success()
                    self.assertTrue(interrupted)
                    self.assertEqual(self.failure_receipt()["error_type"], "KeyboardInterrupt")
                    self.assertTrue(temporary.is_file())
                    self.assertEqual(temporary.stat().st_nlink, 1)
                    self.assertFalse(any((self.output / final).exists() for final in
                                         (pack.ORIGINAL_NAME, pack.ENVELOPE_NAME, pack.RECEIPT_NAME)))
                    self.assertEqual(self.tree_bytes(), originals)
                    self.output = self.root / (name + "-" + str(after_unlink))

    def test_final_publication_rehash_rejects_changed_zip_bytes(self):
        original = pack._publish

        def corrupt(source, target):
            original(source, target)
            if target.name == pack.ORIGINAL_NAME:
                target.write_bytes(b"changed after verification")

        with mock.patch.object(pack, "_publish", side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, "ZIP bytes changed after verification"):
                self.success()
        failure = self.failure_receipt()
        self.assertFalse((self.output / pack.RECEIPT_NAME).exists())
        self.assertFalse((self.output / pack.ORIGINAL_NAME).exists())
        retained = next(row for row in failure["created_files"] if row["filename"].endswith(pack.ORIGINAL_NAME))
        body = (self.output / retained["filename"]).read_bytes()
        self.assertEqual(retained["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(retained["size_bytes"], len(body))

    def test_failed_receipt_withdrawal_keeps_referenced_archives_and_failure_status(self):
        original = pack._publish
        originals = self.tree_bytes()
        for after_link in (False, True):
            with self.subTest(after_link=after_link):
                self.output = self.root / ("failed-withdrawal-" + str(after_link))
                receipt_bytes = None

                def interrupt_and_fail_rollback(source, target):
                    nonlocal receipt_bytes
                    if source.name == pack.RECEIPT_NAME:
                        if after_link:
                            os.link(source, target, follow_symlinks=False)
                        raise OSError("injected receipt withdrawal failure")
                    original(source, target)
                    if target.name == pack.RECEIPT_NAME:
                        receipt_bytes = target.read_bytes()
                        raise KeyboardInterrupt()

                with mock.patch.object(pack, "_publish", side_effect=interrupt_and_fail_rollback):
                    with self.assertRaises(KeyboardInterrupt):
                        self.success()
                self.assertIsNotNone(receipt_bytes)
                self.assertEqual((self.output / pack.RECEIPT_NAME).read_bytes(), receipt_bytes)
                receipt = json.loads(receipt_bytes)
                self.assertTrue(receipt["packaging_passed"])
                failure = self.failure_receipt()
                self.assertEqual(failure["error_type"], "KeyboardInterrupt")
                self.assertEqual(failure["stage"], "publish")
                retained = {row["filename"]: row for row in failure["created_files"]}
                for artifact in receipt["archives"]:
                    path = self.output / artifact["filename"]
                    self.assertTrue(path.is_file())
                    body = path.read_bytes()
                    self.assertEqual(path.stat().st_nlink, 1)
                    self.assertEqual(artifact["sha256"], hashlib.sha256(body).hexdigest())
                    self.assertEqual(artifact["size_bytes"], len(body))
                    self.assertEqual(retained[path.name]["sha256"], artifact["sha256"])
                    self.assertEqual(retained[path.name]["size_bytes"], artifact["size_bytes"])
                self.assertTrue(failure["published_receipt_withdrawal_unresolved"])
                self.assertEqual(set(retained), {pack.ORIGINAL_NAME, pack.ENVELOPE_NAME})
                self.assertFalse(list(self.output.glob("incomplete-*.zip")))
                self.assertEqual(self.tree_bytes(), originals)

    def test_cli_success_and_failure_never_print_raw_evidence_or_sensitive_paths(self):
        base = ["success", "--source-dir", str(self.source), "--workspace-dir", str(self.workspace),
                "--output-dir", str(self.output), "--writers-finished", "--extra-root",
                "acquisition=" + str(self.extra)]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(pack.main(base), 0)
        self.assertEqual(json.loads(output.getvalue())["classification"], "PRIVATE")
        self.assertNotIn(str(self.root), output.getvalue())
        self.assertNotIn("Micron", output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(pack.main(base), 1)
        self.assertFalse(json.loads(output.getvalue())["packaging_passed"])
        self.assertNotIn(str(self.root), output.getvalue())

    def test_cli_rejects_duplicate_extra_root_labels(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = pack.main(["partial", "--source-dir", str(self.source), "--workspace-dir", str(self.workspace),
                              "--output-dir", str(self.output), "--writers-finished",
                              "--extra-root", "same=" + str(self.extra), "--extra-root", "same=" + str(self.extra)])
        self.assertEqual(code, 1)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
