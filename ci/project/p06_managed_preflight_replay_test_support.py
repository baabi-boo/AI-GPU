# SPDX-License-Identifier: Apache-2.0
"""Mutation helpers for inert copies of the independently pinned original archive.

Packet is a context-managed mutable overlay: reads never modify the original,
and write() streams one unchanged member at a time. json() and report return
detached values; use edit_json()/edit_report() or assign encoded bytes to save.
Descriptor repair is automatic for replace_retained(), but semantic observations
and binding identities are changed only by an explicit helper call.
"""

from collections.abc import MutableMapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "docs/project/evidence/p06-managed-preflight/native"
ORIGINAL = NATIVE / "run-45085300171-attempt1.zip"
ORIGINAL_SHA256 = "cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d"
REVISION = "57248e73dfce4ae2d21d2cbdb82c3953eef2e3db"
SOURCE_INVENTORY = NATIVE / "source-inventory-57248e73.json"
SOURCE_INVENTORY_SHA256 = "72ca7e9237060ca2831a275811d27ec6fdb3507dfd9a00b693aa177aa68382e8"
SOURCE_DERIVATION = NATIVE / "source-derivation-57248e73.json"
SOURCE_DERIVATION_SHA256 = "3b25d30eceeee2dc5cebd1cce8ed7ab90da0fec64857e82fc7cc7fc3ca38e171"
FAILED_ORIGINAL = NATIVE / "run-45084009157-attempt1.zip"
FAILED_SHA256 = "4f1e177ba930c132f5e8cc7558b3087d39789c346763f00a9d1bdd2a6d17d00c"
FAILED_REVISION = "8756f40029e59c87546fa22f4da33acd4e5d8e02"
FAILED_INVENTORY = NATIVE / "source-inventory-8756f400-replay.json"
FAILED_INVENTORY_SHA256 = "57a1290e4cadb7e357d109b49ff7e2ee85459c42b9a54d9522e1e178f3323c30"
FAILED_DERIVATION = NATIVE / "source-derivation-8756f400-replay.json"
FAILED_DERIVATION_SHA256 = "492b142b047e71a84a62425aebf5d46bb35f2ec022a173d42d6463e04fe834b8"
PREFIX = "managed-preflight/"
REPORT = PREFIX + "report.json"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def descriptor(relative, body):
    return {"path": relative, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def binding_digest(value):
    return hashlib.sha256(encoded(value)[:-1]).hexdigest()


def _repair_descriptors(value, replacements):
    changed = False
    if type(value) is dict:
        if type(value.get("path")) is str and value["path"] in replacements and {"sha256", "size_bytes"} <= value.keys():
            replacement = replacements[value["path"]]
            for key in ("sha256", "size_bytes"):
                if value[key] != replacement[key]:
                    value[key] = replacement[key]
                    changed = True
        for child in value.values():
            changed = _repair_descriptors(child, replacements) or changed
    elif type(value) is list:
        for child in value:
            changed = _repair_descriptors(child, replacements) or changed
    return changed


def _replace_identity(value, old, new):
    if type(value) is str:
        return new if value == old else value
    if type(value) is dict:
        return {key: _replace_identity(child, old, new) for key, child in value.items()}
    if type(value) is list:
        return [_replace_identity(child, old, new) for child in value]
    return value


class Packet(MutableMapping):
    """Overlay original ZIP members; close it with a with block."""

    def __init__(self, path=ORIGINAL, sha256=ORIGINAL_SHA256):
        self.original = Path(path)
        if digest_file(self.original) != sha256:
            raise AssertionError("original fixture differs from its independent digest")
        self.archive = zipfile.ZipFile(self.original, "r")
        self.names = tuple(row.filename for row in self.archive.infolist() if not row.is_dir())
        if len(set(self.names)) != len(self.names):
            self.archive.close()
            raise AssertionError("original fixture has duplicate members")
        self.original_names = set(self.names)
        self.overlay = {}
        self.deleted = set()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.archive.close()

    def __getitem__(self, name):
        if name in self.deleted:
            raise KeyError(name)
        if name in self.overlay:
            return self.overlay[name]
        return self.archive.read(name)

    def __setitem__(self, name, body):
        if type(name) is not str or type(body) is not bytes:
            raise TypeError("packet members require string names and byte bodies")
        self.overlay[name] = body
        self.deleted.discard(name)

    def __delitem__(self, name):
        if name not in self:
            raise KeyError(name)
        self.overlay.pop(name, None)
        self.deleted.add(name)

    def __iter__(self):
        yield from (name for name in self.names if name not in self.deleted)
        yield from (name for name in self.overlay if name not in self.original_names and name not in self.deleted)

    def __len__(self):
        return sum(1 for _ in self)

    def __contains__(self, name):
        return name not in self.deleted and (name in self.original_names or name in self.overlay)

    def _name(self, name):
        return name if name.startswith(PREFIX) or name in self else PREFIX + name

    def json(self, name):
        return json.loads(self[self._name(name)])

    @property
    def report(self):
        return self.json(REPORT)

    def edit_report(self, change):
        value = self.report
        change(value)
        self[REPORT] = encoded(value)

    def edit_json(self, name, change):
        name = self._name(name)
        value = self.json(name)
        change(value)
        self.replace_retained(name, encoded(value))

    def _control_names(self):
        return [name for name in self if name == REPORT or
                name.startswith(PREFIX + "snapshots/") and name.endswith(".json")]

    def repair_descriptors(self, identities):
        """Propagate explicit member identities through retained JSON descriptors."""
        pending = dict(identities)
        for _ in range(8):
            following = {}
            for name in self._control_names():
                value = self.json(name)
                if _repair_descriptors(value, pending):
                    self[name] = encoded(value)
                    if name != REPORT:
                        relative = name.removeprefix(PREFIX)
                        following[relative] = descriptor(relative, self[name])
            if not following:
                return
            pending = following
        raise AssertionError("descriptor repair did not converge")

    def replace_retained(self, relative, body, *, aliases=()):
        """Replace bytes and hash references; aliases apply to every control JSON."""
        name = self._name(relative)
        self[name] = body
        if name.startswith(PREFIX) and name != REPORT:
            relative = name.removeprefix(PREFIX)
            self.repair_descriptors({key: descriptor(key, body) for key in (relative, *aliases)})

    def replace_log(self, command_id, transform):
        report = self.report
        command = next(row for row in report["commands"] if row["id"] == command_id)
        original = self[PREFIX + command["log"]]
        body = transform(original)
        if type(body) is not bytes or body == original:
            raise AssertionError("log mutation must change its selected bytes")
        identity = descriptor(command["log"], body)
        command.update(log_sha256=identity["sha256"], log_size_bytes=identity["size_bytes"])
        self[REPORT] = encoded(report)
        self.replace_retained(command["log"], body)

    def rehash_snapshots(self):
        """Explicitly synchronize build copies and stability digests to before snapshots."""
        report = self.report
        snapshots = {key: self.json(report[key + "_before"]["path"])
                     for key in ("source", "tools", "dependencies")}
        for variant in report["variants"]:
            binding = self.json(variant["binding"]["path"])
            binding.update(deepcopy(snapshots))
            self.replace_retained(variant["binding"]["path"], encoded(binding))
        self.edit_report(lambda value: [row.update({key + "_sha256": binding_digest(snapshot)
            for key, snapshot in snapshots.items()}) for row in value["stability_checks"]])

    def rehash_bindings(self):
        """Explicitly propagate build/process identities, including observation/log IDs."""
        report = self.report
        bindings = {}
        for variant in report["variants"]:
            value = self.json(variant["binding"]["path"])
            variant["build_binding_sha256"] = binding_digest(value)
            bindings[variant["format"]] = value
        self[REPORT] = encoded(report)
        for process_id in [row["id"] for row in report["processes"]]:
            report = self.report
            process = next(row for row in report["processes"] if row["id"] == process_id)
            binding = self.json(process["binding"]["path"])
            binding["build"] = deepcopy(bindings[process["format"]])
            binding["build_binding_sha256"] = binding_digest(binding["build"])
            old, new = process["execution_binding_sha256"], binding_digest(binding)
            process["build_binding_sha256"] = binding["build_binding_sha256"]
            report = _replace_identity(report, old, new)
            self[REPORT] = encoded(report)
            self.replace_retained(process["binding"]["path"], encoded(binding))
            if old != new:
                observation_path = process["retained_observation"]["path"]
                observation = _replace_identity(self.json(observation_path), old, new)
                self.replace_log(process["command_id"], lambda body: body.replace(old.encode(), new.encode()))
                body = self[PREFIX + process["log"]]
                warm, separator, witness = body[:-1].rpartition(b"\n")
                if not body.endswith(b"\n") or not separator or not (warm + separator).endswith(b"PASSED!\n"):
                    raise AssertionError("managed log must end with a witness after warm success")
                raw_digest = hashlib.sha256(warm + separator).hexdigest()
                observation["warm"]["raw_log_sha256"] = raw_digest
                self.replace_retained(observation_path, encoded(observation))
                self.edit_report(lambda value: next(row for row in value["processes"]
                    if row["id"] == process_id)["observation"]["warm"].__setitem__("raw_log_sha256", raw_digest))

    def write(self, path):
        path = Path(path)
        if path.resolve() == self.original.resolve():
            raise AssertionError("a mutation must not overwrite its original")
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as output:
            for name in self:
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                output.writestr(info, self[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
        return digest_file(path)


def replay(path=ORIGINAL, sha256=ORIGINAL_SHA256, *, revision=REVISION,
           inventory=SOURCE_INVENTORY, inventory_sha256=SOURCE_INVENTORY_SHA256,
           derivation=SOURCE_DERIVATION, derivation_sha256=SOURCE_DERIVATION_SHA256, **kwargs):
    import p06_managed_preflight_replay as reader
    return reader.replay_archive(path, sha256, expected_revision=revision,
        source_inventory_path=inventory, source_inventory_sha256=inventory_sha256,
        source_derivation_path=derivation, source_derivation_sha256=derivation_sha256, **kwargs)
