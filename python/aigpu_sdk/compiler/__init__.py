# SPDX-License-Identifier: Apache-2.0
"""Vortex AI compiler frontend, SSA IR, fusion passes, and resident memory planner."""

from __future__ import annotations

from .fx_onnx_frontend import (
    FrontendLoweringError,
    FusionReport,
    fuse_graph,
    lower_fx_trace_spec,
    lower_onnx_graph,
    lower_torch_fx,
)
from .ir import (
    CompiledGraph,
    DTYPE_ELEMENT_BYTES,
    IRValidationError,
    OpKind,
    OpNode,
    TensorSpec,
    normalize_dtype,
    validate_graph,
)
from .planner import (
    MemorySlot,
    PlannedResidentStep,
    ResidentExecutionPlan,
    TensorLifetime,
    analyze_liveness,
    plan_resident_execution,
)

__all__ = (
    "CompiledGraph",
    "DTYPE_ELEMENT_BYTES",
    "FrontendLoweringError",
    "FusionReport",
    "IRValidationError",
    "MemorySlot",
    "OpKind",
    "OpNode",
    "PlannedResidentStep",
    "ResidentExecutionPlan",
    "TensorLifetime",
    "TensorSpec",
    "analyze_liveness",
    "fuse_graph",
    "lower_fx_trace_spec",
    "lower_onnx_graph",
    "lower_torch_fx",
    "normalize_dtype",
    "plan_resident_execution",
    "validate_graph",
)
