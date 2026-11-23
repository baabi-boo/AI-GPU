# SPDX-License-Identifier: Apache-2.0
"""Validate explicitly selected warm records and their complete lifetime witness."""

from __future__ import annotations

import p06_managed_preflight_contract as preflight
import p06_managed_preflight_records as managed_records
import p06_native_lifetime_contract as lifetime_contract
import p06_native_lifetime_records as lifetime_records
import p06_warm_records as warm_records


CONTRACT_ID = "p06-qualified-warm-counter-witness-v1"
LIFETIME_CONTRACT_ID = "p06-qualified-warm-lifetime-witness-v1"
require = preflight.require
fixed = preflight.fixed
fields = preflight.fields


def process_identity(fmt, policy, binding_id, pair_index, phase):
    require(type(fmt) is str and fmt in preflight.FORMATS,
            "unsupported qualified warm format")
    require(type(policy) is str and policy in preflight.POLICIES,
            "unsupported qualified warm allocation policy")
    preflight.digest(binding_id, "qualified warm execution binding")
    require(type(pair_index) is int and 0 <= pair_index <= 5,
            "qualified warm pair index must be an integer from zero through five")
    fixed(phase, "warmup" if pair_index == 0 else "measured", "qualified warm phase")
    sample_id = f"warm-simx-{fmt}-pair{pair_index}-{policy}"
    return {"schema_version": 1, "contract_id": CONTRACT_ID,
            "process_id": sample_id, "sample_id": sample_id,
            "execution_binding_sha256": binding_id, "format": fmt, "policy": policy}


def verify_output(text, *, contract, case, fmt, policy, binding_id, sample_id,
                  process_id, expected_libraries, pair_index, phase):
    """Check original bytes without conferring archive or performance qualification."""
    preflight.validate_contract(contract)
    identity = process_identity(fmt, policy, binding_id, pair_index, phase)
    fixed(sample_id, identity["sample_id"], "qualified warm sample identity")
    fixed(process_id, identity["process_id"], "qualified warm process identity")
    fields(expected_libraries, preflight.LOADED_LIBRARY_NAMES, "expected loaded library paths")

    parent_text, lifetime = lifetime_records._split_output(text)
    warm_text, witness = managed_records._split_output(parent_text)
    fields(witness, preflight.WITNESS_FIELDS, "qualified warm counter witness")
    fields(lifetime, lifetime_contract.WITNESS_FIELDS, "qualified warm lifetime witness")
    for record, expected, label in (
        (witness, identity, "qualified warm counter witness"),
        (lifetime, dict(identity, contract_id=LIFETIME_CONTRACT_ID), "qualified warm lifetime witness"),
    ):
        for name, value in expected.items():
            fixed(record[name], value, label + "." + name)
        for name, value in lifetime_contract.ROUTE.items():
            fixed(record[name], value, label + "." + name)
        preflight.false_claims(record, label)
        fixed(record["unresolved_obligations"], list(preflight.UNRESOLVED_OBLIGATIONS),
              label + ".unresolved_obligations")
    preflight.validate_loaded_libraries(witness["loaded_libraries"], expected_libraries)
    warm = warm_records.verify_output(
        warm_text, case=case, fmt=fmt, policy=policy, binding_id=binding_id,
        sample_id=sample_id, pair_index=pair_index, phase=phase,
        contract=preflight.warm.load_contract(preflight.ROOT))
    managed_records._observation(witness["observation"])
    managed_records._snapshots(witness, warm, preflight.counter_inventory(contract))
    managed_records._cache_flushes(witness)

    fixed(lifetime["trace_overflow"], False, "qualified warm lifetime trace_overflow")
    lifetime_records._model(lifetime["constructed_state"], "qualified warm constructed state",
                           witness["observation"]["constructed_state"])
    baseline = lifetime["constructed_state"]["reset_generation"]
    require(baseline <= lifetime_contract.MAX_UINT64 - lifetime_contract.OPERATIONS,
            "qualified warm reset generation would overflow")
    lifetime_records._snapshots(lifetime, witness, baseline)
    lifetime_records._pending_reads(lifetime["reads"], witness["reads"], "qualified warm MPM reads")
    lifetime_records._pending_reads(lifetime["cache_flush_reads"], witness["cache_flush_reads"],
                                   "qualified warm cache-flush reads")
    lifetime_records._runs(lifetime, witness, baseline)
    lifetime_records._destruction(lifetime, witness)
    return {"warm": warm, "witness": witness, "lifetime": lifetime}
