# SPDX-License-Identifier: Apache-2.0
"""Separate original compiler/linker record checks for the workspace caller.

The existing P02, P03 and cold P06 contracts are not rewritten or relaxed. Each
original compiler line passes the trusted P02 validator independently, followed
by this caller's narrower option, include-path and instrumentation checks.
"""

from collections import Counter
from pathlib import Path

from baseline_packet_contract import _stamp_defines, _stamp_words
from compiler_records import _records, _syntax
from p02_matrix_records import _record, require
from p06_compiler_records import COMMON_OPTIONS, _options


MAX_RECORD_BYTES = 1024 * 1024
WRAP_FLAGS = (
    "-Wl,--wrap=vx_buffer_create", "-Wl,--wrap=vx_buffer_release",
    "-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release",
)


# Complete resolved RV64 p02-tfr configuration at the frozen workspace baseline
# 3235cd59d724663dda1bece20645d5ccf30462e1. Derived independently from the union
# of ci/gen_config.py --config=VX_config.toml --profile=p02-tfr --xlen=64
# --cflags=-DVX_CFG_XLEN=64 with --merge-configs and with --format=cflags.
# The union retains the profile's explicit *_DISABLE selectors, which resolved
# flags alone omit. This is an explicit contract, not a record-derived oracle:
# unknown names, added selectors and changed derived values must fail closed.
# Input SHA-256:
# VX_config.toml: a1c49de52a0373b5f74706528d46bea1181c54f7769dd03994e033c7ddd710bf
# profiles/p02-tfr.json: 79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102
# ci/gen_config.py: b710a1b80c89d327adf079e61aec9f5d4f950d89342b633b6b00871e50abe165
_EXPANDED_CONFIGURATION = {
    "VX_CFG_AMO_RS_SIZE": "4",
    "VX_CFG_CP_LLC_CLIENT": "1",
    "VX_CFG_CP_ON_LLC": "0",
    "VX_CFG_CTLB_SIZE": "8",
    "VX_CFG_DCACHE_BANK_HASH": "0",
    "VX_CFG_DCACHE_CRSQ_SIZE": "0",
    "VX_CFG_DCACHE_DIRTYBYTES": "1",
    "VX_CFG_DCACHE_ENABLE": "1",
    "VX_CFG_DCACHE_ENABLED": "1",
    "VX_CFG_DCACHE_LATENCY": "2",
    "VX_CFG_DCACHE_LAZY_FETCH": "1",
    "VX_CFG_DCACHE_LINE_SIZE": "64",
    "VX_CFG_DCACHE_MREQ_SIZE": "0",
    "VX_CFG_DCACHE_MRSQ_SIZE": "4",
    "VX_CFG_DCACHE_MSHR_SIZE": "16",
    "VX_CFG_DCACHE_NUM_BANKS": "1",
    "VX_CFG_DCACHE_NUM_WAYS": "4",
    "VX_CFG_DCACHE_READ_MERGE": "1",
    "VX_CFG_DCACHE_REPL_POLICY": "1",
    "VX_CFG_DCACHE_SECTOR_SIZE": "64",
    "VX_CFG_DCACHE_SET_HASH": "1",
    "VX_CFG_DCACHE_SIZE": "16384",
    "VX_CFG_DCACHE_WORD_SIZE": "16",
    "VX_CFG_DCACHE_WRITEBACK": "1",
    "VX_CFG_DISPATCH_QUEUE_SIZE": "4",
    "VX_CFG_DTLB_SIZE": "16",
    "VX_CFG_DXA_MAX_INFLIGHT": "8",
    "VX_CFG_DXA_MEM_PORTS": "1",
    "VX_CFG_DXA_QUEUE_SIZE": "16",
    "VX_CFG_EXT_A_ENABLED": "0",
    "VX_CFG_EXT_C_ENABLED": "0",
    "VX_CFG_EXT_DMA_ENABLED": "0",
    "VX_CFG_EXT_DXA_ENABLED": "0",
    "VX_CFG_EXT_D_ENABLE": "1",
    "VX_CFG_EXT_D_ENABLED": "1",
    "VX_CFG_EXT_F_ENABLE": "1",
    "VX_CFG_EXT_F_ENABLED": "1",
    "VX_CFG_EXT_LDST_MATRIX_DISABLE": "1",
    "VX_CFG_EXT_LDST_MATRIX_ENABLED": "0",
    "VX_CFG_EXT_LDST_WIDE_ENABLED": "0",
    "VX_CFG_EXT_MUFU_ENABLED": "0",
    "VX_CFG_EXT_M_ENABLE": "1",
    "VX_CFG_EXT_M_ENABLED": "1",
    "VX_CFG_EXT_OM_ENABLED": "0",
    "VX_CFG_EXT_RASTER_ENABLED": "0",
    "VX_CFG_EXT_RTU_ENABLED": "0",
    "VX_CFG_EXT_TCU_ENABLE": "1",
    "VX_CFG_EXT_TCU_ENABLED": "1",
    "VX_CFG_EXT_TEX_ENABLED": "0",
    "VX_CFG_EXT_ZACAS_ENABLED": "0",
    "VX_CFG_EXT_ZFHMIN_ENABLED": "0",
    "VX_CFG_EXT_ZICOND_ENABLE": "1",
    "VX_CFG_EXT_ZICOND_ENABLED": "1",
    "VX_CFG_FCVT_LATENCY": "5",
    "VX_CFG_FCVT_PE_RATIO": "1",
    "VX_CFG_FDIV_LATENCY": "32",
    "VX_CFG_FDIV_PE_RATIO": "1",
    "VX_CFG_FETCH_WIDTH": "1",
    "VX_CFG_FLEN": "64",
    "VX_CFG_FLEN_64": "1",
    "VX_CFG_FMA64_PE_RATIO": "1",
    "VX_CFG_FMA_LATENCY": "12",
    "VX_CFG_FMA_PE_RATIO": "1",
    "VX_CFG_FNCP_LATENCY": "2",
    "VX_CFG_FNCP_PE_RATIO": "1",
    "VX_CFG_FPU_QUEUE_SIZE": "2",
    "VX_CFG_FPU_TYPE": "STD",
    "VX_CFG_FPU_TYPE_STD": "1",
    "VX_CFG_FPU_USE_DSP": "0",
    "VX_CFG_FSQRT_LATENCY": "32",
    "VX_CFG_FSQRT_PE_RATIO": "1",
    "VX_CFG_IBUF_SIZE": "4",
    "VX_CFG_ICACHE_CRSQ_SIZE": "0",
    "VX_CFG_ICACHE_ENABLE": "1",
    "VX_CFG_ICACHE_ENABLED": "1",
    "VX_CFG_ICACHE_LATENCY": "2",
    "VX_CFG_ICACHE_MEM_PORTS": "1",
    "VX_CFG_ICACHE_MREQ_SIZE": "0",
    "VX_CFG_ICACHE_MRSQ_SIZE": "0",
    "VX_CFG_ICACHE_MSHR_SIZE": "16",
    "VX_CFG_ICACHE_NUM_BANKS": "1",
    "VX_CFG_ICACHE_NUM_WAYS": "4",
    "VX_CFG_ICACHE_READ_MERGE": "1",
    "VX_CFG_ICACHE_REPL_POLICY": "1",
    "VX_CFG_ICACHE_SIZE": "16384",
    "VX_CFG_ISSUE_WIDTH": "1",
    "VX_CFG_ITLB_SIZE": "8",
    "VX_CFG_L1_LINE_SIZE": "64",
    "VX_CFG_L1_LINK_LATENCY": "0",
    "VX_CFG_L1_MEM_PORTS": "1",
    "VX_CFG_L1_TLB_MSHR_SIZE": "4",
    "VX_CFG_L2_BANK_HASH": "1",
    "VX_CFG_L2_CRSQ_SIZE": "0",
    "VX_CFG_L2_DIRTYBYTES": "0",
    "VX_CFG_L2_ENABLED": "0",
    "VX_CFG_L2_LATENCY": "4",
    "VX_CFG_L2_LAZY_FETCH": "0",
    "VX_CFG_L2_LINE_SIZE": "64",
    "VX_CFG_L2_LINK_LATENCY": "0",
    "VX_CFG_L2_MEM_PORTS": "0",
    "VX_CFG_L2_MREQ_SIZE": "0",
    "VX_CFG_L2_MRSQ_SIZE": "4",
    "VX_CFG_L2_MSHR_SIZE": "16",
    "VX_CFG_L2_NUM_BANKS": "1",
    "VX_CFG_L2_NUM_WAYS": "8",
    "VX_CFG_L2_REPL_POLICY": "1",
    "VX_CFG_L2_SECTOR_SIZE": "64",
    "VX_CFG_L2_SIZE": "1048576",
    "VX_CFG_L2_TLB_LATENCY": "4",
    "VX_CFG_L2_TLB_MEGA_SIZE": "8",
    "VX_CFG_L2_TLB_MSHR_SIZE": "8",
    "VX_CFG_L2_TLB_NUM_WAYS": "4",
    "VX_CFG_L2_TLB_SIZE": "512",
    "VX_CFG_L2_WRITEBACK": "0",
    "VX_CFG_L3_CRSQ_SIZE": "0",
    "VX_CFG_L3_DIRTYBYTES": "0",
    "VX_CFG_L3_ENABLED": "0",
    "VX_CFG_L3_LATENCY": "4",
    "VX_CFG_L3_LAZY_FETCH": "0",
    "VX_CFG_L3_LINE_SIZE": "64",
    "VX_CFG_L3_MEM_PORTS": "0",
    "VX_CFG_L3_MREQ_SIZE": "0",
    "VX_CFG_L3_MRSQ_SIZE": "4",
    "VX_CFG_L3_MSHR_SIZE": "16",
    "VX_CFG_L3_NUM_BANKS": "1",
    "VX_CFG_L3_NUM_WAYS": "8",
    "VX_CFG_L3_REPL_POLICY": "1",
    "VX_CFG_L3_SECTOR_SIZE": "64",
    "VX_CFG_L3_SIZE": "2097152",
    "VX_CFG_L3_WRITEBACK": "0",
    "VX_CFG_LMEM_ENABLE": "1",
    "VX_CFG_LMEM_ENABLED": "1",
    "VX_CFG_LMEM_LOG_SIZE": "14",
    "VX_CFG_LMEM_NUM_BANKS": "4",
    "VX_CFG_LMEM_SIZE": "16384",
    "VX_CFG_LSU_LINE_SIZE": "32",
    "VX_CFG_LSU_PENDING_LIMIT": "32",
    "VX_CFG_LSU_PENDING_SIZE": "8",
    "VX_CFG_LSU_QUEUE_IN_SIZE": "4",
    "VX_CFG_LSU_STACK_INTERLEAVE_ENABLE": "1",
    "VX_CFG_LSU_STACK_INTERLEAVE_ENABLED": "1",
    "VX_CFG_MAX_BAR_EVENTS": "32",
    "VX_CFG_MEM_ADDR_WIDTH": "48",
    "VX_CFG_MEM_BLOCK_SIZE": "64",
    "VX_CFG_MISA_EXT": "563",
    "VX_CFG_MISA_STD": "9441576",
    "VX_CFG_NUM_ALU_BLOCKS": "1",
    "VX_CFG_NUM_ALU_LANES": "4",
    "VX_CFG_NUM_BARRIERS": "8",
    "VX_CFG_NUM_CLUSTERS": "1",
    "VX_CFG_NUM_CORES": "1",
    "VX_CFG_NUM_DCACHES": "1",
    "VX_CFG_NUM_DXA_CORES": "1",
    "VX_CFG_NUM_FPU_BLOCKS": "1",
    "VX_CFG_NUM_FPU_LANES": "4",
    "VX_CFG_NUM_GPR_BANKS": "4",
    "VX_CFG_NUM_ICACHES": "1",
    "VX_CFG_NUM_LSU_BLOCKS": "1",
    "VX_CFG_NUM_LSU_LANES": "4",
    "VX_CFG_NUM_MUFU_LANES": "1",
    "VX_CFG_NUM_OCACHES": "1",
    "VX_CFG_NUM_OM_CORES": "1",
    "VX_CFG_NUM_OPCS": "1",
    "VX_CFG_NUM_RASTER_CORES": "1",
    "VX_CFG_NUM_RCACHES": "1",
    "VX_CFG_NUM_RTCACHES": "1",
    "VX_CFG_NUM_RTU_BLOCKS": "2",
    "VX_CFG_NUM_RTU_CORES": "1",
    "VX_CFG_NUM_SFU_BLOCKS": "1",
    "VX_CFG_NUM_SFU_LANES": "4",
    "VX_CFG_NUM_TCACHES": "1",
    "VX_CFG_NUM_TCU_BLOCKS": "1",
    "VX_CFG_NUM_TCU_LANES": "4",
    "VX_CFG_NUM_TEX_CORES": "1",
    "VX_CFG_NUM_THREADS": "4",
    "VX_CFG_NUM_VGPR_BANKS": "2",
    "VX_CFG_NUM_VPU_BLOCKS": "1",
    "VX_CFG_NUM_VPU_LANES": "4",
    "VX_CFG_NUM_WARPS": "4",
    "VX_CFG_OCACHE_CRSQ_SIZE": "0",
    "VX_CFG_OCACHE_MREQ_SIZE": "0",
    "VX_CFG_OCACHE_MRSQ_SIZE": "0",
    "VX_CFG_OCACHE_MSHR_SIZE": "16",
    "VX_CFG_OCACHE_NUM_BANKS": "1",
    "VX_CFG_OCACHE_NUM_WAYS": "2",
    "VX_CFG_OCACHE_SIZE": "16384",
    "VX_CFG_OM_MEM_QUEUE_SIZE": "4",
    "VX_CFG_PLATFORM_CLOCK_RATE": "400",
    "VX_CFG_PLATFORM_MEMORY_ADDR_WIDTH": "48",
    "VX_CFG_PLATFORM_MEMORY_DATA_RATE": "800",
    "VX_CFG_PLATFORM_MEMORY_DATA_SIZE": "64",
    "VX_CFG_PLATFORM_MEMORY_INTERLEAVE": "1",
    "VX_CFG_PLATFORM_MEMORY_LATENCY": "0",
    "VX_CFG_PLATFORM_MEMORY_NUM_BANKS": "2",
    "VX_CFG_PLATFORM_MEMORY_PEAK_BW": "460000",
    "VX_CFG_PLATFORM_MEMORY_QUEUE_SIZE": "0",
    "VX_CFG_PLATFORM_MEMORY_TYPE": "HBM2",
    "VX_CFG_PLATFORM_MEMORY_TYPE_HBM2": "1",
    "VX_CFG_PTW_NUM_WALKERS": "2",
    "VX_CFG_PTW_WALK_CACHE_SIZE": "16",
    "VX_CFG_RASTER_BIN_LOG_SIZE": "7",
    "VX_CFG_RASTER_BLOCK_LOG_SIZE": "2",
    "VX_CFG_RASTER_EARLYZ_ENABLED": "0",
    "VX_CFG_RASTER_MEM_FIFO_DEPTH": "8",
    "VX_CFG_RASTER_MEM_QUEUE_SIZE": "4",
    "VX_CFG_RASTER_NUM_SLICES": "1",
    "VX_CFG_RASTER_QUAD_FIFO_DEPTH": "32",
    "VX_CFG_RASTER_TILE_LOG_SIZE": "5",
    "VX_CFG_RCACHE_CRSQ_SIZE": "0",
    "VX_CFG_RCACHE_MREQ_SIZE": "0",
    "VX_CFG_RCACHE_MRSQ_SIZE": "0",
    "VX_CFG_RCACHE_MSHR_SIZE": "16",
    "VX_CFG_RCACHE_NUM_BANKS": "1",
    "VX_CFG_RCACHE_NUM_WAYS": "2",
    "VX_CFG_RCACHE_SIZE": "4096",
    "VX_CFG_RESET_DELAY": "8",
    "VX_CFG_RTCACHE_CRSQ_SIZE": "2",
    "VX_CFG_RTCACHE_MREQ_SIZE": "4",
    "VX_CFG_RTCACHE_MRSQ_SIZE": "0",
    "VX_CFG_RTCACHE_MSHR_SIZE": "16",
    "VX_CFG_RTCACHE_NUM_BANKS": "1",
    "VX_CFG_RTCACHE_NUM_WAYS": "2",
    "VX_CFG_RTCACHE_SIZE": "8192",
    "VX_CFG_RTU_BVH_WIDTH": "4",
    "VX_CFG_RTU_FDIV_LATENCY": "17",
    "VX_CFG_RTU_MERGE_DEPTH": "0",
    "VX_CFG_RTU_NUM_CTX": "4",
    "VX_CFG_RTU_NUM_SLOTS": "1",
    "VX_CFG_RTU_RECIP_DSP_SEED": "0",
    "VX_CFG_RTU_STACK_DEPTH": "16",
    "VX_CFG_RTU_TLAS_ENABLED": "0",
    "VX_CFG_RTU_USE_DSP": "0",
    "VX_CFG_SIMD_WIDTH": "4",
    "VX_CFG_SOCKET_SIZE": "1",
    "VX_CFG_TCACHE_CRSQ_SIZE": "0",
    "VX_CFG_TCACHE_MREQ_SIZE": "0",
    "VX_CFG_TCACHE_MRSQ_SIZE": "0",
    "VX_CFG_TCACHE_MSHR_SIZE": "16",
    "VX_CFG_TCACHE_NUM_BANKS": "1",
    "VX_CFG_TCACHE_NUM_WAYS": "2",
    "VX_CFG_TCACHE_SIZE": "8192",
    "VX_CFG_TCU_DSM_DISABLE": "1",
    "VX_CFG_TCU_DSM_ENABLED": "0",
    "VX_CFG_TCU_FP16_ENABLE": "1",
    "VX_CFG_TCU_FP16_ENABLED": "1",
    "VX_CFG_TCU_FP4_DISABLE": "1",
    "VX_CFG_TCU_FP4_ENABLED": "0",
    "VX_CFG_TCU_FP8_DISABLE": "1",
    "VX_CFG_TCU_FP8_ENABLED": "0",
    "VX_CFG_TCU_INT4_DISABLE": "1",
    "VX_CFG_TCU_INT4_ENABLED": "0",
    "VX_CFG_TCU_INT8_DISABLE": "1",
    "VX_CFG_TCU_INT8_ENABLED": "0",
    "VX_CFG_TCU_LATENCY": "4",
    "VX_CFG_TCU_MXFP4_DISABLE": "1",
    "VX_CFG_TCU_MXFP4_ENABLED": "0",
    "VX_CFG_TCU_MX_DISABLE": "1",
    "VX_CFG_TCU_MX_ENABLED": "0",
    "VX_CFG_TCU_NVFP4_DISABLE": "1",
    "VX_CFG_TCU_NVFP4_ENABLED": "0",
    "VX_CFG_TCU_PE_RATIO": "1",
    "VX_CFG_TCU_SPARSE_DISABLE": "1",
    "VX_CFG_TCU_SPARSE_ENABLED": "0",
    "VX_CFG_TCU_TF32_DISABLE": "1",
    "VX_CFG_TCU_TF32_ENABLED": "0",
    "VX_CFG_TCU_TYPE": "TFR",
    "VX_CFG_TCU_TYPE_TFR": "1",
    "VX_CFG_TCU_USE_DSP": "0",
    "VX_CFG_TCU_WGMMA_DISABLE": "1",
    "VX_CFG_TCU_WGMMA_ENABLED": "0",
    "VX_CFG_TEX_MEM_QUEUE_SIZE": "8",
    "VX_CFG_TEX_REQ_QUEUE_SIZE": "8",
    "VX_CFG_TLB_SIZE": "32",
    "VX_CFG_UTLB_SIZE": "8",
    "VX_CFG_VLEN": "256",
    "VX_CFG_VM_ENABLED": "0",
    "VX_CFG_VM_PINNED_REGION_SIZE": "0x10000000",
    "VX_CFG_XLEN": "64",
    "VX_CFG_XLEN_64": "1",
}

# The backend Makefiles deliberately record raw profile overrides instead of
# the expanded defaults. SimX and Verilator append the two arithmetic selectors;
# the RTL C++ shim does not select RTL arithmetic and records neither selector.
_RAW_CONFIGURATION = {
    "VX_CFG_EXT_LDST_MATRIX_DISABLE": "1",
    "VX_CFG_EXT_TCU_ENABLE": "1",
    "VX_CFG_FPU_TYPE": "STD",
    "VX_CFG_ISSUE_WIDTH": "1",
    "VX_CFG_LMEM_ENABLE": "1",
    "VX_CFG_NUM_ALU_BLOCKS": "1",
    "VX_CFG_NUM_CLUSTERS": "1",
    "VX_CFG_NUM_CORES": "1",
    "VX_CFG_NUM_FPU_BLOCKS": "1",
    "VX_CFG_NUM_LSU_BLOCKS": "1",
    "VX_CFG_NUM_THREADS": "4",
    "VX_CFG_NUM_WARPS": "4",
    "VX_CFG_TCU_DSM_DISABLE": "1",
    "VX_CFG_TCU_FP16_ENABLE": "1",
    "VX_CFG_TCU_FP4_DISABLE": "1",
    "VX_CFG_TCU_FP8_DISABLE": "1",
    "VX_CFG_TCU_INT4_DISABLE": "1",
    "VX_CFG_TCU_INT8_DISABLE": "1",
    "VX_CFG_TCU_LATENCY": "4",
    "VX_CFG_TCU_MXFP4_DISABLE": "1",
    "VX_CFG_TCU_MX_DISABLE": "1",
    "VX_CFG_TCU_NVFP4_DISABLE": "1",
    "VX_CFG_TCU_PE_RATIO": "1",
    "VX_CFG_TCU_SPARSE_DISABLE": "1",
    "VX_CFG_TCU_TF32_DISABLE": "1",
    "VX_CFG_TCU_TYPE": "TFR",
    "VX_CFG_TCU_USE_DSP": "0",
    "VX_CFG_TCU_WGMMA_DISABLE": "1",
    "VX_CFG_XLEN": "64",
    "VX_CFG_XLEN_64": "1",
}

_ARITHMETIC_SELECTORS = {"VX_CFG_FPU_TYPE_STD": "1", "VX_CFG_TCU_TYPE_TFR": "1"}


def _bounded_records(text, label):
    require(type(text) is str, label + " must be compiler-record text")
    try:
        size = len(text.encode("utf-8", errors="strict"))
    except UnicodeError as error:
        raise ValueError(label + " contains invalid Unicode") from error
    require(size <= MAX_RECORD_BYTES, label + " exceeds its byte limit")
    return _records(text, label)


def _extra_configuration(text, label, *, role, driver, fmt):
    """Match the complete original macro map for this specific compiler role.

    No defaults are filled in from the submitted record or another compiler
    role. Raw records must retain their smaller original map; expanded records
    must carry every resolved value, including disabled-feature mirrors.
    """
    defines = _stamp_defines(text, label)
    expanded = role in ("runtime", "kernel", "host")
    expected = dict(_EXPANDED_CONFIGURATION if expanded else _RAW_CONFIGURATION)
    if not expanded and not (driver == "rtlsim" and role == "backend_cpp"):
        expected.update(_ARITHMETIC_SELECTORS)
    expected.update(VX_PROFILE="p02-tfr", ITYPE=fmt, OTYPE="fp32", KUNROLL="1", NDEBUG="1")
    if expanded:
        expected.update(VX_DBG_STALL_TIMEOUT="100000", VX_DBG_DEBUG_LEVEL="3")
    if role == "kernel":
        expected["__VORTEX__"] = "1"
    if role == "host":
        expected.update(OMPI_SKIP_MPICXX="1", MPICH_SKIP_MPICXX="1")
    if driver == "rtlsim" and role in ("verilator", "backend_cpp"):
        expected.update(SIMULATION="1", SV_DPI="1")
    missing = sorted(expected.keys() - defines.keys())
    extra = sorted(defines.keys() - expected.keys())
    conflicting = sorted(name for name in expected.keys() & defines.keys()
                         if expected[name] != defines[name])
    require(not (missing or extra or conflicting),
            label + " differs from its frozen role macro contract"
            + "; missing=" + repr(missing) + "; extra=" + repr(extra)
            + "; conflicting=" + repr(conflicting))


def _rtl_includes(source, build, role):
    if role == "runtime":
        return [source / "sw/runtime/include", build / "sw", build / "hw",
                source / "sim/rtlsim", source / "sim/common", source / "sw/common",
                source / "sw/runtime/common"]
    if role == "backend_cpp":
        return [build / "sw", build / "hw", source / "sim/common", source / "sw/common",
                source / "third_party/softfloat/source/include",
                source / "third_party/ramulator/ext/spdlog/include",
                source / "third_party/ramulator/ext/yaml-cpp/include",
                source / "third_party/ramulator/src"]
    return [build / "sw", build / "hw", source / "sim/rtlsim", source / "hw/rtl",
            source / "hw/dpi", *(source / "hw/rtl" / name for name in
                                 ("libs", "interfaces", "core", "mem", "vm", "cache",
                                  "fpu", "tcu", "tcu/tfr"))]


def _rtl_options(words, label, *, role, source, build, jobs):
    """Additional exact options/includes after the shared compiler syntax check."""
    selected, includes = [], []

    def scan(arguments, *, forwarded=False):
        pending = iter(arguments)
        preprocessor = []

        def operand():
            value = next(pending, None)
            require(value is not None, label + " has an option without an operand")
            return value

        for word in pending:
            option, separator, _ = word.partition("=")
            if word.startswith(("-D", "-U")):
                if len(word) == 2:
                    operand()
            elif option in ("--define-macro", "--undefine-macro"):
                if not separator:
                    operand()
            elif not forwarded and word.startswith("-Wp,"):
                preprocessor.extend(word[4:].split(","))
            elif not forwarded and word == "-Xpreprocessor":
                preprocessor.append(operand())
            elif not forwarded and word.startswith("-I"):
                includes.append(operand() if word == "-I" else word[2:])
            else:
                require(not forwarded, label + " forwards a non-macro option")
                selected.append(word)
        if preprocessor:
            scan(preprocessor, forwarded=True)

    scan(words)
    require(includes == [str(path) for path in _rtl_includes(source, build, role)],
            label + " changes the frozen include search order")
    if role == "verilator":
        expected = [
            "--exe", "--language", "1800-2012", "--assert", "-Wall", "-Wpedantic",
            "-Wno-DECLFILENAME", "-Wno-REDEFMACRO", "--replication-limit", "65536",
            "--x-initial", "unique", "--x-assign", "unique", "verilator.vlt",
            *(str(source / "hw/rtl" / name) for name in
              ("VX_gpu_pkg.sv", "fpu/VX_fpu_pkg.sv", "tcu/VX_tcu_pkg.sv", "VX_trace_pkg.sv")),
            "--cc", "rtlsim_shim", "--top-module", "rtlsim_shim", "-j", str(jobs),
            "-MAKEFLAGS", "OPT_FAST=-O2", "-MAKEFLAGS", "OPT_GLOBAL=-O2",
        ]
        require(selected == expected, label + " differs from the frozen processor Verilator options")
    else:
        expected = COMMON_OPTIONS | {"-std=c++17", "-fPIC"}
        expected |= {"-pedantic", "-O2"} if role == "runtime" else {"-fno-tree-loop-distribute-patterns"}
        require(Counter(selected) == Counter(expected),
                label + " has missing, repeated or changed C++ options")
    return includes


def validate_records(runtime, backend, application, *, driver, fmt, source, build, jobs):
    """Return independent original compiler roles after checking the exact link.

    Linker records are checked but are not compiler roles and are never expanded
    into compile flags. The returned hashes cover unchanged original lines.
    """
    require(type(driver) is str and driver in ("simx", "rtlsim"), "unsupported workspace backend")
    require(type(fmt) is str and fmt in ("fp16", "bf16"), "unsupported workspace format")
    require(type(jobs) is int and jobs in (1, 2), "unsupported workspace job budget")
    source, build = Path(source), Path(build)
    require(source.is_absolute() and build.is_absolute()
            and ".." not in source.parts and ".." not in build.parts,
            "workspace compiler bindings require absolute source and build paths")
    runtime_lines = _bounded_records(runtime, "workspace runtime stamp")
    backend_lines = _bounded_records(backend, "workspace backend stamp")
    application_lines = _bounded_records(application, "workspace application stamp")
    roles = ("verilator", "backend_cpp") if driver == "rtlsim" else ("backend_cpp",)
    require(len(runtime_lines) == 1 and len(backend_lines) == len(roles)
            and len(application_lines) == 3,
            "workspace requires separate runtime, backend, kernel, host and linker records")
    records = [(runtime_lines[0], "runtime"), *zip(backend_lines, roles),
               (application_lines[0], "kernel"), (application_lines[1], "host")]
    result = []
    for text, role in records:
        label = "workspace " + role + " stamp"
        row = _record(text, label, fmt, role=role, source=source, jobs=jobs,
                      selectors=not (driver == "rtlsim" and role == "backend_cpp"))
        _extra_configuration(text, label, role=role, driver=driver, fmt=fmt)
        words = _stamp_words(text, label)
        if driver == "rtlsim" and role in ("runtime", "backend_cpp", "verilator"):
            includes = _rtl_options(words, label, role=role, source=source, build=build, jobs=jobs)
        else:
            includes = _options(words, label, role=role, source=source, build=build)
        row["include_paths"] = includes
        result.append(row)
    linker = application_lines[2]
    _syntax(linker, "workspace linker stamp")
    require(_stamp_words(linker, "workspace linker stamp") ==
            [*WRAP_FLAGS, "-L" + str(build / "sw/runtime"), "-lvortex"],
            "workspace linker differs from the exact four wrappers and original runtime binding")
    return result
