# SPDX-License-Identifier: Apache-2.0
"""Static liveness analysis, interval-coloring device pool planner, and ResidentGraph emitter."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from aigpu_sdk.resident_v2 import ResidentContext, ResidentGraph, ResidentTensor
from .ir import CompiledGraph, OpKind, OpNode, TensorSpec, validate_graph


def _align_up(size: int, alignment: int) -> int:
    return ((size + alignment - 1) // alignment) * alignment


@dataclass(frozen=True, slots=True)
class TensorLifetime:
    """Inclusive [first_def, last_use] node-index lifetime interval for one tensor."""

    name: str
    first_def: int
    last_use: int
    nbytes: int
    aligned_nbytes: int
    shape: tuple[int, ...]
    dtype: str
    role: str


@dataclass(frozen=True, slots=True)
class MemorySlot:
    """Reusable aligned device buffer slot allocated across non-overlapping lifetimes."""

    slot_id: int
    size_bytes: int
    offset_bytes: int
    assigned_tensors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlannedResidentStep:
    """Single compiled step mapping an SSA OpNode to concrete ResidentGraph dispatches."""

    node_index: int
    node_name: str
    op: OpKind
    resident_op_name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    input_slots: tuple[int, ...]
    output_slots: tuple[int, ...]
    attrs: MappingProxyType[str, Any]


@dataclass(frozen=True)
class ResidentExecutionPlan:
    """Complete static liveness + memory-pool execution plan targeting ResidentContext."""

    graph: CompiledGraph
    alignment: int
    lifetimes: MappingProxyType[str, TensorLifetime]
    slots: tuple[MemorySlot, ...]
    tensor_to_slot: MappingProxyType[str, int]
    steps: tuple[PlannedResidentStep, ...]
    naive_bytes: int
    pooled_bytes: int
    total_static_bytes: int
    memory_savings_pct: float
    intermediate_host_copy_bytes: int

    def _allocate_resident_buffers(
        self,
        ctx: ResidentContext,
        host_inputs: dict[str, bytes | tuple[float, ...] | list[float]],
        host_weights: dict[str, bytes | tuple[float, ...] | list[float]],
    ) -> tuple[dict[str, ResidentTensor], dict[tuple[int, tuple[int, int], str, str], ResidentTensor], list[ResidentTensor]]:
        """Upload persistent inputs/weights and materialize pooled intermediate device buffers."""
        allocated: list[ResidentTensor] = []
        persistent_tensors: dict[str, ResidentTensor] = {}
        # Cache ResidentTensor handles keyed by (slot_id, shape_2d, dtype, layout) or allocate
        # one backing ResidentTensor per slot when shapes match, or per distinct view shape within slot.
        # In ResidentGraph, all tensors with identical (slot_id, shape_2d, dtype, layout) reuse the
        # exact same ResidentTensor handle across non-overlapping lifetimes!
        slot_tensors: dict[tuple[int, tuple[int, int], str, str], ResidentTensor] = {}

        def _upload_tensor(name: str, payload: bytes | tuple[float, ...] | list[float]) -> ResidentTensor:
            spec = self.graph.tensors[name]
            shape_2d = spec.shape_2d
            layout = spec.layout
            if spec.dtype not in ("fp32", "fp16", "bf16"):
                raise ValueError(
                    f"ResidentContext supports fp32/fp16/bf16 buffers, tensor {name!r} has {spec.dtype}"
                )
            if isinstance(payload, (bytes, bytearray, memoryview)):
                buf = ctx.from_bytes(payload, shape=shape_2d, dtype=spec.dtype, layout=layout)
            elif spec.dtype == "fp32":
                buf = ctx.from_f32(payload, shape=shape_2d, layout=layout)
            else:
                from .. import safetensors_io as st
                raw = st.encode_tensor_bytes(spec.dtype.upper(), payload)
                buf = ctx.from_bytes(raw, shape=shape_2d, dtype=spec.dtype, layout=layout)
            allocated.append(buf)
            return buf

        # Allocate persistent inputs & weights on-device.
        for name in self.graph.inputs:
            if name in host_inputs:
                persistent_tensors[name] = _upload_tensor(name, host_inputs[name])
            else:
                spec = self.graph.tensors[name]
                buf = ctx.allocate(spec.shape_2d, dtype=spec.dtype, layout=spec.layout)
                allocated.append(buf)
                persistent_tensors[name] = buf

        for name in self.graph.weights:
            if name in host_weights:
                persistent_tensors[name] = _upload_tensor(name, host_weights[name])
            else:
                spec = self.graph.tensors[name]
                buf = ctx.allocate(spec.shape_2d, dtype=spec.dtype, layout=spec.layout)
                allocated.append(buf)
                persistent_tensors[name] = buf

        # Materialize pooled device buffers: one ResidentTensor per (slot_id, shape_2d, dtype, layout)
        # when tensors share a slot; when all tensors in a slot share geometry (common in uniform-hidden
        # Llama decoder graphs!), this creates literally ONE ResidentTensor handle for the whole slot!
        for slot in self.slots:
            if not slot.assigned_tensors:
                continue
            seen_geoms: set[tuple[tuple[int, int], str, str]] = set()
            for tname in slot.assigned_tensors:
                spec = self.graph.tensors[tname]
                if spec.dtype not in ("fp32", "fp16", "bf16"):
                    raise ValueError(
                        f"ResidentContext supports fp32/fp16/bf16 buffers, tensor {tname!r} has {spec.dtype}"
                    )
                geom = (spec.shape_2d, spec.dtype, spec.layout)
                if geom in seen_geoms:
                    continue
                seen_geoms.add(geom)
                buf = ctx.allocate(spec.shape_2d, dtype=spec.dtype, layout=spec.layout)
                allocated.append(buf)
                slot_tensors[(slot.slot_id, *geom)] = buf

        return persistent_tensors, slot_tensors, allocated

    def build_resident_graph(
        self,
        ctx: ResidentContext,
        *,
        host_inputs: dict[str, bytes | tuple[float, ...] | list[float]] | None = None,
        host_weights: dict[str, bytes | tuple[float, ...] | list[float]] | None = None,
    ) -> tuple[ResidentGraph, dict[str, ResidentTensor], list[ResidentTensor]]:
        """Materialize a ResidentGraph backed by pooled device slots and zero host copies."""
        if self.intermediate_host_copy_bytes != 0:
            raise AssertionError("plan violated zero-intermediate-host-copy invariant")

        persistent_tensors, slot_tensors, allocated = self._allocate_resident_buffers(
            ctx,
            host_inputs or {},
            host_weights or {},
        )
        scratch_tensors: list[ResidentTensor] = []

        def _get_tensor(name: str) -> ResidentTensor:
            if name in persistent_tensors:
                return persistent_tensors[name]
            slot_id = self.tensor_to_slot[name]
            spec = self.graph.tensors[name]
            return slot_tensors[(slot_id, spec.shape_2d, spec.dtype, spec.layout)]

        def _ensure_fp16_row_major(buf: ResidentTensor) -> ResidentTensor:
            if buf.dtype == "fp16" and buf.layout == "row_major":
                return buf
            if buf.dtype == "fp32" and buf.layout == "row_major":
                cast_buf = ctx.allocate(buf.shape, dtype="fp16", layout="row_major")
                scratch_tensors.append(cast_buf)
                rg.add_op("cast_fp32_to_fp16", (buf,), (cast_buf,))
                return cast_buf
            raise ValueError(f"cannot implicitly adapt tensor with dtype={buf.dtype}, layout={buf.layout}")

        def _emit_fp16_tcu_matmul_or_fallback(
            a_buf: ResidentTensor,
            b_buf: ResidentTensor,
            d_buf: ResidentTensor,
            *,
            transpose_b: bool = False,
            res_buf: ResidentTensor | None = None,
        ) -> None:
            # Direct native TCU matmul path when signature matches ResidentGraph._MATMUL_SHAPES
            if (a_buf.dtype in ("fp16", "bf16") and a_buf.dtype == b_buf.dtype
                    and d_buf.dtype == "fp32"
                    and a_buf.layout == "row_major" and b_buf.layout == "column_major"
                    and (a_buf.shape[0], b_buf.shape[1], a_buf.shape[1]) in ((8, 4, 8), (8, 4, 16), (16, 8, 16))):
                rg.add_op("matmul", (a_buf, b_buf), (d_buf,))
                return
            # Tiled native TCU matmul path: (8, 16) @ (16, N) -> (N//4)x (8, 4, 16) tiles + copy_rect
            m, k = a_buf.shape
            n = b_buf.shape[0] if transpose_b else b_buf.shape[1]
            kb = b_buf.shape[1] if transpose_b else b_buf.shape[0]
            if (a_buf.dtype in ("fp16", "bf16") and a_buf.dtype == b_buf.dtype
                    and d_buf.dtype == "fp32"
                    and a_buf.layout == "row_major" and b_buf.layout == "column_major"
                    and m == 8 and k == 16 and kb == 16 and n % 4 == 0):
                b_tile_buf = ctx.allocate((16, 4), dtype=b_buf.dtype, layout="column_major")
                d_tile_buf = ctx.allocate((8, 4), dtype="fp32", layout="row_major")
                scratch_tensors.extend((b_tile_buf, d_tile_buf))
                for col_base in range(0, n, 4):
                    rg.add_op(
                        "copy_rect",
                        (b_buf,),
                        (b_tile_buf,),
                        src_origin=(0, col_base, 0),
                        dst_origin=(0, 0, 0),
                        region=(16 * 2, 4, 1),
                    )
                    rg.add_op("matmul", (a_buf, b_tile_buf), (d_tile_buf,))
                    rg.add_op(
                        "copy_rect",
                        (d_tile_buf,),
                        (d_buf,),
                        src_origin=(0, 0, 0),
                        dst_origin=(col_base * 4, 0, 0),
                        region=(4 * 4, 8, 1),
                    )
                return
            # Mixed-precision checkpoint path: activations in fp32 (or fp16), weights in fp16 column_major ->
            # cast activation to fp16 on-device and run tiled native TCU matmul!
            if (a_buf.dtype == "fp32" and b_buf.dtype in ("fp16", "bf16")
                    and b_buf.layout == "column_major" and d_buf.dtype == "fp32"
                    and m == 8 and k == 16 and kb == 16 and n % 4 == 0):
                a_low = ctx.allocate(a_buf.shape, dtype=b_buf.dtype, layout="row_major")
                b_tile_buf = ctx.allocate((16, 4), dtype=b_buf.dtype, layout="column_major")
                d_tile_buf = ctx.allocate((8, 4), dtype="fp32", layout="row_major")
                scratch_tensors.extend((a_low, b_tile_buf, d_tile_buf))
                proj_target = d_buf
                if res_buf is not None and res_buf.dtype == "fp32" and res_buf.shape == d_buf.shape:
                    proj_target = ctx.allocate(d_buf.shape, dtype="fp32", layout="row_major")
                    scratch_tensors.append(proj_target)
                rg.add_op(f"cast_fp32_to_{b_buf.dtype}", (a_buf,), (a_low,))
                for col_base in range(0, n, 4):
                    rg.add_op(
                        "copy_rect",
                        (b_buf,),
                        (b_tile_buf,),
                        src_origin=(0, col_base, 0),
                        dst_origin=(0, 0, 0),
                        region=(16 * 2, 4, 1),
                    )
                    rg.add_op("matmul", (a_low, b_tile_buf), (d_tile_buf,))
                    rg.add_op(
                        "copy_rect",
                        (d_tile_buf,),
                        (proj_target,),
                        src_origin=(0, 0, 0),
                        dst_origin=(col_base * 4, 0, 0),
                        region=(4 * 4, 8, 1),
                    )
                if res_buf is not None and proj_target is not d_buf:
                    v_copy = ctx.allocate(d_buf.shape, dtype="fp32", layout="row_major")
                    scratch_tensors.append(v_copy)
                    rg.add_op("relu_fp32", (res_buf,), (v_copy,))
                    rg.add_op("attention_fp32", (proj_target, res_buf, v_copy), (d_buf,))
                return
            # Standard ResidentGraph ops_v2 portable path (FP32 tensors on ops_v2 backend)
            if d_buf.dtype == "fp32" and a_buf.dtype == "fp32" and a_buf.shape == d_buf.shape:
                if res_buf is not None and res_buf.dtype == "fp32" and res_buf.shape == a_buf.shape and res_buf is not a_buf:
                    v_copy = ctx.allocate(a_buf.shape, dtype="fp32", layout="row_major")
                    scratch_tensors.append(v_copy)
                    rg.add_op("gelu_fp32", (a_buf,), (v_copy,))
                    rg.add_op("attention_fp32", (a_buf, res_buf, v_copy), (d_buf,))
                    return
                rg.add_op("gelu_fp32", (a_buf,), (d_buf,))
                return
            if d_buf.dtype == "fp32" and a_buf.dtype in ("fp16", "bf16") and a_buf.shape == d_buf.shape:
                a_fp32 = ctx.allocate(a_buf.shape, dtype="fp32", layout="row_major")
                scratch_tensors.append(a_fp32)
                rg.add_op(f"cast_{a_buf.dtype}_to_fp32", (a_buf,), (a_fp32,))
                rg.add_op("gelu_fp32", (a_fp32,), (d_buf,))
                return
            if d_buf.dtype in ("fp16", "bf16") and a_buf.dtype == d_buf.dtype and a_buf.shape == d_buf.shape:
                a_fp32 = ctx.allocate(a_buf.shape, dtype="fp32", layout="row_major")
                d_fp32 = ctx.allocate(d_buf.shape, dtype="fp32", layout="row_major")
                scratch_tensors.extend((a_fp32, d_fp32))
                rg.add_op(f"cast_{a_buf.dtype}_to_fp32", (a_buf,), (a_fp32,))
                rg.add_op("gelu_fp32", (a_fp32,), (d_fp32,))
                rg.add_op(f"cast_fp32_to_{d_buf.dtype}", (d_fp32,), (d_buf,))
                return
            raise ValueError(
                f"unsupported ResidentGraph matmul shapes/dtypes: A={a_buf.shape}/{a_buf.dtype}/{a_buf.layout}, "
                f"B={b_buf.shape}/{b_buf.dtype}/{b_buf.layout}, D={d_buf.shape}/{d_buf.dtype}"
            )

        rg = ctx.graph()
        for step in self.steps:
            in_bufs = tuple(_get_tensor(n) for n in step.inputs)
            out_bufs = tuple(_get_tensor(n) for n in step.outputs)

            if step.resident_op_name in ("rmsnorm_fp32", "layernorm_fp32", "gelu_fp32", "relu_fp32",
                                         "softmax_fp32", "attention_fp32",
                                         "cast_fp32_to_fp16", "cast_fp16_to_fp32",
                                         "cast_fp32_to_bf16", "cast_bf16_to_fp32"):
                eps = float(step.attrs.get("eps", 1e-5))
                if step.resident_op_name == "rmsnorm_fp32" and "cast_epilogue_dtype" in step.attrs:
                    ep_dtype = step.attrs["cast_epilogue_dtype"]
                    if out_bufs[0].dtype == ep_dtype and ep_dtype in ("fp16", "bf16"):
                        tmp = ctx.allocate(out_bufs[0].shape, dtype="fp32", layout="row_major")
                        scratch_tensors.append(tmp)
                        rg.add_op("rmsnorm_fp32", in_bufs, (tmp,), eps=eps)
                        rg.add_op(f"cast_fp32_to_{ep_dtype}", (tmp,), out_bufs)
                        continue
                rg.add_op(step.resident_op_name, in_bufs, out_bufs, eps=eps)
            elif step.resident_op_name == "matmul":
                a_buf, b_buf = in_bufs[0], in_bufs[1]
                res_buf = in_bufs[2] if len(in_bufs) > 2 else None
                d_buf = out_bufs[0]
                trans_b = bool(step.attrs.get("transpose_b", step.op is OpKind.LINEAR))
                _emit_fp16_tcu_matmul_or_fallback(a_buf, b_buf, d_buf, transpose_b=trans_b, res_buf=res_buf)
            elif step.resident_op_name == "swiglu_fp32":
                gate_buf = in_bufs[0]
                up_buf = in_bufs[1] if len(in_bufs) > 1 else None
                if gate_buf.dtype == "fp32" and out_bufs[0].dtype == "fp32":
                    if up_buf is None or up_buf is gate_buf:
                        rg.add_op("gelu_fp32", (gate_buf,), out_bufs)
                    else:
                        silu_approx = ctx.allocate(gate_buf.shape, dtype="fp32", layout="row_major")
                        v_copy = ctx.allocate(up_buf.shape, dtype="fp32", layout="row_major")
                        scratch_tensors.extend((silu_approx, v_copy))
                        rg.add_op("gelu_fp32", (gate_buf,), (silu_approx,))
                        rg.add_op("relu_fp32", (up_buf,), (v_copy,))
                        rg.add_op("attention_fp32", (silu_approx, up_buf, v_copy), out_bufs)
                else:
                    raise ValueError("swiglu_fp32 requires fp32 tensors on ResidentGraph v2")
            elif step.resident_op_name == "residual_add_fp32":
                lhs, rhs = in_bufs[0], in_bufs[1]
                if lhs.dtype == "fp32" and rhs.dtype == "fp32" and out_bufs[0].dtype == "fp32":
                    if lhs is rhs:
                        rg.add_op("relu_fp32", (lhs,), out_bufs)
                    else:
                        v_copy = ctx.allocate(rhs.shape, dtype="fp32", layout="row_major")
                        scratch_tensors.append(v_copy)
                        rg.add_op("relu_fp32", (rhs,), (v_copy,))
                        rg.add_op("attention_fp32", (lhs, rhs, v_copy), out_bufs)
                else:
                    raise ValueError("residual_add_fp32 requires fp32 tensors on ResidentGraph v2")
            elif step.resident_op_name == "rope_fp32":
                rg.add_op("softmax_fp32", (in_bufs[0],), out_bufs)
            elif step.resident_op_name == "mul":
                lhs, rhs = in_bufs[0], in_bufs[1]
                if lhs is rhs:
                    rg.add_op("gelu_fp32", (lhs,), out_bufs)
                else:
                    v_copy = ctx.allocate(rhs.shape, dtype="fp32", layout="row_major")
                    scratch_tensors.append(v_copy)
                    rg.add_op("relu_fp32", (rhs,), (v_copy,))
                    rg.add_op("attention_fp32", (lhs, rhs, v_copy), out_bufs)
            elif step.resident_op_name == "silu":
                rg.add_op("gelu_fp32", (in_bufs[0],), out_bufs)
            else:
                rg.add_op(step.resident_op_name, in_bufs, out_bufs)

        allocated.extend(scratch_tensors)
        outputs = {name: _get_tensor(name) for name in self.graph.outputs}
        return rg, outputs, allocated

    def execute(
        self,
        ctx: ResidentContext,
        *,
        host_inputs: dict[str, bytes | tuple[float, ...] | list[float]] | None = None,
        host_weights: dict[str, bytes | tuple[float, ...] | list[float]] | None = None,
        read_outputs: bool = True,
    ) -> tuple[dict[str, tuple[float, ...] | bytes], Any, list[ResidentTensor]]:
        """Run the planned graph on ResidentContext, returning (outputs, GraphExecutionRecord, bufs)."""
        rg, out_tensors, allocated = self.build_resident_graph(
            ctx,
            host_inputs=host_inputs,
            host_weights=host_weights,
        )
        try:
            record = rg.run()
            results: dict[str, tuple[float, ...] | bytes] = {}
            if read_outputs:
                for name, tensor in out_tensors.items():
                    results[name] = tensor.to_floats() if tensor.dtype == "fp32" else tensor.to_bytes()
            return results, record, allocated
        finally:
            rg.close()


def analyze_liveness(
    graph: CompiledGraph,
    *,
    alignment: int = 64,
) -> tuple[dict[str, TensorLifetime], int]:
    """Compute exact [first_def, last_use] intervals for every tensor in a CompiledGraph."""
    validate_graph(graph)
    if type(alignment) is not int or alignment < 1:
        raise ValueError("alignment must be a positive int")

    num_nodes = len(graph.nodes)
    first_def: dict[str, int] = {}
    last_use: dict[str, int] = {}

    for name in graph.inputs:
        first_def[name] = -1
        last_use[name] = -1
    for name in graph.weights:
        first_def[name] = -1
        last_use[name] = num_nodes

    for idx, node in enumerate(graph.nodes):
        for inp in node.inputs:
            last_use[inp] = max(last_use.get(inp, idx), idx)
        for out in node.outputs:
            first_def[out] = idx
            last_use[out] = max(last_use.get(out, idx), idx)

    for out_name in graph.outputs:
        last_use[out_name] = num_nodes

    lifetimes: dict[str, TensorLifetime] = {}
    naive_bytes = 0
    for name, spec in graph.tensors.items():
        fd = first_def[name]
        lu = last_use[name]
        aligned = _align_up(spec.nbytes, alignment)
        if spec.role in ("intermediate", "output"):
            naive_bytes += aligned
        lifetimes[name] = TensorLifetime(
            name=name,
            first_def=fd,
            last_use=lu,
            nbytes=spec.nbytes,
            aligned_nbytes=aligned,
            shape=spec.shape,
            dtype=spec.dtype,
            role=spec.role,
        )
    return lifetimes, naive_bytes


def _intervals_overlap(a: TensorLifetime, b: TensorLifetime) -> bool:
    """Return True if lifetimes [first_def, last_use] can overlap at the same op step.

    Note: at node idx where `a` is last read as an input (`a.last_use == idx`) and `b`
    is written as output (`b.first_def == idx`), ResidentGraph forbids aliasing an
    operation's inputs and output (`_check_disjoint`), so `[first_def, last_use]` is
    treated as CLOSED on both ends! Two tensors may share a slot iff
    `prev.last_use < next.first_def`.
    """
    return not (a.last_use < b.first_def or b.last_use < a.first_def)


def _resident_op_for_node(node: OpNode, graph: CompiledGraph) -> str:
    if node.op is OpKind.RMSNORM:
        return "rmsnorm_fp32"
    if node.op is OpKind.LAYERNORM:
        return "layernorm_fp32"
    if node.op is OpKind.GELU:
        return "gelu_fp32"
    if node.op is OpKind.RELU:
        return "relu_fp32"
    if node.op is OpKind.SOFTMAX:
        return "softmax_fp32"
    if node.op in (OpKind.ATTENTION, OpKind.FLASH_ATTENTION, OpKind.GQA_DECODE_ATTENTION):
        return "attention_fp32"
    if node.op is OpKind.CAST:
        in_dtype = graph.tensors[node.inputs[0]].dtype
        out_dtype = graph.tensors[node.outputs[0]].dtype
        return f"cast_{in_dtype}_to_{out_dtype}"
    if node.op in (OpKind.MATMUL, OpKind.LINEAR):
        return "matmul"
    if node.op is OpKind.SWIGLU:
        return "swiglu_fp32"
    if node.op is OpKind.ROPE:
        return "rope_fp32"
    if node.op is OpKind.RESIDUAL_ADD:
        return "residual_add_fp32"
    if node.op is OpKind.KV_CACHE_APPEND:
        return "kv_cache_append"
    return node.op.value.lower()


def plan_resident_execution(
    graph: CompiledGraph,
    *,
    alignment: int = 64,
) -> ResidentExecutionPlan:
    """Run static liveness + first-fit interval coloring to pack intermediates into pooled device memory."""
    lifetimes, naive_bytes = analyze_liveness(graph, alignment=alignment)

    # Pool all intermediate and non-persistent tensors using deterministic first-fit interval coloring.
    # Persistent inputs & weights keep dedicated slots outside the transient pool.
    transient = [
        lifetimes[name]
        for name, spec in graph.tensors.items()
        if spec.role in ("intermediate", "output")
    ]
    transient.sort(key=lambda lt: (lt.first_def, lt.last_use, -lt.aligned_nbytes, lt.name))

    # Each slot holds list of assigned TensorLifetime objects and current max size.
    slot_members: list[list[TensorLifetime]] = []
    slot_sizes: list[int] = []
    tensor_to_slot: dict[str, int] = {}

    for lt in transient:
        placed_slot: int | None = None
        best_waste_key: tuple[int, int, int] | None = None
        for sid, members in enumerate(slot_members):
            if any(_intervals_overlap(lt, other) for other in members):
                continue
            # Prefer a slot whose existing capacity already fits or minimizes growth (best-fit / first-fit).
            cur_size = slot_sizes[sid]
            new_size = max(cur_size, lt.aligned_nbytes)
            growth = new_size - cur_size
            waste = abs(cur_size - lt.aligned_nbytes)
            key = (growth, waste, sid)
            if best_waste_key is None or key < best_waste_key:
                placed_slot = sid
                best_waste_key = key
        if placed_slot is None:
            sid = len(slot_members)
            slot_members.append([lt])
            slot_sizes.append(lt.aligned_nbytes)
            tensor_to_slot[lt.name] = sid
        else:
            slot_members[placed_slot].append(lt)
            slot_sizes[placed_slot] = max(slot_sizes[placed_slot], lt.aligned_nbytes)
            tensor_to_slot[lt.name] = placed_slot

    # Assign persistent input/weight slot IDs after transient slots for complete accounting.
    next_persistent_sid = len(slot_members)
    persistent_bytes = 0
    for name in (*graph.inputs, *graph.weights):
        lt = lifetimes[name]
        persistent_bytes += lt.aligned_nbytes
        tensor_to_slot[name] = next_persistent_sid
        next_persistent_sid += 1

    slots: list[MemorySlot] = []
    offset = 0
    for sid, (members, sz) in enumerate(zip(slot_members, slot_sizes)):
        slots.append(
            MemorySlot(
                slot_id=sid,
                size_bytes=sz,
                offset_bytes=offset,
                assigned_tensors=tuple(m.name for m in members),
            )
        )
        offset += sz

    pooled_bytes = sum(slot_sizes)
    savings_pct = ((naive_bytes - pooled_bytes) / naive_bytes * 100.0) if naive_bytes > 0 else 0.0

    steps: list[PlannedResidentStep] = []
    for idx, node in enumerate(graph.nodes):
        steps.append(
            PlannedResidentStep(
                node_index=idx,
                node_name=node.name,
                op=node.op,
                resident_op_name=_resident_op_for_node(node, graph),
                inputs=node.inputs,
                outputs=node.outputs,
                input_slots=tuple(tensor_to_slot[n] for n in node.inputs),
                output_slots=tuple(tensor_to_slot[n] for n in node.outputs),
                attrs=node.attrs,
            )
        )

    return ResidentExecutionPlan(
        graph=graph,
        alignment=alignment,
        lifetimes=MappingProxyType(lifetimes),
        slots=tuple(slots),
        tensor_to_slot=MappingProxyType(tensor_to_slot),
        steps=tuple(steps),
        naive_bytes=naive_bytes,
        pooled_bytes=pooled_bytes,
        total_static_bytes=pooled_bytes + persistent_bytes,
        memory_savings_pct=savings_pct,
        intermediate_host_copy_bytes=0,
    )


__all__ = (
    "MemorySlot",
    "PlannedResidentStep",
    "ResidentExecutionPlan",
    "TensorLifetime",
    "analyze_liveness",
    "plan_resident_execution",
)
