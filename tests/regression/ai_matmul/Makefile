ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := ai_matmul
SRC_DIR := $(VORTEX_HOME)/tests/regression/$(PROJECT)
AI_DIR := $(VORTEX_HOME)/sw/runtime/ai

SRCS := $(SRC_DIR)/main.cpp $(AI_DIR)/contract.cpp $(AI_DIR)/runtime.cpp
HDRS := $(AI_DIR)/contract.h $(AI_DIR)/runtime.h \
        $(VORTEX_HOME)/tests/regression/sgemm_tcu/p02_fixtures.h \
        $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

VX_SRCS := $(VORTEX_HOME)/sw/kernel/ai/matmul.cpp
VX_HDRS := $(SW_COMMON_DIR)/ai_matmul_args.h $(SW_COMMON_DIR)/ai_matmul_profile.h

CXXFLAGS += -I$(AI_DIR)
KERNEL_LIB := vortex2

include ../common.mk
