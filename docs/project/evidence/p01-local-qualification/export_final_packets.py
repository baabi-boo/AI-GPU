#!/usr/bin/env python3
"""One-time publication helper for completed local records; not a production gate.

The audited native exporter is imported unchanged. No workload, test, compiler,
Git operation or retained source is executed. Only named text evidence is read;
binary/model identities are retained without reading those binary/model files.

  python3 -B work-notes/blockers/export_final_packets.py check-completed
  python3 -B work-notes/blockers/export_final_packets.py export --destination FINAL
  python3 -B work-notes/blockers/export_final_packets.py verify FINAL --raw-workspace .

Export always requires both finished native attempts, the finished two-unit
follow-up, and exactly 60 completed, hash-matched agent notes. check-completed
checks the same finished execution payload without the final agent ledger;
it neither publishes a final packet nor substitutes for unfinished records.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile

import export_local_packets as safe


SCHEMA = "local-qualification-final-text-v1"
NOTES = safe.NOTES
UNIT_PACKET = "local-qualification-units"
UNIT_CASES = ["cp-llc-port", "mm-axi-arb"]
UNIT_SIDECARS = ["unit-source.json", "unit-command.json", "unit-plan.json",
                 "unit-launch.json", "unit-run.stdout.json", "unit-run.stderr.log"]
IDENTITY_FILES = [NOTES + "/b09d.json", NOTES + "/b09d.md",
                  NOTES + "/9532327.commit", NOTES + "/7e4ac58.commit",
                  NOTES + "/143c69f.commit", NOTES + "/prepared-code-mapping.json"]
require = safe.require


def parsed(data, name):
    """The retained CP manifest is a JSON array; keep the audited parser rules."""
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=safe.unique_keys,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               safe.ExportError("nonfinite JSON constant")))
        require(isinstance(value, (dict, list)), name + ": JSON object/array required")
        return value
    except (UnicodeError, ValueError, RecursionError) as error:
        raise safe.ExportError(name + ": invalid JSON: " + str(error)) from error


def literal(text, rules):
    for prefix, token in rules:
        text = text.replace(prefix.decode("utf-8"), token.decode("ascii"))
    return text


def transform(data, name, rules):
    # Use the audited byte transform and residual-path scanner. Parse arrays and
    # normalize path-bearing dictionary keys separately (the n8 record has them).
    public, counts, _ = safe.transform(data, name + ".text", rules)
    checked = 0
    if name.endswith(".json"):
        raw, result = parsed(data, name), parsed(public, name)
        before = safe.protected_values(raw)
        normalized = {tuple(literal(k, rules) if isinstance(k, str) else k for k in path): value
                      for path, value in before.items()}
        require(normalized == safe.protected_values(result),
                name + ": protected outcome/hash field changed")
        # Literal substitution changes strings only. All numbers, booleans,
        # expected/observed exits, array ordering and dictionary structure remain.
        def changed(value):
            if isinstance(value, str):
                return literal(value, rules)
            if isinstance(value, list):
                return [changed(item) for item in value]
            if isinstance(value, dict):
                pairs = [(literal(key, rules), changed(item)) for key, item in value.items()]
                require(len({key for key, _ in pairs}) == len(pairs), "redacted JSON key collision")
                return dict(pairs)
            return value
        require(changed(raw) == result, name + ": nonliteral JSON change")
        safe.no_machine_paths(public, name, result)
        checked = len(before)
    return public, counts, checked


def publication_rules(capture):
    private_bytes = capture.read(safe.PRIVATE_MAPPING)
    private = safe.decode_json(private_bytes, "private prefix mapping")
    pairs = []
    by_token = {}
    for item in private["public_layout_proposal"]["prefix_mapping_private"]:
        prefix, token = item["raw_prefix"], item["token"]
        require(safe.digest(prefix.encode()) == item["raw_prefix_sha256_utf8"],
                "private prefix-map hash mismatch")
        require(safe.TOKEN.fullmatch(token) and prefix.startswith("/") and prefix != "/",
                "invalid private prefix mapping")
        by_token[token] = prefix
    # These are explicitly named publication roots, not discovered filesystem
    # paths. The old native exports keep their own narrower rules unchanged.
    roots = {
        "$RETRY_BUILD": capture.workspace / "build-local-qualification-2",
        "$RETRY_OUTPUT": capture.workspace / "local-qualification-run-2",
        "$UNIT_BUILD": capture.workspace / "build-local-qualification-units",
        "$UNIT_OUTPUT": capture.workspace / UNIT_PACKET,
        "$DIAGNOSTIC_N8": capture.workspace / "diagnostic-stencil-n8",
        "$CP_SETUP": capture.workspace / NOTES / "b08d-run",
        "$CP_PROOF": capture.workspace / NOTES / "b08d-run-2",
        "$BLOCKER_NOTES": capture.workspace / NOTES,
        "$WORKSPACE": capture.workspace,
        "$BASELINE_WORKSPACE": Path(by_token["$TOOLS"]).parent,
        "$AGENT_TREE": Path("/") / "root",
        "$SYSTEM_TMP": Path("/") / "tmp",
    }
    by_token.update({key: str(value) for key, value in roots.items()})
    require(len(set(by_token.values())) == len(by_token), "duplicate publication prefix")
    pairs.extend((prefix.encode(), token.encode()) for token, prefix in by_token.items())
    # Agent notes discuss generic root labels in backticks; match those exact
    # quoted labels rather than allowing arbitrary unknown machine paths.
    for label, token in [("workspace", "DEPLOYMENT_ROOT"), ("home", "HOME_ROOT"),
                         ("opt", "OPTIONAL_SOFTWARE_ROOT")]:
        for suffix in ("", "/"):
            pairs.append((("`/" + label + suffix + "`").encode(),
                          ("`$" + token + suffix + "`").encode()))
    return sorted(pairs, key=lambda pair: (-len(pair[0]), pair[0])), private_bytes


def finished_report(report, label):
    require(report.get("state") == "finished" and report.get("finished_at")
            and not report.get("active_command"), label + ": run is unfinished; export refused")
    require(report.get("mode") == "run" and report.get("outcome") in {"pass", "fail", "blocked"},
            label + ": invalid final run outcome")
    require(report.get("supplemental") is True and report.get("phase_complete") is False
            and report.get("qualifies_P01_A03") is False
            and report.get("vendor_execution_performed") is False,
            label + ": unexpected qualification claim")


def ledger_inputs(capture):
    ledger_name = NOTES + "/execution-ledger.json"
    ledger = safe.decode_json(capture.read(ledger_name), ledger_name)
    agents = ledger["agents"]
    require(ledger.get("requested_agents") == 60 and ledger.get("requested_waves") == 10
            and len(agents) == 60 and {row["number"] for row in agents} == set(range(1, 61)),
            "final ledger does not contain exactly agents 1 through 60")
    inputs = [(ledger_name, "agent-notes/execution-ledger.json")]
    for row in sorted(agents, key=lambda item: item["number"]):
        number = row["number"]
        expected_name = "b%02d%s.md" % ((number - 1) // 6 + 1, "abcdef"[(number - 1) % 6])
        require(row.get("status") == "complete" and row.get("note") == expected_name
                and row.get("wave") == (number - 1) // 6 + 1,
                "agent " + str(number) + ": note is not finalized")
        name = NOTES + "/" + expected_name
        require(safe.digest(capture.read(name)) == row.get("note_sha256"),
                "final ledger note hash mismatch: " + expected_name)
        inputs.append((name, "agent-notes/" + expected_name))
    return inputs


def unit_inputs(capture):
    report = safe.decode_json(capture.read(UNIT_PACKET + "/report.json"), "unit report")
    finished_report(report, "two-unit follow-up")
    source = safe.decode_json(capture.read(NOTES + "/unit-source.json"), "unit source")
    revision, tree = source["source_revision"], source["source_tree"]
    require(all(isinstance(value, str) and len(value) == 40
                and all(c in "0123456789abcdef" for c in value) for value in [revision, tree]),
            "unit source needs exact commit/tree identities")
    require(source.get("selected_cases") == UNIT_CASES and source.get("full_suite_executed") is False,
            "unit follow-up must explicitly be two selected units without a fresh full suite")
    actual = report["inputs_before"]["source"]
    require(actual["revision"] == revision and actual["tree"] == tree
            and report.get("selected_ids") == UNIT_CASES
            and [case["id"] for case in report["cases"]] == UNIT_CASES,
            "unit source/case identity mismatch")
    require(Path(report["paths"]["output"]) == capture.workspace / UNIT_PACKET,
            "unit report names another output packet")
    sidecars = {name: capture.read(NOTES + "/" + name) for name in UNIT_SIDECARS}
    launcher = safe.decode_json(sidecars["unit-launch.json"], "unit launcher")
    command = safe.decode_json(sidecars["unit-command.json"], "unit command")
    plan = safe.decode_json(sidecars["unit-plan.json"], "unit plan")
    stdout = safe.decode_json(sidecars["unit-run.stdout.json"], "unit stdout")
    require(launcher.get("finished_at") and type(launcher.get("exit_code")) is int
            and launcher.get("source_revision") == revision,
            "unit launcher is unfinished or has another source identity")
    require(plan.get("mode") == "plan" and plan.get("state") == "planned"
            and plan.get("outcome") == "pass" and plan.get("execution_performed") is False
            and plan.get("selected_ids") == UNIT_CASES
            and plan["inputs_before"]["source"]["revision"] == revision
            and plan["inputs_before"]["source"]["tree"] == tree,
            "unit preflight sidecar is not the matching nonexecuted plan")
    for argv, mode in [(command["argv"], "plan"), (launcher["argv"], "run")]:
        require(isinstance(argv, list) and len(argv) > 3 and argv[3] == mode,
                "unexpected unit command mode")
        require([argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--case"] == UNIT_CASES,
                "unit command selected cases differ")
    require(safe.protected_values(stdout) == safe.protected_values(report),
            "unit stdout/canonical report protected fields differ")
    members = capture.tree(UNIT_PACKET)
    unreferenced = safe.check_report_evidence(report, members)
    inputs = [(UNIT_PACKET + "/" + member, "local-units-followup/" +
               ("report.redacted.json" if member == "report.json" else member))
              for member in sorted(members)]
    inputs.extend((NOTES + "/" + name, "local-units-followup/tooling/" + name)
                  for name in UNIT_SIDECARS)
    summary = {"id": "units", "kind": "two affected units only", "directory": "local-units-followup",
               "report": "local-units-followup/report.redacted.json", "reported_outcome": report["outcome"],
               "source_revision": revision, "source_tree": tree, "cases": report["selected_ids"],
               "case_outcomes": {case["id"]: case["outcome"] for case in report["cases"]},
               "launcher_exit": launcher["exit_code"], "full_suite_executed": False,
               "raw_report_sha256": safe.digest(members["report.json"]),
               "command_logs_verified": len(report["commands"]),
               "text_snapshots_verified": len(report["snapshots"]),
               "unreferenced_text_files_retained": unreferenced}
    return inputs, summary, [Path(value) for value in report["paths"].values() if value]


def extra_inputs(capture):
    inputs, summaries, omissions = [], [], []
    root = "diagnostic-stencil-n8"
    record = safe.decode_json(capture.read(root + "/record.json"), "n8 record")
    require(record.get("finished_at") and record["result"].get("cleanup_complete") is True
            and type(record["result"].get("exit_code")) is int,
            "n8 diagnostic is unfinished; export refused")
    require(record.get("qualifies_frozen_axi_case") is False and record.get("qualifies_P01_A03") is False,
            "n8 record contains a qualification claim")
    safe.assert_identity(capture.read(root + "/run.log"), record["result"], "n8 run log",
                         "log_sha256", "log_size_bytes")
    for member in ["record.json", "run.log", "ramulator.stats.log"]:
        inputs.append((root + "/" + member, "extras/" + root + "/" + member))
    summaries.append({"id": "n8-diagnostic", "kind": "nonqualification small-shape diagnostic",
                      "report": "extras/diagnostic-stencil-n8/record.json",
                      "reported_outcome": record["result"]["outcome"],
                      "observed_exit": record["result"]["exit_code"],
                      "source_revision": record["source_revision"],
                      "qualifies_frozen_axi_case": False, "qualifies_P01_A03": False})
    preservation_name = NOTES + "/b09c-final.json"
    preservation = safe.decode_json(capture.read(preservation_name), "preservation audit")
    require(preservation.get("finished_at") and preservation.get("outcome") == "pass"
            and preservation.get("failures") == [], "preservation audit is incomplete")
    inputs.append((preservation_name, "extras/preservation/b09c-final.json"))
    summaries.append({"id": "preservation-audit", "kind": "read-only source preservation audit; no execution",
                      "report": "extras/preservation/b09c-final.json", "reported_outcome": preservation["outcome"],
                      "source_revision": preservation["head_after"][0], "source_tree": preservation["head_after"][1]})
    guardrail_name = NOTES + "/ci-guardrail-143c69f.json"
    guardrail = safe.decode_json(capture.read(guardrail_name), "CI guardrail record")
    guardrail_log = capture.read(NOTES + "/ci-guardrail-143c69f.log")
    require(type(guardrail.get("exit_code")) is int and safe.digest(guardrail_log) == guardrail.get("log_sha256"),
            "CI guardrail result/log identity is incomplete")
    inputs.extend([(guardrail_name, "extras/ci-guardrail/record.json"),
                   (NOTES + "/ci-guardrail-143c69f.log", "extras/ci-guardrail/run.log")])
    summaries.append({"id": "ci-guardrail", "kind": "single targeted host tooling test; not a full suite",
                      "report": "extras/ci-guardrail/record.json", "observed_exit": guardrail["exit_code"],
                      "source_revision": guardrail["source_revision"], "full_suite_executed": False})
    for raw_dir, public_dir, setup in [("b08d-run", "setup-failure", True),
                                       ("b08d-run-2", "proof", False)]:
        prefix = NOTES + "/" + raw_dir
        public = "extras/cp-mutations/" + public_dir
        report = safe.decode_json(capture.read(prefix + "/report.json"), "CP report")
        records = parsed(capture.read(prefix + "/manifest.json"), "CP manifest")
        require(isinstance(records, list), "CP manifest must be an array")
        raw_root = capture.workspace / prefix
        listed = {}
        for row in records:
            path = Path(row["path"])
            require(path.is_absolute() and path.is_relative_to(raw_root), "CP manifest path escapes its packet")
            member = safe.relative_name(path.relative_to(raw_root).as_posix())
            require(member not in listed and safe.SHA256.fullmatch(row["sha256"])
                    and type(row["size_bytes"]) is int and row["size_bytes"] >= 0,
                    "invalid/duplicate CP manifest identity")
            listed[member] = row
        chosen = {name for name in listed if name in {"report.json", "expectations.json",
                  "support/baseline_process.py"} or name.startswith(("logs/", "sources/"))}
        require({"report.json", "expectations.json"} <= chosen, "CP packet lacks required metadata")
        for member in sorted(chosen):
            data = capture.read(prefix + "/" + member)
            safe.assert_identity(data, listed[member], "CP selected manifest member")
            inputs.append((prefix + "/" + member, public + "/" + member))
        inputs.append((prefix + "/manifest.json", public + "/raw-packet-manifest.json"))
        for member in sorted(set(listed) - chosen):
            row = listed[member]
            omissions.append({"section": "cp-" + public_dir, "raw_path": prefix + "/" + member,
                              "raw_sha256": row["sha256"], "raw_size_bytes": row["size_bytes"],
                              "identity_source": public + "/raw-packet-manifest.json",
                              "bytes_reread_by_exporter": False,
                              "reason": "binary/model/build or unselected support copy; recorded identity retained"})
        commands = {command["name"]: command for command in report["commands"]}
        require(len(commands) == len(report["commands"]) and report.get("resources_after"),
                "CP command names repeat or completed resources are absent")
        for command in report["commands"]:
            member = safe.relative_name(command["log"])
            require(member in chosen and command.get("cleanup_complete") is True
                    and type(command.get("exit_code")) is int, "CP command is incomplete")
            safe.assert_identity(capture.read(prefix + "/" + member), command, "CP command log",
                                 "log_sha256", "log_size_bytes")
        script = "b08d-failed-setup-script.py" if setup else "b08d-executed-runner.py"
        safe.assert_identity(capture.read(NOTES + "/" + script), report["script"], "CP executed script")
        inputs.append((NOTES + "/" + script, public + "/executed-runner.py"))
        case_summary = []
        if setup:
            require(report.get("outcome") == "fail" and report.get("error")
                    and not report["cases"] and len(commands) == 5
                    and all(name.startswith(("git-", "compiler-")) for name in commands),
                    "CP setup-failure record is not the completed metadata-only failure")
            diagnosis_name = NOTES + "/b08d-setup-failure.json"
            diagnosis = safe.decode_json(capture.read(diagnosis_name), "CP setup diagnosis")
            require(diagnosis.get("no_harness_compilation_or_simulation") is True
                    and diagnosis["attempt_report_sha256"] == safe.digest(capture.read(prefix + "/report.json")),
                    "CP setup diagnosis disagrees with retained report")
            inputs.append((diagnosis_name, public + "/diagnosis.json"))
        else:
            require(report.get("outcome") == "pass" and len(report["cases"]) == 8
                    and report.get("final_normal_rerun_passed") is True
                    and report.get("unchanged_inputs_verified") is True,
                    "CP mutation proof is unfinished or differs from the completed proof")
            for case in report["cases"]:
                command = commands[case["name"] + "-run"]
                source_member = "sources/" + case["name"] + ".cpp"
                require(source_member in chosen, "CP source variant missing")
                safe.assert_identity(capture.read(prefix + "/" + source_member), case["source"], "CP variant")
                binary_member = "build/" + case["name"]
                require(binary_member in listed and case["binary"]["sha256"] == listed[binary_member]["sha256"]
                        and case["binary"]["size_bytes"] == listed[binary_member]["size_bytes"],
                        "CP binary identity disagrees with retained manifest")
                require(command["exit_code"] == case["expected_exit"]
                        and command.get("expected_exit_observed") is True and case.get("expectation_met") is True,
                        "CP expected and observed exits disagree")
                case_summary.append({"name": case["name"], "expected_exit": case["expected_exit"],
                                     "observed_exit": command["exit_code"], "command_outcome": command["outcome"],
                                     "expectation_met": case["expectation_met"],
                                     "expected_marker": case["expected_marker"],
                                     "expected_mutation_hits": case["expected_mutation_hits"],
                                     "observed_mutation_hits": case["observed_mutation_hits"]})
            verification_name = NOTES + "/b08d-verification.json"
            verification = safe.decode_json(capture.read(verification_name), "CP verification")
            require(verification.get("outcome") == "pass" and verification.get("command_logs_verified") is True
                    and verification.get("manifest_bytes_verified") is True,
                    "CP independent verification is incomplete")
            inputs.append((verification_name, public + "/verification.json"))
        summaries.append({"id": "cp-" + public_dir, "kind": "nonqualification mutation evidence",
                          "report": public + "/report.json", "reported_outcome": report["outcome"],
                          "metadata_only_failure": setup, "source_revision": report["base_revision"],
                          "command_logs_verified": len(commands), "cases": case_summary,
                          "expected_nonzero_exits_are_qualification_passes": False})
    return inputs, summaries, omissions


def build_bundle(workspace, final=True, identity_files=(), maximum=safe.MAX_BYTES):
    require(0 < maximum <= safe.MAX_BYTES, "byte ceiling exceeds audited limit")
    capture = safe.Capture(workspace, maximum)
    native_ids = list(safe.ATTEMPTS)
    native, forbidden = safe.build_bundle(workspace, native_ids, maximum)
    native_manifest = safe.decode_json(native["manifest.json"], "native manifest")
    output = {"native-attempts/" + name: data for name, data in native.items()}
    artifacts = [{**row, "public_path": "native-attempts/" + row["public_path"],
                  "section": "native-" + row["attempt"]} for row in native_manifest["artifacts"]]
    generated = [{**row, "public_path": "native-attempts/" + row["public_path"]}
                 for row in native_manifest["generated_files"]]
    generated.append({"public_path": "native-attempts/manifest.json", "public_sha256": safe.digest(native["manifest.json"]),
                      "public_size_bytes": len(native["manifest.json"]), "origin": "audited_native_manifest"})
    rules, private_bytes = publication_rules(capture)
    inputs, extras, omissions = extra_inputs(capture)
    unit_files, units, unit_forbidden = unit_inputs(capture)
    inputs.extend(unit_files)
    forbidden.extend(unit_forbidden)
    require(all(item["source_revision"] == units["source_revision"] for item in extras
                if item["id"] in {"ci-guardrail", "preservation-audit"}),
            "follow-up audit/guardrail source differs from the unit run")
    if final:
        inputs.extend(ledger_inputs(capture))
    identities = sorted(set(IDENTITY_FILES + list(identity_files)))
    commits = []
    for name in identities:
        safe.relative_name(name)
        require(name.startswith(NOTES + "/") and Path(name).suffix in {".json", ".md", ".commit"},
                "identity extras must be explicitly named blocker text sidecars")
        data = capture.read(name)
        inputs.append((name, "identities/" + Path(name).name))
        if name.endswith(".commit"):
            commits.append({"path": "identities/" + Path(name).name,
                            "git_commit_sha1": hashlib.sha1(b"commit " + str(len(data)).encode() + b"\0" + data).hexdigest(),
                            "raw_sha256": safe.digest(data), "raw_size_bytes": len(data)})
    prepared = safe.decode_json(capture.read(NOTES + "/prepared-code-mapping.json"), "prepared code mapping")
    expected_trees = {spec["revision"]: spec["tree"] for spec in safe.ATTEMPTS.values()}
    expected_trees[units["source_revision"]] = units["source_tree"]
    require(len(prepared["commits"]) == 3 and {row["local"]: row["tree"] for row in prepared["commits"]} == expected_trees,
            "prepared code map does not match the three executed local source identities")
    require(set(expected_trees) <= {row["git_commit_sha1"] for row in commits},
            "raw original Git commit bytes do not match the executed local source identities")
    totals = {token.decode("ascii"): 0 for _, token in rules}
    protected = 0
    for raw_path, public_path in sorted(inputs, key=lambda pair: pair[1]):
        require(public_path not in output, "duplicate final public path")
        raw = capture.read(raw_path)
        public, counts, checked = transform(raw, public_path, rules)
        require(not raw_path.endswith(".commit") or raw == public,
                "raw Git commit bytes would require redaction; exact identity export refused")
        output[public_path] = public
        protected += checked
        for token, count in counts.items():
            totals[token] += count
        artifacts.append({"section": public_path.split("/")[0], "raw_path": raw_path,
                          "public_path": public_path, "raw_sha256": safe.digest(raw),
                          "public_sha256": safe.digest(public), "raw_size_bytes": len(raw),
                          "public_size_bytes": len(public), "replacement_counts": counts,
                          "transformation_id": safe.PROFILE if counts else "byte-preserving-copy"})

    def metadata(name, value):
        data = value if isinstance(value, bytes) else safe.encode_json(value)
        require(name not in output, "duplicate final metadata path")
        safe.no_machine_paths(data, name, parsed(data, name) if name.endswith(".json") else None)
        output[name] = data
        generated.append({"public_path": name, "public_sha256": safe.digest(data),
                          "public_size_bytes": len(data), "origin": "publication_metadata"})

    index = {"scope": "final" if final else "completed-record-validation",
             "native_attempts": [{**row, "directory": "native-attempts/" + row["directory"]}
                                 for row in native_manifest["attempts"]],
             "two_unit_followup": units, "nonqualification_extras": extras, "raw_commit_objects": commits,
             "finalized_agent_notes": 60 if final else 0,
             "historical_identity_audit": "identities/b09d.json",
             "prepared_code_mapping": "identities/prepared-code-mapping.json",
             "identity_caveat": "The dated prepared-object audit is not a fresh remote-ref read or evidence of publication.",
             "qualifies_P01_A03": False, "phase_complete": False, "vendor_execution_performed": False}
    metadata("index.json", index)
    metadata("redaction-rules.json", {"profile": safe.PROFILE, "native_rules": "inside native-attempts directories",
             "algorithm": "literal UTF-8 bytes, longest prefix first; original hashes and nonpath values unchanged",
             "tokens_are_executable": False, "rules": [{"display_token": token.decode("ascii"),
             "raw_prefix_sha256_utf8": safe.digest(prefix), "raw_prefix_utf8_bytes": len(prefix),
             "replacements": totals[token.decode("ascii")]} for prefix, token in rules]})
    rows = "\n".join("| " + item["id"] + " | " + item["reported_outcome"] + " | `" +
                     item["source_revision"] + "` |" for item in native_manifest["attempts"])
    unit_text = ("The separate two-unit follow-up records **" + units["reported_outcome"] + "** at revision `" +
                 units["source_revision"] + "`, tree `" + units["source_tree"] + "`. It selects only `cp-llc-port` and "
                 "`mm-axi-arb`; launcher exit **" + str(units["launcher_exit"]) + "**. Its source sidecar explicitly "
                 "records `full_suite_executed: false`. Earlier full-suite results retain their original source identities.")
    mutation_rows = "\n".join("| " + item["name"] + " | " + str(item["expected_exit"]) + " | " +
                              str(item["observed_exit"]) + " | " + item["command_outcome"] + " |"
                              for item in extras[-1]["cases"])
    readme = f"""# Local evidence publication ({index['scope']})

This is a one-time, unsigned publication of retained records. It executes no test
or workload and is not a production gate. All phase/vendor qualification flags
remain false. Supplemental local execution does not establish vendor runtime,
platform, hw_emu, physical FPGA, cache-coherence or silicon qualification.

## Native attempts and the separate affected-unit follow-up

| Native attempt | Recorded outcome | Actual source revision |
|---|---|---|
{rows}

The audited native export is preserved under `native-attempts/`, including its
own manifest, source identities, all logs/snapshots, failed/not-run outcomes and
matched full-suite sidecars. Its original verifier can check that subdirectory.

{unit_text}

## Nonqualification extras

`extras/diagnostic-stencil-n8/` is the completed 8-cubed, block-size-2 diagnostic,
with observed exit {extras[0]['observed_exit']}. It does not qualify the frozen 64-cubed case.
Its executable, kernel and runtime library identities remain in the record;
those binary bytes are not shipped.

`extras/cp-mutations/setup-failure/` preserves the failed inventory attempt:
five metadata commands completed, but no harness was compiled or simulated.
Its report, logs, expectations, exact failed runner and diagnosis are retained.

`extras/cp-mutations/proof/` is the later isolated paired C++ mutation proof.
Its report, command logs, source variants/diffs, executed runner and independent
verification are retained. The proof used one unchanged copied RTL model and a
proposed, uncommitted harness. These expected negative exits are mutation
evidence; they are not normal qualification passes or a fresh full native suite.

| Mutation case | Expected exit | Observed exit | Raw command outcome |
|---|---:|---:|---|
{mutation_rows}

The final normal strengthened rerun passed. First-word checks and total read
completion accounting do not establish all-word data checks, independent later
read values, unique per-request identity or response-backpressure coverage.
The retained CP raw-packet manifests preserve all binary, object, static model
and unselected support identities. `manifest.json` explicitly lists omitted
members and states that their bytes were not reread by this publication helper.

`extras/preservation/` retains the completed source-preservation audit.
`extras/ci-guardrail/` retains one targeted host tooling test and its exact log.
Neither extra is a fresh full suite or additional native qualification run.

## Provenance, notes and verification

`index.json` separates these evidence scopes. `identities/` retains the dated
prepared-object audit and exact original Git commit bytes. Prepared objects do
not prove that a branch was published; only a separately retained later ref
observation can establish that. This packet includes {index['finalized_agent_notes']} finalized agent notes.
The final mode requires all 60 ledger entries complete and each note's raw hash
matched before inclusion. Historical note statements retain their time context.

Root `manifest.json` inventories every distributed member except itself. Each
evidence row maps its exact raw path/hash/size to its public path/hash/size.
Embedded report hashes, expected/observed exits and byte counts continue to
identify raw evidence. Verify distributed bytes with public identities. Literal
path tokenization is documented in the redaction rules; tokens are inert display
labels. `$AGENT_TREE` denotes the logical agent task namespace, preserving each
unique task-name suffix; it is not a home or temporary filesystem root. Other
tokens separately identify filesystem prefixes and generic root labels in prose.

Use the original `export_final_packets.py verify DESTINATION` helper to check
distributed bytes; add `--raw-workspace RAW_WORKSPACE` to reproduce the exact
transformation. Verification does not authenticate original execution. The
manifest is unsigned; the printed bundle digest covers its bytes too.
Archive members are sorted, regular files only, mode 0644, with zero timestamps,
ownership and gzip timestamp, and no gzip filename. Directory and tar forms
contain identical bytes. Existing destinations and raw files are never replaced.
"""
    metadata("README.md", readme.encode())
    # Re-read every native artifact too, so extension construction cannot make
    # the earlier audited capture stale. Omitted model/build files stay unread.
    for row in artifacts:
        safe.assert_identity(capture.read(row["raw_path"]), row, "final raw recheck", "raw_sha256", "raw_size_bytes")
    manifest = {"schema": SCHEMA, "schema_version": 1, "scope": index["scope"],
                "native_attempt_ids": native_ids, "unit_followup_included": True, "finalized_agent_notes": 60 if final else 0,
                "identity_files": identities, "limits": {"total_bytes": maximum, "files": safe.MAX_FILES,
                "per_file_bytes": safe.MAX_FILE_BYTES}, "artifacts": sorted(artifacts, key=lambda row: row["public_path"]),
                "generated_files": sorted(generated, key=lambda row: row["public_path"]), "omitted_inputs": omissions,
                "extension_protected_json_fields_checked": protected,
                "raw_retained_bytes": sum(row["raw_size_bytes"] for row in artifacts),
                "public_retained_bytes": sum(row["public_size_bytes"] for row in artifacts),
                "private_configuration": {"raw_path": safe.PRIVATE_MAPPING, "raw_sha256": safe.digest(private_bytes),
                "raw_size_bytes": len(private_bytes), "published": False},
                "hash_semantics": native_manifest["hash_semantics"], "original_execution_authenticated": False}
    output["manifest.json"] = safe.encode_json(manifest)
    require(len(output) <= safe.MAX_FILES and sum(map(len, output.values())) <= maximum
            and all(len(data) <= safe.MAX_FILE_BYTES for data in output.values()), "final export ceiling exceeded")
    for name, data in output.items():
        safe.no_machine_paths(data, name, parsed(data, name) if name.endswith(".json") else None)
    capture.recheck()
    forbidden.extend(capture.workspace / name for name in ["diagnostic-stencil-n8", NOTES + "/b08d-run", NOTES + "/b08d-run-2"])
    return output, forbidden


def verify(members, raw_workspace=None):
    manifest = safe.decode_json(members["manifest.json"], "final manifest")
    require(manifest.get("schema") == SCHEMA, "unsupported final publication schema")
    rows = manifest["artifacts"] + manifest["generated_files"]
    mapping = {safe.relative_name(row["public_path"]): row for row in rows}
    require(len(mapping) == len(rows) and set(mapping) | {"manifest.json"} == set(members),
            "final manifest does not cover exactly the distributed files")
    for name, row in mapping.items():
        safe.assert_identity(members[name], row, name, "public_sha256", "public_size_bytes")
    for name, data in members.items():
        safe.no_machine_paths(data, name, parsed(data, name) if name.endswith(".json") else None)
    native = {name[len("native-attempts/"):]: data for name, data in members.items() if name.startswith("native-attempts/")}
    native_result = safe.verify(native)
    native_manifest = safe.decode_json(native["manifest.json"], "nested native manifest")
    for row in native_manifest["artifacts"]:
        expected = {**row, "public_path": "native-attempts/" + row["public_path"]}
        require({key: mapping[expected["public_path"]].get(key) for key in expected} == expected,
                "root/native raw-public mappings disagree")
    index = safe.decode_json(members["index.json"], "public index")
    for commit in index["raw_commit_objects"]:
        data = members[commit["path"]]
        observed = hashlib.sha1(b"commit " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(observed == commit["git_commit_sha1"] and mapping[commit["path"]]["raw_sha256"] == safe.digest(data),
                "original Git commit bytes/identity disagree")

    def link(name, sha, size):
        require(name in mapping and mapping[name].get("raw_sha256") == sha
                and mapping[name].get("raw_size_bytes") == size, "embedded identity differs from raw/public mapping: " + name)

    n8 = safe.decode_json(members["extras/diagnostic-stencil-n8/record.json"], "public n8")
    link("extras/diagnostic-stencil-n8/run.log", n8["result"]["log_sha256"], n8["result"]["log_size_bytes"])
    guardrail = safe.decode_json(members["extras/ci-guardrail/record.json"], "public CI guardrail")
    require(mapping["extras/ci-guardrail/run.log"]["raw_sha256"] == guardrail["log_sha256"],
            "CI guardrail log differs from its recorded raw hash")
    for directory in ["setup-failure", "proof"]:
        prefix = "extras/cp-mutations/" + directory + "/"
        report = safe.decode_json(members[prefix + "report.json"], "public CP report")
        records = parsed(members[prefix + "raw-packet-manifest.json"], "public CP raw manifest")
        token = "$CP_SETUP/" if directory == "setup-failure" else "$CP_PROOF/"
        raw_prefix = NOTES + "/" + ("b08d-run/" if directory == "setup-failure" else "b08d-run-2/")
        omitted = {row["raw_path"]: row for row in manifest["omitted_inputs"]
                   if row["section"] == "cp-" + directory}
        seen_omitted = set()
        for row in records:
            require(row["path"].startswith(token), "CP identity does not name its tokenized packet")
            member = safe.relative_name(row["path"][len(token):])
            if prefix + member in mapping:
                link(prefix + member, row["sha256"], row["size_bytes"])
            else:
                name = raw_prefix + member
                require(name in omitted and omitted[name]["raw_sha256"] == row["sha256"]
                        and omitted[name]["raw_size_bytes"] == row["size_bytes"]
                        and omitted[name]["bytes_reread_by_exporter"] is False,
                        "omitted CP identity differs from its retained raw manifest")
                seen_omitted.add(name)
        require(seen_omitted == set(omitted), "unmatched omitted CP identity")
        for command in report["commands"]:
            link(prefix + safe.relative_name(command["log"]), command["log_sha256"], command["log_size_bytes"])
        link(prefix + "executed-runner.py", report["script"]["sha256"], report["script"]["size_bytes"])
        for case in report["cases"]:
            link(prefix + "sources/" + safe.relative_name(case["name"]) + ".cpp", case["source"]["sha256"], case["source"]["size_bytes"])
    if manifest["unit_followup_included"]:
        prefix = "local-units-followup/"
        report = safe.decode_json(members[prefix + "report.redacted.json"], "public unit report")
        finished_report(report, "public units")
        require(index["two_unit_followup"]["reported_outcome"] == report["outcome"]
                and index["two_unit_followup"]["raw_report_sha256"] == mapping[prefix + "report.redacted.json"]["raw_sha256"]
                and index["two_unit_followup"]["full_suite_executed"] is False,
                "unit index outcome/raw anchor differs from retained report")
        for command in report["commands"]:
            link(prefix + safe.relative_name(command["log"]), command["log_sha256"], command["log_size_bytes"])
        for snapshot in report["snapshots"]:
            row = snapshot["retained"]
            link(prefix + safe.relative_name(row["path"]), row["sha256"], row["size_bytes"])
    if manifest["finalized_agent_notes"]:
        ledger = safe.decode_json(members["agent-notes/execution-ledger.json"], "public ledger")
        require(len(ledger["agents"]) == 60 and all(row["status"] == "complete" for row in ledger["agents"]),
                "public final ledger is incomplete")
        for agent in ledger["agents"]:
            name = "agent-notes/" + safe.relative_name(agent["note"])
            require(mapping[name]["raw_sha256"] == agent["note_sha256"], "public ledger raw note hash mismatch")
    reproduced = False
    if raw_workspace is not None:
        expected, _ = build_bundle(raw_workspace, final=manifest["scope"] == "final",
                                   identity_files=manifest["identity_files"], maximum=manifest["limits"]["total_bytes"])
        require(expected == members, "final published bytes differ from raw-input reproduction")
        reproduced = True
    return {"published_integrity": "verified", "raw_to_public_reproduced": reproduced,
            "original_execution_authenticated": False, "scope": manifest["scope"], "files": len(members),
            "bytes": sum(map(len, members.values())), "bundle_sha256": safe.bundle_identity(members),
            "native_attempt_outcomes": native_result["attempt_outcomes"],
            "unit_followup_included": manifest["unit_followup_included"],
            "finalized_agent_notes": manifest["finalized_agent_notes"],
            "omitted_cp_members_with_recorded_identities": len(manifest["omitted_inputs"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ["export", "check-completed"]:
        command = actions.add_parser(name)
        command.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[2])
        command.add_argument("--identity-file", action="append", default=[])
        command.add_argument("--max-bytes", type=int, default=safe.MAX_BYTES)
        if name == "export":
            command.add_argument("--destination", type=Path, required=True)
            command.add_argument("--format", choices=["directory", "tar.gz"], default="directory")
    check = actions.add_parser("verify")
    check.add_argument("destination", type=Path)
    check.add_argument("--raw-workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "verify":
            result = verify(safe.load_public(args.destination), args.raw_workspace)
        else:
            final = args.action == "export"
            if final:
                require(not os.path.lexists(args.destination), "destination exists; nothing overwritten")
            members, forbidden = build_bundle(args.workspace, final, args.identity_file, args.max_bytes)
            result = verify(members)
            if final:
                result.update(safe.publish(args.workspace, args.destination, members, forbidden, args.format, args.max_bytes))
                require(safe.load_public(args.destination) == members, "written final bytes differ")
                result.update({"raw_to_public_reproduced": True, "raw_inputs_rechecked_unchanged": True, "format": args.format})
            else:
                archive = safe.archive_bytes(members)
                require(archive == safe.archive_bytes(members), "nondeterministic archive")
                result.update({"published": False, "deterministic_archive_sha256": safe.digest(archive),
                               "deterministic_archive_bytes": len(archive), "raw_inputs_rechecked_unchanged": True})
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (safe.ExportError, OSError, UnicodeError, KeyError, TypeError, ValueError, tarfile.TarError, EOFError) as error:
        print("export_final_packets: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
