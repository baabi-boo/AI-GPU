# SPDX-License-Identifier: Apache-2.0
"""Reproduce retained headers with the pinned, trusted configuration renderer."""

from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import sys
from types import MappingProxyType, SimpleNamespace

from baseline_packet_io import PacketReader
from p06_replay import _same, require


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-managed-preflight-generated-replay-v1"
GENERATOR_PATH = "ci/gen_config.py"
GENERATOR_MODULE_NAME = "p06_managed_preflight_trusted_gen_config"
INPUT_SHA256 = MappingProxyType({
    GENERATOR_PATH: "b710a1b80c89d327adf079e61aec9f5d4f950d89342b633b6b00871e50abe165",
    "VX_config.toml": "a1c49de52a0373b5f74706528d46bea1181c54f7769dd03994e033c7ddd710bf",
    "VX_types.toml": "f8eb0b3343f66ebe0a3c9030c8c9150c13638e7c23744b00b2fcf8ce005d5f23",
    "profiles/p02-tfr.json": "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102",
})
HEADERS = ("sw/VX_config.h", "hw/VX_config.vh", "sw/VX_types.h", "hw/VX_types.vh")
LIMITATIONS = [
    "Only the four retained configuration/type headers are reproduced; generated vortex_opae headers were not retained.",
    "Trusted configuration rendering does not compile a binary or prove that the original compiler consumed these bytes.",
]


def _trusted_inputs():
    bodies = {}
    with PacketReader(ROOT, max_total_bytes=256 * 1024, max_files=len(INPUT_SHA256)) as reader:
        for name, digest in INPUT_SHA256.items():
            body = reader.read_bytes(name, limit=128 * 1024)
            _same(hashlib.sha256(body).hexdigest(), digest, "trusted generated input " + name)
            bodies[name] = body
        reader.recheck()
    return bodies


def _identity(name, body):
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


_TRUSTED_INPUTS = MappingProxyType(_trusted_inputs())
TRUSTED_GENERATOR_SOURCE = _identity(GENERATOR_PATH, _TRUSTED_INPUTS[GENERATOR_PATH])


def _load_renderer():
    path = ROOT / GENERATOR_PATH
    spec = importlib.util.spec_from_file_location(GENERATOR_MODULE_NAME, path)
    require(spec is not None, "trusted configuration renderer has no module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[GENERATOR_MODULE_NAME] = module
    # Compile the verified current source directly, avoiding an unchecked .pyc.
    exec(compile(_TRUSTED_INPUTS[GENERATOR_PATH], str(path), "exec"), module.__dict__)
    local = {str(ROOT / name): body.decode("utf-8") for name, body in _TRUSTED_INPUTS.items()
             if name != GENERATOR_PATH}

    def open_input(name, mode="r", *, encoding=None):
        require(type(name) is str and name in local and mode == "r" and encoding == "utf-8",
                "configuration renderer requested an unapproved input")
        return io.StringIO(local[name])

    module.open = open_input
    module.os = SimpleNamespace(
        environ=MappingProxyType({"XLEN": "64"}),
        path=SimpleNamespace(basename=lambda name: name.rsplit("/", 1)[-1],
            join=lambda parent, name: parent.rstrip("/") + "/" + name,
            isfile=lambda name: name in local))
    module.sys = SimpleNamespace(argv=("gen_config.py",))
    return module


TRUSTED_GENERATOR_MODULE = _load_renderer()


def trusted_generator_identity():
    """Check the explicit trusted module path and current source bytes."""
    _same(TRUSTED_GENERATOR_MODULE.__file__, str(ROOT / GENERATOR_PATH),
          "trusted configuration renderer module path")
    _same(TRUSTED_GENERATOR_MODULE.__spec__.origin, str(ROOT / GENERATOR_PATH),
          "trusted configuration renderer module origin")
    bodies = _trusted_inputs()
    _same(bodies, dict(_TRUSTED_INPUTS), "trusted generated input stability")
    return dict(TRUSTED_GENERATOR_SOURCE)


def _bound_inputs(source_body):
    identity = trusted_generator_identity()
    for name, body in _TRUSTED_INPUTS.items():
        _same(source_body(name), body, "retained configuration source " + name)
    return identity


def _configuration(name):
    renderer = TRUSTED_GENERATOR_MODULE
    path = str(ROOT / (name + ".toml"))
    document = renderer._load_toml(path)
    base, layout = renderer._flatten_with_layout(document)
    enums = renderer._load_enums(document)
    builtins = renderer._load_var_table(document, "builtin")
    params = renderer._load_var_table(document, "param")
    externs = set(renderer._load_var_table(document, "extern"))
    hexadecimal = renderer._scan_hex_literals(path)
    profile = None
    if name == "VX_config":
        profile = renderer.load_profile("p02-tfr", str(ROOT / "profiles"))
        renderer.validate_profile(profile, base, enums, set(params) | set(builtins))
        _same(profile.xlen, 64, "trusted configuration profile XLEN")
    return base, layout, enums, builtins, params, externs, hexadecimal, profile


def _resolve(base, layout, enums, builtins, params, externs, overrides):
    renderer = TRUSTED_GENERATOR_MODULE
    resolver = renderer.Resolver(base=base, overrides=overrides, enums=enums,
        builtins=builtins, params=params, externs=externs)
    values, pending = {}, []
    for name in layout.ordered_keys:
        try:
            values[name] = resolver.resolve(name)
        except renderer._Deferred:
            pending.append(name)
    for name in enums:
        if name not in values:
            values[name] = resolver.resolve(name)
    deferred = {}
    if pending:
        local = renderer._build_local_asts(base)
        symbolic = externs | set(pending)
        deferred = {name: renderer._fold_deferred(base[name], resolver, symbolic, local) for name in pending}
    return values, deferred


def _render_headers():
    renderer = TRUSTED_GENERATOR_MODULE
    result = {}
    for name in ("VX_config", "VX_types"):
        base, layout, enums, builtins, params, externs, hexadecimal, profile = _configuration(name)
        if profile is not None:
            base.update(profile.values)
        if name == "VX_types":
            values, deferred = _resolve(base, layout, enums, builtins, params, externs, {})
        for fmt, path in (("cpp", "sw/" + name + ".h"), ("verilog", "hw/" + name + ".vh")):
            if name == "VX_types":
                text = renderer.emit_resolved_header(values, layout, enums, fmt, path, hexadecimal, deferred)
            else:
                text = renderer.emit_unresolved_header(base, layout, enums, fmt, path, hexadecimal, set(params))
            result[path] = text.encode("utf-8")
    return result


def validate_generated_headers(*, source_body, build_body):
    """Compare all retained headers to trusted rendering without any build execution."""
    generator = _bound_inputs(source_body)
    headers = _render_headers()
    for name, body in headers.items():
        _same(build_body(name), body, "reproduced generated header " + name)
    trusted_generator_identity()
    return {"contract_id": CONTRACT_ID, "generator": generator, "xlen": 64, "profile": "p02-tfr",
        "headers": [_identity(name, headers[name]) for name in HEADERS],
        "inputs": [_identity(name, body) for name, body in _TRUSTED_INPUTS.items()],
        "retained_code_executed": False, "native_execution": "not_run", "limitations": list(LIMITATIONS)}


def validate_generated_flags(text, *, source_body, fmt):
    """Reproduce the complete retained cflags output for either fixed input format."""
    require(type(fmt) is str and fmt in ("fp16", "bf16"), "unsupported generated flags format")
    generator = _bound_inputs(source_body)
    renderer = TRUSTED_GENERATOR_MODULE
    base, layout, enums, builtins, params, externs, hexadecimal, profile = _configuration("VX_config")
    raw = "-DITYPE=" + fmt + " -DOTYPE=fp32 -DKUNROLL=1 -DVX_CFG_XLEN=64"
    merged = renderer.merge_configs(profile, raw, enums)
    overrides, _ = renderer._apply_overrides(renderer._parse_defines_from_cflags(merged), enums)
    values, _ = _resolve(base, layout, enums, builtins, params, externs, overrides)
    expected = renderer.emit_cflags(values, layout, enums, hexadecimal)
    _same(text, expected, "reproduced generated flags " + fmt)
    trusted_generator_identity()
    return {"contract_id": CONTRACT_ID, "generator": generator, "format": fmt,
        "flags_sha256": hashlib.sha256(expected.encode("utf-8")).hexdigest(),
        "flags_count": len(expected.split()), "native_execution": "not_run", "retained_code_executed": False}
