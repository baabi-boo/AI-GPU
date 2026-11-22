#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Index actual agent receipts and an explicit root spawn attestation."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


BASELINE = "4df7186edbca82b21b2b8cba9b3b192248b99209"
SELECTED_SOURCE = "18c888058ac851b802350c99770ed9ac2d27b582"
EXPECTED = tuple(f"w{wave:02d}_a{agent:02d}" for wave in range(1, 11)
                 for agent in range(1, 7))
RECEIPT_NAME = re.compile(r"w([0-9]+)_a([0-9]+)\.md", re.IGNORECASE)


def collect_receipts(packet):
    directory = packet / "agents"
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("agents must be a real directory")
    paths = {}
    for path in sorted(directory.rglob("*")):
        match = RECEIPT_NAME.fullmatch(path.name)
        if match is None:
            continue
        identity = f"w{int(match[1]):02d}_a{int(match[2]):02d}"
        if identity not in EXPECTED:
            raise ValueError(f"unexpected agent ID: {path.relative_to(packet)}")
        if identity in paths:
            raise ValueError(f"duplicate agent ID: {identity}")
        paths[identity] = path
    receipts = {}
    hashes = {}
    for identity, path in paths.items():
        relative = path.relative_to(packet).as_posix()
        if relative != f"agents/{identity}.md" or path.is_symlink() or not path.is_file():
            raise ValueError(f"receipt must be a canonical regular file: {relative}")
        data = path.read_bytes()
        title = next((line[2:].strip() for line in data.decode("utf-8").splitlines()
                      if line.startswith("# ")), "")
        if not title:
            raise ValueError(f"receipt has no nonempty H1 title: {relative}")
        digest = hashlib.sha256(data).hexdigest()
        if digest in hashes:
            raise ValueError(f"duplicate receipt bytes: {identity} and {hashes[digest]}")
        hashes[digest] = identity
        receipts[identity] = {
            "path": relative, "sha256": digest, "size_bytes": len(data),
            "title": title, "topic": re.split(r"\s*—\s*|:\s*", title, maxsplit=1)[-1],
        }
    return receipts


def build_ledger(packet, attested_count):
    if attested_count is not None and (type(attested_count) is not int or not 0 <= attested_count <= 60):
        raise ValueError("root attestation must be an integer from 0 through 60")
    receipts = collect_receipts(packet)
    entries = []
    for identity in EXPECTED:
        receipt = receipts.get(identity)
        entries.append({
            "id": identity, "canonical_agent": "/root/" + identity,
            "wave": int(identity[1:3]), "agent_in_wave": int(identity[5:7]),
            "receipt_present": receipt is not None, "receipt": receipt,
        })
    missing = [entry["id"] for entry in entries if not entry["receipt_present"]]
    complete = not missing and attested_count == len(EXPECTED)
    waves = []
    for wave in range(1, 11):
        members = [entry for entry in entries if entry["wave"] == wave]
        waves.append({
            "wave": wave, "expected_agents": 6,
            "receipt_count": sum(entry["receipt_present"] for entry in members),
            "missing_agents": [entry["id"] for entry in members if not entry["receipt_present"]],
            "focus_from_receipt_topics": [entry["receipt"]["topic"] for entry in members
                                          if entry["receipt_present"]],
        })
    return {
        "schema_version": 1, "scope": "agent roster and receipt inventory",
        "baseline_revision": BASELINE, "selected_implementation_revision": SELECTED_SOURCE,
        "expected_agent_count": 60, "expected_wave_count": 10, "agents_per_wave": 6,
        "root_counted_as_worker": False, "worker_concurrency_limit": 3,
        "scheduling": "Six agents per wave, executed in batches; late validation and review follow-ups overlapped.",
        "root_spawn_attestation": {
            "attested_agent_count": attested_count,
            "supplied": attested_count is not None,
            "basis": "Explicit /root attestation supplied by command-line argument; the script does not inspect agent runtime history.",
        },
        "receipt_count": len(receipts), "missing_agents": missing,
        "roster_complete": complete,
        "limitations": [
            "Receipt presence and root spawn attestation document the roster; they do not independently prove every execution statement in a receipt.",
            "Some receipts are intermediate checkpoints or retain open findings; roster completion does not mean all CI jobs, review obligations or phase gates passed.",
            "Use the source-bound native, circuit, governance and review packets for execution and acceptance conclusions.",
            "The root coordinator is excluded. This is not a claim that 60 agents ran simultaneously.",
            "Follow-up work reuses existing agents and does not increase the distinct-agent count.",
            "The generated ledger files are excluded from their own hash inventory; rerun after receipt edits.",
        ],
        "waves": waves, "agents": entries,
    }


def markdown_cell(value):
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(ledger):
    attested = ledger["root_spawn_attestation"]["attested_agent_count"]
    state = "Complete roster" if ledger["roster_complete"] else "Incomplete roster"
    lines = [
        "# P06 transport agent work ledger", "",
        f"**{state}: {ledger['receipt_count']} of 60 completion receipts present.** "
        + (f"The root coordinator explicitly attests that {attested} distinct agents were spawned."
           if attested is not None else "No root spawn attestation was supplied."),
        "",
        "The requested work is organized into **10 waves of six agents**. Three worker "
        "slots plus the root coordinator were available, so workers ran in batches; "
        "late validation and review follow-ups overlapped. The root is not counted, "
        "and this is not a claim of 60 simultaneous workers. Reusing an agent for a "
        "follow-up does not add another distinct agent.", "",
        f"Baseline: `{BASELINE}`. Selected implementation checkpoint: `{SELECTED_SOURCE}`. "
        "The ledger inventories work receipts, including intermediate findings. "
        "It does not turn cancelled jobs, failed attempts, raw area failures or "
        "unrun checks into passes, and it does not qualify warm performance or close "
        "a phase gate. Consult the [evidence index](README.md) and its source-bound reviews.", "",
        "## Wave focus", "",
        "Topics below are extracted from the actual receipt headings. Missing "
        "receipts contribute no invented topic or completed work.", "",
        "| Wave | Receipts | Focus from recorded receipts |",
        "|---|---:|---|",
    ]
    for wave in ledger["waves"]:
        topics = "; ".join(wave["focus_from_receipt_topics"]) or "No receipts yet"
        lines.append(f"| {wave['wave']} | {wave['receipt_count']}/6 | {markdown_cell(topics)} |")
    lines += ["", "## Individual receipts", "",
              "The [JSON ledger](agent-ledger.json) stores each full SHA-256 and byte count. "
              "The prefixes below are navigation aids, not substitute integrity checks.", "",
              "| Agent | Receipt topic | SHA-256 prefix |",
              "|---|---|---|"]
    for entry in ledger["agents"]:
        receipt = entry["receipt"]
        if receipt is None:
            lines.append(f"| `{entry['id']}` | Missing receipt | — |")
        else:
            lines.append(f"| [{entry['id']}]({receipt['path']}) | "
                         f"{markdown_cell(receipt['topic'])} | `{receipt['sha256'][:16]}` |")
    lines += ["", "## Reproduce", "",
              "After the root has confirmed all 60 actual spawns and every receipt "
              "is final, run from the repository root:", "", "```bash",
              "python3 docs/project/evidence/p06-mpm-transport/build_agent_ledger.py \\",
              "  --root-attested-spawn-count 60 --require-complete", "```", "",
              "Without the attestation flag, the generator records that the attestation "
              "is absent. With `--require-complete`, missing receipts or an incomplete "
              "attestation produce exit 1 after writing an honest incomplete inventory. "
              "Duplicate IDs, noncanonical receipt paths, duplicate receipt bytes and "
              "unexpected matching IDs are errors. The outputs are deterministic for "
              "the same receipt bytes and attestation; neither ledger hashes itself.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--root-attested-spawn-count", type=int, choices=range(61), metavar="0..60")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        ledger = build_ledger(args.packet_dir, args.root_attested_spawn_count)
        encoded = json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (args.packet_dir / "agent-ledger.json").write_text(encoded, encoding="utf-8")
        (args.packet_dir / "agent-ledger.md").write_text(render_markdown(ledger), encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        print("Agent ledger error: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps({"receipt_count": ledger["receipt_count"],
                      "root_attested_spawn_count": args.root_attested_spawn_count,
                      "missing_agents": ledger["missing_agents"],
                      "roster_complete": ledger["roster_complete"]}, sort_keys=True))
    return int(args.require_complete and not ledger["roster_complete"])


if __name__ == "__main__":
    raise SystemExit(main())
