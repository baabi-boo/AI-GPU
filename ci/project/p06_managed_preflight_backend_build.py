# SPDX-License-Identifier: Apache-2.0
"""Close the original managed backend log without executing retained commands."""

from collections import Counter
import hashlib
import re

from baseline_packet_contract import _stamp_words
from p02_matrix_records import require
import p06_managed_preflight_build as build_records


CONTRACT_ID = "p06-managed-preflight-backend-replay-v1"
RECIPE_SHA256 = {
    "config.mk.in": "28fa1d7ad7076018ebb22a720df7cf3c792a5989a71834418f0ccb86a67551d1",
    "sim/common.mk": "086294bb98d1f5ac2324ffbf5fc66a377bc2f63d2b73f321f6351c9a7e2ecf0b",
    "sw/runtime/common.mk": "2af4343c0738db4a665c96e24f90f78912302b20597dda74d9592afb6676736e",
    "sim/simx/Makefile": "c719966647f32fef5421dd798a89d3eeddccd692e7c61046e5744b7a8e722403",
    "sw/runtime/simx/Makefile": "a904a327b54481567d5efd205da7cba3fed0f7ecb6410ab641753d789c8ee975",
    "tests/regression/ai_counter_preflight/backend.mk":
        "d71ba6fe3f653a19e42aea6d52c605e9d41d92f99fc1aa8ef1448fc03e72a326",
}


def _line(text):
    return re.sub(r"[ \t]+", " ", text).strip(" ")


def validate_backend_build(text, runtime, backend, backend_linker, *, source, build,
                           compiler, make, fmt, source_files, source_body):
    """Verify all 46 records and their prerequisites around the original parser."""
    source, build = build_records._roots(source, build)
    compiler = str(build_records._path(compiler, "backend replay compiler"))
    make = str(build_records._path(make, "backend replay make"))
    for name, expected in RECIPE_SHA256.items():
        body = source_body(name)
        require(type(body) is bytes and hashlib.sha256(body).hexdigest() == expected,
                "backend build recipe differs from the reviewed source: " + name)
    lines = [_line(line) for line in build_records._lines(text, "backend replay log")]
    require(len(lines) == 46, "backend build log requires exactly 46 commands")
    original = build_records.validate_build_commands(text, runtime, backend, backend_linker,
        source=source, build=build, compiler=compiler, make=make, fmt=fmt,
        source_files=source_files)
    directory = build / "sw/runtime"
    model, wrapped = str(directory / "libsimx.so"), str(directory / "libvortex-simx.so")
    nested = " ".join(("DESTDIR=" + str(directory), make, "-C",
                       str(build / "sim/simx"), model))
    objects = {str(build_records.expected_object(name, build)): "model:" + name
               for name in build_records.MODEL_SOURCES}
    graph = {name: ("model_compile", {"nested-make"}) for name in objects.values()}
    graph.update({"nested-make": ("recursive_make", set()),
                  "model-link": ("model_link", set(objects.values())),
                  "backend-link": ("backend_link", {"model-link"})})
    targets = dict(objects, **{model: "model-link", wrapped: "backend-link"})
    seen, order = set(), []
    for index, line in enumerate(lines, 1):
        if line == nested:
            name = "nested-make"
        else:
            words = _stamp_words(line, "backend replay command")
            require(words and words[0] == compiler and words[-1] in targets,
                    "backend build log contains an unsupported command at record " + str(index))
            name = targets[words[-1]]
        require(name not in seen, "backend build log repeats command " + name)
        require(graph[name][1] <= seen,
                "backend build command precedes its prerequisites: " + name)
        seen.add(name)
        order.append(name)
    require(seen == set(graph), "backend build command inventory differs")
    return {"contract_id": CONTRACT_ID, "format": fmt, "command_count": len(lines),
        "command_counts": dict(sorted(Counter(kind for kind, _ in graph.values()).items())),
        "command_order": order, "recipe_sha256": dict(RECIPE_SHA256),
        "normalized_commands_sha256": hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest(),
        "model_build_records": original}
