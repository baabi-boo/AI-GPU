ROOT_DIR := $(realpath ../../..)
ifeq ($(wildcard $(ROOT_DIR)/config.mk),)
$(error Run this Makefile from a freshly configured RV64 build tree)
endif
include $(ROOT_DIR)/config.mk

ifeq ($(realpath $(ROOT_DIR)),$(realpath $(VORTEX_HOME)))
$(error The tensor contract must be built out of tree)
endif
ifneq ($(XLEN),64)
$(error The tensor contract requires configure --xlen=64)
endif

NUM_REGS ?= 2
W ?= 25
LATENCY ?= 4
USE_DSP ?= 0
LANE_MASK ?= 1
THREADS ?= 2
ifneq ($(NUM_REGS):$(W):$(LATENCY):$(USE_DSP):$(LANE_MASK),2:25:4:0:1)
$(error The frozen profile requires NUM_REGS=2 W=25 LATENCY=4 USE_DSP=0 LANE_MASK=1)
endif
ifneq ($(strip $(PARAMS)),)
$(error PARAMS cannot override the frozen tensor contract)
endif

PROJECT := tcu_contract
MODEL_PROJECT := tfr_model
SRC_DIR := $(VORTEX_HOME)/hw/unittest/$(PROJECT)
RTL_DIR := $(VORTEX_HOME)/hw/rtl
FIXTURE_HEADER := $(VORTEX_HOME)/hw/unittest/common/p02_tfr_vectors.h

CONFIGS += -DSIMULATION -DVX_CFG_EXT_TCU_ENABLE
XCONFIGS := $(shell python3 $(ROOT_DIR)/ci/gen_config.py --config=$(VORTEX_HOME)/VX_config.toml --cflags='$(CONFIGS) -DVX_CFG_XLEN=$(XLEN)')
ifneq ($(.SHELLSTATUS),0)
$(error Cannot resolve the tensor contract configuration)
endif
ifeq ($(filter -DVX_CFG_TCU_TYPE_TFR,$(XCONFIGS)),)
$(error The tensor contract requires TCU_TYPE_TFR)
endif
ifneq ($(filter -DVX_CFG_TCU_LATENCY=%,$(XCONFIGS)),-DVX_CFG_TCU_LATENCY=4)
$(error The tensor contract requires the configured TFR latency to be 4)
endif
ifneq ($(filter -DVX_CFG_TCU_USE_DSP=%,$(XCONFIGS)),-DVX_CFG_TCU_USE_DSP=0)
$(error The tensor contract requires configured TCU_USE_DSP=0)
endif
ifneq ($(filter -DVX_CFG_NUM_THREADS=%,$(XCONFIGS)),-DVX_CFG_NUM_THREADS=4)
$(error The tensor contract requires configured NUM_THREADS=4)
endif

CXXFLAGS := -I$(SRC_DIR) -I$(VORTEX_HOME)/hw/unittest/common -I$(SW_COMMON_DIR)
CXXFLAGS += -I$(ROOT_DIR)/sw -I$(ROOT_DIR)/hw
CXXFLAGS += -DP02_NUM_REGS=$(NUM_REGS) -DP02_WINDOW=$(W) -DP02_LATENCY=$(LATENCY)
CXXFLAGS += -DP02_USE_DSP=$(USE_DSP) -DP02_LANE_MASK=$(LANE_MASK)

SRCS := $(SRC_DIR)/main.cpp
override PARAMS := -GN=$(NUM_REGS) -GW=$(W) -GLATENCY=$(LATENCY) -GUSE_DSP=$(USE_DSP) -GLANE_MASK=$(LANE_MASK)
RTL_PKGS := $(RTL_DIR)/VX_gpu_pkg.sv $(RTL_DIR)/tcu/VX_tcu_pkg.sv
RTL_INCLUDE := -I$(RTL_DIR) -I$(RTL_DIR)/libs -I$(RTL_DIR)/tcu -I$(RTL_DIR)/tcu/tfr
VL_FLAGS += -I$(ROOT_DIR)/sw -I$(ROOT_DIR)/hw
TOP := VX_tcu_fedp_tfr
OPTS ?= --format=all

include ../common.mk

# Raw profile enums do not define the selector macros used by the C++ guards.
CXXFLAGS += $(XCONFIGS)

.PHONY: model run-model clean-model FORCE

$(DESTDIR)/$(PROJECT): $(FIXTURE_HEADER) $(ROOT_DIR)/sw/VX_config.h $(ROOT_DIR)/hw/VX_config.vh \
                      $(ROOT_DIR)/hw/VX_types.vh ../verilator.vlt $(MAKEFILE_LIST) config.stamp

model: $(DESTDIR)/$(MODEL_PROJECT)

$(DESTDIR)/$(MODEL_PROJECT): $(SRCS) $(FIXTURE_HEADER) $(SW_COMMON_DIR)/fedp.h \
                            $(ROOT_DIR)/sw/VX_config.h $(MAKEFILE_LIST) config.stamp
	$(CXX) $(CXXFLAGS) -DP02_MODEL_ONLY $(SRC_DIR)/main.cpp -o $@ $(LDFLAGS)

run-model: $(DESTDIR)/$(MODEL_PROJECT)
	$(DESTDIR)/$(MODEL_PROJECT) $(OPTS)

# Verilator's nested make does not track changes to compiler or elaboration flags.
config.stamp: FORCE
	@set -e; stamp_tmp=$@.tmp.$$$$; \
	 printf '%s\n' '$(CXXFLAGS)' '$(VL_FLAGS)' '$(LDFLAGS)' > $$stamp_tmp; \
	 if ! cmp -s $$stamp_tmp $@; then \
	   rm -rf obj_dir; \
	   rm -f $(DESTDIR)/$(PROJECT) $(DESTDIR)/$(MODEL_PROJECT); \
	   mv -f $$stamp_tmp $@; \
	 else \
	   rm -f $$stamp_tmp; \
	 fi

FORCE:

clean: clean-model

clean-model:
	rm -f $(DESTDIR)/$(MODEL_PROJECT) config.stamp config.stamp.tmp.*
