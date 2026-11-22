# SPDX-License-Identifier: Apache-2.0
include Makefile

P06_PREFLIGHT_DIR := $(VORTEX_HOME)/tests/regression/ai_counter_preflight
P06_PREFLIGHT_LINK_STAMP := $(DESTDIR)/preflight_backend_link.stamp

SRCS += $(P06_PREFLIGHT_DIR)/hooks.cpp
LDFLAGS += -Wl,--wrap=_ZN6vortex9ProcessorC1Ev \
           -Wl,--wrap=_ZN6vortex9ProcessorD1Ev \
           -Wl,--wrap=_ZN6vortex9Processor11run_checkedEv \
           -Wl,--wrap=_ZN6vortex9Processor8dcr_readEjjPj \
           -Wl,--wrap=_ZN6vortex9Processor9dcr_writeEjj

.PHONY: p06-preflight-relink

$(DESTDIR)/$(PROJECT): $(P06_PREFLIGHT_DIR)/hooks.cpp $(P06_PREFLIGHT_DIR)/hooks.h \
                      $(P06_PREFLIGHT_DIR)/backend.mk $(P06_PREFLIGHT_LINK_STAMP) \
                      p06-preflight-relink

$(P06_PREFLIGHT_LINK_STAMP): force
	@mkdir -p $(@D)
	@printf '%s\n' '$(subst ','"'"',$(LDFLAGS))' > $@
