"""Additive AI-GPU v2/v3 Python SDK (resident graphs, safetensors, FX/ONNX compiler).

Preserves the frozen P05 ``vortex_ai`` package inventory untouched.
"""

from . import compiler, resident_v2, safetensors_io

__all__ = ["compiler", "resident_v2", "safetensors_io"]
