ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := ai_workspace
SRC_DIR := $(VORTEX_HOME)/tests/regression/$(PROJECT)
AI_DIR := $(VORTEX_HOME)/sw/runtime/ai

SRCS := $(SRC_DIR)/main.cpp $(SRC_DIR)/observer.cpp \
        $(AI_DIR)/contract.cpp $(AI_DIR)/runtime.cpp
HDRS := $(SRC_DIR)/observer.h $(AI_DIR)/contract.h $(AI_DIR)/runtime.h \
        $(VORTEX_HOME)/tests/regression/sgemm_tcu/p02_fixtures.h \
        $(VORTEX_HOME)/sw/runtime/include/vortex2.h \
        $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

VX_SRCS := $(VORTEX_HOME)/sw/kernel/ai/matmul.cpp
VX_HDRS := $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

CXXFLAGS += -I$(AI_DIR)
LDFLAGS += -Wl,--wrap=vx_buffer_create -Wl,--wrap=vx_buffer_release \
           -Wl,--wrap=vx_device_open -Wl,--wrap=vx_device_release
KERNEL_LIB := vortex2

include ../common.mk
