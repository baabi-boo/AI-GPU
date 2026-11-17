ROOT_DIR := $(realpath ../../..)
ifeq ($(wildcard $(ROOT_DIR)/config.mk),)
$(error Configure an out-of-tree RV64 build first)
endif
include $(ROOT_DIR)/config.mk
ifeq ($(realpath $(ROOT_DIR)),$(realpath $(VORTEX_HOME)))
$(error The WGMMA harness must be built out of tree)
endif
ifneq ($(XLEN),64)
$(error The WGMMA harness requires RV64)
endif
ifneq ($(strip $(PARAMS)),)
$(error The WGMMA harness has no parameter overrides)
endif

PROJECT := tcu_wgmma
THREADS ?= 2
SRC_DIR := $(VORTEX_HOME)/hw/unittest/$(PROJECT)
RTL_DIR := $(VORTEX_HOME)/hw/rtl
CONFIGS += -DSIMULATION
XCONFIGS := $(shell python3 $(ROOT_DIR)/ci/gen_config.py --config=$(VORTEX_HOME)/VX_config.toml --cflags='$(CONFIGS) -DVX_CFG_XLEN=$(XLEN)')
ifneq ($(.SHELLSTATUS),0)
$(error Cannot resolve WGMMA configuration)
endif
REQUIRED_FLAGS := -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_WGMMA_ENABLE -DVX_CFG_TCU_SPARSE_ENABLE -DVX_CFG_TCU_TYPE_TFR -DVX_CFG_TCU_FP16_ENABLE
ifneq ($(filter-out $(XCONFIGS),$(REQUIRED_FLAGS)),)
$(error WGMMA harness requires enabled sparse/native TFR FP16 WGMMA)
endif
$(foreach pair,NUM_THREADS=8 NUM_WARPS=8 ISSUE_WIDTH=4 NUM_TCU_BLOCKS=4 NUM_LSU_BLOCKS=1 NUM_LSU_LANES=8 LMEM_NUM_BANKS=8 TCU_LATENCY=4 TCU_USE_DSP=0,$(if $(filter -DVX_CFG_$(pair),$(XCONFIGS)),,$(error WGMMA harness requires $(pair))))
ifneq ($(filter -DVX_CFG_TCU_FEDP2K -DVX_CFG_TCU_FEDP2K=% -DSV_DPI -DSV_DPI=%,$(XCONFIGS) $(CONFIGS)),)
$(error This harness requires native no-FEDP2K arithmetic without DPI)
endif

CXXFLAGS := -I$(SRC_DIR) -I$(ROOT_DIR)/sw -I$(ROOT_DIR)/hw
SRCS := $(SRC_DIR)/main.cpp
RTL_PKGS := $(RTL_DIR)/VX_gpu_pkg.sv $(RTL_DIR)/tcu/VX_tcu_pkg.sv
RTL_INCLUDE := -I$(ROOT_DIR)/sw -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(RTL_DIR)/libs -I$(RTL_DIR)/tcu -I$(RTL_DIR)/tcu/tfr -I$(RTL_DIR)/interfaces -I$(RTL_DIR)/core -I$(RTL_DIR)/mem -I$(SRC_DIR)
TOP := VX_tcu_wgmma_top
OPTS ?= --all
include ../common.mk
CXXFLAGS += $(XCONFIGS) -UNDEBUG
VL_FLAGS += -UNDEBUG $(filter -DVX_CFG_TCU_TYPE_% -DVX_CFG_FPU_TYPE_%,$(XCONFIGS))

.PHONY: FORCE
$(DESTDIR)/$(PROJECT): $(ROOT_DIR)/sw/VX_config.h $(ROOT_DIR)/hw/VX_config.vh $(ROOT_DIR)/hw/VX_types.vh ../verilator.vlt $(MAKEFILE_LIST) config.stamp
config.stamp: FORCE
	@set -e; stamp_tmp=$@.tmp.$$$$; \
	 printf '%s\n' '$(CXXFLAGS)' '$(VL_FLAGS)' '$(LDFLAGS)' > $$stamp_tmp; \
	 if ! cmp -s $$stamp_tmp $@; then \
	   rm -rf obj_dir; rm -f $(DESTDIR)/$(PROJECT); mv -f $$stamp_tmp $@; \
	 else rm -f $$stamp_tmp; fi
FORCE:
