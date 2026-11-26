# SPDX-License-Identifier: Apache-2.0
"""Portable ONNX & PyTorch FX graph lowering plus algebraic operator fusion passes."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
from typing import Any

from .ir import (
    CompiledGraph,
    IRValidationError,
    OpKind,
    OpNode,
    TensorSpec,
    normalize_dtype,
)


class FrontendLoweringError(ValueError):
    """Raised when an ONNX or PyTorch FX graph cannot be safely lowered to Vortex SSA IR."""


@dataclass(frozen=True)
class FusionReport:
    """Summary of algebraic operator fusions applied to a CompiledGraph."""

    swiglu_fusions: int = 0
    residual_fusions: int = 0
    rmsnorm_cast_fusions: int = 0
    original_node_count: int = 0
    fused_node_count: int = 0

    @property
    def total_fusions(self) -> int:
        return self.swiglu_fusions + self.residual_fusions + self.rmsnorm_cast_fusions


# ---------------------------------------------------------------------------
# Shape inference helpers
# ---------------------------------------------------------------------------

def _infer_matmul_shape(
    a_shape: tuple[int, ...],
    b_shape: tuple[int, ...],
    *,
    trans_a: bool = False,
    trans_b: bool = False,
) -> tuple[int, ...]:
    if len(a_shape) == 1:
        a_eff = (1, a_shape[0])
    elif len(a_shape) == 2:
        a_eff = (a_shape[1], a_shape[0]) if trans_a else a_shape
    else:
        a_eff = (a_shape[-1], a_shape[-2]) if trans_a else (a_shape[-2], a_shape[-1])

    if len(b_shape) == 1:
        b_eff = (b_shape[0], 1)
    elif len(b_shape) == 2:
        b_eff = (b_shape[1], b_shape[0]) if trans_b else b_shape
    else:
        b_eff = (b_shape[-1], b_shape[-2]) if trans_b else (b_shape[-2], b_shape[-1])

    if a_eff[1] != b_eff[0]:
        raise FrontendLoweringError(
            f"MatMul/Gemm inner dimension mismatch: {a_shape} (transA={trans_a}) vs "
            f"{b_shape} (transB={trans_b})"
        )
    if len(a_shape) <= 2 and len(b_shape) <= 2:
        return (a_eff[0], b_eff[1])
    prefix = a_shape[:-2] if len(a_shape) >= len(b_shape) else b_shape[:-2]
    return (*prefix, a_eff[0], b_eff[1])


def _infer_linear_shape(
    x_shape: tuple[int, ...],
    w_shape: tuple[int, ...],
    *,
    trans_b: bool = True,
) -> tuple[int, ...]:
    if len(w_shape) != 2:
        raise FrontendLoweringError(f"Linear weight must be 2-D, got {w_shape}")
    out_features, in_features = w_shape if trans_b else (w_shape[1], w_shape[0])
    if x_shape[-1] != in_features:
        raise FrontendLoweringError(
            f"Linear feature mismatch: x={x_shape} vs weight={w_shape} (trans_b={trans_b})"
        )
    return (*x_shape[:-1], out_features)


# ---------------------------------------------------------------------------
# ONNX JSON / GraphProto-style portable frontend
# ---------------------------------------------------------------------------

_ONNX_DIRECT_OP_MAP: dict[str, OpKind] = {
    "Relu": OpKind.RELU,
    "Gelu": OpKind.GELU,
    "FastGelu": OpKind.GELU,
    "Silu": OpKind.SILU,
    "Softmax": OpKind.SOFTMAX,
    "LayerNormalization": OpKind.LAYERNORM,
    "RMSNormalization": OpKind.RMSNORM,
    "SimplifiedLayerNormalization": OpKind.RMSNORM,
    "RotaryEmbedding": OpKind.ROPE,
    "SwiGLU": OpKind.SWIGLU,
    "Attention": OpKind.ATTENTION,
    "MultiHeadAttention": OpKind.ATTENTION,
    "Add": OpKind.RESIDUAL_ADD,
    "Mul": OpKind.MUL,
    "Cast": OpKind.CAST,
}

_ONNX_ELEM_DTYPE_CODES: dict[int, str] = {
    1: "fp32",   # FLOAT
    2: "u8",     # UINT8
    3: "i8",     # INT8
    10: "fp16",  # FLOAT16
    16: "bf16",  # BFLOAT16
    17: "f8_e4m3",
}


def _parse_onnx_tensor_spec(entry: dict[str, Any], *, role: str) -> TensorSpec:
    if not isinstance(entry, dict) or "name" not in entry or "shape" not in entry:
        raise FrontendLoweringError(f"ONNX {role} descriptor must define 'name' and 'shape': {entry!r}")
    raw_dtype = entry.get("dtype", entry.get("elem_type", "fp32"))
    if isinstance(raw_dtype, int):
        if raw_dtype not in _ONNX_ELEM_DTYPE_CODES:
            raise FrontendLoweringError(f"unsupported ONNX numeric elem_type {raw_dtype}")
        dtype = _ONNX_ELEM_DTYPE_CODES[raw_dtype]
    else:
        dtype = normalize_dtype(str(raw_dtype))
    shape = tuple(int(d) for d in entry["shape"])
    layout = entry.get("layout", "row_major")
    return TensorSpec(name=str(entry["name"]), shape=shape, dtype=dtype, layout=layout, role=role)


def _onnx_proto_to_dict(model_or_graph: Any) -> dict[str, Any]:
    """Convert an onnx.ModelProto or onnx.GraphProto into the portable dict schema."""
    graph = getattr(model_or_graph, "graph", model_or_graph)

    def _tensor_value_info(vi: Any) -> dict[str, Any]:
        tt = vi.type.tensor_type
        dims = [int(d.dim_value) for d in tt.shape.dim]
        return {"name": vi.name, "shape": dims, "dtype": int(tt.elem_type)}

    def _initializer_info(init: Any) -> dict[str, Any]:
        return {
            "name": init.name,
            "shape": [int(d) for d in init.dims],
            "dtype": int(init.data_type),
        }

    def _attr_value(attr: Any) -> Any:
        # ONNX AttributeProto type codes: 1=FLOAT, 2=INT, 3=STRING, 6=FLOATS, 7=INTS
        t = getattr(attr, "type", 0)
        if t == 1:
            return float(attr.f)
        if t == 2:
            return int(attr.i)
        if t == 3:
            return attr.s.decode("utf-8") if isinstance(attr.s, (bytes, bytearray)) else str(attr.s)
        if t == 6:
            return [float(v) for v in attr.floats]
        if t == 7:
            return [int(v) for v in attr.ints]
        return None

    nodes = []
    for idx, node in enumerate(graph.node):
        attrs = {a.name: _attr_value(a) for a in node.attribute}
        nodes.append({
            "name": node.name or f"{node.op_type}_{idx}",
            "op_type": node.op_type,
            "inputs": list(node.input),
            "outputs": list(node.output),
            "attributes": attrs,
        })

    return {
        "name": getattr(graph, "name", "") or "onnx_graph",
        "inputs": [_tensor_value_info(vi) for vi in graph.input],
        "initializers": [_initializer_info(init) for init in graph.initializer],
        "outputs": [vi.name for vi in graph.output],
        "value_info": [_tensor_value_info(vi) for vi in getattr(graph, "value_info", ())],
        "nodes": nodes,
    }


def _toposort_onnx_nodes(
    nodes: list[dict[str, Any]],
    initially_defined: set[str],
) -> list[dict[str, Any]]:
    """Topologically order ONNX nodes when input JSON is not already sorted."""
    defined = set(initially_defined)
    remaining = list(nodes)
    ordered: list[dict[str, Any]] = []
    while remaining:
        progressed = False
        next_remaining: list[dict[str, Any]] = []
        for node in remaining:
            ins = [name for name in node.get("inputs", ()) if name]
            if all(name in defined for name in ins):
                ordered.append(node)
                for out in node.get("outputs", ()):
                    if out:
                        defined.add(out)
                progressed = True
            else:
                next_remaining.append(node)
        if not progressed:
            missing = []
            for node in next_remaining:
                for name in node.get("inputs", ()):
                    if name and name not in defined:
                        missing.append((node.get("name", node.get("op_type")), name))
            raise FrontendLoweringError(
                f"ONNX graph contains a cycle or unresolved inputs: {missing}"
            )
        remaining = next_remaining
    return ordered


def lower_onnx_graph(graph_spec: Any) -> CompiledGraph:
    """Lower a portable ONNX dict (or optional onnx.ModelProto/GraphProto) into CompiledGraph."""
    if not isinstance(graph_spec, dict):
        if hasattr(graph_spec, "node") or hasattr(graph_spec, "graph"):
            graph_spec = _onnx_proto_to_dict(graph_spec)
        else:
            raise FrontendLoweringError("graph_spec must be a dict or ONNX ModelProto/GraphProto")

    graph_name = str(graph_spec.get("name") or "onnx_graph")
    tensors: dict[str, TensorSpec] = {}
    inputs: list[str] = []
    weights: list[str] = []

    init_names = {init["name"] for init in graph_spec.get("initializers", ())}
    for entry in graph_spec.get("inputs", ()):
        name = str(entry["name"])
        role = "weight" if name in init_names else "input"
        spec = _parse_onnx_tensor_spec(entry, role=role)
        tensors[name] = spec
        if role == "weight":
            if name not in weights:
                weights.append(name)
        else:
            inputs.append(name)

    for entry in graph_spec.get("initializers", ()):
        name = str(entry["name"])
        if name not in tensors:
            tensors[name] = _parse_onnx_tensor_spec(entry, role="weight")
        if name not in weights:
            weights.append(name)

    hints: dict[str, TensorSpec] = {}
    for entry in graph_spec.get("value_info", ()):
        spec = _parse_onnx_tensor_spec(entry, role="intermediate")
        hints[spec.name] = spec

    raw_outputs = graph_spec.get("outputs", ())
    output_names: list[str] = []
    for out_item in raw_outputs:
        if isinstance(out_item, dict):
            spec = _parse_onnx_tensor_spec(out_item, role="output")
            hints[spec.name] = spec
            output_names.append(spec.name)
        else:
            output_names.append(str(out_item))

    if not output_names:
        raise FrontendLoweringError("ONNX graph must declare at least one output")

    raw_nodes = list(graph_spec.get("nodes", ()))
    ordered_nodes = _toposort_onnx_nodes(raw_nodes, set(tensors.keys()))

    ir_nodes: list[OpNode] = []
    used_node_names: set[str] = set()
    for idx, raw in enumerate(ordered_nodes):
        op_type = raw.get("op_type")
        if type(op_type) is not str or not op_type:
            raise FrontendLoweringError(f"ONNX node[{idx}] missing op_type")
        node_name = str(raw.get("name") or f"{op_type.lower()}_{idx}")
        while node_name in used_node_names:
            node_name = f"{node_name}_{idx}"
        used_node_names.add(node_name)

        node_inputs = tuple(name for name in raw.get("inputs", ()) if name)
        node_outputs = tuple(name for name in raw.get("outputs", ()) if name)
        attrs = dict(raw.get("attributes") or {})
        if not node_inputs or len(node_outputs) != 1:
            raise FrontendLoweringError(
                f"ONNX node {node_name!r} ({op_type}) must have >=1 input and 1 output"
            )
        out_name = node_outputs[0]

        if op_type == "MatMul":
            if len(node_inputs) != 2:
                raise FrontendLoweringError(f"ONNX MatMul {node_name!r} requires 2 inputs")
            a, b = tensors[node_inputs[0]], tensors[node_inputs[1]]
            out_shape = _infer_matmul_shape(a.shape, b.shape)
            out_dtype = normalize_dtype(str(attrs.get("out_dtype", a.dtype)))
            ir_op = OpKind.MATMUL
            ir_attrs = {k: v for k, v in attrs.items() if k != "out_dtype"}
        elif op_type == "Gemm":
            if len(node_inputs) not in (2, 3):
                raise FrontendLoweringError(f"ONNX Gemm {node_name!r} requires 2 or 3 inputs")
            trans_a = bool(attrs.get("transA", 0))
            trans_b = bool(attrs.get("transB", 0))
            a, b = tensors[node_inputs[0]], tensors[node_inputs[1]]
            out_shape = _infer_matmul_shape(a.shape, b.shape, trans_a=trans_a, trans_b=trans_b)
            out_dtype = normalize_dtype(str(attrs.get("out_dtype", a.dtype)))
            ir_op = OpKind.MATMUL
            ir_attrs = {
                "transpose_a": trans_a,
                "transpose_b": trans_b,
                "alpha": float(attrs.get("alpha", 1.0)),
                "beta": float(attrs.get("beta", 1.0)),
            }
        elif op_type in _ONNX_DIRECT_OP_MAP:
            ir_op = _ONNX_DIRECT_OP_MAP[op_type]
            x = tensors[node_inputs[0]]
            out_shape = x.shape
            out_dtype = x.dtype
            ir_attrs = dict(attrs)
            if ir_op is OpKind.CAST:
                to_val = attrs.get("to", attrs.get("target_dtype"))
                if to_val is None:
                    raise FrontendLoweringError(f"ONNX Cast {node_name!r} requires 'to' attribute")
                if isinstance(to_val, int):
                    if to_val not in _ONNX_ELEM_DTYPE_CODES:
                        raise FrontendLoweringError(f"unsupported ONNX Cast target code {to_val}")
                    out_dtype = _ONNX_ELEM_DTYPE_CODES[to_val]
                else:
                    out_dtype = normalize_dtype(str(to_val))
                ir_attrs["target_dtype"] = out_dtype
            elif ir_op is OpKind.RMSNORM:
                ir_attrs.setdefault("eps", float(attrs.get("epsilon", 1e-5)))
            elif ir_op is OpKind.LAYERNORM:
                ir_attrs.setdefault("eps", float(attrs.get("epsilon", 1e-5)))
            elif ir_op is OpKind.SWIGLU and len(node_inputs) == 1:
                out_shape = (*x.shape[:-1], x.shape[-1] // 2)
            elif ir_op is OpKind.ATTENTION:
                q, v = tensors[node_inputs[0]], tensors[node_inputs[2]]
                out_shape = (*q.shape[:-1], v.shape[-1])
        else:
            raise FrontendLoweringError(f"unsupported ONNX op_type: {op_type!r}")

        if out_name in hints:
            hint = hints[out_name]
            if hint.shape != out_shape:
                raise FrontendLoweringError(
                    f"ONNX output {out_name!r} hint shape {hint.shape} != inferred {out_shape}"
                )
            out_dtype = hint.dtype

        role = "output" if out_name in output_names else "intermediate"
        tensors[out_name] = TensorSpec(
            name=out_name,
            shape=out_shape,
            dtype=out_dtype,
            layout="row_major",
            role=role,
        )
        ir_nodes.append(
            OpNode(
                name=node_name,
                op=ir_op,
                inputs=node_inputs,
                outputs=(out_name,),
                attrs=ir_attrs,
            )
        )

    for out_name in output_names:
        if out_name not in tensors:
            raise FrontendLoweringError(f"ONNX graph output {out_name!r} was not produced")
        tensors[out_name] = tensors[out_name].with_role("output")

    return CompiledGraph.create(
        name=graph_name,
        tensors=tensors,
        inputs=inputs,
        weights=weights,
        outputs=output_names,
        nodes=ir_nodes,
        metadata={"frontend": "onnx"},
    )


# ---------------------------------------------------------------------------
# PyTorch FX portable trace spec & optional live torch.fx frontend
# ---------------------------------------------------------------------------

def _normalize_fx_target_name(target: Any) -> str:
    if isinstance(target, str):
        return target
    name = getattr(target, "__name__", None)
    mod = getattr(target, "__module__", "")
    if name:
        return f"{mod}.{name}" if mod else name
    return str(target)


def _fx_resolve_ref(arg: Any) -> str | None:
    if isinstance(arg, str):
        return arg
    if hasattr(arg, "name") and type(getattr(arg, "name", None)) is str:
        return arg.name
    return None


def lower_fx_trace_spec(trace_spec: dict[str, Any]) -> CompiledGraph:
    """Lower a pure-Python FX trace specification dict into CompiledGraph without torch."""
    if not isinstance(trace_spec, dict):
        raise FrontendLoweringError("trace_spec must be a dict")
    graph_name = str(trace_spec.get("name") or "fx_graph")
    tensors: dict[str, TensorSpec] = {}
    inputs: list[str] = []
    weights: list[str] = []
    outputs: list[str] = []

    modules = trace_spec.get("modules", {})
    raw_nodes = trace_spec.get("nodes", ())
    ir_nodes: list[OpNode] = []

    for idx, raw in enumerate(raw_nodes):
        op = raw.get("op")
        name = str(raw.get("name") or f"fx_{idx}")
        target = raw.get("target")
        args = tuple(raw.get("args", ()))
        kwargs = dict(raw.get("kwargs") or {})
        meta = dict(raw.get("meta") or {})

        if op == "placeholder":
            dtype = normalize_dtype(str(meta.get("dtype", "fp32")))
            shape = tuple(int(d) for d in meta["shape"])
            tensors[name] = TensorSpec(name=name, shape=shape, dtype=dtype, role="input")
            inputs.append(name)
        elif op == "get_attr":
            dtype = normalize_dtype(str(meta.get("dtype", "fp32")))
            shape = tuple(int(d) for d in meta["shape"])
            tensors[name] = TensorSpec(name=name, shape=shape, dtype=dtype, role="weight")
            weights.append(name)
        elif op == "output":
            out_arg = args[0] if len(args) == 1 else args
            items = out_arg if isinstance(out_arg, (tuple, list)) else (out_arg,)
            for item in items:
                ref = _fx_resolve_ref(item)
                if ref is None or ref not in tensors:
                    raise FrontendLoweringError(f"FX output references unknown tensor {item!r}")
                outputs.append(ref)
        elif op == "call_module":
            mod_key = str(target)
            if mod_key not in modules:
                raise FrontendLoweringError(f"FX call_module references unknown module {mod_key!r}")
            mod_info = modules[mod_key]
            mod_type = str(mod_info.get("type", ""))
            x_name = _fx_resolve_ref(args[0])
            if x_name is None or x_name not in tensors:
                raise FrontendLoweringError(f"FX call_module {name!r} missing valid input tensor")
            x_spec = tensors[x_name]

            if mod_type in ("Linear", "nn.Linear", "torch.nn.modules.linear.Linear"):
                w_name = f"{mod_key}.weight"
                w_shape = tuple(int(d) for d in mod_info["weight_shape"])
                w_dtype = normalize_dtype(str(mod_info.get("dtype", x_spec.dtype)))
                if w_name not in tensors:
                    tensors[w_name] = TensorSpec(name=w_name, shape=w_shape, dtype=w_dtype, role="weight")
                    weights.append(w_name)
                in_names: list[str] = [x_name, w_name]
                if mod_info.get("bias_shape") is not None:
                    b_name = f"{mod_key}.bias"
                    b_shape = tuple(int(d) for d in mod_info["bias_shape"])
                    if b_name not in tensors:
                        tensors[b_name] = TensorSpec(name=b_name, shape=b_shape, dtype=w_dtype, role="weight")
                        weights.append(b_name)
                    in_names.append(b_name)
                out_shape = _infer_linear_shape(x_spec.shape, w_shape, trans_b=True)
                out_dtype = normalize_dtype(str(meta.get("dtype", x_spec.dtype)))
                tensors[name] = TensorSpec(name=name, shape=out_shape, dtype=out_dtype, role="intermediate")
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.LINEAR,
                        inputs=tuple(in_names),
                        outputs=(name,),
                        attrs={"transpose_b": True},
                    )
                )
            elif mod_type in ("LayerNorm", "nn.LayerNorm", "torch.nn.modules.normalization.LayerNorm"):
                w_name = f"{mod_key}.weight"
                b_name = f"{mod_key}.bias"
                cols = x_spec.shape[-1]
                w_shape = tuple(int(d) for d in mod_info.get("weight_shape", (cols,)))
                w_dtype = normalize_dtype(str(mod_info.get("dtype", x_spec.dtype)))
                if w_name not in tensors:
                    tensors[w_name] = TensorSpec(name=w_name, shape=w_shape, dtype=w_dtype, role="weight")
                    weights.append(w_name)
                in_names = [x_name, w_name]
                if mod_info.get("has_bias", True):
                    b_shape = tuple(int(d) for d in mod_info.get("bias_shape", (cols,)))
                    if b_name not in tensors:
                        tensors[b_name] = TensorSpec(name=b_name, shape=b_shape, dtype=w_dtype, role="weight")
                        weights.append(b_name)
                    in_names.append(b_name)
                tensors[name] = TensorSpec(
                    name=name, shape=x_spec.shape, dtype=x_spec.dtype, role="intermediate"
                )
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.LAYERNORM,
                        inputs=tuple(in_names),
                        outputs=(name,),
                        attrs={"eps": float(mod_info.get("eps", 1e-5))},
                    )
                )
            elif mod_type in ("RMSNorm", "nn.RMSNorm", "torch.nn.modules.normalization.RMSNorm"):
                w_name = f"{mod_key}.weight"
                w_shape = tuple(int(d) for d in mod_info.get("weight_shape", (x_spec.shape[-1],)))
                w_dtype = normalize_dtype(str(mod_info.get("dtype", x_spec.dtype)))
                if w_name not in tensors:
                    tensors[w_name] = TensorSpec(name=w_name, shape=w_shape, dtype=w_dtype, role="weight")
                    weights.append(w_name)
                tensors[name] = TensorSpec(
                    name=name, shape=x_spec.shape, dtype=x_spec.dtype, role="intermediate"
                )
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.RMSNORM,
                        inputs=(x_name, w_name),
                        outputs=(name,),
                        attrs={"eps": float(mod_info.get("eps", 1e-5))},
                    )
                )
            elif mod_type in ("ReLU", "nn.ReLU", "torch.nn.modules.activation.ReLU"):
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.RELU, inputs=(x_name,), outputs=(name,)))
            elif mod_type in ("GELU", "nn.GELU", "torch.nn.modules.activation.GELU"):
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.GELU, inputs=(x_name,), outputs=(name,)))
            elif mod_type in ("SiLU", "nn.SiLU", "torch.nn.modules.activation.SiLU"):
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.SILU, inputs=(x_name,), outputs=(name,)))
            elif mod_type in ("Softmax", "nn.Softmax", "torch.nn.modules.activation.Softmax"):
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.SOFTMAX,
                        inputs=(x_name,),
                        outputs=(name,),
                        attrs={"dim": int(mod_info.get("dim", -1))},
                    )
                )
            else:
                raise FrontendLoweringError(f"unsupported FX module type: {mod_type!r}")

        elif op in ("call_function", "call_method"):
            tname = _normalize_fx_target_name(target)
            short = tname.rsplit(".", 1)[-1]
            in_names = tuple(_fx_resolve_ref(a) or "" for a in args if _fx_resolve_ref(a) is not None)
            if not in_names or any(n not in tensors for n in in_names):
                raise FrontendLoweringError(
                    f"FX {op} {name!r} ({tname}) has unresolved input arguments {args!r}"
                )
            x_spec = tensors[in_names[0]]

            if short in ("matmul", "mm", "bmm"):
                b_spec = tensors[in_names[1]]
                out_shape = _infer_matmul_shape(x_spec.shape, b_spec.shape)
                out_dtype = normalize_dtype(str(meta.get("dtype", x_spec.dtype)))
                tensors[name] = TensorSpec(name=name, shape=out_shape, dtype=out_dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.MATMUL, inputs=in_names[:2], outputs=(name,)))
            elif short == "linear":
                w_spec = tensors[in_names[1]]
                out_shape = _infer_linear_shape(x_spec.shape, w_spec.shape, trans_b=True)
                out_dtype = normalize_dtype(str(meta.get("dtype", x_spec.dtype)))
                tensors[name] = TensorSpec(name=name, shape=out_shape, dtype=out_dtype)
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.LINEAR,
                        inputs=in_names[:3],
                        outputs=(name,),
                        attrs={"transpose_b": True},
                    )
                )
            elif short == "relu":
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.RELU, inputs=(in_names[0],), outputs=(name,)))
            elif short == "gelu":
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.GELU, inputs=(in_names[0],), outputs=(name,)))
            elif short == "silu":
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.SILU, inputs=(in_names[0],), outputs=(name,)))
            elif short == "softmax":
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.SOFTMAX,
                        inputs=(in_names[0],),
                        outputs=(name,),
                        attrs={"dim": int(kwargs.get("dim", -1))},
                    )
                )
            elif short == "layer_norm":
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                norm_inputs: list[str] = [in_names[0]]
                weight_ref = _fx_resolve_ref(kwargs.get("weight")) or (in_names[1] if len(in_names) > 1 else None)
                bias_ref = _fx_resolve_ref(kwargs.get("bias")) or (in_names[2] if len(in_names) > 2 else None)
                if weight_ref is None:
                    raise FrontendLoweringError(f"FX layer_norm {name!r} requires weight tensor")
                norm_inputs.append(weight_ref)
                if bias_ref is not None:
                    norm_inputs.append(bias_ref)
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.LAYERNORM,
                        inputs=tuple(norm_inputs),
                        outputs=(name,),
                        attrs={"eps": float(kwargs.get("eps", 1e-5))},
                    )
                )
            elif short in ("rms_norm", "rmsnorm"):
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                weight_ref = _fx_resolve_ref(kwargs.get("weight")) or (in_names[1] if len(in_names) > 1 else None)
                if weight_ref is None:
                    raise FrontendLoweringError(f"FX rms_norm {name!r} requires weight tensor")
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.RMSNORM,
                        inputs=(in_names[0], weight_ref),
                        outputs=(name,),
                        attrs={"eps": float(kwargs.get("eps", 1e-5))},
                    )
                )
            elif short in ("add", "iadd"):
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.RESIDUAL_ADD, inputs=in_names[:2], outputs=(name,)))
            elif short in ("mul", "imul"):
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=x_spec.dtype)
                ir_nodes.append(OpNode(name=name, op=OpKind.MUL, inputs=in_names[:2], outputs=(name,)))
            elif short == "scaled_dot_product_attention":
                q_spec, v_spec = tensors[in_names[0]], tensors[in_names[2]]
                out_shape = (*q_spec.shape[:-1], v_spec.shape[-1])
                tensors[name] = TensorSpec(name=name, shape=out_shape, dtype=q_spec.dtype)
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.ATTENTION,
                        inputs=in_names[:3],
                        outputs=(name,),
                        attrs={"is_causal": bool(kwargs.get("is_causal", False))},
                    )
                )
            elif short in ("to", "cast"):
                raw_dtype = kwargs.get("dtype") or meta.get("target_dtype") or meta.get("dtype")
                if raw_dtype is None:
                    raise FrontendLoweringError(f"FX cast/to node {name!r} requires target dtype")
                target_dtype = normalize_dtype(str(raw_dtype))
                tensors[name] = TensorSpec(name=name, shape=x_spec.shape, dtype=target_dtype)
                ir_nodes.append(
                    OpNode(
                        name=name,
                        op=OpKind.CAST,
                        inputs=(in_names[0],),
                        outputs=(name,),
                        attrs={"target_dtype": target_dtype},
                    )
                )
            else:
                raise FrontendLoweringError(f"unsupported FX function/method target: {tname!r}")
        else:
            raise FrontendLoweringError(f"unsupported FX node op {op!r} on node {name!r}")

    if not outputs:
        raise FrontendLoweringError("FX graph must contain an 'output' node")

    for out_name in outputs:
        tensors[out_name] = tensors[out_name].with_role("output")

    return CompiledGraph.create(
        name=graph_name,
        tensors=tensors,
        inputs=inputs,
        weights=weights,
        outputs=outputs,
        nodes=ir_nodes,
        metadata={"frontend": "torch_fx"},
    )


def _fx_graph_module_to_trace_spec(gm: Any, example_inputs: dict[str, tuple[tuple[int, ...], str]] | None = None) -> dict[str, Any]:
    """Convert a real (or duck-typed) torch.fx.GraphModule into our portable trace spec dict."""
    if not hasattr(gm, "graph") or not hasattr(gm.graph, "nodes"):
        raise FrontendLoweringError("expected a torch.fx.GraphModule with .graph.nodes")

    named_modules = dict(gm.named_modules()) if hasattr(gm, "named_modules") else {}
    named_params = dict(gm.named_parameters()) if hasattr(gm, "named_parameters") else {}
    named_buffers = dict(gm.named_buffers()) if hasattr(gm, "named_buffers") else {}

    modules_spec: dict[str, dict[str, Any]] = {}
    for mod_name, mod in named_modules.items():
        if not mod_name:
            continue
        cls_name = type(mod).__name__
        entry: dict[str, Any] = {"type": cls_name}
        if hasattr(mod, "weight") and getattr(mod, "weight") is not None:
            w = mod.weight
            entry["weight_shape"] = tuple(int(d) for d in w.shape)
            entry["dtype"] = normalize_dtype(str(w.dtype))
        if hasattr(mod, "bias") and getattr(mod, "bias") is not None:
            b = mod.bias
            entry["bias_shape"] = tuple(int(d) for d in b.shape)
            entry["has_bias"] = True
        else:
            entry["has_bias"] = False
        if hasattr(mod, "eps"):
            entry["eps"] = float(mod.eps)
        if hasattr(mod, "dim") and getattr(mod, "dim") is not None:
            entry["dim"] = int(mod.dim)
        modules_spec[mod_name] = entry

    nodes_spec: list[dict[str, Any]] = []
    for node in gm.graph.nodes:
        meta: dict[str, Any] = {}
        tensor_meta = node.meta.get("tensor_meta") if hasattr(node, "meta") and isinstance(node.meta, dict) else None
        if tensor_meta is not None:
            meta["shape"] = tuple(int(d) for d in tensor_meta.shape)
            meta["dtype"] = normalize_dtype(str(tensor_meta.dtype))
        elif example_inputs and node.name in example_inputs:
            shape, dtype = example_inputs[node.name]
            meta["shape"] = tuple(int(d) for d in shape)
            meta["dtype"] = normalize_dtype(dtype)
        elif node.op == "get_attr":
            param = named_params.get(str(node.target)) or named_buffers.get(str(node.target))
            if param is None and hasattr(gm, str(node.target)):
                param = getattr(gm, str(node.target))
            if param is not None and hasattr(param, "shape"):
                meta["shape"] = tuple(int(d) for d in param.shape)
                meta["dtype"] = normalize_dtype(str(param.dtype))

        def _conv_arg(arg: Any) -> Any:
            if isinstance(arg, (tuple, list)):
                return [_conv_arg(a) for a in arg]
            if hasattr(arg, "name") and type(getattr(arg, "name", None)) is str:
                return arg.name
            return arg

        nodes_spec.append({
            "op": node.op,
            "name": node.name,
            "target": node.target,
            "args": _conv_arg(node.args),
            "kwargs": {k: _conv_arg(v) for k, v in dict(node.kwargs).items()},
            "meta": meta,
        })

    return {
        "name": type(gm).__name__,
        "modules": modules_spec,
        "nodes": nodes_spec,
    }


def lower_torch_fx(
    graph_module_or_spec: Any,
    *,
    example_inputs: dict[str, tuple[tuple[int, ...], str]] | None = None,
) -> CompiledGraph:
    """Lower either a live torch.fx.GraphModule or a portable FX trace spec dict."""
    if isinstance(graph_module_or_spec, dict):
        return lower_fx_trace_spec(graph_module_or_spec)
    trace_spec = _fx_graph_module_to_trace_spec(graph_module_or_spec, example_inputs=example_inputs)
    return lower_fx_trace_spec(trace_spec)


# ---------------------------------------------------------------------------
# Algebraic Operator Fusion Pass
# ---------------------------------------------------------------------------

def _consumer_counts(graph: CompiledGraph) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in graph.nodes:
        for inp in node.inputs:
            counts[inp] += 1
    for out in graph.outputs:
        counts[out] += 1
    return counts


def fuse_graph(graph: CompiledGraph) -> tuple[CompiledGraph, FusionReport]:
    """Fuse SiLU*up -> SWIGLU, MatMul/Linear+Add -> fused residual, and RMSNorm+Cast."""
    original_count = len(graph.nodes)
    current = graph
    swiglu_count = 0
    residual_count = 0
    rmsnorm_cast_count = 0

    # Pass 1: SiLU(gate) -> silu_out; Mul(silu_out, up) -> out  ==>  SwiGLU(gate, up) -> out
    # (Also handles Mul(up, silu_out).)
    counts = _consumer_counts(current)
    nodes = list(current.nodes)
    by_output: dict[str, OpNode] = {n.outputs[0]: n for n in nodes if len(n.outputs) == 1}
    dead_silu: set[str] = set()
    replaced_nodes: list[OpNode] = []

    for node in nodes:
        if node.op is OpKind.MUL and len(node.inputs) == 2:
            lhs, rhs = node.inputs
            cand_silu = None
            other = None
            if lhs in by_output and by_output[lhs].op is OpKind.SILU and counts[lhs] == 1:
                cand_silu = by_output[lhs]
                other = rhs
            elif rhs in by_output and by_output[rhs].op is OpKind.SILU and counts[rhs] == 1:
                cand_silu = by_output[rhs]
                other = lhs
            if cand_silu is not None and other is not None:
                gate = cand_silu.inputs[0]
                dead_silu.add(cand_silu.name)
                replaced_nodes.append(
                    OpNode(
                        name=f"{node.name}_swiglu",
                        op=OpKind.SWIGLU,
                        inputs=(gate, other),
                        outputs=node.outputs,
                        attrs={"fused_from": (cand_silu.name, node.name)},
                    )
                )
                swiglu_count += 1
                continue
        replaced_nodes.append(node)

    nodes_after_swiglu = [n for n in replaced_nodes if n.name not in dead_silu]
    used_tensors = set(current.inputs) | set(current.weights) | set(current.outputs)
    for n in nodes_after_swiglu:
        used_tensors.update(n.inputs)
        used_tensors.update(n.outputs)
    tensors_after_swiglu = {k: v for k, v in current.tensors.items() if k in used_tensors}
    current = CompiledGraph.create(
        name=current.name,
        tensors=tensors_after_swiglu,
        inputs=current.inputs,
        weights=current.weights,
        outputs=current.outputs,
        nodes=nodes_after_swiglu,
        metadata=dict(current.metadata),
    )

    # Pass 2: MatMul/Linear(a, b) -> prod; ResidualAdd(prod, res) -> out  ==>  fused residual attr on MatMul/Linear
    counts = _consumer_counts(current)
    nodes = list(current.nodes)
    by_output = {n.outputs[0]: n for n in nodes if len(n.outputs) == 1}
    fused_producers: dict[str, OpNode] = {}
    dead_adds: set[str] = set()

    for node in nodes:
        if node.op is OpKind.RESIDUAL_ADD and len(node.inputs) == 2:
            lhs, rhs = node.inputs
            prod_node = None
            res_tensor = None
            if lhs in by_output and by_output[lhs].op in (OpKind.MATMUL, OpKind.LINEAR) and counts[lhs] == 1:
                prod_node = by_output[lhs]
                res_tensor = rhs
            elif rhs in by_output and by_output[rhs].op in (OpKind.MATMUL, OpKind.LINEAR) and counts[rhs] == 1:
                prod_node = by_output[rhs]
                res_tensor = lhs
            if prod_node is not None and res_tensor is not None and len(prod_node.inputs) == 2:
                if prod_node.name in fused_producers:
                    continue
                if current.tensors[res_tensor].dtype == current.tensors[prod_node.outputs[0]].dtype:
                    new_attrs = dict(prod_node.attrs)
                    new_attrs["fused_residual"] = True
                    new_attrs["fused_from"] = (prod_node.name, node.name)
                    fused_producers[prod_node.name] = OpNode(
                        name=f"{prod_node.name}_fused_res",
                        op=prod_node.op,
                        inputs=(*prod_node.inputs, res_tensor),
                        outputs=node.outputs,
                        attrs=new_attrs,
                    )
                    dead_adds.add(node.name)
                    residual_count += 1

    # Emit the fused node at the Add site: both prod_node.inputs and res_tensor are guaranteed
    # defined before the Add site in valid SSA order, and prod_node.outputs had consumer count 1.
    nodes_after_res: list[OpNode] = []
    deferred: dict[str, OpNode] = {}
    for node in nodes:
        if node.name in fused_producers:
            deferred[node.outputs[0]] = fused_producers[node.name]
            continue
        if node.name in dead_adds:
            lhs, rhs = node.inputs
            prod_out = lhs if lhs in deferred else rhs
            nodes_after_res.append(deferred.pop(prod_out))
            continue
        nodes_after_res.append(node)

    used_tensors = set(current.inputs) | set(current.weights) | set(current.outputs)
    for n in nodes_after_res:
        used_tensors.update(n.inputs)
        used_tensors.update(n.outputs)
    tensors_after_res = {k: v for k, v in current.tensors.items() if k in used_tensors}
    current = CompiledGraph.create(
        name=current.name,
        tensors=tensors_after_res,
        inputs=current.inputs,
        weights=current.weights,
        outputs=current.outputs,
        nodes=nodes_after_res,
        metadata=dict(current.metadata),
    )

    # Pass 3: RMSNorm(x, w) -> norm_out; Cast(norm_out) -> cast_out (when norm_out has 1 consumer)
    counts = _consumer_counts(current)
    nodes = list(current.nodes)
    by_output = {n.outputs[0]: n for n in nodes if len(n.outputs) == 1}
    dead_norms: set[str] = set()
    replaced_norm_cast: list[OpNode] = []
    updated_tensors = dict(current.tensors)

    for node in nodes:
        if node.op is OpKind.CAST and len(node.inputs) == 1:
            src = node.inputs[0]
            if src in by_output and by_output[src].op is OpKind.RMSNORM and counts[src] == 1:
                norm_node = by_output[src]
                out_name = node.outputs[0]
                cast_dtype = updated_tensors[out_name].dtype
                new_attrs = dict(norm_node.attrs)
                new_attrs["cast_epilogue_dtype"] = cast_dtype
                new_attrs["fused_from"] = (norm_node.name, node.name)
                dead_norms.add(norm_node.name)
                replaced_norm_cast.append(
                    OpNode(
                        name=f"{norm_node.name}_cast_{cast_dtype}",
                        op=OpKind.RMSNORM,
                        inputs=norm_node.inputs,
                        outputs=node.outputs,
                        attrs=new_attrs,
                    )
                )
                rmsnorm_cast_count += 1
                continue
        replaced_norm_cast.append(node)

    final_nodes = [n for n in replaced_norm_cast if n.name not in dead_norms]
    used_tensors = set(current.inputs) | set(current.weights) | set(current.outputs)
    for n in final_nodes:
        used_tensors.update(n.inputs)
        used_tensors.update(n.outputs)
    final_tensors = {k: v for k, v in updated_tensors.items() if k in used_tensors}
    meta = dict(current.metadata)
    meta["fused"] = True
    fused_graph = CompiledGraph.create(
        name=current.name,
        tensors=final_tensors,
        inputs=current.inputs,
        weights=current.weights,
        outputs=current.outputs,
        nodes=final_nodes,
        metadata=meta,
    )

    report = FusionReport(
        swiglu_fusions=swiglu_count,
        residual_fusions=residual_count,
        rmsnorm_cast_fusions=rmsnorm_cast_count,
        original_node_count=original_count,
        fused_node_count=len(fused_graph.nodes),
    )
    return fused_graph, report


__all__ = (
    "FrontendLoweringError",
    "FusionReport",
    "fuse_graph",
    "lower_fx_trace_spec",
    "lower_onnx_graph",
    "lower_torch_fx",
)
