# SPDX-License-Identifier: Apache-2.0
include Makefile

CHECKED_COUNTERS_TEST_OBJ := $(OBJ_DIR)/tests/checked_counters_test.o
CHECKED_COUNTERS_TEST := $(DESTDIR)/checked_counters_test
CHECKED_COUNTERS_DIR := $(VORTEX_HOME)/tests/unittest/checked_counters
CHECKED_COUNTERS_ACCESS_NAMES := access_socket access_cache access_memory access_tcu counter_access
CHECKED_COUNTERS_ACCESS_OBJS := $(addprefix $(OBJ_DIR)/tests/checked_counters/,$(addsuffix .o,$(CHECKED_COUNTERS_ACCESS_NAMES)))
CHECKED_COUNTERS_TCU_OBJ := $(OBJ_DIR)/tests/checked_counters/access_tcu.o
CHECKED_COUNTERS_TCU_SOURCE := $(OBJ_DIR)/tests/checked_counters/access_tcu.generated.cpp
CHECKED_COUNTERS_DIRECT_ACCESS_OBJS := $(filter-out $(CHECKED_COUNTERS_TCU_OBJ),$(CHECKED_COUNTERS_ACCESS_OBJS))
CHECKED_COUNTERS_REPLACED_OBJS := $(OBJ_DIR)/socket.o $(OBJ_DIR)/mem/cache.o $(OBJ_DIR)/mem/memory.o $(OBJ_DIR)/tcu/tcu_tbuf.o
CHECKED_COUNTERS_MODEL_OBJS := $(filter-out $(CHECKED_COUNTERS_REPLACED_OBJS),$(OBJS))

.PHONY: test-checked-counters clean-checked-counters

test-checked-counters: $(CHECKED_COUNTERS_TEST)
	$(CHECKED_COUNTERS_TEST) boundaries

$(CHECKED_COUNTERS_TEST_OBJ): $(VORTEX_HOME)/tests/unittest/checked_counters/main.cpp $(CONFIG_FILE)
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(CHECKED_COUNTERS_DIRECT_ACCESS_OBJS): $(OBJ_DIR)/tests/checked_counters/%.o: $(CHECKED_COUNTERS_DIR)/%.cpp $(CHECKED_COUNTERS_DIR)/counter_access.h $(CONFIG_FILE) $(VORTEX_HOME)/sim/simx/checked_counters.mk
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -c $< -o $@

# GCC diagnoses the anonymous Buffer member only when its body is included.
$(CHECKED_COUNTERS_TCU_SOURCE): $(VORTEX_HOME)/sim/simx/tcu/tcu_tbuf.cpp $(CHECKED_COUNTERS_DIR)/access_tcu.cpp $(VORTEX_HOME)/sim/simx/checked_counters.mk
	@mkdir -p $(@D)
	@printf '\n' | cat $(VORTEX_HOME)/sim/simx/tcu/tcu_tbuf.cpp - $(CHECKED_COUNTERS_DIR)/access_tcu.cpp > $@

$(CHECKED_COUNTERS_TCU_OBJ): $(CHECKED_COUNTERS_TCU_SOURCE) $(CHECKED_COUNTERS_DIR)/counter_access.h $(CONFIG_FILE)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(CHECKED_COUNTERS_TEST): $(CHECKED_COUNTERS_MODEL_OBJS) $(CHECKED_COUNTERS_ACCESS_OBJS) $(CHECKED_COUNTERS_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ $(LDFLAGS) -o $@

-include $(CHECKED_COUNTERS_TEST_OBJ:.o=.d) $(CHECKED_COUNTERS_ACCESS_OBJS:.o=.d)

clean-exe: clean-checked-counters
clean-checked-counters:
	rm -f $(CHECKED_COUNTERS_TEST)
