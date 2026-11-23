# SPDX-License-Identifier: Apache-2.0
"""Fixed inputs and bounds for fresh selected SimX dependency provenance."""

from copy import deepcopy
import hashlib
import json


CONTRACT_ID = "p06-dependency-provenance-v1"
MANAGED_CONTRACT_ID = "p06-managed-dependency-lifetime-v1"
SCHEMA_VERSION = 1
PINS = {
    "softfloat": {
        "url": "https://github.com/ucb-bar/berkeley-softfloat-3.git",
        "revision": "b51ef8f3201669b2288104c28546fc72532a1ea4",
        "tree": "8d9d47a6d74670d25bbbcc956a04de4c2605253b",
        "path": "third_party/softfloat",
    },
    "ramulator": {
        "url": "https://github.com/CMU-SAFARI/ramulator2.git",
        "revision": "e62c84a6f0e06566ba6e182d308434b4532068a5",
        "tree": "01dce703c539f6bf5ca1ac73e759067f0dd2717b",
        "path": "third_party/ramulator",
    },
    "yaml-cpp": {
        "url": "https://github.com/jbeder/yaml-cpp.git",
        "revision": "0579ae3d976091d7d664aa9d2527e0d0cff25763",
        "tree": "3b4adf4e0b979fd6fb9213034acaf4864327d1aa",
        "path": "third_party/ramulator/ext/yaml-cpp",
    },
    "spdlog": {
        "url": "https://github.com/gabime/spdlog.git",
        "revision": "ad0e89cbfb4d0c1ce4d097e134eb7be67baebb36",
        "tree": "64a823f2b9c61b35897fb89f2a32844a24e87cb6",
        "path": "third_party/ramulator/ext/spdlog",
    },
    "argparse": {
        "url": "https://github.com/p-ranav/argparse.git",
        "revision": "997da9255618311d1fcb0135ce86022729d1f1cb",
        "tree": "da4b4bb886f2521f326dc3aacf8304aede1044c1",
        "path": "third_party/ramulator/ext/argparse",
    },
}
PRODUCTS = {
    "softfloat": "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
    "ramulator": "third_party/ramulator/libramulator.so",
    "extension": "third_party/ramulator_ext/libramulator-vortex.so",
}
TRANSLATION_UNITS = {"softfloat": 309, "ramulator": 60, "yaml-cpp": 29,
                     "spdlog": 7, "extension": 1}
FALSE_CLAIMS = ("qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
                "acceptance_claimed", "phase_acceptance", "performance_acceptance")
BUDGET = {"jobs": 2, "simulation_workers": 1, "min_free_bytes": 15 * 1024**3,
          "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2,
          "configure_timeout_seconds": 120, "build_timeout_seconds": 1800,
          "process_timeout_seconds": 180}
SOFTFLOAT_OPTIONS = ("-fPIC", "-DSOFTFLOAT_ROUND_ODD", "-DINLINE_LEVEL=5",
                     "-DSOFTFLOAT_FAST_DIV32TO16", "-DSOFTFLOAT_FAST_DIV64TO32",
                     "-DTHREAD_LOCAL=_Thread_local")
MAX_SOURCE_BYTES = 64 * 1024**2
MAX_FILE_BYTES = 64 * 1024**2
MAX_PACKET_BYTES = 1024**3
MAX_RECEIPT_BYTES = 16 * 1024**2
MAX_RECORDS = 1024
LIMITATIONS = (
    "The selected dependency source, observed commands and products are bound; complete compiler/system-input closure is not claimed.",
    "Inert receipt review establishes consistency of a caller-pinned original, not execution or producer authentication.",
    "Before/after stability checks do not protect against malicious concurrent filesystem writers.",
    "Disconnected CMake source selection prevents implicit population; it is not operating-system network isolation.",
    "Native lifetime observations do not establish complete 40-component counter qualification or an absolute no-wrap bound.",
    "All qualification, warm execution, performance and phase-acceptance claims remain false.",
)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def contract():
    return {"schema_version": SCHEMA_VERSION, "contract_id": CONTRACT_ID,
            "managed_contract_id": MANAGED_CONTRACT_ID,
            "pins": deepcopy(PINS), "products": dict(PRODUCTS),
            "translation_units": dict(TRANSLATION_UNITS), "budget": dict(BUDGET),
            "softfloat_options": list(SOFTFLOAT_OPTIONS),
            "source_limit_bytes": MAX_SOURCE_BYTES, "file_limit_bytes": MAX_FILE_BYTES,
            "packet_limit_bytes": MAX_PACKET_BYTES, "receipt_limit_bytes": MAX_RECEIPT_BYTES,
            "record_limit": MAX_RECORDS, "false_claims": list(FALSE_CLAIMS),
            "limitations": list(LIMITATIONS)}


def contract_hash():
    return digest(contract())
