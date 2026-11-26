ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := ai_mlp_fused
SRC_DIR := $(VORTEX_HOME)/tests/regression/$(PROJECT)

# Apply the p02-tfr native TFR/STD WMMA defaults when invoked directly without
# --profile=p02-tfr, while letting explicit caller CONFIGS (e.g. ITYPE=bf16)
# override or supplement them.
DEFAULT_TFR_CONFIGS := \
  -DVX_CFG_NUM_CLUSTERS=1 \
  -DVX_CFG_NUM_CORES=1 \
  -DVX_CFG_NUM_WARPS=4 \
  -DVX_CFG_NUM_THREADS=4 \
  -DVX_CFG_ISSUE_WIDTH=1 \
  -DVX_CFG_NUM_ALU_BLOCKS=1 \
  -DVX_CFG_NUM_LSU_BLOCKS=1 \
  -DVX_CFG_NUM_FPU_BLOCKS=1 \
  -DVX_CFG_FPU_TYPE_STD \
  -DVX_CFG_EXT_TCU_ENABLE \
  -DVX_CFG_TCU_TYPE_TFR \
  -DVX_CFG_TCU_PE_RATIO=1 \
  -DVX_CFG_TCU_LATENCY=4 \
  -DVX_CFG_TCU_USE_DSP=0 \
  -DVX_CFG_TCU_FP16_ENABLE \
  -DVX_CFG_LMEM_ENABLE

ifeq ($(strip $(PROFILE)),)
override CONFIGS := $(DEFAULT_TFR_CONFIGS) $(CONFIGS)
endif

override CONFIGS := $(if $(findstring -DITYPE=,$(CONFIGS)),$(CONFIGS),$(CONFIGS) -DITYPE=fp16)
override CONFIGS := $(if $(findstring -DOTYPE=,$(CONFIGS)),$(CONFIGS),$(CONFIGS) -DOTYPE=fp32)
override CONFIGS := $(if $(findstring -DKUNROLL=,$(CONFIGS)),$(CONFIGS),$(CONFIGS) -DKUNROLL=1)

SRCS := $(SRC_DIR)/main.cpp
HDRS := $(VORTEX_HOME)/tests/regression/ai_mlp/p04_fixtures.h \
        $(VORTEX_HOME)/sw/runtime/include/vortex2.h \
        $(SW_COMMON_DIR)/ai_mlp_fused_args.h \
        $(SW_COMMON_DIR)/ai_matmul_profile.h

VX_SRCS := $(VORTEX_HOME)/sw/kernel/ai/mlp_fused.cpp
VX_HDRS := $(SW_COMMON_DIR)/ai_mlp_fused_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

KERNEL_LIB := vortex2

include ../common.mk

ifneq ($(XLEN),64)
$(error ai_mlp_fused requires an XLEN=64 build tree)
endif
