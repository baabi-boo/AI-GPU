#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate the ADR-006 pre-silicon tapeout readiness ledger offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = Path("docs/project/presilicon_readiness.json")
DEFAULT_ROADMAP_PATH = Path("docs/project/roadmap.json")

ALLOWED_LEVELS = ("source_present", "simulated", "rtl_verified")
FORBIDDEN_LEVELS = ("fpga_measured", "silicon_measured")
ALL_LEVELS = ALLOWED_LEVELS + FORBIDDEN_LEVELS
ALLOWED_STATUSES = ("not_started", "in_progress", "complete")
EXPECTED_TRACK_IDS = ("TRACK-A", "TRACK-B", "TRACK-C", "TRACK-D", "TRACK-E", "TRACK-F")
EXPECTED_TARGET_ARCHITECTURE = "aigpu-b1"
EXPECTED_RTL_SLICE_PROFILE = "aigpu-b1-tile"
EXPECTED_ADR = "ADR-006"

HEX_COMMIT_RE = re.compile(r"[0-9a-fA-F]{7,64}\Z")
HEX64_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
FORBIDDEN_LEVEL_TOKEN_RE = re.compile(r"\b(?:fpga_measured|silicon_measured)\b", re.IGNORECASE)

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

EXPECTED_TOP_KEYS = (
    "schema_version",
    "adr",
    "target_architecture",
    "target_silicon_class",
    "rtl_slice_profile",
    "rtl_slice_description",
    "allowed_evidence_levels",
    "forbidden_evidence_levels",
    "physical_gates_unwaived",
    "roadmap_reference",
    "tracks",
)
EXPECTED_TRACK_KEYS = (
    "id",
    "title",
    "status",
    "required_evidence_level",
    "deliverables",
    "acceptance_criteria",
    "evidence",
)
EXPECTED_EVIDENCE_KEYS = (
    "path",
    "sha256",
    "evidence_level",
    "commit",
    "summary",
)
PHYSICAL_PHASE_IDS = ("P07", "P08", "P09", "P10", "P11")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _load_json(path: Path, where: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            errors.append(f"{where}: missing file: {path}")
            return None
        if path.stat().st_size > MAX_JSON_BYTES:
            errors.append(f"{where}: file exceeds {MAX_JSON_BYTES} bytes")
            return None
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{where}: cannot read UTF-8 JSON ({type(exc).__name__})")
        return None
    try:
        data = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError) as exc:
        errors.append(f"{where}: invalid JSON ({exc})")
        return None
    if not isinstance(data, dict):
        errors.append(f"{where}: JSON root must be an object")
        return None
    return data


def _check_object_keys(
    obj: Any,
    expected_keys: tuple[str, ...],
    where: str,
    errors: list[str],
) -> bool:
    if not isinstance(obj, dict):
        errors.append(f"{where}: expected a JSON object")
        return False
    missing = set(expected_keys) - obj.keys()
    extra = obj.keys() - set(expected_keys)
    if missing:
        errors.append(f"{where}: missing fields: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"{where}: unknown fields: {', '.join(sorted(map(str, extra)))}")
    return not missing and not extra


def _nonempty_str(value: Any, where: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: expected a nonempty string")
        return False
    return True


def _nonempty_str_list(value: Any, where: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        errors.append(f"{where}: expected a nonempty list of strings")
        return []
    items: list[str] = []
    for idx, item in enumerate(value):
        if _nonempty_str(item, f"{where}[{idx}]", errors):
            if item in items:
                errors.append(f"{where}: duplicate entry {item!r}")
            else:
                items.append(item)
    return items


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_repo_file(value: Any, root: Path, where: str, errors: list[str]) -> Path | None:
    if not _nonempty_str(value, where, errors):
        return None
    if (
        PurePosixPath(value).is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
        or any(char in value for char in ("\x00", "#", "?"))
    ):
        errors.append(f"{where}: requires a canonical repository-relative path")
        return None
    try:
        resolved = (root / value).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{where}: cannot resolve path ({type(exc).__name__})")
        return None
    if not _inside(resolved, root):
        errors.append(f"{where}: path escapes repository")
        return None
    if not resolved.is_file():
        errors.append(f"{where}: missing file on disk: {value}")
        return None
    return resolved


def _sha256_file(path: Path, where: str, errors: list[str]) -> str | None:
    try:
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            errors.append(f"{where}: artifact exceeds limit of {MAX_ARTIFACT_BYTES} bytes")
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        errors.append(f"{where}: cannot hash file ({type(exc).__name__})")
        return None


def _scan_forbidden_level_claims(
    value: Any,
    where: str,
    errors: list[str],
    *,
    skip_keys: frozenset[str] = frozenset(),
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in skip_keys:
                continue
            _scan_forbidden_level_claims(item, f"{where}.{key}", errors)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _scan_forbidden_level_claims(item, f"{where}[{idx}]", errors)
    elif isinstance(value, str):
        if value in FORBIDDEN_LEVELS:
            errors.append(
                f"{where}: forbidden physical/silicon evidence level {value!r} "
                f"is prohibited in the pre-silicon ledger"
            )
        elif FORBIDDEN_LEVEL_TOKEN_RE.search(value) and (
            where.endswith(".evidence_level")
            or where.endswith(".required_evidence_level")
            or ".allowed_evidence_levels" in where
        ):
            errors.append(
                f"{where}: forbidden evidence level reference {value!r} in pre-silicon scope"
            )


def _validate_roadmap_honesty(
    roadmap: dict[str, Any],
    root: Path,
    errors: list[str],
) -> None:
    phases = roadmap.get("phases")
    if not isinstance(phases, list):
        errors.append("roadmap.phases: expected a list")
        return
    phase_map = {
        phase.get("id"): phase
        for phase in phases
        if isinstance(phase, dict) and isinstance(phase.get("id"), str)
    }

    p01 = phase_map.get("P01")
    if p01 is None:
        errors.append("roadmap: missing required phase P01")
    else:
        p01_status = p01.get("status")
        if p01_status == "complete":
            p01_ev = p01.get("evidence")
            a03_records = [
                ref for ref in (p01_ev if isinstance(p01_ev, list) else [])
                if isinstance(ref, dict) and ref.get("acceptance_id") == "P01-A03"
            ]
            if not a03_records:
                errors.append("roadmap.P01: marked complete without P01-A03 evidence")
            else:
                a03_passed = False
                for ref in a03_records:
                    rec_rel = ref.get("record")
                    rec_path = _resolve_repo_file(rec_rel, root, "roadmap.P01.P01-A03", errors)
                    if rec_path is None:
                        continue
                    rec_data = _load_json(rec_path, "roadmap.P01.P01-A03", errors)
                    if (
                        isinstance(rec_data, dict)
                        and rec_data.get("outcome") == "pass"
                        and rec_data.get("evidence_level") in ("rtl_verified", "fpga_measured", "silicon_measured")
                    ):
                        a03_passed = True
                if not a03_passed:
                    errors.append(
                        "roadmap.P01: marked complete without passing P01-A03 hardware-emulation evidence"
                    )
        elif p01_status != "blocked":
            errors.append(
                f"roadmap.P01.status: expected 'blocked' (or 'complete' only if P01-A03 hardware emulation passes), got {p01_status!r}"
            )

        acceptance = p01.get("acceptance")
        if not isinstance(acceptance, list) or not any(
            isinstance(item, dict) and item.get("id") == "P01-A03" for item in acceptance
        ):
            errors.append("roadmap.P01: P01-A03 acceptance criterion was silently removed")

    expected_deps = {
        "P07": ("P01",),
        "P08": ("P07",),
        "P09": ("P08",),
        "P10": ("P08",),
        "P11": ("P10",),
    }
    expected_levels = {
        "P07": "fpga_measured",
        "P08": "fpga_measured",
        "P09": "fpga_measured",
        "P11": "silicon_measured",
    }

    for pid in PHYSICAL_PHASE_IDS:
        phase = phase_map.get(pid)
        if phase is None:
            errors.append(f"roadmap: missing physical/silicon gate phase {pid}")
            continue
        acceptance = phase.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance:
            errors.append(f"roadmap.{pid}: missing acceptance criteria")
            acc_levels: list[Any] = []
        else:
            acc_levels = [
                item.get("evidence_level")
                for item in acceptance
                if isinstance(item, dict)
            ]
        if pid in expected_levels and expected_levels[pid] not in acc_levels:
            errors.append(
                f"roadmap.{pid}: {expected_levels[pid]} acceptance criteria were silently removed"
            )
        deps = phase.get("depends_on")
        for req_dep in expected_deps[pid]:
            if not isinstance(deps, list) or req_dep not in deps:
                errors.append(f"roadmap.{pid}.depends_on: must retain {req_dep} dependency")
        if phase.get("status") == "complete":
            ev = phase.get("evidence")
            if not isinstance(ev, list) or not ev:
                errors.append(
                    f"roadmap.{pid}: physical/silicon gate marked complete without evidence"
                )


def _level_rank(level: str) -> int:
    return ALLOWED_LEVELS.index(level)


def validate_presilicon_data(
    ledger: Any,
    root: Path,
    roadmap: dict[str, Any] | None = None,
) -> list[str]:
    """Validate an already-parsed pre-silicon readiness ledger against root and roadmap."""
    errors: list[str] = []
    try:
        root = Path(root).resolve()
        if not root.is_dir():
            return ["presilicon: project root is not a directory"]
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return [f"presilicon: invalid project root ({type(exc).__name__})"]

    if not _check_object_keys(ledger, EXPECTED_TOP_KEYS, "presilicon", errors):
        if not isinstance(ledger, dict):
            return errors

    # Unconditionally reject any fpga_measured or silicon_measured claim in the ledger
    # outside the explicit forbidden_evidence_levels declaration and roadmap preservation notes.
    _scan_forbidden_level_claims(
        ledger,
        "presilicon",
        errors,
        skip_keys=frozenset({"forbidden_evidence_levels", "roadmap_reference"}),
    )

    if type(ledger.get("schema_version")) is not int or ledger["schema_version"] != 1:
        errors.append("presilicon.schema_version: expected integer 1")
    if ledger.get("adr") != EXPECTED_ADR:
        errors.append(f"presilicon.adr: expected {EXPECTED_ADR!r}")
    if ledger.get("target_architecture") != EXPECTED_TARGET_ARCHITECTURE:
        errors.append(
            f"presilicon.target_architecture: expected {EXPECTED_TARGET_ARCHITECTURE!r}"
        )
    if not _nonempty_str(ledger.get("target_silicon_class"), "presilicon.target_silicon_class", errors):
        pass
    elif "64-core" not in ledger["target_silicon_class"]:
        errors.append("presilicon.target_silicon_class: must record 64-core datacenter AI-only SoC target")
    if ledger.get("rtl_slice_profile") != EXPECTED_RTL_SLICE_PROFILE:
        errors.append(
            f"presilicon.rtl_slice_profile: expected {EXPECTED_RTL_SLICE_PROFILE!r}"
        )
    if not _nonempty_str(ledger.get("rtl_slice_description"), "presilicon.rtl_slice_description", errors):
        pass
    elif "4-core" not in ledger["rtl_slice_description"]:
        errors.append("presilicon.rtl_slice_description: must record 4-core RTL-verifiable compute tile")

    if ledger.get("allowed_evidence_levels") != list(ALLOWED_LEVELS):
        errors.append(
            f"presilicon.allowed_evidence_levels: must equal {list(ALLOWED_LEVELS)!r}"
        )
    if ledger.get("forbidden_evidence_levels") != list(FORBIDDEN_LEVELS):
        errors.append(
            f"presilicon.forbidden_evidence_levels: must equal {list(FORBIDDEN_LEVELS)!r}"
        )

    if ledger.get("physical_gates_unwaived") is not True:
        errors.append("presilicon.physical_gates_unwaived: must be boolean true")

    roadmap_ref = ledger.get("roadmap_reference")
    if _check_object_keys(
        roadmap_ref,
        ("path", "preserved_states"),
        "presilicon.roadmap_reference",
        errors,
    ):
        ref_path = _resolve_repo_file(
            roadmap_ref.get("path"), root, "presilicon.roadmap_reference.path", errors
        )
        if roadmap_ref.get("path") != DEFAULT_ROADMAP_PATH.as_posix():
            errors.append(
                f"presilicon.roadmap_reference.path: must be {DEFAULT_ROADMAP_PATH.as_posix()!r}"
            )
        preserved = roadmap_ref.get("preserved_states")
        if not isinstance(preserved, dict):
            errors.append("presilicon.roadmap_reference.preserved_states: expected an object")
        else:
            for pid in ("P01",) + PHYSICAL_PHASE_IDS:
                if pid not in preserved:
                    errors.append(
                        f"presilicon.roadmap_reference.preserved_states: missing {pid}"
                    )
            p01_ref = preserved.get("P01")
            if isinstance(p01_ref, dict):
                if p01_ref.get("status") not in ("blocked", "complete"):
                    errors.append(
                        "presilicon.roadmap_reference.preserved_states.P01.status: must be 'blocked' (or 'complete' if hardware passed)"
                    )
                blocked_ids = p01_ref.get("blocked_acceptance_ids")
                if p01_ref.get("status") == "blocked" and (
                    not isinstance(blocked_ids, list) or "P01-A03" not in blocked_ids
                ):
                    errors.append(
                        "presilicon.roadmap_reference.preserved_states.P01.blocked_acceptance_ids: must include 'P01-A03'"
                    )
            for pid in PHYSICAL_PHASE_IDS:
                pref = preserved.get(pid)
                if not isinstance(pref, dict) or pref.get("status") != "not_started":
                    errors.append(
                        f"presilicon.roadmap_reference.preserved_states.{pid}.status: must be 'not_started'"
                    )

        if roadmap is None and ref_path is not None:
            roadmap = _load_json(ref_path, "roadmap", errors)

    if roadmap is not None:
        _validate_roadmap_honesty(roadmap, root, errors)

    tracks = ledger.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errors.append("presilicon.tracks: expected a nonempty list")
        return errors

    seen_ids: list[str] = []
    for idx, track in enumerate(tracks):
        where = f"presilicon.tracks[{idx}]"
        if not _check_object_keys(track, EXPECTED_TRACK_KEYS, where, errors):
            if not isinstance(track, dict):
                continue

        track_id = track.get("id")
        if not isinstance(track_id, str) or track_id not in EXPECTED_TRACK_IDS:
            errors.append(
                f"{where}.id: expected one of {EXPECTED_TRACK_IDS!r}, got {track_id!r}"
            )
        elif track_id in seen_ids:
            errors.append(f"{where}.id: duplicate track id {track_id!r}")
        else:
            seen_ids.append(track_id)

        label = track_id if isinstance(track_id, str) and track_id else where
        _nonempty_str(track.get("title"), f"{label}.title", errors)

        status = track.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(
                f"{label}.status: unsupported status {status!r}; allowed: {ALLOWED_STATUSES!r}"
            )

        req_level = track.get("required_evidence_level")
        if req_level in FORBIDDEN_LEVELS:
            errors.append(
                f"{label}.required_evidence_level: forbidden level {req_level!r} not allowed in pre-silicon ledger"
            )
        elif req_level not in ALLOWED_LEVELS:
            errors.append(
                f"{label}.required_evidence_level: unsupported level {req_level!r}; allowed: {ALLOWED_LEVELS!r}"
            )

        _nonempty_str_list(track.get("deliverables"), f"{label}.deliverables", errors)
        _nonempty_str_list(
            track.get("acceptance_criteria"), f"{label}.acceptance_criteria", errors
        )

        evidence = track.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{label}.evidence: expected a list")
            continue

        valid_sufficient_evidence = 0
        for ev_idx, entry in enumerate(evidence):
            ev_where = f"{label}.evidence[{ev_idx}]"
            before_entry_errors = len(errors)
            if not _check_object_keys(entry, EXPECTED_EVIDENCE_KEYS, ev_where, errors):
                if not isinstance(entry, dict):
                    continue

            ev_path = _resolve_repo_file(entry.get("path"), root, f"{ev_where}.path", errors)
            digest = entry.get("sha256")
            if not isinstance(digest, str) or not HEX64_RE.fullmatch(digest):
                errors.append(f"{ev_where}.sha256: expected a 64-hex SHA-256")
            elif ev_path is not None:
                actual_sha = _sha256_file(ev_path, ev_where, errors)
                if actual_sha is not None and actual_sha != digest.lower():
                    errors.append(
                        f"{ev_where}.sha256: SHA-256 mismatch for {entry.get('path')} "
                        f"(expected {digest.lower()}, actual {actual_sha})"
                    )

            commit = entry.get("commit")
            if (
                not isinstance(commit, str)
                or not HEX_COMMIT_RE.fullmatch(commit)
                or set(commit.lower()) == {"0"}
            ):
                errors.append(
                    f"{ev_where}.commit: expected a valid nonzero hex commit hash (7-64 hex chars)"
                )

            _nonempty_str(entry.get("summary"), f"{ev_where}.summary", errors)
            summary_text = entry.get("summary")
            if isinstance(summary_text, str) and FORBIDDEN_LEVEL_TOKEN_RE.search(summary_text):
                if not re.search(
                    r"(?:zero|no|not|without)\s+(?:fpga_measured|silicon_measured)|(?:fpga_measured|silicon_measured)\s*=\s*false",
                    summary_text,
                    re.IGNORECASE,
                ):
                    errors.append(
                        f"{ev_where}.summary: affirmative physical/silicon level reference is prohibited in pre-silicon scope"
                    )

            ev_level = entry.get("evidence_level")
            if ev_level in FORBIDDEN_LEVELS:
                errors.append(
                    f"{ev_where}.evidence_level: forbidden physical/silicon level {ev_level!r} "
                    f"in pre-silicon ledger"
                )
            elif ev_level not in ALLOWED_LEVELS:
                errors.append(
                    f"{ev_where}.evidence_level: unsupported level {ev_level!r}; "
                    f"allowed: {ALLOWED_LEVELS!r}"
                )
            else:
                if ev_level == "rtl_verified" and ev_path is not None:
                    if ev_path.suffix.lower() != ".json":
                        errors.append(
                            f"{ev_where}.path: rtl_verified evidence must reference a structured .json report, got {entry.get('path')!r}"
                        )
                    else:
                        ev_json = _load_json(ev_path, ev_where, errors)
                        if isinstance(ev_json, dict):
                            inner_level = ev_json.get("evidence_level")
                            if inner_level == "source_present":
                                errors.append(
                                    f"{ev_where}.evidence_level: cannot promote source_present JSON artifact {entry.get('path')!r} to rtl_verified"
                                )
                            elif inner_level in FORBIDDEN_LEVELS:
                                errors.append(
                                    f"{ev_where}.path: referenced JSON artifact claims forbidden level {inner_level!r}"
                                )
                if req_level in ALLOWED_LEVELS:
                    if _level_rank(ev_level) < _level_rank(req_level):
                        errors.append(
                            f"{ev_where}.evidence_level: {ev_level!r} is below track "
                            f"required_evidence_level {req_level!r}"
                        )
                    elif len(errors) == before_entry_errors:
                        valid_sufficient_evidence += 1

        if status == "complete":
            if not evidence:
                errors.append(
                    f"{label}: track marked 'complete' cannot have empty evidence"
                )
            elif valid_sufficient_evidence == 0:
                errors.append(
                    f"{label}: track marked 'complete' lacks an evidence entry meeting "
                    f"required_evidence_level {req_level!r}"
                )

    if tuple(seen_ids) != EXPECTED_TRACK_IDS:
        errors.append(
            f"presilicon.tracks: must contain ordered tracks {list(EXPECTED_TRACK_IDS)!r}, "
            f"got {seen_ids!r}"
        )

    return errors


def validate_presilicon(
    root: Path = ROOT,
    ledger_path: Path | None = None,
    roadmap_path: Path | None = None,
) -> list[str]:
    """Load and validate the pre-silicon readiness ledger and roadmap from disk."""
    errors: list[str] = []
    try:
        resolved_root = Path(root).resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return [f"presilicon: invalid project root ({type(exc).__name__})"]
    if not resolved_root.is_dir():
        return ["presilicon: project root is not a directory"]

    resolved_ledger = (
        Path(ledger_path)
        if ledger_path is not None
        else resolved_root / DEFAULT_LEDGER_PATH
    )
    resolved_roadmap = (
        Path(roadmap_path)
        if roadmap_path is not None
        else resolved_root / DEFAULT_ROADMAP_PATH
    )

    ledger = _load_json(resolved_ledger, "presilicon", errors)
    roadmap = _load_json(resolved_roadmap, "roadmap", errors)
    if ledger is None:
        return errors
    errors.extend(validate_presilicon_data(ledger, resolved_root, roadmap=roadmap))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository source root (default: this script's checkout)",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="optional override path to presilicon_readiness.json",
    )
    parser.add_argument(
        "--roadmap",
        type=Path,
        default=None,
        help="optional override path to roadmap.json",
    )
    args = parser.parse_args(argv)
    errors = validate_presilicon(
        root=args.root,
        ledger_path=args.ledger,
        roadmap_path=args.roadmap,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            f"Pre-silicon readiness validation failed: {len(errors)} error(s).",
            file=sys.stderr,
        )
        return 1
    print(
        "Pre-silicon readiness validation passed "
        "(ADR-006 Tracks A-F; physical FPGA/silicon gates remain unwaived)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
