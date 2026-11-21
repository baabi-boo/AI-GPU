ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := ai_bench_mlp
SRC_DIR := $(VORTEX_HOME)/tests/regression/ai_mlp
AI_DIR := $(VORTEX_HOME)/sw/runtime/ai
OBSERVER_DIR := $(VORTEX_HOME)/tests/regression/ai_bench_common

SRCS := $(SRC_DIR)/main.cpp $(AI_DIR)/contract.cpp $(AI_DIR)/runtime.cpp \
        $(AI_DIR)/mlp_host.cpp $(AI_DIR)/mlp_runtime.cpp $(OBSERVER_DIR)/observer.cpp
HDRS := $(SRC_DIR)/records.h $(SRC_DIR)/p04_fixtures.h \
        $(AI_DIR)/contract.h $(AI_DIR)/runtime.h \
        $(AI_DIR)/mlp_host.h $(AI_DIR)/mlp_runtime.h \
        $(VORTEX_HOME)/sw/runtime/include/vortex2.h $(OBSERVER_DIR)/counters.h \
        $(ROOT_DIR)/sw/VX_config.h $(ROOT_DIR)/sw/VX_types.h \
        $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

VX_SRCS := $(VORTEX_HOME)/sw/kernel/ai/matmul.cpp
VX_HDRS := $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

CXXFLAGS += -I$(AI_DIR)
LDFLAGS += -Wl,--wrap=vx_device_open -Wl,--wrap=vx_device_release
KERNEL_LIB := vortex2

include ../common.mk
