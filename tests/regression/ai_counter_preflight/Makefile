# SPDX-License-Identifier: Apache-2.0
ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := ai_counter_preflight
SRC_DIR := $(VORTEX_HOME)/tests/regression/$(PROJECT)
WARM_DIR := $(VORTEX_HOME)/tests/regression/ai_warm_workspace
AI_DIR := $(VORTEX_HOME)/sw/runtime/ai
RT_COMMON_DIR := $(VORTEX_HOME)/sw/runtime/common

SRCS := $(SRC_DIR)/main.cpp $(WARM_DIR)/observer.cpp \
        $(AI_DIR)/contract.cpp $(AI_DIR)/runtime.cpp
HDRS := $(SRC_DIR)/hooks.h $(WARM_DIR)/main.cpp $(WARM_DIR)/observer.h \
        $(AI_DIR)/contract.h $(AI_DIR)/runtime.h \
        $(VORTEX_HOME)/tests/regression/ai_bench_common/counters.h \
        $(VORTEX_HOME)/tests/regression/sgemm_tcu/p02_fixtures.h \
        $(VORTEX_HOME)/sw/runtime/include/vortex2.h \
        $(VORTEX_HOME)/sw/runtime/common/vortex2_internal.h \
        $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

VX_SRCS := $(VORTEX_HOME)/sw/kernel/ai/matmul.cpp
VX_HDRS := $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

CXXFLAGS += -I$(AI_DIR) -I$(RT_COMMON_DIR)
LDFLAGS += -Wl,--wrap=vx_buffer_create -Wl,--wrap=vx_buffer_release \
           -Wl,--wrap=vx_device_open -Wl,--wrap=vx_device_release \
           -Wl,--wrap=vx_device_mpm_query
KERNEL_LIB := vortex2

include ../common.mk

LDFLAGS += -lvortex-simx
