# SPDX-License-Identifier: Apache-2.0
include Makefile

LDFLAGS += -Wl,-Map,$(DESTDIR)/dependency-model.map
