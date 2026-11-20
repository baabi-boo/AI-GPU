ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := ai_mlp
SRC_DIR := $(VORTEX_HOME)/tests/regression/$(PROJECT)
AI_DIR := $(VORTEX_HOME)/sw/runtime/ai

SRCS := $(SRC_DIR)/main.cpp $(AI_DIR)/contract.cpp $(AI_DIR)/runtime.cpp \
        $(AI_DIR)/mlp_host.cpp $(AI_DIR)/mlp_runtime.cpp
HDRS := $(SRC_DIR)/records.h $(SRC_DIR)/p04_fixtures.h \
        $(AI_DIR)/contract.h $(AI_DIR)/runtime.h \
        $(AI_DIR)/mlp_host.h $(AI_DIR)/mlp_runtime.h \
        $(VORTEX_HOME)/sw/runtime/include/vortex2.h \
        $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

VX_SRCS := $(VORTEX_HOME)/sw/kernel/ai/matmul.cpp
VX_HDRS := $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

CXXFLAGS += -I$(AI_DIR)
KERNEL_LIB := vortex2

include ../common.mk
