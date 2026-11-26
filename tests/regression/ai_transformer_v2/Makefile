ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := ai_transformer_v2
SRC_DIR := $(VORTEX_HOME)/tests/regression/$(PROJECT)

# Apply the p02-tfr native TFR/STD defaults when invoked directly without
# --profile=p02-tfr, while letting explicit caller CONFIGS override or supplement.
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
HDRS := $(VORTEX_HOME)/sw/runtime/include/vortex2.h \
        $(SW_COMMON_DIR)/ai_ops_v2_args.h \
        $(SW_COMMON_DIR)/ai_matmul_args.h

VX_SRCS := $(VORTEX_HOME)/sw/kernel/ai/ops_v2.cpp
VX_HDRS := $(SW_COMMON_DIR)/ai_ops_v2_args.h

KERNEL_LIB := vortex2

include ../common.mk

ifneq ($(XLEN),64)
$(error ai_transformer_v2 requires an XLEN=64 build tree)
endif

# Build the companion native matmul kernel at a disjoint VMA so ops_v2 and
# matmul modules remain co-resident on-device without module reload overhead.
MATMUL_STARTUP_ADDR ?= 0x180400000
MATMUL_SRCS := $(VORTEX_HOME)/sw/kernel/ai/matmul.cpp
MATMUL_HDRS := $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h
MATMUL_LDFLAGS := -Wl,-Bstatic,--gc-sections,-T,$(VORTEX_HOME)/sw/kernel/scripts/link$(XLEN).ld,--defsym=STARTUP_ADDR=$(MATMUL_STARTUP_ADDR) $(VORTEX_KN_PATH)/lib$(KERNEL_LIB).a $(VX_LIBS)

matmul.elf: $(MATMUL_SRCS) $(MATMUL_HDRS) $(VORTEX_KN_PATH)/lib$(KERNEL_LIB).a $(CONFIG_STAMP)
	$(VX_CXX) $(VX_CFLAGS) -c $(MATMUL_SRCS) -o matmul.o
	$(VX_CXX) $(VX_CFLAGS) -DNEED_GP -DNEED_TLS -DNEED_INITFINI $(VX_KMU_FLAG) -c $(VX_STARTUP_SRC) -o matmul_start.o
	$(VX_CXX) $(VX_CFLAGS) matmul_start.o matmul.o $(MATMUL_LDFLAGS) -o matmul_start.o.elf
	$(VX_CXX) $(VX_CFLAGS) $$($(KERNEL_STARTUP) $(VX_DP) matmul_start.o.elf) $(VX_KMU_FLAG) -c $(VX_STARTUP_SRC) -o matmul_start.o && rm -f matmul_start.o.elf
	$(VX_CXX) $(VX_CFLAGS) matmul_start.o matmul.o $(MATMUL_LDFLAGS) -o $@ && rm -f matmul_start.o matmul.o

matmul.vxbin: matmul.elf
	OBJCOPY=$(VX_CP) $(VORTEX_HOME)/sw/kernel/scripts/vxbin.py $< $@

all: matmul.vxbin
run-simx run-rtlsim run-opae run-xrt run-firesim run-foldsim run-aved: matmul.vxbin
