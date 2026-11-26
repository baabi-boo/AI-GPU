# SPDX-License-Identifier: Apache-2.0
"""SSA Graph IR and validation for the Vortex AI compiler stack."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import Any


DTYPE_ELEMENT_BYTES: dict[str, int] = {
    "fp32": 4,
    "fp16": 2,
    "bf16": 2,
    "i8": 1,
    "u8": 1,
    "f8_e4m3": 1,
}

_DTYPE_ALIASES: dict[str, str] = {
    "fp32": "fp32",
    "float32": "fp32",
    "f32": "fp32",
    "F32": "fp32",
    "float": "fp32",
    "fp16": "fp16",
    "float16": "fp16",
    "f16": "fp16",
    "F16": "fp16",
    "half": "fp16",
    "bf16": "bf16",
    "bfloat16": "bf16",
    "BF16": "bf16",
    "i8": "i8",
    "int8": "i8",
    "I8": "i8",
    "u8": "u8",
    "uint8": "u8",
    "U8": "u8",
    "f8_e4m3": "f8_e4m3",
    "F8_E4M3": "f8_e4m3",
    "float8_e4m3fn": "f8_e4m3",
}

_VALID_LAYOUTS = frozenset(("row_major", "column_major"))


def normalize_dtype(dtype: str) -> str:
    """Normalize external/ONNX/PyTorch/safetensors dtype names to canonical Vortex IR dtypes."""
    if type(dtype) is not str:
        raise IRValidationError(f"dtype must be a string, got {type(dtype).__name__}")
    key = dtype.removeprefix("torch.")
    if key not in _DTYPE_ALIASES:
        raise IRValidationError(f"unsupported IR tensor dtype: {dtype!r}")
    return _DTYPE_ALIASES[key]


class IRValidationError(ValueError):
    """Raised when a CompiledGraph violates SSA, acyclicity, shape, or dtype invariants."""


class OpKind(str, Enum):
    """Canonical SSA operator kinds supported by the Vortex compiler IR."""

    MATMUL = "MATMUL"
    LINEAR = "LINEAR"
    RMSNORM = "RMSNORM"
    LAYERNORM = "LAYERNORM"
    ROPE = "ROPE"
    SWIGLU = "SWIGLU"
    GELU = "GELU"
    SILU = "SILU"
    RELU = "RELU"
    SOFTMAX = "SOFTMAX"
    ATTENTION = "ATTENTION"
    FLASH_ATTENTION = "FLASH_ATTENTION"
    GQA_DECODE_ATTENTION = "GQA_DECODE_ATTENTION"
    KV_CACHE_APPEND = "KV_CACHE_APPEND"
    RESIDUAL_ADD = "RESIDUAL_ADD"
    MUL = "MUL"
    CAST = "CAST"


@dataclass(frozen=True, slots=True)
class TensorSpec:
    """Immutable SSA value descriptor with concrete shape, canonical dtype, and layout."""

    name: str
    shape: tuple[int, ...]
    dtype: str = "fp32"
    layout: str = "row_major"
    role: str = "intermediate"  # "input" | "weight" | "intermediate" | "output" | "kv_cache"

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name:
            raise IRValidationError(f"TensorSpec.name must be a nonempty string, got {self.name!r}")
        if type(self.shape) is list:
            object.__setattr__(self, "shape", tuple(self.shape))
        elif type(self.shape) is not tuple:
            raise IRValidationError(f"TensorSpec {self.name!r}: shape must be a tuple of ints")
        if not self.shape:
            raise IRValidationError(f"TensorSpec {self.name!r}: scalar 0-D shape is unsupported")
        for idx, dim in enumerate(self.shape):
            if type(dim) is not int or dim <= 0:
                raise IRValidationError(
                    f"TensorSpec {self.name!r}: shape[{idx}] must be a positive int, got {dim!r}"
                )
        norm_dtype = normalize_dtype(self.dtype)
        object.__setattr__(self, "dtype", norm_dtype)
        if self.layout not in _VALID_LAYOUTS:
            raise IRValidationError(
                f"TensorSpec {self.name!r}: layout must be in {sorted(_VALID_LAYOUTS)}, got {self.layout!r}"
            )
        if self.role not in ("input", "weight", "intermediate", "output", "kv_cache"):
            raise IRValidationError(f"TensorSpec {self.name!r}: unsupported role {self.role!r}")

    @property
    def numel(self) -> int:
        return math.prod(self.shape)

    @property
    def elem_bytes(self) -> int:
        return DTYPE_ELEMENT_BYTES[self.dtype]

    @property
    def nbytes(self) -> int:
        return self.numel * self.elem_bytes

    @property
    def shape_2d(self) -> tuple[int, int]:
        """Flatten leading dimensions into [rows, cols] for ResidentTensor allocation."""
        if len(self.shape) == 1:
            return (1, self.shape[0])
        if len(self.shape) == 2:
            return self.shape
        return (math.prod(self.shape[:-1]), self.shape[-1])

    def with_role(self, role: str) -> TensorSpec:
        return TensorSpec(
            name=self.name,
            shape=self.shape,
            dtype=self.dtype,
            layout=self.layout,
            role=role,
        )

    def with_dtype(self, dtype: str) -> TensorSpec:
        return TensorSpec(
            name=self.name,
            shape=self.shape,
            dtype=dtype,
            layout=self.layout,
            role=self.role,
        )

    def with_layout(self, layout: str) -> TensorSpec:
        return TensorSpec(
            name=self.name,
            shape=self.shape,
            dtype=self.dtype,
            layout=layout,
            role=self.role,
        )


def _freeze_attrs(attrs: dict[str, Any] | MappingProxyType[str, Any] | None) -> MappingProxyType[str, Any]:
    if not attrs:
        return MappingProxyType({})
    clean: dict[str, Any] = {}
    for k, v in attrs.items():
        if type(k) is not str or not k:
            raise IRValidationError(f"attribute key must be a nonempty string, got {k!r}")
        clean[k] = tuple(v) if isinstance(v, list) else v
    return MappingProxyType(clean)


@dataclass(frozen=True, slots=True)
class OpNode:
    """Single SSA operator node consuming named input tensors and producing named output tensors."""

    name: str
    op: OpKind
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    attrs: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name:
            raise IRValidationError(f"OpNode.name must be a nonempty string, got {self.name!r}")
        if not isinstance(self.op, OpKind):
            object.__setattr__(self, "op", OpKind(self.op))
        if type(self.inputs) is not tuple:
            object.__setattr__(self, "inputs", tuple(self.inputs))
        if type(self.outputs) is not tuple:
            object.__setattr__(self, "outputs", tuple(self.outputs))
        if not self.inputs or not self.outputs:
            raise IRValidationError(f"OpNode {self.name!r}: inputs and outputs must be nonempty")
        if any(type(v) is not str or not v for v in self.inputs + self.outputs):
            raise IRValidationError(f"OpNode {self.name!r}: tensor names must be nonempty strings")
        object.__setattr__(self, "attrs", _freeze_attrs(self.attrs))


def _effective_2d_matmul_shape(spec: TensorSpec, *, transpose: bool = False) -> tuple[int, int]:
    if len(spec.shape) == 1:
        r, c = (1, spec.shape[0])
    elif len(spec.shape) == 2:
        r, c = spec.shape
    else:
        r, c = (math.prod(spec.shape[:-1]), spec.shape[-1])
    return (c, r) if transpose else (r, c)


def _check_op_signature(node: OpNode, tensors: dict[str, TensorSpec]) -> None:
    ins = [tensors[name] for name in node.inputs]
    outs = [tensors[name] for name in node.outputs]
    op = node.op

    if op is OpKind.MATMUL:
        if len(ins) not in (2, 3) or len(outs) != 1:
            raise IRValidationError(f"{node.name}: MATMUL requires 2 or 3 inputs and 1 output")
        trans_a = bool(node.attrs.get("transpose_a", False))
        trans_b = bool(node.attrs.get("transpose_b", False))
        m, k_a = _effective_2d_matmul_shape(ins[0], transpose=trans_a)
        k_b, n = _effective_2d_matmul_shape(ins[1], transpose=trans_b)
        if k_a != k_b:
            raise IRValidationError(
                f"{node.name}: MATMUL inner dimension mismatch {k_a} != {k_b} "
                f"for shapes {ins[0].shape} and {ins[1].shape}"
            )
        if ins[0].dtype != ins[1].dtype:
            raise IRValidationError(
                f"{node.name}: MATMUL operand dtypes must match ({ins[0].dtype} != {ins[1].dtype})"
            )
        if outs[0].shape_2d != (m, n):
            raise IRValidationError(
                f"{node.name}: MATMUL output shape {outs[0].shape} incompatible with ({m}, {n})"
            )
        if len(ins) == 3 and ins[2].shape_2d not in ((m, n), (1, n), (n, 1)):
            raise IRValidationError(
                f"{node.name}: MATMUL residual/bias shape {ins[2].shape} incompatible with ({m}, {n})"
            )

    elif op is OpKind.LINEAR:
        # Linear: x[M, K] @ weight[N, K]^T (+ optional bias[N] or residual[M, N]) -> out[M, N]
        if len(ins) not in (2, 3) or len(outs) != 1:
            raise IRValidationError(f"{node.name}: LINEAR requires (x, weight[, bias_or_res]) -> out")
        x, w = ins[0], ins[1]
        if len(w.shape) != 2:
            raise IRValidationError(f"{node.name}: LINEAR weight must be 2-D, got {w.shape}")
        trans_b = bool(node.attrs.get("transpose_b", True))
        m, k = x.shape_2d
        n, wk = w.shape if trans_b else (w.shape[1], w.shape[0])
        if k != wk:
            raise IRValidationError(
                f"{node.name}: LINEAR inner dimension mismatch {k} != {wk} for x={x.shape}, w={w.shape}"
            )
        if outs[0].shape_2d != (m, n):
            raise IRValidationError(
                f"{node.name}: LINEAR output shape {outs[0].shape} incompatible with ({m}, {n})"
            )
        if len(ins) == 3 and ins[2].shape_2d not in ((1, n), (m, n)):
            raise IRValidationError(
                f"{node.name}: LINEAR 3rd input shape {ins[2].shape} incompatible with ({m}, {n})"
            )

    elif op is OpKind.RMSNORM:
        if len(ins) != 2 or len(outs) != 1:
            raise IRValidationError(f"{node.name}: RMSNORM requires (x, weight) -> out")
        x, w, y = ins[0], ins[1], outs[0]
        if x.shape != y.shape:
            raise IRValidationError(f"{node.name}: RMSNORM shape mismatch {x.shape} != {y.shape}")
        if w.shape_2d != (1, x.shape[-1]):
            raise IRValidationError(
                f"{node.name}: RMSNORM weight shape {w.shape} incompatible with (1, {x.shape[-1]})"
            )
        if "cast_epilogue_dtype" in node.attrs:
            ep = normalize_dtype(str(node.attrs["cast_epilogue_dtype"]))
            if y.dtype != ep:
                raise IRValidationError(
                    f"{node.name}: RMSNORM cast_epilogue_dtype {ep} != output dtype {y.dtype}"
                )
        elif y.dtype != x.dtype:
            raise IRValidationError(f"{node.name}: RMSNORM dtype mismatch {x.dtype} != {y.dtype}")
        eps = node.attrs.get("eps", 1e-5)
        if not isinstance(eps, (int, float)) or isinstance(eps, bool) or not math.isfinite(eps) or eps < 0:
            raise IRValidationError(f"{node.name}: RMSNORM eps must be finite non-negative, got {eps!r}")

    elif op is OpKind.LAYERNORM:
        if len(ins) not in (2, 3) or len(outs) != 1:
            raise IRValidationError(f"{node.name}: LAYERNORM requires (x, gamma[, beta]) -> out")
        x, g, y = ins[0], ins[1], outs[0]
        if x.shape != y.shape or g.shape_2d != (1, x.shape[-1]):
            raise IRValidationError(
                f"{node.name}: LAYERNORM shape mismatch x={x.shape}, gamma={g.shape}, out={y.shape}"
            )
        if len(ins) == 3 and ins[2].shape_2d != (1, x.shape[-1]):
            raise IRValidationError(
                f"{node.name}: LAYERNORM beta shape {ins[2].shape} != (1, {x.shape[-1]})"
            )

    elif op is OpKind.ROPE:
        if len(ins) not in (1, 3) or len(outs) != 1:
            raise IRValidationError(f"{node.name}: ROPE requires (x[, cos, sin]) -> out")
        if ins[0].shape != outs[0].shape or ins[0].dtype != outs[0].dtype:
            raise IRValidationError(
                f"{node.name}: ROPE input {ins[0].shape}/{ins[0].dtype} != output {outs[0].shape}/{outs[0].dtype}"
            )
        if ins[0].shape[-1] % 2 != 0:
            raise IRValidationError(f"{node.name}: ROPE head dim must be even, got {ins[0].shape[-1]}")

    elif op is OpKind.SWIGLU:
        if len(ins) not in (1, 2) or len(outs) != 1:
            raise IRValidationError(f"{node.name}: SWIGLU requires (gate, up) or (fused_gate_up,) -> out")
        if len(ins) == 2:
            if ins[0].shape != ins[1].shape or ins[0].shape != outs[0].shape:
                raise IRValidationError(
                    f"{node.name}: SWIGLU shape mismatch {ins[0].shape}, {ins[1].shape} -> {outs[0].shape}"
                )
            if ins[0].dtype != ins[1].dtype or ins[0].dtype != outs[0].dtype:
                raise IRValidationError(f"{node.name}: SWIGLU dtype mismatch")
        else:
            if ins[0].shape[:-1] != outs[0].shape[:-1] or ins[0].shape[-1] != 2 * outs[0].shape[-1]:
                raise IRValidationError(
                    f"{node.name}: packed SWIGLU requires last dim 2*out_dim, got {ins[0].shape} -> {outs[0].shape}"
                )

    elif op in (OpKind.GELU, OpKind.SILU, OpKind.RELU, OpKind.SOFTMAX):
        if len(ins) != 1 or len(outs) != 1:
            raise IRValidationError(f"{node.name}: {op.value} requires 1 input and 1 output")
        if ins[0].shape != outs[0].shape or ins[0].dtype != outs[0].dtype:
            raise IRValidationError(
                f"{node.name}: {op.value} input ({ins[0].shape}, {ins[0].dtype}) != "
                f"output ({outs[0].shape}, {outs[0].dtype})"
            )

    elif op in (OpKind.ATTENTION, OpKind.FLASH_ATTENTION, OpKind.GQA_DECODE_ATTENTION):
        if len(ins) < 3 or len(outs) != 1:
            raise IRValidationError(f"{node.name}: {op.value} requires at least (Q, K, V) -> out")
        q, k, v, y = ins[0], ins[1], ins[2], outs[0]
        if q.shape[-1] != k.shape[-1]:
            raise IRValidationError(
                f"{node.name}: {op.value} Q/K head dim mismatch {q.shape[-1]} != {k.shape[-1]}"
            )
        if k.shape[:-1] != v.shape[:-1]:
            raise IRValidationError(
                f"{node.name}: {op.value} K/V sequence/head mismatch {k.shape} vs {v.shape}"
            )
        if y.shape[:-1] != q.shape[:-1] or y.shape[-1] != v.shape[-1]:
            raise IRValidationError(
                f"{node.name}: {op.value} output shape {y.shape} incompatible with Q={q.shape}, V={v.shape}"
            )
        if len({q.dtype, k.dtype, v.dtype, y.dtype}) != 1:
            raise IRValidationError(f"{node.name}: {op.value} operands and output must share dtype")

    elif op is OpKind.KV_CACHE_APPEND:
        if len(ins) != 2 or len(outs) != 1:
            raise IRValidationError(f"{node.name}: KV_CACHE_APPEND requires (cache, new_kv) -> updated_cache")
        cache, new_kv, out = ins[0], ins[1], outs[0]
        if cache.dtype != new_kv.dtype or cache.dtype != out.dtype:
            raise IRValidationError(f"{node.name}: KV_CACHE_APPEND dtype mismatch")
        if cache.shape[-1] != new_kv.shape[-1] or out.shape[-1] != cache.shape[-1]:
            raise IRValidationError(f"{node.name}: KV_CACHE_APPEND trailing head_dim mismatch")

    elif op in (OpKind.RESIDUAL_ADD, OpKind.MUL):
        if len(ins) != 2 or len(outs) != 1:
            raise IRValidationError(f"{node.name}: {op.value} requires 2 inputs and 1 output")
        a, b, y = ins[0], ins[1], outs[0]
        if a.shape != y.shape:
            raise IRValidationError(f"{node.name}: {op.value} output shape {y.shape} != lhs {a.shape}")
        if b.shape != a.shape and b.shape_2d != (1, a.shape[-1]):
            raise IRValidationError(
                f"{node.name}: {op.value} incompatible shapes {a.shape} and {b.shape}"
            )
        if a.dtype != b.dtype or a.dtype != y.dtype:
            raise IRValidationError(
                f"{node.name}: {op.value} dtype mismatch {a.dtype}, {b.dtype} -> {y.dtype}"
            )

    elif op is OpKind.CAST:
        if len(ins) != 1 or len(outs) != 1:
            raise IRValidationError(f"{node.name}: CAST requires 1 input and 1 output")
        if ins[0].shape != outs[0].shape:
            raise IRValidationError(
                f"{node.name}: CAST shape mismatch {ins[0].shape} != {outs[0].shape}"
            )
        if "target_dtype" in node.attrs:
            td = normalize_dtype(node.attrs["target_dtype"])
            if td != outs[0].dtype:
                raise IRValidationError(
                    f"{node.name}: CAST target_dtype {td} != output dtype {outs[0].dtype}"
                )


@dataclass(frozen=True)
class CompiledGraph:
    """Validated topologically ordered SSA computation graph."""

    name: str
    tensors: MappingProxyType[str, TensorSpec]
    inputs: tuple[str, ...]
    weights: tuple[str, ...]
    outputs: tuple[str, ...]
    nodes: tuple[OpNode, ...]
    metadata: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def create(
        cls,
        *,
        name: str,
        tensors: dict[str, TensorSpec],
        inputs: tuple[str, ...] | list[str],
        weights: tuple[str, ...] | list[str] = (),
        outputs: tuple[str, ...] | list[str],
        nodes: tuple[OpNode, ...] | list[OpNode],
        metadata: dict[str, Any] | None = None,
    ) -> CompiledGraph:
        if type(name) is not str or not name:
            raise IRValidationError("CompiledGraph.name must be a nonempty string")
        tensor_copy: dict[str, TensorSpec] = {}
        for key, spec in tensors.items():
            if key != spec.name:
                raise IRValidationError(f"tensor key {key!r} != TensorSpec.name {spec.name!r}")
            tensor_copy[key] = spec
        graph = cls(
            name=name,
            tensors=MappingProxyType(tensor_copy),
            inputs=tuple(inputs),
            weights=tuple(weights),
            outputs=tuple(outputs),
            nodes=tuple(nodes),
            metadata=_freeze_attrs(metadata),
        )
        validate_graph(graph)
        return graph


def validate_graph(graph: CompiledGraph) -> None:
    """Validate SSA single-assignment, topological acyclicity, zero unresolved inputs, and shapes/dtypes."""
    if not isinstance(graph, CompiledGraph):
        raise IRValidationError("expected a CompiledGraph instance")

    defined: set[str] = set()
    for name in graph.inputs:
        if name not in graph.tensors:
            raise IRValidationError(f"graph input {name!r} missing from tensor table")
        if name in defined:
            raise IRValidationError(f"duplicate graph input {name!r}")
        defined.add(name)

    for name in graph.weights:
        if name not in graph.tensors:
            raise IRValidationError(f"graph weight {name!r} missing from tensor table")
        if name in defined:
            raise IRValidationError(f"weight {name!r} collides with already defined tensor")
        defined.add(name)

    if not graph.outputs:
        raise IRValidationError("graph must declare at least one output")

    seen_node_names: set[str] = set()
    for node in graph.nodes:
        if node.name in seen_node_names:
            raise IRValidationError(f"duplicate node name {node.name!r}")
        seen_node_names.add(node.name)

        # In strict topological SSA, every input must already be defined strictly before use.
        # Any cycle or forward reference fails immediately here.
        for inp in node.inputs:
            if inp not in graph.tensors:
                raise IRValidationError(f"node {node.name!r} references unknown tensor {inp!r}")
            if inp not in defined:
                raise IRValidationError(
                    f"node {node.name!r} uses unresolved/non-SSA-ordered tensor {inp!r} "
                    "(cycle or use-before-def)"
                )

        for out in node.outputs:
            if out not in graph.tensors:
                raise IRValidationError(f"node {node.name!r} produces unknown tensor {out!r}")
            if out in defined:
                raise IRValidationError(
                    f"SSA violation: tensor {out!r} defined more than once (by node {node.name!r})"
                )

        _check_op_signature(node, graph.tensors)
        for out in node.outputs:
            defined.add(out)

    for out in graph.outputs:
        if out not in graph.tensors:
            raise IRValidationError(f"graph output {out!r} missing from tensor table")
        if out not in defined:
            raise IRValidationError(f"graph output {out!r} is never produced")


__all__ = (
    "CompiledGraph",
    "DTYPE_ELEMENT_BYTES",
    "IRValidationError",
    "OpKind",
    "OpNode",
    "TensorSpec",
    "normalize_dtype",
    "validate_graph",
)
