#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate the frozen P06 native benchmark inputs without executing a GPU."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tomllib

import p02_wmma_fixtures as operator_fixtures
import p04_fixture_adapter as model_fixtures


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = "ci/project/p06_benchmark_contract.json"
CONTRACT_ID = "p06-native-baseline-v1"
FORMATS = ("fp16", "bf16")
MAX_MANIFEST_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_INTEGER_DIGITS = 20
MAX_UINT64 = (1 << 64) - 1

_SOURCE_HASHES = {'VX_config.toml': 'a1c49de52a0373b5f74706528d46bea1181c54f7769dd03994e033c7ddd710bf',
 'VX_types.toml': 'f8eb0b3343f66ebe0a3c9030c8c9150c13638e7c23744b00b2fcf8ce005d5f23',
 'ci/gen_config.py': 'b710a1b80c89d327adf079e61aec9f5d4f950d89342b633b6b00871e50abe165',
 'ci/project/fixtures/p02_layout_v1.json': '0543f9f4208de3ff4743fe1894d97ccf3b8cca4707e9a26acd1f3dde884725b2',
 'ci/project/fixtures/p02_wmma_numerical_v1.json': '4102d74024e92e9887d7324b9326c0d6ad1fff206b5fad33f45c530d5bd03a73',
 'ci/project/fixtures/p04_tiny_mlp_v1.json': 'd22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03',
 'ci/project/p02_fixture_oracle.py': '12e546864a4fef5b05e10c7a04b1006bcd59376e5921ea1221c4d42668490145',
 'ci/project/p02_layout_fixture_oracle.py': '34e78c0313e2b032930615f02a790729d1c49293349728b55f7d04a29a2568a7',
 'ci/project/p02_wmma_fixtures.py': '4a672a5d3357f220120f43e5f5d7e880f7d0ba36df380d69cd1873ea4879835e',
 'ci/project/p02_wmma_numerical_fixture_oracle.py': '083450dc11712e5fc6dce7d19fb854bd9ef25b738347efd56bd07e81b079570b',
 'ci/project/p03_operator_manifest.json': '09f7071a40cec46f3fd7290a4aaadefc730a2bf006dc401a220050246d229f6b',
 'ci/project/p04_fixture_adapter.py': '37a50f6f0f80fd79b926b7ed5d13a233de6bf518590da7fa7d40800dcc91094a',
 'ci/project/p04_model_contract.py': 'c184d980d57aec54567d79025845c5fb34887741697ac78a66692a65da02e4b3',
 'ci/project/p04_model_manifest.json': '8eb6acc6c8d19990eca2fc328395a1dcc3f41c7a3d6deee904a3e923163e9ec2',
 'ci/project/p04_reference.py': '115a7db51948d69fc6267d5fe658d1a8e68c22e9f200d5ddc3f0a5181d7140a9',
 'profiles/p02-tfr.json': '79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102',
 'sim/common/cmd_processor.cpp': 'c7090583f8dd1774d71755dc96f11845ff4d96340e51451643ec1ab16b14dd42',
 'sim/simx/Makefile': 'c719966647f32fef5421dd798a89d3eeddccd692e7c61046e5744b7a8e722403',
 'sim/simx/core.cpp': '7409ef4c0f0826d6bacb43912994de3ab0b66543b32261e790834d1b201fb411',
 'sim/simx/mem/cache.cpp': 'c8eacd73616bb9f82533bbe45ba8a317524717948de08d73ecdb78dfb0c4a53d',
 'sim/simx/mem/local_mem.cpp': '07aa27331d6ef604a432b99e70df12b7853787d4151cc1517092d76406cd4d33',
 'sim/simx/processor.cpp': '2b706eef0741b9c594c67d2d4914ad8e1a79d872a323aea9b49417958a50731e',
 'sim/simx/tcu/tcu_tbuf.cpp': 'da6fbd571c11c10adb8f80299a1c36d7de0e1137d6284e83a600f196cf2a8c23',
 'sim/simx/tcu/tcu_unit.cpp': 'b48d0e7fe5145292ad354168d3fe73b0bcdbbb508335656ce6fe07608af8fb5b',
 'sim/simx/types.h': '2cdd672188cdcbf03558bc9bd2058c9715466c35eacece5078f692f46d809809',
 'sw/common/ai_matmul_args.h': '732bd11a5002a4486ffe89b75f082f199f4bd2436c984ddaaae63d0748f02147',
 'sw/common/ai_matmul_profile.h': '8b2eb9a819506227808537612672c08a574230736f13f840a9d83bbd35675680',
 'sw/kernel/ai/matmul.cpp': 'ad3b6107f0eef91ec676412bc795ab70cd1c9f31647b2cea854de6234fe71d3e',
 'sw/runtime/ai/contract.cpp': '0accd8d6a977b61f66035ced218b2fb95cf88287b7dec6f6286f361c3371b5ff',
 'sw/runtime/ai/contract.h': '7d6194824706b1a256c4810b131340af3f5e8e45ccb81313546507b914c33d5b',
 'sw/runtime/ai/mlp_host.cpp': 'de11f87400c61b166ab70913f437921ad9beed61a1aaa6ba8d35eb8eeb275256',
 'sw/runtime/ai/mlp_host.h': '309e437aa9ca80c3a9c7c8ca7544478cdce4861203d32280709e2e940425cd0b',
 'sw/runtime/ai/mlp_runtime.cpp': '0dab325434c513b85b66b108ca3b896304ab797252b9fd01919435fc8655ddd1',
 'sw/runtime/ai/mlp_runtime.h': '56750815b71361eb036aa8000716b977569a657a2cee650f9bdd048c06b81182',
 'sw/runtime/ai/runtime.cpp': '5540092240fb926f1c3066b0e8956a0096cb6be42b71f8b60d075434518e0be5',
 'sw/runtime/ai/runtime.h': 'dc9c5f789c0a58dfbdce10420fce32f1d17c8e71fb83a7608d6e38489d4d4ad1',
 'sw/runtime/common/caps.h': '3ffcb14c88433fd02254322a73c6b58008b7f223e6fd47dee023be4d6b9b49bb',
 'sw/runtime/common/common.h': '3504e28ddde5e0ab5f34de9dbe5f9b51ffc637cdb303c31f0d2ddd4f81b03c83',
 'sw/runtime/common/device.cpp': '9b32e38a9bbc0460a7f2af522fd5efdc96e1c06e359e28c5151285557f89d90a',
 'sw/runtime/common/perf.cpp': 'fa6945cf379ae184d4e3edca5fcbc147d11f725e5ad3574ff3f89a16167099b3',
 'sw/runtime/simx/vortex.cpp': '5558f262394cb278db3b5d170e976162c2c1ccf84b6479204bad83f5afab91a3',
 'tests/regression/ai_matmul/main.cpp': '31428ef514ba3f3f8ba687fd3cecf4f032126a8e0055fd37ca6f7eab99f54317',
 'tests/regression/ai_mlp/main.cpp': '1abf4706aaa5265a4ddd959587d2095e2a01f32ad6b1ca94d30fffd8e562eb9b',
 'tests/regression/ai_mlp/p04_fixtures.h': '61a1368572b0cee5e67e0cc803b32e57b19557f53eb6b8e32e079a55b237e773',
 'tests/regression/ai_mlp/records.h': '13a4d51ab7058a799b9598c0ba410b64b6bd28d77c305f88de702ef0db8daf29',
 'tests/regression/sgemm_tcu/p02_fixtures.h': '1e692ad5d14e895286e57e45bf9d1730cf2380a33ccbaa486c601db838daa64e'}

# Historical analysis uses current, reviewed readers and independent producers.
# These are the frozen inputs needed to interpret the manifest, CSR table and
# workload fixtures; they are deliberately enumerated rather than derived by
# excluding whichever execution sources happen to have changed. The P04 model
# validator also verifies its transitive documentation/license inputs against
# the pinned model manifest, and the P02 validator reproduces its leaf fixture.
# All execution-source pins remain mandatory in validate_contract() and must
# separately be checked against retained source bytes by an archive replayer.
ANALYSIS_SOURCE_PATHS = (
    "VX_config.toml",
    "VX_types.toml",
    "ci/gen_config.py",
    "ci/project/fixtures/p02_layout_v1.json",
    "ci/project/fixtures/p02_wmma_numerical_v1.json",
    "ci/project/fixtures/p04_tiny_mlp_v1.json",
    "ci/project/p02_fixture_oracle.py",
    "ci/project/p02_layout_fixture_oracle.py",
    "ci/project/p02_wmma_fixtures.py",
    "ci/project/p02_wmma_numerical_fixture_oracle.py",
    "ci/project/p03_operator_manifest.json",
    "ci/project/p04_fixture_adapter.py",
    "ci/project/p04_model_contract.py",
    "ci/project/p04_model_manifest.json",
    "ci/project/p04_reference.py",
    "profiles/p02-tfr.json",
    "sw/common/ai_matmul_args.h",
    "sw/common/ai_matmul_profile.h",
    "sw/runtime/ai/contract.h",
    "sw/runtime/ai/mlp_host.cpp",
    "sw/runtime/ai/mlp_host.h",
)
_ANALYSIS_HELPERS = (
    ("ci/project/p02_fixture_oracle.py", operator_fixtures.leaf),
    ("ci/project/p02_layout_fixture_oracle.py", operator_fixtures.layout),
    ("ci/project/p02_wmma_fixtures.py", operator_fixtures),
    ("ci/project/p02_wmma_numerical_fixture_oracle.py", operator_fixtures.numerical),
    ("ci/project/p04_fixture_adapter.py", model_fixtures),
    ("ci/project/p04_model_contract.py", model_fixtures.contract),
    ("ci/project/p04_reference.py", model_fixtures.reference),
)

_CAPABILITIES = (('num_cores', 3),
 ('num_clusters', 10),
 ('socket_size', 11),
 ('num_warps', 2),
 ('num_threads', 1),
 ('issue_width', 12),
 ('isa_flags', 7),
 ('cache_line_bytes', 4),
 ('local_mem_bytes', 6),
 ('global_mem_bytes', 5),
 ('num_mem_banks', 8),
 ('mem_bank_bytes', 9),
 ('vm_support', 15))
_COUNTERS = (
    ('cycles', 0, 2816, 0, 'core', 'active_core_cycles', 0, 'VX_DCR_MPM_CLASS_BASE', 'VX_CSR_MCYCLE'),
    ('instructions', 0, 2818, 0, 'core', 'retired_macroinstructions', 0, 'VX_DCR_MPM_CLASS_BASE', 'VX_CSR_MINSTRET'),
    ('core_sched_idle', 1, 2819, 0, 'core', 'cycles', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_SCHED_IDLE'),
    ('core_active_warps', 1, 2820, 0, 'core', 'warp_cycles', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_ACTIVE_WARPS'),
    ('core_stalled_warps', 1, 2821, 0, 'core', 'warp_cycles', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_STALLED_WARPS'),
    ('core_issued_warps', 1, 2822, 0, 'core', 'warps', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_ISSUED_WARPS'),
    ('core_issued_threads', 1, 2823, 0, 'core', 'threads', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_ISSUED_THREADS'),
    ('core_stall_scrb', 1, 2826, 0, 'core', 'cycles', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_STALL_SCRB'),
    ('core_stall_lsu', 1, 2830, 0, 'core', 'cycles', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_STALL_LSU'),
    ('core_stall_tcu', 1, 2832, 0, 'core', 'cycles', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_STALL_TCU'),
    ('core_instr_tcu', 1, 2839, 0, 'core', 'instructions', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_INSTR_TCU'),
    ('core_loads', 1, 2844, 0, 'core', 'issued_lane_requests', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_LOADS'),
    ('core_stores', 1, 2846, 0, 'core', 'issued_lane_requests', 0, 'VX_DCR_MPM_CLASS_CORE', 'VX_CSR_MPM_STORES'),
    ('icache_reads', 3, 2819, 0, 'socket', 'requests', 4294967296, 'VX_DCR_MPM_CLASS_ICACHE', 'VX_CSR_MPM_ICACHE_READS'),
    ('icache_miss_r', 3, 2820, 0, 'socket', 'requests', 4294967296, 'VX_DCR_MPM_CLASS_ICACHE', 'VX_CSR_MPM_ICACHE_MISS_R'),
    ('icache_mshr_st', 3, 2821, 0, 'socket', 'cycles', 4294967296, 'VX_DCR_MPM_CLASS_ICACHE', 'VX_CSR_MPM_ICACHE_MSHR_ST'),
    ('dcache_reads', 4, 2819, 0, 'socket', 'requests', 8589934592, 'VX_DCR_MPM_CLASS_DCACHE', 'VX_CSR_MPM_DCACHE_READS'),
    ('dcache_writes', 4, 2820, 0, 'socket', 'requests', 8589934592, 'VX_DCR_MPM_CLASS_DCACHE', 'VX_CSR_MPM_DCACHE_WRITES'),
    ('dcache_miss_r', 4, 2821, 0, 'socket', 'requests', 8589934592, 'VX_DCR_MPM_CLASS_DCACHE', 'VX_CSR_MPM_DCACHE_MISS_R'),
    ('dcache_miss_w', 4, 2822, 0, 'socket', 'requests', 8589934592, 'VX_DCR_MPM_CLASS_DCACHE', 'VX_CSR_MPM_DCACHE_MISS_W'),
    ('dcache_evicts', 4, 2823, 0, 'socket', 'requests', 8589934592, 'VX_DCR_MPM_CLASS_DCACHE', 'VX_CSR_MPM_DCACHE_EVICTS'),
    ('dcache_mshr_st', 4, 2825, 0, 'socket', 'cycles', 8589934592, 'VX_DCR_MPM_CLASS_DCACHE', 'VX_CSR_MPM_DCACHE_MSHR_ST'),
    ('l2cache_reads', 5, 2819, 0, 'cluster', 'requests', 17179869184, 'VX_DCR_MPM_CLASS_L2CACHE', 'VX_CSR_MPM_L2CACHE_READS'),
    ('l2cache_writes', 5, 2820, 0, 'cluster', 'requests', 17179869184, 'VX_DCR_MPM_CLASS_L2CACHE', 'VX_CSR_MPM_L2CACHE_WRITES'),
    ('l2cache_miss_r', 5, 2821, 0, 'cluster', 'requests', 17179869184, 'VX_DCR_MPM_CLASS_L2CACHE', 'VX_CSR_MPM_L2CACHE_MISS_R'),
    ('l2cache_miss_w', 5, 2822, 0, 'cluster', 'requests', 17179869184, 'VX_DCR_MPM_CLASS_L2CACHE', 'VX_CSR_MPM_L2CACHE_MISS_W'),
    ('l2cache_evicts', 5, 2823, 0, 'cluster', 'requests', 17179869184, 'VX_DCR_MPM_CLASS_L2CACHE', 'VX_CSR_MPM_L2CACHE_EVICTS'),
    ('l2cache_mshr_st', 5, 2825, 0, 'cluster', 'cycles', 17179869184, 'VX_DCR_MPM_CLASS_L2CACHE', 'VX_CSR_MPM_L2CACHE_MSHR_ST'),
    ('l3cache_reads', 6, 2819, 0, 'global', 'requests', 34359738368, 'VX_DCR_MPM_CLASS_L3CACHE', 'VX_CSR_MPM_L3CACHE_READS'),
    ('l3cache_writes', 6, 2820, 0, 'global', 'requests', 34359738368, 'VX_DCR_MPM_CLASS_L3CACHE', 'VX_CSR_MPM_L3CACHE_WRITES'),
    ('l3cache_miss_r', 6, 2821, 0, 'global', 'requests', 34359738368, 'VX_DCR_MPM_CLASS_L3CACHE', 'VX_CSR_MPM_L3CACHE_MISS_R'),
    ('l3cache_miss_w', 6, 2822, 0, 'global', 'requests', 34359738368, 'VX_DCR_MPM_CLASS_L3CACHE', 'VX_CSR_MPM_L3CACHE_MISS_W'),
    ('l3cache_evicts', 6, 2823, 0, 'global', 'requests', 34359738368, 'VX_DCR_MPM_CLASS_L3CACHE', 'VX_CSR_MPM_L3CACHE_EVICTS'),
    ('l3cache_mshr_st', 6, 2825, 0, 'global', 'cycles', 34359738368, 'VX_DCR_MPM_CLASS_L3CACHE', 'VX_CSR_MPM_L3CACHE_MSHR_ST'),
    ('lmem_reads', 7, 2823, 0, 'core', 'requests', 68719476736, 'VX_DCR_MPM_CLASS_MEM', 'VX_CSR_MPM_LMEM_READS'),
    ('lmem_writes', 7, 2824, 0, 'core', 'requests', 68719476736, 'VX_DCR_MPM_CLASS_MEM', 'VX_CSR_MPM_LMEM_WRITES'),
    ('lmem_bank_st', 7, 2825, 0, 'core', 'cycles', 68719476736, 'VX_DCR_MPM_CLASS_MEM', 'VX_CSR_MPM_LMEM_BANK_ST'),
    ('coalescer_miss', 7, 2826, 0, 'core', 'extra_coalescing_rounds', 0, 'VX_DCR_MPM_CLASS_MEM', 'VX_CSR_MPM_COALESCER_MISS'),
    ('memory_reads', 7, 2819, 0, 'global', 'requests', 0, 'VX_DCR_MPM_CLASS_MEM', 'VX_CSR_MPM_MEM_READS'),
    ('memory_writes', 7, 2820, 0, 'global', 'requests', 0, 'VX_DCR_MPM_CLASS_MEM', 'VX_CSR_MPM_MEM_WRITES'),
    ('memory_lt', 7, 2821, 0, 'global', 'request_cycles', 0, 'VX_DCR_MPM_CLASS_MEM', 'VX_CSR_MPM_MEM_LT'),
    ('memory_bank_st', 7, 2822, 0, 'global', 'cycles', 0, 'VX_DCR_MPM_CLASS_MEM', 'VX_CSR_MPM_MEM_BANK_ST'),
    ('tcu_tbuf_stalls', 11, 2819, 0, 'core', 'cycles', 2199023255552, 'VX_DCR_MPM_CLASS_TCU', 'VX_CSR_MPM_TCU_TBUF_STALLS'),
    ('tcu_tbuf_cache_hits', 11, 2820, 0, 'core', 'tile_reuse_hits', 2199023255552, 'VX_DCR_MPM_CLASS_TCU', 'VX_CSR_MPM_TCU_TBUF_CACHE_HITS'),
    ('tcu_lmem_reads', 11, 2821, 0, 'core', 'requests', 2199023255552, 'VX_DCR_MPM_CLASS_TCU', 'VX_CSR_MPM_TCU_LMEM_READS'),
)

_CAPABILITY_VALUES = {
    "num_cores": 1, "num_clusters": 1, "socket_size": 1,
    "num_warps": 4, "num_threads": 4, "issue_width": 1,
    "isa_flags": 2420223512872, "cache_line_bytes": 64,
    "local_mem_bytes": 16384, "global_mem_bytes": 8589934592,
    "num_mem_banks": 2, "mem_bank_bytes": 140737488355328, "vm_support": 0,
}

_SELECTIONS = (
    ("single-dense_boundaries", "matmul", "ci/project/fixtures/p02_layout_v1.json",
     ((8, 4, 8),)),
    ("numerical-cross_tile_rounding_positive", "matmul",
     "ci/project/fixtures/p02_wmma_numerical_v1.json", ((8, 4, 16),)),
    ("multi-dense_boundaries", "matmul", "ci/project/fixtures/p02_layout_v1.json",
     ((16, 8, 16),)),
    ("seeded_dense", "mlp", "ci/project/fixtures/p04_tiny_mlp_v1.json",
     ((16, 8, 16), (8, 4, 8), (8, 4, 8))),
)


class ContractError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ContractError(message)


def _same(actual, expected, label):
    _require(type(actual) is type(expected), label + ": incorrect value type")
    if type(expected) is dict:
        _require(set(actual) == set(expected), label + ": missing or unknown fields")
        for key, value in expected.items():
            _same(actual[key], value, label + "." + key)
    elif type(expected) is list:
        _require(len(actual) == len(expected), label + ": incorrect inventory size")
        for index, value in enumerate(expected):
            _same(actual[index], value, label + "[" + str(index) + "]")
    else:
        _require(actual == expected, label + ": differs from the frozen contract")


def _read_file(path, maximum):
    path = Path(path).absolute()
    _require(not any(item.is_symlink() for item in (path, *path.parents)),
             "source input traverses a symlink: " + str(path))
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum,
                 "source input is not a bounded regular file: " + str(path))
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(maximum + 1)
        _require(len(data) <= maximum and len(data) == info.st_size,
                 "source input changed size or exceeded its bound: " + str(path))
        return data
    except OSError as error:
        raise ContractError("cannot read source input: " + str(path) + ": " + str(error)) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON field: " + key)
        result[key] = value
    return result


def _integer(token):
    _require(len(token) <= MAX_JSON_INTEGER_DIGITS, "JSON integer exceeds its digit bound")
    value = int(token)
    _require(0 <= value <= MAX_UINT64, "JSON integer is outside uint64")
    return value


def _reject_number(token):
    raise ContractError("floating-point or nonfinite JSON number is forbidden: " + token)


def decode_contract(data):
    _require(type(data) is bytes and len(data) <= MAX_MANIFEST_BYTES,
             "contract must be bounded UTF-8 bytes")
    try:
        text = data.decode("utf-8", errors="strict")
        depth = 0
        quoted = escaped = False
        for character in text:
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                depth += 1
                _require(depth <= MAX_JSON_DEPTH, "contract exceeds its nesting bound")
            elif character in "]}":
                depth -= 1
        value = json.loads(text, object_pairs_hook=_unique, parse_int=_integer,
                           parse_float=_reject_number, parse_constant=_reject_number)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ContractError("invalid P06 contract JSON: " + str(error)) from error
    _require(type(value) is dict, "contract must contain one JSON object")
    return value


def _accounting(shapes, *, model):
    macs = sum(m * n * k for m, n, k in shapes)
    inputs = sum(2 * (m * k + k * n) for m, n, k in shapes)
    outputs = sum(4 * m * n for m, n, k in shapes)
    return {
        "macs": macs, "flops": 2 * macs,
        "input_h2d_bytes": inputs, "poison_h2d_bytes": outputs,
        "tensor_h2d_bytes": inputs + outputs, "tensor_d2h_bytes": outputs,
        "argument_payload_bytes": 56 * len(shapes),
        "host_relu_elements": 128 if model else 0,
        "host_cast_elements": 128 if model else 0,
        "host_bridge_input_bytes": 512 if model else 0,
        "host_bridge_output_bytes": 256 if model else 0,
        "host_assembly_bytes": 256 if model else 0,
    }


def expected_contract():
    workloads = []
    for fmt in FORMATS:
        for suffix, kind, fixture, shapes in _SELECTIONS:
            row = {
                "id": fmt + "-" + suffix, "kind": kind, "format": fmt,
                "case_id": fmt + "-" + suffix, "fixture": fixture,
                "fixture_sha256": _SOURCE_HASHES[fixture],
                "native_shapes": [list(shape) for shape in shapes],
                "expected_launches": len(shapes),
                "accounting": _accounting(shapes, model=kind == "mlp"),
            }
            if kind == "matmul":
                row.update(zip(("m", "n", "k"), shapes[0]))
            workloads.append(row)
    counters = [dict(zip(("name", "mpm_class", "csr", "core_id", "scope", "unit",
                          "required_isa", "class_macro", "csr_macro"), row))
                for row in _COUNTERS]
    return {
        "schema_version": 1, "contract_id": CONTRACT_ID, "contract_version": 1,
        "work_package": "P06-T01", "target_acceptance": "P06-A01",
        "acceptance_claimed": False, "execution_claimed": False,
        "source_inputs": [{"path": name, "sha256": digest}
                          for name, digest in sorted(_SOURCE_HASHES.items())],
        "profile": {"path": "profiles/p02-tfr.json",
                    "sha256": _SOURCE_HASHES["profiles/p02-tfr.json"],
                    "backend": "simx", "simulation_mode": "timing", "xlen": 64,
                    "tensor_arithmetic": "TFR", "scalar_arithmetic": "STD",
                    "performance_backend_macro": "PERF_ENABLE",
                    "forbidden_macros": ["SIMX_FUNCTIONAL", "SIMX_MT"]},
        "capabilities": [{"name": name, "id": identifier}
                         for name, identifier in _CAPABILITIES],
        "capability_values": dict(_CAPABILITY_VALUES),
        "geometry": {"compiled_memory_block_bytes": 64, "icache_bytes": 16384,
                     "dcache_bytes": 16384, "local_memory_bytes": 16384,
                     "l2_enabled": False, "l3_enabled": False,
                     "dynamic_local_bytes_per_launch": 0},
        "formats": list(FORMATS), "workloads": workloads, "counters": counters,
        "sampling": {"warmup_runs": 1, "measured_runs": 5, "iterations_per_process": 1,
                     "order": "format_workload_warmup_then_measurement",
                     "context_policy": "fresh_process_and_device_context_per_invocation",
                     "cache_policy": "fresh_device_context_not_warm_device_cache",
                     "failed_sample_policy": "retain_and_fail_attempt", "outlier_policy": "none",
                     "statistics": ["count", "minimum", "maximum", "median", "population_stddev"]},
        "inventory": {"workloads": 8, "warmup_processes": 8, "measured_processes": 40,
                      "total_processes": 48, "warmup_launches": 12,
                      "measured_launches": 60, "total_launches": 72},
        "observation": {
            "snapshot_markers": ["P06_BEGIN", "P06_END"], "release_marker": "P06_RELEASE",
            "failure_marker": "P06_FAILURE", "sample_id_pattern": "[a-z0-9][a-z0-9_-]{0,127}",
            "snapshot_keys": ["schema_version", "sample_id", "context_id", "device_index",
                              "compiled_memory_block_bytes", "query_begin_ns", "query_end_ns",
                              "capabilities", "counters"],
            "release_keys": ["schema_version", "sample_id", "context_id", "status"],
            "context_id": 1, "device_index": 0, "counter_bits": 64,
            "counter_delta_policy": "checked_after_minus_before_no_wrap_or_reset",
            "positive_counter_deltas": ["cycles", "instructions"],
            "disabled_counter_policy": "enabled_false_status_null_value_null",
            "marker_order": {
                "matmul": ["P06_BEGIN", "P03_RESULT", "P06_END", "P06_RELEASE", "PASSED!"],
                "mlp": ["P06_BEGIN", "P06_END", "P06_RELEASE", "P04_RESULT", "PASSED!"],
            },
        },
        "boundaries": {
            "counters": "whole_device_context_after_open_to_before_final_release",
            "cycles": "modeled_active_core_cycles_not_model_wall_time",
            "instructions": "retired_macroinstructions_not_lane_operations_or_flops",
            "host_process": "startup_fixture_io_execution_checks_cleanup_and_observer_inclusive",
            "model_host_profiles": "original_nested_intervals_with_create_and_close_observer_inclusive",
            "observer_time": "host_steady_clock_query_intervals_never_subtracted",
            "tensor_bytes": "explicit_input_poison_output_buffers_only",
            "memory_counters": "modeled_requests_not_useful_tensor_payload_bytes",
            "argument_bytes": "encoded_argument_payload_not_measured_control_bus_traffic",
            "host_work": "logical_relu_cast_bridge_and_assembly_counts_not_cpu_memory_traffic",
            "mac_flop_convention": "one_multiply_plus_one_add_counts_as_two_flops",
            "sparsity": "dense_execution_even_when_fixture_values_are_zero",
        },
        "budget": {"jobs_max": 2, "max_rss_bytes": 4 * 1024**3,
                   "min_free_bytes": 15 * 1024**3, "max_log_bytes": 16 * 1024**2,
                   "build_timeout_seconds": 1800, "run_timeout_seconds": 180},
        "limitations": [
            "The manifest defines workloads; only actual execution and independent review can establish acceptance.",
            "SimX counters describe the timing model, not physical device speed, bandwidth, power or energy.",
            "One fresh-process warm-up does not warm the following device context or establish steady-state reuse.",
            "Whole-context counters include setup and transfers and cannot be divided into per-kernel or model-stage costs.",
            "Cache-port bank-arbitration counters reset on each launch and are excluded from whole-context totals; local-memory and external-memory stall counters have separate cumulative lifetimes.",
            "Host intervals include instrumentation and numerical checks; nested intervals overlap and must not be added or subtracted as exclusive costs.",
            "Cache and external-memory requests have their own boundaries and are not useful tensor payload bytes.",
            "Capability memory sizes are configured apertures, not observed physical memory capacity.",
            "Five measured samples establish no tail distribution, physical-speed comparison or optimization result.",
            "P06-A02/A03, vendor XRT integration, physical FPGA, synthesis and silicon remain separate obligations.",
        ],
    }


def _validate_workload_sources(contract, source):
    operators = operator_fixtures.load_cases(source)
    models = model_fixtures.load_cases(source)
    by_kind = {"matmul": {row["id"]: row for row in operators},
               "mlp": {row["id"]: row for row in models}}
    _require(len(by_kind["matmul"]) == len(operators) == 88,
             "operator fixture inventory is not the frozen 88 cases")
    _require(len(by_kind["mlp"]) == len(models) == 10,
             "model fixture inventory is not the frozen ten cases")
    for workload in contract["workloads"]:
        case = by_kind[workload["kind"]].get(workload["case_id"])
        _require(case is not None and case["format"] == workload["format"],
                 "selected workload is missing from its independent fixture")
        if workload["kind"] == "matmul":
            dimensions = [case[key] for key in ("m", "n", "k")]
            _same(workload["native_shapes"], [dimensions], "independent operator dimensions")
            _require(len(case["a_words"]) * 4 + len(case["b_words"]) * 4
                     == workload["accounting"]["input_h2d_bytes"], "operator input byte count differs")
            _require(len(case["expected"]) * 4 == workload["accounting"]["tensor_d2h_bytes"],
                     "operator output byte count differs")
        else:
            _require((len(case["input_words"]), len(case["w1_words"]), len(case["w2_words"]),
                      len(case["hidden_words"]), len(case["bridge_words"]), len(case["output_words"]))
                     == (128, 64, 16, 128, 64, 64), "model fixture dimensions differ")
            _require(4 * (len(case["input_words"]) + len(case["w1_words"])
                          + len(case["bridge_words"]) + 2 * len(case["w2_words"]))
                     == workload["accounting"]["input_h2d_bytes"], "model input byte count differs")
            _require(4 * (len(case["hidden_words"]) + len(case["output_words"]))
                     == workload["accounting"]["tensor_d2h_bytes"], "model output byte count differs")


def _validated_inputs(contract, source, paths):
    _same(contract, expected_contract(), "P06 contract")
    source = Path(source).absolute()
    _require(source.is_dir(), "source root must be an existing directory")
    contents = {}
    for path in paths:
        data = _read_file(source / path, MAX_SOURCE_BYTES)
        _require(hashlib.sha256(data).hexdigest() == _SOURCE_HASHES[path],
                 "frozen source input differs: " + path)
        contents[path] = data
    return source, contents


def _validate_counter_sources(contract, contents):
    types = tomllib.loads(contents["VX_types.toml"].decode("utf-8"))
    sections = ("dcr_mpm_class", "csr_mpm_base", "csr_mpm_core", "csr_mpm_icache",
                "csr_mpm_dcache", "csr_mpm_l2cache", "csr_mpm_l3cache", "csr_mpm_mem",
                "csr_mpm_tcu")
    _require(all(type(types.get(name)) is dict for name in sections),
             "frozen CSR source lacks its required sections")
    symbols = {key: value for name in sections for key, value in types[name].items()}
    for counter in contract["counters"]:
        _require(symbols.get(counter["class_macro"]) == counter["mpm_class"]
                 and symbols.get(counter["csr_macro"]) == counter["csr"],
                 "counter class/address differs from the frozen CSR definition: " + counter["name"])


def validate_contract(contract, source=ROOT):
    """Check all frozen execution sources and the independent workload inventory."""
    source, contents = _validated_inputs(contract, source, sorted(_SOURCE_HASHES))
    _validate_counter_sources(contract, contents)
    _validate_workload_sources(contract, source)
    return contract


def load_contract(source=ROOT):
    """Load the original native execution contract; changed runtime sources fail."""
    source = Path(source).absolute()
    return validate_contract(decode_contract(_read_file(source / MANIFEST_PATH, MAX_MANIFEST_BYTES)), source)


def validate_analysis_contract(contract, source=ROOT):
    """Check the frozen definition and trusted inputs for historical analysis.

    This does not qualify source for native execution or validate an archive.
    A replayer must independently verify every source_inputs pin against the
    archive's retained bytes. Archived Python is never imported here.
    """
    source, contents = _validated_inputs(contract, source, ANALYSIS_SOURCE_PATHS)
    for path, module in _ANALYSIS_HELPERS:
        invoking = Path(module.__file__).absolute()
        _require(invoking == ROOT / path,
                 "analysis helper did not load from the trusted repository: " + path)
        _require(hashlib.sha256(_read_file(invoking, MAX_SOURCE_BYTES)).hexdigest()
                 == _SOURCE_HASHES[path], "trusted analysis helper differs: " + path)
    _validate_counter_sources(contract, contents)
    _validate_workload_sources(contract, source)
    return contract


def load_analysis_contract(source=ROOT):
    """Load the frozen definition for historical analysis with current readers."""
    source = Path(source).absolute()
    return validate_analysis_contract(
        decode_contract(_read_file(source / MANIFEST_PATH, MAX_MANIFEST_BYTES)), source)


def select_workloads(contract, formats=None):
    """Select distinct supported formats while preserving canonical workload order."""
    _same(contract, expected_contract(), "P06 contract")
    if formats is None:
        selected = set(FORMATS)
    else:
        _require(type(formats) in (list, tuple) and formats,
                 "format selection must be a nonempty list or tuple")
        _require(all(type(fmt) is str and fmt in FORMATS for fmt in formats),
                 "format selection contains an unsupported value")
        _require(len(formats) == len(set(formats)), "duplicate format selection")
        selected = set(formats)
    return deepcopy([row for row in contract["workloads"] if row["format"] in selected])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.source_dir)
        print(json.dumps({"outcome": "pass", "contract_id": contract["contract_id"],
                          "workloads": len(contract["workloads"]),
                          "counters": len(contract["counters"]), "native_execution": "not_run"}))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error), "native_execution": "not_run"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
