# SPDX-License-Identifier: Apache-2.0
include checked_counters.mk

.DEFAULT_GOAL := checked-public

ifneq ($(XLEN),64)
$(error checked-public requires XLEN=64)
endif
ifneq ($(PROFILE),p02-tfr)
$(error checked-public requires PROFILE=p02-tfr)
endif
ifneq ($(PERF),1)
$(error checked-public requires PERF=1)
endif
ifneq ($(filter -DSIMX_CHECKED_COUNTERS=1,$(CONFIGS)),-DSIMX_CHECKED_COUNTERS=1)
$(error checked-public requires CONFIGS containing SIMX_CHECKED_COUNTERS=1 exactly once)
endif
ifdef DEBUG
$(error checked-public requires the release configuration)
endif
ifneq ($(USE_SST)$(USE_GEM5),00)
$(error checked-public requires the standalone model)
endif

CHECKED_PUBLIC_DIR := $(DESTDIR)/checked-public
CHECKED_PUBLIC_MAKEFILE := $(ROOT_DIR)/tests/unittest/checked_counters/public.mk
CHECKED_PUBLIC_SOURCE_MAKEFILE := $(CHECKED_COUNTERS_DIR)/public.mk
CHECKED_PUBLIC_MODEL := $(CHECKED_PUBLIC_DIR)/libchecked-simx.so
CHECKED_PUBLIC_BACKEND := $(CHECKED_PUBLIC_DIR)/libvortex-simx.so
CHECKED_PUBLIC_RUNTIME := $(CHECKED_PUBLIC_DIR)/libvortex.so
CHECKED_PUBLIC_TEST := $(CHECKED_PUBLIC_DIR)/checked_public_test
CHECKED_PUBLIC_HOOKS_OBJ := $(OBJ_DIR)/tests/checked_counters/public_hooks.o
CHECKED_PUBLIC_MAIN_OBJ := $(CHECKED_PUBLIC_DIR)/obj/public_main.o
CHECKED_PUBLIC_RUNTIME_ROOT := $(VORTEX_HOME)/sw/runtime
CHECKED_PUBLIC_RUNTIME_COMMON := $(CHECKED_PUBLIC_RUNTIME_ROOT)/common
CHECKED_PUBLIC_RUNTIME_INCLUDE := $(CHECKED_PUBLIC_RUNTIME_ROOT)/include

CHECKED_PUBLIC_RUNTIME_SRCS := $(CHECKED_PUBLIC_RUNTIME_ROOT)/stub/vortex.cpp \
  $(addprefix $(CHECKED_PUBLIC_RUNTIME_COMMON)/,graphics.cpp result.cpp device.cpp \
    buffer.cpp queue.cpp event.cpp module.cpp runtime_helpers.cpp perf.cpp \
    legacy_runtime.cpp legacy_utils.cpp utils.cpp vm.cpp)
CHECKED_PUBLIC_RUNTIME_OBJS := $(patsubst $(CHECKED_PUBLIC_RUNTIME_ROOT)/%.cpp,$(CHECKED_PUBLIC_DIR)/obj/runtime/%.o,$(CHECKED_PUBLIC_RUNTIME_SRCS))
CHECKED_PUBLIC_BACKEND_OBJS := $(addprefix $(CHECKED_PUBLIC_DIR)/obj/backend/,vortex.o utils.o cmd_processor.o)
CHECKED_PUBLIC_RUNTIME_STAMP := $(CHECKED_PUBLIC_DIR)/runtime_config.stamp
CHECKED_PUBLIC_BACKEND_STAMP := $(CHECKED_PUBLIC_DIR)/backend_config.stamp
CHECKED_PUBLIC_MAIN_STAMP := $(CHECKED_PUBLIC_DIR)/main_config.stamp
CHECKED_PUBLIC_STAMPS := $(CHECKED_PUBLIC_RUNTIME_STAMP) $(CHECKED_PUBLIC_BACKEND_STAMP) $(CHECKED_PUBLIC_MAIN_STAMP)
CHECKED_PUBLIC_MAKEFILES := $(CHECKED_PUBLIC_MAKEFILE) $(CHECKED_PUBLIC_SOURCE_MAKEFILE)
CHECKED_PUBLIC_GENERATED := $(ROOT_DIR)/sw/VX_config.h $(ROOT_DIR)/sw/VX_types.h

# Runtime configuration is expanded independently of the model's header flags.
CHECKED_PUBLIC_RUNTIME_FLAGS = $(XCONFIGS) -std=c++17 -Wall -Wextra -Wfatal-errors -Werror \
  -I$(CHECKED_PUBLIC_RUNTIME_INCLUDE) -I$(VORTEX_HOME)/sw/kernel/include \
  -I$(ROOT_DIR)/sw -I$(ROOT_DIR)/hw -I$(SW_COMMON_DIR) -I$(CHECKED_PUBLIC_RUNTIME_COMMON) \
  -fPIC $(CONFIGS) -O2 -DNDEBUG -MMD -MP -MF $(@:.o=.d)
CHECKED_PUBLIC_BACKEND_FLAGS = $(XCONFIGS) -std=c++17 -Wall -Wextra -Wfatal-errors -Werror -fPIC \
  -I$(CHECKED_PUBLIC_RUNTIME_INCLUDE) -I$(ROOT_DIR)/sw/runtime/common \
  -I$(ROOT_DIR)/sw -I$(ROOT_DIR)/hw -I$(VORTEX_HOME)/sim/simx \
  -I$(SIM_COMMON_DIR) -I$(SW_COMMON_DIR) -I$(CHECKED_PUBLIC_RUNTIME_COMMON) \
  -DVX_CFG_XLEN=$(XLEN) -DVX_CFG_XLEN_$(XLEN) $(CONFIGS) \
  -O2 -DNDEBUG -MMD -MP -MF $(@:.o=.d)
CHECKED_PUBLIC_MAIN_FLAGS = $(CHECKED_PUBLIC_RUNTIME_FLAGS)
CHECKED_PUBLIC_WRAPS := _ZN6vortex9ProcessorC1Ev _ZN6vortex9ProcessorD1Ev \
  _ZN6vortex9Processor11run_checkedEv _ZN6vortex9Processor8dcr_readEjjPj \
  _ZN6vortex9Processor9dcr_writeEjj

.PHONY: checked-public clean-checked-public

checked-public: $(CHECKED_PUBLIC_TEST)

$(CHECKED_PUBLIC_RUNTIME_STAMP): CHECKED_PUBLIC_STAMP_FLAGS = $(CHECKED_PUBLIC_RUNTIME_FLAGS)
$(CHECKED_PUBLIC_BACKEND_STAMP): CHECKED_PUBLIC_STAMP_FLAGS = $(CHECKED_PUBLIC_BACKEND_FLAGS)
$(CHECKED_PUBLIC_MAIN_STAMP): CHECKED_PUBLIC_STAMP_FLAGS = $(CHECKED_PUBLIC_MAIN_FLAGS)
$(CHECKED_PUBLIC_STAMPS): force
	@mkdir -p $(@D)
	@printf '%s\n' "$(CHECKED_PUBLIC_STAMP_FLAGS)" > $@.tmp
	@if ! cmp -s $@.tmp $@; then mv $@.tmp $@; else rm $@.tmp; fi

$(CHECKED_PUBLIC_HOOKS_OBJ): $(CHECKED_COUNTERS_DIR)/public_hooks.cpp $(CHECKED_COUNTERS_DIR)/public_hooks.h $(CHECKED_COUNTERS_DIR)/counter_access.h $(CONFIG_FILE) $(CHECKED_PUBLIC_MAKEFILES)
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(CHECKED_PUBLIC_DIR)/obj/runtime/%.o: $(CHECKED_PUBLIC_RUNTIME_ROOT)/%.cpp $(CHECKED_PUBLIC_RUNTIME_STAMP) $(CHECKED_PUBLIC_GENERATED) $(CHECKED_PUBLIC_MAKEFILES)
	@mkdir -p $(@D)
	$(CXX) $(CHECKED_PUBLIC_RUNTIME_FLAGS) -c $< -o $@

$(CHECKED_PUBLIC_DIR)/obj/backend/vortex.o: $(CHECKED_PUBLIC_RUNTIME_ROOT)/simx/vortex.cpp
$(CHECKED_PUBLIC_DIR)/obj/backend/utils.o: $(CHECKED_PUBLIC_RUNTIME_COMMON)/utils.cpp
$(CHECKED_PUBLIC_DIR)/obj/backend/cmd_processor.o: $(SIM_COMMON_DIR)/cmd_processor.cpp
$(CHECKED_PUBLIC_BACKEND_OBJS): $(CHECKED_PUBLIC_BACKEND_STAMP) $(CHECKED_PUBLIC_GENERATED) $(CHECKED_PUBLIC_MAKEFILES)
	@mkdir -p $(@D)
	$(CXX) $(CHECKED_PUBLIC_BACKEND_FLAGS) -c $(filter %.cpp,$^) -o $@

$(CHECKED_PUBLIC_MAIN_OBJ): $(CHECKED_COUNTERS_DIR)/public_main.cpp $(CHECKED_COUNTERS_DIR)/public_hooks.h $(CHECKED_PUBLIC_MAIN_STAMP) $(CHECKED_PUBLIC_GENERATED) $(CHECKED_PUBLIC_MAKEFILES)
	@mkdir -p $(@D)
	$(CXX) $(CHECKED_PUBLIC_MAIN_FLAGS) -c $< -o $@

$(CHECKED_PUBLIC_MODEL): $(CHECKED_COUNTERS_MODEL_OBJS) $(CHECKED_COUNTERS_ACCESS_OBJS) $(CHECKED_PUBLIC_MAKEFILES)
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) $(filter %.o,$^) -shared $(LDFLAGS) -Wl,-soname,libchecked-simx.so -o $@

$(CHECKED_PUBLIC_RUNTIME): $(CHECKED_PUBLIC_RUNTIME_OBJS) $(CHECKED_PUBLIC_MAKEFILES)
	$(CXX) $(filter %.o,$^) -shared -pthread -ldl -Wl,-soname,libvortex.so -Wl,-rpath,'$$ORIGIN' -o $@

# Interception belongs on this link, where the backend's Processor calls resolve.
$(CHECKED_PUBLIC_BACKEND): $(CHECKED_PUBLIC_BACKEND_OBJS) $(CHECKED_PUBLIC_HOOKS_OBJ) $(CHECKED_PUBLIC_MODEL) $(CHECKED_PUBLIC_MAKEFILES)
	$(CXX) $(filter %.o,$^) -shared -pthread -Wl,-rpath,'$$ORIGIN' \
	  $(foreach symbol,$(CHECKED_PUBLIC_WRAPS),-Wl,--wrap=$(symbol)) \
	  -L$(CHECKED_PUBLIC_DIR) -lchecked-simx -o $@

$(CHECKED_PUBLIC_TEST): $(CHECKED_PUBLIC_MAIN_OBJ) $(CHECKED_PUBLIC_RUNTIME) $(CHECKED_PUBLIC_BACKEND) $(CHECKED_PUBLIC_MAKEFILES)
	$(CXX) $(CHECKED_PUBLIC_MAIN_OBJ) -L$(CHECKED_PUBLIC_DIR) -lvortex -lvortex-simx \
	  -pthread -Wl,-rpath,'$$ORIGIN' -Wl,-rpath-link,$(CHECKED_PUBLIC_DIR) -o $@

-include $(CHECKED_PUBLIC_HOOKS_OBJ:.o=.d) $(CHECKED_PUBLIC_MAIN_OBJ:.o=.d) \
  $(CHECKED_PUBLIC_RUNTIME_OBJS:.o=.d) $(CHECKED_PUBLIC_BACKEND_OBJS:.o=.d)

clean-checked-public:
	rm -f $(CHECKED_PUBLIC_TEST) $(CHECKED_PUBLIC_RUNTIME) $(CHECKED_PUBLIC_BACKEND) $(CHECKED_PUBLIC_MODEL)
