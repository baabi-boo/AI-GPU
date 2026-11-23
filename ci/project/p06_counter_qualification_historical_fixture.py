# SPDX-License-Identifier: Apache-2.0
"""Original caller bytes for synthetic four-process qualification packets."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CALLER = "tests/regression/ai_counter_preflight/main.cpp"
FIXTURE = "ci/project/fixtures/p06_counter_preflight_main_v1.cpp"
SHA256 = "05738177b2930852eb5cf5e6d61de93f3cb465b2f221f0d9d95a8780adce99e1"


def source_body(name):
    if name != CALLER:
        return (ROOT / name).read_bytes()
    body = (ROOT / FIXTURE).read_bytes()
    if len(body) != 26844 or hashlib.sha256(body).hexdigest() != SHA256:
        raise ValueError("historical counter caller fixture differs from its original proof")
    return body
