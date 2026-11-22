# SPDX-License-Identifier: Apache-2.0
include Makefile

CHECKED_COUNTERS_TEST_OBJ := $(OBJ_DIR)/tests/checked_counters_test.o
CHECKED_COUNTERS_TEST := $(DESTDIR)/checked_counters_test

.PHONY: test-checked-counters clean-checked-counters

test-checked-counters: $(CHECKED_COUNTERS_TEST)
	$(CHECKED_COUNTERS_TEST) boundaries

$(CHECKED_COUNTERS_TEST_OBJ): $(VORTEX_HOME)/tests/unittest/checked_counters/main.cpp $(CONFIG_FILE)
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(CHECKED_COUNTERS_TEST): $(OBJS) $(CHECKED_COUNTERS_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ $(LDFLAGS) -o $@

-include $(CHECKED_COUNTERS_TEST_OBJ:.o=.d)

clean-exe: clean-checked-counters
clean-checked-counters:
	rm -f $(CHECKED_COUNTERS_TEST)
