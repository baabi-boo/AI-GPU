ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := p02_wgmma
SRC_DIR := $(VORTEX_HOME)/tests/regression/$(PROJECT)

ifeq ($(filter -DWGMMA_RS -DWGMMA_RS=% -DWGMMA_SS -DWGMMA_SS=%,$(CONFIGS)),)
$(error Select WGMMA_RS or WGMMA_SS explicitly)
endif

ifneq ($(filter -DP02_WGMMA_SPARSE -DP02_WGMMA_SPARSE=%,$(CONFIGS)),)
KERNEL_SRC_DIR := $(VORTEX_HOME)/tests/regression/sgemm_tcu_wg_sp
else
KERNEL_SRC_DIR := $(VORTEX_HOME)/tests/regression/sgemm_tcu_wg
endif

SRCS := $(SRC_DIR)/main.cpp
HDRS := $(SRC_DIR)/fixtures.h $(KERNEL_SRC_DIR)/common.h
HDRS += $(SW_COMMON_DIR)/tensor_cfg.h $(VORTEX_HOME)/sw/runtime/include/vortex2.h
VX_SRCS := $(KERNEL_SRC_DIR)/kernel.cpp
VX_HDRS := $(KERNEL_SRC_DIR)/common.h $(VORTEX_HOME)/sw/kernel/include/vx_tensor.h \
           $(SW_COMMON_DIR)/tensor_cfg.h
KERNEL_LIB := vortex2

include ../common.mk
