#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise provenance compiler grammar against retained native role stamps.

This component probe performs no native execution or whole-packet acceptance.
Every mutation receives a freshly computed record hash and macro summary.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import sys


def record(audit, line, role):
    flags = [word for word in shlex.split(line) if word.startswith("-D")]
    defines = {}
    for flag in flags:
        name, equal, value = flag[2:].partition("=")
        defines[name] = value if equal else "1"
    return {"role": role, "sha256": audit.digest(line.encode()), "macro_flags": flags,
            "configuration": {k: v for k, v in defines.items()
                              if k.startswith("VX_CFG_") or k in ("ITYPE", "OTYPE", "KUNROLL")}}


def mutations(line, source, fmt):
    words = shlex.split(line)
    indices = [i for i, word in enumerate(words) if word.startswith("-I")]
    first, second = indices[:2]
    changed = {}
    changed["foreign_prepend"] = "-I/tmp/unbound-shadow-headers " + line
    changed["foreign_append"] = line + " -I/tmp/unbound-shadow-headers"
    changed["traversal_prepend"] = "-I" + source + "/sw/../../foreign " + line
    replacement = list(words)
    replacement[first] += "/../foreign"
    changed["traversal_replace"] = shlex.join(replacement)
    replacement[first] = "-I" + source + "/sw/../sw"
    changed["normalized_alias"] = shlex.join(replacement)
    changed["duplicate_root"] = shlex.join(words[:first] + [words[first]] + words[first:])
    changed["missing_root"] = shlex.join(words[:first] + words[first + 1:])
    replacement = list(words)
    replacement[first], replacement[second] = replacement[second], replacement[first]
    changed["reordered_roots"] = shlex.join(replacement)
    changed["split_include_flag"] = shlex.join(words[:first] + ["-I", words[first][2:]] + words[first + 1:])
    for name, flag in (
            ("system_include", "-isystem /tmp/foreign"),
            ("quote_include", "-iquote /tmp/foreign"),
            ("after_include", "-idirafter /tmp/foreign"),
            ("forced_include", "-include /tmp/override.h"),
            ("macro_include", "-imacros /tmp/override.h"),
            ("sysroot_override", "--sysroot=/tmp/foreign"),
            ("preprocessor_include", "-Wp,-I/tmp/foreign"),
            ("forwarded_include", "-Xpreprocessor -I/tmp/foreign"),
            ("verilator_include", "+incdir+/tmp/foreign"),
            ("dpi_tensor", "-DVX_CFG_TCU_TYPE_DPI"),
            ("dpi_fpu", "-DVX_CFG_FPU_TYPE_DPI"),
            ("wrong_input_type", "-DITYPE=" + ("bf16" if fmt == "fp16" else "fp16")),
            ("wrong_threads", "-DVX_CFG_NUM_THREADS=8"),
            ("fast_math", "-ffast-math"),
            ("finite_math", "-ffinite-math-only"),
            ("undefine_selector", "-UVX_CFG_TCU_TYPE_TFR"),
            ("response_file", "@override.flags")):
        changed[name] = line + " " + flag
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    auditor = Path(__file__).with_name("audit_provenance.py")
    spec = importlib.util.spec_from_file_location("provenance_audit", auditor)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    result = {"schema_version": 1, "scope": "retained compiler-record components",
              "outcome": "fail", "acceptance_claimed": False, "native_execution": False,
              "whole_packet_audit_performed": False, "auditor_sha256": audit.digest(auditor.read_bytes()),
              "probe_sha256": audit.digest(Path(__file__).read_bytes()), "packets": []}
    count = negatives = 0
    try:
        for selected in args.packet:
            packet = selected.resolve()
            if packet.name == "report.json":
                packet = packet.parent
            report_bytes = audit.read(packet, "report.json")
            report = audit.decode(report_bytes)
            packet_result = {"packet": str(packet), "report_sha256": audit.digest(report_bytes), "roles": []}
            for variant in report["variants"]:
                backend, fmt = variant["backend"], variant["format"]
                prefix = "artifacts/" + variant["id"] + "/"
                artifact_ids = audit.inventory(variant["artifacts_before"])

                def stamp(name):
                    data = audit.checked(packet, dict(artifact_ids[name], path=prefix + name))
                    return data.decode().splitlines()

                runtime = stamp("sw/runtime/" + backend + "_rt_config.stamp")
                native = stamp("sw/runtime/" + backend + "_config.stamp")
                application = stamp("tests/regression/ai_mlp/config.stamp")
                roles = ["runtime"] + (["verilator", "backend_cpp"] if backend == "rtlsim"
                                       else ["backend_cpp"]) + ["kernel", "host"]
                audit.require(len(runtime) == 1 and len(native) == len(roles) - 3
                              and len(application) == 3 and len(variant["compiler_records"]) == len(roles),
                              "invalid role inventory")
                for line, role, reported in zip(runtime + native + application[:2], roles,
                                                variant["compiler_records"]):
                    source = report["paths"]["source"]
                    kwargs = {"backend": backend, "build": report["paths"]["work"] + "/" + variant["id"],
                              "selectors": not (backend == "rtlsim" and role == "backend_cpp")}
                    audit.compiler_record(line, role, fmt, reported, source, report["budget"]["jobs"], **kwargs)
                    count += 1
                    failures = []
                    for name, mutated in mutations(line, source, fmt).items():
                        try:
                            audit.compiler_record(mutated, role, fmt, record(audit, mutated, role),
                                                  source, report["budget"]["jobs"], **kwargs)
                        except ValueError as error:
                            failures.append({"mutation": name, "reason": str(error)})
                            negatives += 1
                        else:
                            raise ValueError("accepted mutation: " + variant["id"] + "/" + role + "/" + name)
                    packet_result["roles"].append({"variant": variant["id"], "role": role,
                                                   "raw_record_sha256": audit.digest(line.encode()),
                                                   "rejected_mutations": failures})
            result["packets"].append(packet_result)
        result.update(outcome="pass", compiler_roles_checked=count, mutations_rejected=negatives)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        result["reason"] = str(error)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "packets"}, indent=2, sort_keys=True))
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
