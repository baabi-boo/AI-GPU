# SPDX-License-Identifier: Apache-2.0
ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

PROJECT := simx_completion
SRC_DIR := $(VORTEX_HOME)/tests/regression/$(PROJECT)
SRCS := $(SRC_DIR)/main.cpp
HDRS := $(SRC_DIR)/common.h
VX_SRCS := $(SRC_DIR)/kernel.cpp
VX_HDRS := $(SRC_DIR)/common.h
KERNEL_LIB := vortex2

include ../common.mk
