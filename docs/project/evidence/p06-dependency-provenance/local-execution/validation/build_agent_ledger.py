#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build a deterministic work-report ledger without executing retained content."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import stat
import sys


WAVES = 10
ASSIGNMENTS_PER_WAVE = 6
EXPECTED = tuple(f"w{wave:02d}_a{assignment:02d}"
                 for wave in range(1, WAVES + 1)
                 for assignment in range(1, ASSIGNMENTS_PER_WAVE + 1))
NAME = re.compile(r"w([0-9]{2})_a([0-9]{2})", re.IGNORECASE)
PREFIX = re.compile(r"^(?:Wave|W)\s*[0-9]+\s*[/,]?\s*"
                    r"(?:agent|assignment|A)\s*[0-9]+\s*(?:—|:|-)?\s*", re.IGNORECASE)
MAX_REPORT_BYTES = 2 * 1024 * 1024
FALSE_CLAIMS = ("qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
                "acceptance_claimed", "phase_acceptance", "performance_acceptance")
LIMITATIONS = [
    "This ledger inventories named completed-work reports. It is not an authenticated scheduler transcript or proof of process execution.",
    "Assignments are grouped into ten named waves of six; the coordinator reported a maximum of three concurrent worker agents. A wave does not mean six workers ran simultaneously.",
    "Each report retains its own source revision, reviewed file identities, evidence type and limitations. A report-level PASS does not promote an enclosing failed original.",
    "Test counts overlap across reports and revisions. They must not be summed or represented as a full-suite pass at a later revision.",
    "Earlier readiness recommendations remain historical. Later failure reviews, corrected originals and the current runbook determine the active state.",
    "The ledger does not execute code, retest results, authenticate an original producer, or grant qualification, warm readiness or acceptance.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def read_report(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            "report must be a regular unlinked file: " + str(path))
    require(0 < before.st_size <= MAX_REPORT_BYTES, "report is empty or too large: " + str(path))
    body = path.read_bytes()
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "report changed during reading: " + str(path))
    text = body.decode("utf-8", errors="strict")
    headings = [line[2:].strip() for line in text.splitlines() if line.startswith("# ")]
    require(len(headings) == 1 and headings[0], "report needs one nonempty title: " + str(path))
    return body, headings[0]


def report_paths(directory):
    return sorted(path for path in directory.rglob("*")
                  if path.suffix.lower() == ".md")


def build(evidence_root, require_complete=False):
    root = evidence_root.resolve(strict=True)
    agents = root / "agents"
    require(agents.is_dir() and not agents.is_symlink(), "agents directory must exist without a symlink")
    paths = report_paths(agents)
    parsed = [(path, NAME.fullmatch(path.stem)) for path in paths]
    counts = Counter(match.group(0).lower() for _, match in parsed if match)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    unexpected = sorted(path.relative_to(agents).as_posix() for path, match in parsed
                        if not match or path.parent != agents
                        or path.name != match.group(0).lower() + ".md"
                        or match.group(0).lower() not in EXPECTED)
    require(not duplicates, "duplicate agent report identifiers: " + ", ".join(duplicates))
    require(not unexpected, "unexpected agent reports: " + ", ".join(unexpected))
    present = {path.stem: path for path in paths}
    missing = [name for name in EXPECTED if name not in present]
    require(not require_complete or not missing, "incomplete agent reports: " + ", ".join(missing))
    entries, snapshots = [], {}
    for name in EXPECTED:
        wave, assignment = int(name[1:3]), int(name[5:7])
        row = {"agent": name, "canonical_task": "/root/" + name,
               "wave": wave, "assignment": assignment,
               "status": "report_missing", "report_path": "agents/" + name + ".md",
               "report_title": None, "reported_task": None,
               "size_bytes": None, "sha256": None}
        if name in present:
            body, title = read_report(present[name])
            summary = PREFIX.sub("", title).strip()
            require(summary, "report title has no task description: " + name)
            snapshots[name] = body
            row.update(status="report_retained", report_title=title, reported_task=summary,
                       size_bytes=len(body), sha256=digest(body))
        entries.append(row)
    require(report_paths(agents) == paths, "report directory changed during inventory")
    for name, original in snapshots.items():
        require(read_report(present[name])[0] == original, "report changed during inventory: " + name)
    identity_rows = [{key: row[key] for key in ("agent", "report_path", "size_bytes", "sha256")}
                     for row in entries if row["status"] == "report_retained"]
    return {"schema_version": 1, "contract_id": "p06-local-agent-work-ledger-v1",
            "scope": "Named completed-work report inventory, with source and result scope retained in each report",
            "requested_waves": WAVES, "requested_assignments_per_wave": ASSIGNMENTS_PER_WAVE,
            "requested_agent_total": len(EXPECTED), "retained_report_count": len(present),
            "complete": not missing, "missing_reports": missing,
            "unexpected_reports": [], "duplicate_agent_ids": [],
            "reported_worker_concurrency_limit": 3,
            "reported_task_source": "Report title with the wave/assignment prefix removed; not an inferred execution result",
            "report_identity_set_sha256": digest(json.dumps(identity_rows, sort_keys=True,
                separators=(",", ":")).encode("utf-8")),
            "waves": [{"wave": wave, "requested": ASSIGNMENTS_PER_WAVE,
                       "retained": sum(row["wave"] == wave and row["status"] == "report_retained"
                                       for row in entries)} for wave in range(1, WAVES + 1)],
            "entries": entries, **dict.fromkeys(FALSE_CLAIMS, False), "limitations": LIMITATIONS}


def markdown(document):
    count, requested = document["retained_report_count"], document["requested_agent_total"]
    state = "Complete report set" if document["complete"] else "Incomplete report set"
    lines = ["# Agent work ledger", "", f"**{state}: {count} of {requested} reports retained.**", "",
             "The requested work is organized into ten named waves of six assignments. "
             "Each linked report records its actual completed work and its own source and evidence scope. "
             "Missing slots are shown explicitly and are not counted as completed work.", "",
             "The coordinator reported a maximum of three concurrent worker agents. "
             "Waves describe assignment groups; this ledger does not assert that six agents ran simultaneously. "
             "Report files do not independently authenticate scheduler activity.", "",
             "[Machine-readable ledger](agent-execution.json) · "
             "[Reproducible builder](validation/build_agent_ledger.py)", "",
             "## Wave inventory", "", "| Wave | Retained reports | Requested |",
             "| --- | ---: | ---: |"]
    lines.extend(f"| {row['wave']:02d} | {row['retained']} | {row['requested']} |"
                 for row in document["waves"])
    lines += ["", "## Recorded assignments", "",
              "Titles below are taken from each report, with its wave/assignment prefix removed. "
              "They describe the reported task, not a new verification or a promotion of its result.", "",
              "| Wave | Agent | Reported completed task | Bytes | SHA-256 |",
              "| --- | --- | --- | ---: | --- |"]
    for row in document["entries"]:
        if row["status"] == "report_retained":
            title = row["reported_task"].replace("|", "\\|")
            lines.append(f"| {row['wave']:02d} | [{row['agent']}]({row['report_path']}) | "
                         f"{title} | {row['size_bytes']:,} | `{row['sha256']}` |")
        else:
            lines.append(f"| {row['wave']:02d} | {row['agent']} | Report not yet retained | — | — |")
    lines += ["", "## Scope and reproduction", "",
              "The report identity-set SHA-256 is `" + document["report_identity_set_sha256"] + "`. "
              "It covers each retained report's agent name, relative path, byte count and SHA-256 in assignment order.", "",
              "The builder accepts incomplete inventories by default. For final publication, run from the repository root:",
              "", "```bash", "python3 docs/project/evidence/p06-dependency-provenance/local-execution/validation/build_agent_ledger.py --require-complete", "```", "",
              "Strict completion rejects missing, unexpected or duplicate identifiers before writing either output. "
              "The builder rechecks report bytes and directory membership, never executes retained content, "
              "and does not hash either generated ledger into itself.", ""]
    lines.extend("- " + limitation for limitation in document["limitations"][2:])
    lines += ["", "All seven qualification, warm and acceptance claims remain false.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        document = build(args.evidence_root, args.require_complete)
        root = args.evidence_root.resolve(strict=True)
        (root / "agent-execution.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                                                  encoding="utf-8")
        (root / "agent-execution.md").write_text(markdown(document), encoding="utf-8")
        print(json.dumps({key: document[key] for key in
                          ("complete", "retained_report_count", "requested_agent_total", "missing_reports")}))
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
