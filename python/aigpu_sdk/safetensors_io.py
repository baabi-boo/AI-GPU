# SPDX-License-Identifier: Apache-2.0
"""Pure-Python HuggingFace .safetensors binary reader, writer, and micro-Llama generator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
import mmap
import os
from pathlib import Path
import struct
import weakref


MAX_HEADER_BYTES = 100 * 1024 * 1024  # 100 MiB HuggingFace safetensors limit.

DTYPE_SIZES: dict[str, int] = {
    "F32": 4,
    "F16": 2,
    "BF16": 2,
    "I8": 1,
    "U8": 1,
    "F8_E4M3": 1,
}
SUPPORTED_DTYPES: frozenset[str] = frozenset(DTYPE_SIZES)


class SafetensorsError(ValueError):
    """Raised when a .safetensors stream or tensor payload violates the format contract."""


@dataclass(frozen=True, slots=True)
class TensorInfo:
    """Validated metadata entry for one tensor stored in a .safetensors file."""

    name: str
    dtype: str
    shape: tuple[int, ...]
    data_offsets: tuple[int, int]
    nbytes: int


@dataclass(frozen=True, slots=True)
class TensorData:
    """Typed tensor payload suitable for serialization or eager loading."""

    dtype: str
    shape: tuple[int, ...]
    data: bytes | bytearray | memoryview

    def __post_init__(self) -> None:
        if type(self.dtype) is not str or self.dtype not in SUPPORTED_DTYPES:
            raise SafetensorsError(f"unsupported safetensors dtype: {self.dtype!r}")
        if type(self.shape) is list:
            object.__setattr__(self, "shape", tuple(self.shape))
        elif type(self.shape) is not tuple:
            raise SafetensorsError("shape must be a tuple or list of non-negative ints")
        for idx, dim in enumerate(self.shape):
            if type(dim) is not int or dim < 0:
                raise SafetensorsError(f"shape[{idx}] must be a non-negative exact int, got {dim!r}")
        expected = math.prod(self.shape) * DTYPE_SIZES[self.dtype]
        if type(self.data) not in (bytes, bytearray, memoryview):
            raise SafetensorsError("tensor data must be bytes, bytearray, or memoryview")
        view = memoryview(self.data)
        try:
            if view.ndim != 1 or view.itemsize != 1 or not view.c_contiguous:
                raise SafetensorsError("tensor data must be contiguous 1-D byte storage")
            if view.nbytes != expected:
                raise SafetensorsError(
                    f"tensor byte length {view.nbytes} does not match expected {expected} "
                    f"for shape {self.shape} and dtype {self.dtype}"
                )
        finally:
            view.release()


def _check_sequence_numbers(values: Sequence[float | int], *, allow_bool: bool = False) -> list[float | int]:
    items = list(values)
    for item in items:
        if type(item) is bool and not allow_bool:
            raise TypeError("numeric sequence elements cannot be bool")
        if type(item) not in (int, float):
            raise TypeError(f"expected int or float element, got {type(item).__name__}")
    return items


def pack_f32(values: Sequence[float | int]) -> bytes:
    """Pack Python floats as little-endian IEEE-754 FP32 bytes."""
    items = _check_sequence_numbers(values)
    return struct.pack(f"<{len(items)}f", *items)


def unpack_f32(data: bytes | bytearray | memoryview) -> tuple[float, ...]:
    """Unpack little-endian IEEE-754 FP32 bytes into Python floats."""
    view = memoryview(data)
    try:
        if view.nbytes % 4 != 0:
            raise SafetensorsError("F32 payload length must be a multiple of 4")
        return struct.unpack(f"<{view.nbytes // 4}f", view)
    finally:
        view.release()


def pack_f16(values: Sequence[float | int]) -> bytes:
    """Pack Python floats as little-endian IEEE-754 FP16 bytes."""
    items = _check_sequence_numbers(values)
    return struct.pack(f"<{len(items)}e", *items)


def unpack_f16(data: bytes | bytearray | memoryview) -> tuple[float, ...]:
    """Unpack little-endian IEEE-754 FP16 bytes into Python floats."""
    view = memoryview(data)
    try:
        if view.nbytes % 2 != 0:
            raise SafetensorsError("F16 payload length must be a multiple of 2")
        return struct.unpack(f"<{view.nbytes // 2}e", view)
    finally:
        view.release()


def _f32_to_bf16_u16(value: float) -> int:
    bits = struct.unpack("<I", struct.pack("<f", float(value)))[0]
    exp = (bits >> 23) & 0xFF
    mant = bits & 0x7FFFFF
    if exp == 0xFF:
        if mant != 0:
            return (bits >> 16) | 0x0040  # Preserve quiet NaN.
        return bits >> 16
    rounding_bias = 0x7FFF + ((bits >> 16) & 1)
    return (bits + rounding_bias) >> 16


def _bf16_u16_to_f32(u16: int) -> float:
    return struct.unpack("<f", struct.pack("<I", (u16 & 0xFFFF) << 16))[0]


def pack_bf16(values: Sequence[float | int]) -> bytes:
    """Pack Python floats as little-endian BF16 bytes using IEEE-754 RNE."""
    items = _check_sequence_numbers(values)
    encoded = [_f32_to_bf16_u16(float(v)) for v in items]
    return struct.pack(f"<{len(encoded)}H", *encoded)


def unpack_bf16(data: bytes | bytearray | memoryview) -> tuple[float, ...]:
    """Unpack little-endian BF16 bytes into Python floats."""
    view = memoryview(data)
    try:
        if view.nbytes % 2 != 0:
            raise SafetensorsError("BF16 payload length must be a multiple of 2")
        u16s = struct.unpack(f"<{view.nbytes // 2}H", view)
        return tuple(_bf16_u16_to_f32(u) for u in u16s)
    finally:
        view.release()


def pack_i8(values: Sequence[int]) -> bytes:
    """Pack signed int8 integers."""
    items = list(values)
    for item in items:
        if type(item) is not int:
            raise TypeError("I8 elements must be exact int")
        if item < -128 or item > 127:
            raise ValueError(f"I8 value {item} out of [-128, 127]")
    return struct.pack(f"<{len(items)}b", *items)


def unpack_i8(data: bytes | bytearray | memoryview) -> tuple[int, ...]:
    """Unpack signed int8 bytes."""
    view = memoryview(data)
    try:
        return struct.unpack(f"<{view.nbytes}b", view)
    finally:
        view.release()


def pack_u8(values: Sequence[int]) -> bytes:
    """Pack unsigned uint8 integers."""
    items = list(values)
    for item in items:
        if type(item) is not int:
            raise TypeError("U8 elements must be exact int")
        if item < 0 or item > 255:
            raise ValueError(f"U8 value {item} out of [0, 255]")
    return struct.pack(f"<{len(items)}B", *items)


def unpack_u8(data: bytes | bytearray | memoryview) -> tuple[int, ...]:
    """Unpack unsigned uint8 bytes."""
    view = memoryview(data)
    try:
        return struct.unpack(f"<{view.nbytes}B", view)
    finally:
        view.release()


def _f32_to_f8_e4m3(value: float) -> int:
    val = float(value)
    if math.isnan(val):
        return 0x7F
    sign = 0x80 if math.copysign(1.0, val) < 0.0 else 0
    aval = abs(val)
    if aval == 0.0:
        return sign
    if aval >= 448.0:
        return sign | 0x7E  # Saturate to max finite E4M3FN = 448.0.
    # Exhaustive search over the 126 non-negative finite E4M3FN encodings with RNE tie-breaking.
    best_code = 0
    best_err = math.inf
    for code in range(0x7F):  # 0x00..0x7E (0x7F is NaN)
        cand = _f8_e4m3_to_f32(code)
        err = abs(aval - cand)
        if err < best_err or (err == best_err and (code & 1) == 0):
            best_err = err
            best_code = code
    return sign | best_code


def _f8_e4m3_to_f32(code: int) -> float:
    code &= 0xFF
    sign = -1.0 if (code & 0x80) else 1.0
    exp = (code >> 3) & 0x0F
    mant = code & 0x07
    if exp == 0x0F and mant == 0x07:
        return math.nan
    if exp == 0:
        if mant == 0:
            return math.copysign(0.0, sign)
        return sign * math.ldexp(mant / 8.0, -6)
    return sign * math.ldexp(1.0 + mant / 8.0, exp - 7)


def pack_f8_e4m3(values: Sequence[float | int]) -> bytes:
    """Pack floats as OCP FP8 E4M3FN bytes."""
    items = _check_sequence_numbers(values)
    return bytes(_f32_to_f8_e4m3(float(v)) for v in items)


def unpack_f8_e4m3(data: bytes | bytearray | memoryview) -> tuple[float, ...]:
    """Unpack OCP FP8 E4M3FN bytes into Python floats."""
    view = memoryview(data)
    try:
        return tuple(_f8_e4m3_to_f32(b) for b in view)
    finally:
        view.release()


def encode_tensor_bytes(dtype: str, values: Sequence[float | int]) -> bytes:
    """Encode a flat Python sequence into little-endian raw bytes for the given dtype."""
    if dtype == "F32":
        return pack_f32(values)
    if dtype == "F16":
        return pack_f16(values)
    if dtype == "BF16":
        return pack_bf16(values)
    if dtype == "I8":
        return pack_i8(values)  # type: ignore[arg-type]
    if dtype == "U8":
        return pack_u8(values)  # type: ignore[arg-type]
    if dtype == "F8_E4M3":
        return pack_f8_e4m3(values)
    raise SafetensorsError(f"unsupported safetensors dtype: {dtype!r}")


def decode_tensor_floats(dtype: str, data: bytes | bytearray | memoryview) -> tuple[float, ...]:
    """Decode raw tensor bytes of any supported dtype into Python floats."""
    if dtype == "F32":
        return unpack_f32(data)
    if dtype == "F16":
        return unpack_f16(data)
    if dtype == "BF16":
        return unpack_bf16(data)
    if dtype == "I8":
        return tuple(float(v) for v in unpack_i8(data))
    if dtype == "U8":
        return tuple(float(v) for v in unpack_u8(data))
    if dtype == "F8_E4M3":
        return unpack_f8_e4m3(data)
    raise SafetensorsError(f"unsupported safetensors dtype: {dtype!r}")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, val in pairs:
        if key in out:
            raise SafetensorsError(f"duplicate JSON key in safetensors header: {key!r}")
        out[key] = val
    return out


def _reject_json_constant(token: str) -> object:
    raise SafetensorsError(f"invalid non-finite JSON constant in safetensors header: {token!r}")


def _parse_and_validate_header(
    root_view: memoryview,
    total_bytes: int,
    *,
    max_header_bytes: int = MAX_HEADER_BYTES,
    strict_contiguous: bool = True,
) -> tuple[int, dict[str, TensorInfo], dict[str, str]]:
    if total_bytes < 8:
        raise SafetensorsError(f"safetensors payload too small ({total_bytes} bytes < 8-byte length prefix)")
    header_len = struct.unpack_from("<Q", root_view, 0)[0]
    if header_len == 0:
        raise SafetensorsError("safetensors header_len must be positive")
    if header_len > max_header_bytes:
        raise SafetensorsError(f"safetensors header_len {header_len} exceeds limit {max_header_bytes}")
    data_start = 8 + header_len
    if data_start > total_bytes:
        raise SafetensorsError(
            f"safetensors header extends past EOF: 8 + {header_len} = {data_start} > {total_bytes}"
        )

    header_slice = root_view[8:data_start]
    try:
        header_text = bytes(header_slice).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SafetensorsError(f"safetensors header is not valid UTF-8: {exc}") from exc
    finally:
        header_slice.release()

    try:
        raw_header = json.loads(
            header_text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except SafetensorsError:
        raise
    except (ValueError, RecursionError) as exc:
        raise SafetensorsError(f"malformed safetensors JSON header: {exc}") from exc

    if type(raw_header) is not dict:
        raise SafetensorsError("safetensors JSON header root must be an object")

    metadata: dict[str, str] = {}
    if "__metadata__" in raw_header:
        raw_meta = raw_header["__metadata__"]
        if type(raw_meta) is not dict:
            raise SafetensorsError("__metadata__ must be a JSON object of string->string")
        for k, v in raw_meta.items():
            if type(k) is not str or type(v) is not str:
                raise SafetensorsError("__metadata__ keys and values must all be strings")
            metadata[k] = v

    payload_len = total_bytes - data_start
    infos: dict[str, TensorInfo] = {}
    intervals: list[tuple[int, int, str]] = []

    for name, entry in raw_header.items():
        if name == "__metadata__":
            continue
        if type(name) is not str or not name:
            raise SafetensorsError(f"tensor name must be a nonempty string, got {name!r}")
        if type(entry) is not dict:
            raise SafetensorsError(f"tensor {name!r} header entry must be a JSON object")
        expected_keys = {"dtype", "shape", "data_offsets"}
        if set(entry.keys()) != expected_keys:
            raise SafetensorsError(
                f"tensor {name!r} metadata keys {sorted(entry.keys())} must equal {sorted(expected_keys)}"
            )

        dtype = entry["dtype"]
        if type(dtype) is not str or dtype not in SUPPORTED_DTYPES:
            raise SafetensorsError(f"tensor {name!r} has unsupported dtype {dtype!r}")

        raw_shape = entry["shape"]
        if type(raw_shape) is not list:
            raise SafetensorsError(f"tensor {name!r} shape must be a JSON list")
        shape_list: list[int] = []
        for idx, dim in enumerate(raw_shape):
            if type(dim) is not int or dim < 0:
                raise SafetensorsError(
                    f"tensor {name!r} shape[{idx}] must be a non-negative integer, got {dim!r}"
                )
            shape_list.append(dim)
        shape = tuple(shape_list)
        numel = math.prod(shape)
        expected_nbytes = numel * DTYPE_SIZES[dtype]

        raw_offsets = entry["data_offsets"]
        if type(raw_offsets) is not list or len(raw_offsets) != 2:
            raise SafetensorsError(f"tensor {name!r} data_offsets must be a 2-element list")
        begin, end = raw_offsets[0], raw_offsets[1]
        if type(begin) is not int or type(end) is not int:
            raise SafetensorsError(f"tensor {name!r} data_offsets must contain exact integers")
        if begin < 0 or end < 0:
            raise SafetensorsError(f"tensor {name!r} has negative data_offsets {(begin, end)}")
        if begin > end:
            raise SafetensorsError(
                f"tensor {name!r} has non-monotonic data_offsets: begin ({begin}) > end ({end})"
            )
        if end > payload_len:
            raise SafetensorsError(
                f"tensor {name!r} data_offsets {(begin, end)} exceed payload length {payload_len}"
            )
        if (end - begin) != expected_nbytes:
            raise SafetensorsError(
                f"tensor {name!r} byte span {end - begin} != expected {expected_nbytes} "
                f"for dtype={dtype} shape={shape}"
            )

        info = TensorInfo(
            name=name,
            dtype=dtype,
            shape=shape,
            data_offsets=(begin, end),
            nbytes=expected_nbytes,
        )
        infos[name] = info
        intervals.append((begin, end, name))

    intervals.sort(key=lambda item: (item[0], item[1], item[2]))
    prev_end = 0
    for begin, end, name in intervals:
        if begin < prev_end:
            raise SafetensorsError(
                f"tensor {name!r} data_offsets {(begin, end)} overlap prior tensor ending at {prev_end}"
            )
        if strict_contiguous and begin != prev_end:
            raise SafetensorsError(
                f"tensor {name!r} data_offsets {(begin, end)} leave unreferenced gap from {prev_end}"
            )
        prev_end = end

    if strict_contiguous and prev_end != payload_len:
        raise SafetensorsError(
            f"safetensors payload has {payload_len - prev_end} trailing unreferenced bytes"
        )

    return data_start, infos, metadata


class SafetensorsFile:
    """Validated reader exposing zero-copy memoryview slices over .safetensors storage."""

    def __init__(
        self,
        *,
        backing: bytes | bytearray | memoryview | mmap.mmap,
        file_obj=None,
        mmap_obj: mmap.mmap | None = None,
        max_header_bytes: int = MAX_HEADER_BYTES,
        strict_contiguous: bool = True,
    ) -> None:
        self._file_obj = file_obj
        self._mmap_obj = mmap_obj
        self._closed = False
        self._exported_views: list[weakref.ref[memoryview]] = []
        self._root_view: memoryview | None = memoryview(backing)
        self._payload_view: memoryview | None = None
        try:
            total_bytes = self._root_view.nbytes
            data_start, infos, metadata = _parse_and_validate_header(
                self._root_view,
                total_bytes,
                max_header_bytes=max_header_bytes,
                strict_contiguous=strict_contiguous,
            )
            self._data_start = data_start
            self._infos = infos
            self._metadata = metadata
            self._payload_view = self._root_view[data_start:]
        except BaseException:
            self.close()
            raise

    def _ensure_open(self) -> None:
        if self._closed or self._payload_view is None:
            raise SafetensorsError("SafetensorsFile is closed")

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def data_offset(self) -> int:
        return self._data_start

    @property
    def metadata(self) -> dict[str, str]:
        return dict(self._metadata)

    @property
    def infos(self) -> dict[str, TensorInfo]:
        return dict(self._infos)

    def keys(self) -> tuple[str, ...]:
        return tuple(self._infos.keys())

    def __len__(self) -> int:
        return len(self._infos)

    def __contains__(self, name: object) -> bool:
        return name in self._infos

    def __iter__(self):
        return iter(self._infos)

    def info(self, name: str) -> TensorInfo:
        if name not in self._infos:
            raise KeyError(f"unknown tensor {name!r}")
        return self._infos[name]

    def tensor_view(self, name: str) -> memoryview:
        """Return a zero-copy read-only memoryview slice of tensor bytes."""
        self._ensure_open()
        info = self.info(name)
        begin, end = info.data_offsets
        assert self._payload_view is not None
        slice_view = self._payload_view[begin:end].toreadonly()
        try:
            self._exported_views.append(weakref.ref(slice_view))
        except TypeError:
            pass
        return slice_view

    def tensor_bytes(self, name: str) -> bytes:
        """Return an owned bytes copy of one tensor's payload."""
        view = self.tensor_view(name)
        try:
            return bytes(view)
        finally:
            view.release()

    def tensor_floats(self, name: str) -> tuple[float, ...]:
        """Decode one tensor's payload into Python floats."""
        info = self.info(name)
        view = self.tensor_view(name)
        try:
            return decode_tensor_floats(info.dtype, view)
        finally:
            view.release()

    def close(self) -> None:
        """Release internal views and close any owned mmap and file descriptors."""
        if self._closed:
            return
        self._closed = True
        for ref in self._exported_views:
            mv = ref()
            if mv is not None:
                try:
                    mv.release()
                except BufferError:
                    pass
        self._exported_views.clear()
        if self._payload_view is not None:
            try:
                self._payload_view.release()
            except BufferError:
                pass
            self._payload_view = None
        if self._root_view is not None:
            try:
                self._root_view.release()
            except BufferError:
                pass
            self._root_view = None
        if self._mmap_obj is not None:
            try:
                self._mmap_obj.close()
            finally:
                self._mmap_obj = None
        if self._file_obj is not None:
            try:
                self._file_obj.close()
            finally:
                self._file_obj = None

    def __enter__(self) -> SafetensorsFile:
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def open_safetensors(
    source: str | os.PathLike[str] | bytes | bytearray | memoryview,
    *,
    use_mmap: bool = True,
    max_header_bytes: int = MAX_HEADER_BYTES,
    strict_contiguous: bool = True,
) -> SafetensorsFile:
    """Open and strictly validate a .safetensors file or in-memory byte buffer."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        view = memoryview(source)
        if view.ndim != 1 or view.itemsize != 1 or not view.c_contiguous:
            view.release()
            raise SafetensorsError("source byte buffer must be contiguous 1-D bytes")
        view.release()
        return SafetensorsFile(
            backing=source,
            max_header_bytes=max_header_bytes,
            strict_contiguous=strict_contiguous,
        )

    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"safetensors file does not exist: {path}")
    size = path.stat().st_size
    if size < 8:
        raise SafetensorsError(f"safetensors file {path} too small ({size} bytes)")
    f = path.open("rb")
    try:
        if use_mmap:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            return SafetensorsFile(
                backing=mm,
                file_obj=f,
                mmap_obj=mm,
                max_header_bytes=max_header_bytes,
                strict_contiguous=strict_contiguous,
            )
        raw = f.read()
        f.close()
        return SafetensorsFile(
            backing=raw,
            max_header_bytes=max_header_bytes,
            strict_contiguous=strict_contiguous,
        )
    except BaseException:
        try:
            f.close()
        except OSError:
            pass
        raise


def load_safetensors(
    source: str | os.PathLike[str] | bytes | bytearray | memoryview,
    *,
    strict_contiguous: bool = True,
) -> tuple[dict[str, TensorData], dict[str, str]]:
    """Eagerly load and validate all tensors and metadata from a .safetensors source."""
    with open_safetensors(source, use_mmap=False, strict_contiguous=strict_contiguous) as sf:
        tensors = {
            name: TensorData(
                dtype=sf.info(name).dtype,
                shape=sf.info(name).shape,
                data=sf.tensor_bytes(name),
            )
            for name in sf.keys()
        }
        return tensors, sf.metadata


def _coerce_tensor_entry(name: str, value: object) -> TensorData:
    if name == "__metadata__":
        raise SafetensorsError("tensor name '__metadata__' is reserved")
    if type(name) is not str or not name:
        raise SafetensorsError(f"tensor name must be a nonempty string, got {name!r}")
    if isinstance(value, TensorData):
        return value
    if isinstance(value, Mapping):
        if not {"dtype", "shape", "data"}.issubset(value.keys()):
            raise SafetensorsError(f"tensor {name!r} mapping requires 'dtype', 'shape', and 'data'")
        return TensorData(dtype=value["dtype"], shape=tuple(value["shape"]), data=value["data"])
    if isinstance(value, tuple) and len(value) == 3:
        return TensorData(dtype=value[0], shape=tuple(value[1]), data=value[2])
    raise SafetensorsError(
        f"tensor {name!r} must be TensorData, {{'dtype','shape','data'}}, or (dtype, shape, data)"
    )


def serialize_safetensors(
    tensors: Mapping[str, TensorData | Mapping[str, object] | tuple[str, Sequence[int], bytes]],
    metadata: Mapping[str, str] | None = None,
    *,
    align_header: int = 8,
) -> bytes:
    """Deterministically serialize tensors (sorted by key) into .safetensors binary bytes."""
    if not isinstance(tensors, Mapping):
        raise SafetensorsError("tensors must be a mapping of name -> tensor entry")
    if type(align_header) is not int or align_header < 1:
        raise ValueError("align_header must be a positive int")

    checked_meta: dict[str, str] | None = None
    if metadata is not None:
        if not isinstance(metadata, Mapping):
            raise SafetensorsError("metadata must be a mapping of str -> str")
        checked_meta = {}
        for k in sorted(metadata.keys()):
            v = metadata[k]
            if type(k) is not str or type(v) is not str:
                raise SafetensorsError("metadata keys and values must all be exact strings")
            checked_meta[k] = v

    sorted_names = sorted(tensors.keys())
    header_obj: dict[str, object] = {}
    if checked_meta is not None:
        header_obj["__metadata__"] = checked_meta

    chunks: list[bytes] = []
    offset = 0
    for name in sorted_names:
        entry = _coerce_tensor_entry(name, tensors[name])
        raw = bytes(entry.data) if not isinstance(entry.data, bytes) else entry.data
        end = offset + len(raw)
        header_obj[name] = {
            "dtype": entry.dtype,
            "shape": list(entry.shape),
            "data_offsets": [offset, end],
        }
        chunks.append(raw)
        offset = end

    header_json = json.dumps(
        header_obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    rem = (8 + len(header_json)) % align_header
    if rem != 0:
        header_json += b" " * (align_header - rem)

    if len(header_json) > MAX_HEADER_BYTES:
        raise SafetensorsError(f"serialized header exceeds {MAX_HEADER_BYTES} bytes")

    prefix = struct.pack("<Q", len(header_json))
    return b"".join([prefix, header_json, *chunks])


def write_safetensors(
    path: str | os.PathLike[str],
    tensors: Mapping[str, TensorData | Mapping[str, object] | tuple[str, Sequence[int], bytes]],
    metadata: Mapping[str, str] | None = None,
    *,
    align_header: int = 8,
) -> Path:
    """Write a deterministic .safetensors checkpoint atomically to disk."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    blob = serialize_safetensors(tensors, metadata=metadata, align_header=align_header)
    target.write_bytes(blob)
    return target


def _splitmix64_next(state: int) -> tuple[int, int]:
    state = (state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    z = z ^ (z >> 31)
    return state, z


def _deterministic_floats(seed: int, count: int, *, scale: float, offset: float = 0.0) -> list[float]:
    state = seed & 0xFFFFFFFFFFFFFFFF
    out: list[float] = []
    for _ in range(count):
        state, z = _splitmix64_next(state)
        u = math.ldexp(float(z >> 40), -24) * 2.0 - 1.0
        out.append(offset + u * scale)
    return out


def make_deterministic_micro_llama_safetensors(
    path: str | os.PathLike[str],
    *,
    layers: int = 2,
    d_model: int = 16,
    n_heads: int = 2,
    n_kv_heads: int = 2,
    d_ff: int = 16,
    vocab_size: int = 32,
    rms_norm_eps: float = 1e-5,
    seed: int = 0x4C4C414D413032,
) -> Path:
    """Generate a reproducible 2-layer Llama micro-checkpoint in real .safetensors format."""
    if layers < 1 or d_model < 1 or n_heads < 1 or n_kv_heads < 1 or d_ff < 1 or vocab_size < 1:
        raise ValueError("all micro-Llama dimensions must be positive")
    if d_model % n_heads != 0:
        raise ValueError("d_model must be divisible by n_heads")
    if n_heads % n_kv_heads != 0:
        raise ValueError("n_heads must be divisible by n_kv_heads")
    d_head = d_model // n_heads
    kv_dim = n_kv_heads * d_head

    tensors: dict[str, TensorData] = {}
    stream_seed = seed

    def next_tensor(name: str, shape: tuple[int, ...], dtype: str, *, scale: float, offset: float = 0.0) -> None:
        nonlocal stream_seed
        stream_seed = (stream_seed + 1) & 0xFFFFFFFFFFFFFFFF
        vals = _deterministic_floats(stream_seed, math.prod(shape), scale=scale, offset=offset)
        tensors[name] = TensorData(dtype=dtype, shape=shape, data=encode_tensor_bytes(dtype, vals))

    next_tensor("model.embed_tokens.weight", (vocab_size, d_model), "F16", scale=0.25)
    for layer_idx in range(layers):
        prefix = f"model.layers.{layer_idx}"
        next_tensor(f"{prefix}.input_layernorm.weight", (d_model,), "F32", scale=0.25, offset=0.75)
        next_tensor(f"{prefix}.self_attn.q_proj.weight", (d_model, d_model), "F16", scale=0.1875)
        next_tensor(f"{prefix}.self_attn.k_proj.weight", (kv_dim, d_model), "F16", scale=0.1875)
        next_tensor(f"{prefix}.self_attn.v_proj.weight", (kv_dim, d_model), "F16", scale=0.1875)
        next_tensor(f"{prefix}.self_attn.o_proj.weight", (d_model, d_model), "F16", scale=0.1875)
        next_tensor(f"{prefix}.post_attention_layernorm.weight", (d_model,), "F32", scale=0.25, offset=0.75)
        next_tensor(f"{prefix}.mlp.gate_proj.weight", (d_ff, d_model), "F16", scale=0.1875)
        next_tensor(f"{prefix}.mlp.up_proj.weight", (d_ff, d_model), "F16", scale=0.1875)
        next_tensor(f"{prefix}.mlp.down_proj.weight", (d_model, d_ff), "F16", scale=0.1875)
    next_tensor("model.norm.weight", (d_model,), "F32", scale=0.25, offset=0.75)
    next_tensor("lm_head.weight", (vocab_size, d_model), "F16", scale=0.1875)

    meta = {
        "architecture": "llama_micro",
        "format": "pt",
        "num_hidden_layers": str(layers),
        "hidden_size": str(d_model),
        "num_attention_heads": str(n_heads),
        "num_key_value_heads": str(n_kv_heads),
        "intermediate_size": str(d_ff),
        "vocab_size": str(vocab_size),
        "rms_norm_eps": str(rms_norm_eps),
        "seed": hex(seed),
    }
    return write_safetensors(path, tensors, metadata=meta)


__all__ = (
    "DTYPE_SIZES",
    "MAX_HEADER_BYTES",
    "SUPPORTED_DTYPES",
    "SafetensorsError",
    "SafetensorsFile",
    "TensorData",
    "TensorInfo",
    "decode_tensor_floats",
    "encode_tensor_bytes",
    "load_safetensors",
    "make_deterministic_micro_llama_safetensors",
    "open_safetensors",
    "pack_bf16",
    "pack_f16",
    "pack_f32",
    "pack_f8_e4m3",
    "pack_i8",
    "pack_u8",
    "serialize_safetensors",
    "unpack_bf16",
    "unpack_f16",
    "unpack_f32",
    "unpack_f8_e4m3",
    "unpack_i8",
    "unpack_u8",
    "write_safetensors",
)
